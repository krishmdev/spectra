"""Agent loop — observe → think → act cycle tying all modules together."""
from __future__ import annotations

import concurrent.futures
import time

from core.tree_reader import TreeReader
from core.planner import Planner
from core.executor import Executor
from core.stuck_detector import StuckDetector
from core.memory import EpisodicMemory, AgentMemory
from core.gates import ConfirmationGate
from core.takeover import TakeoverManager
from core.router import TaskRouter
from core.plan_preview import PlanPreview

import wda
import uuid
import os
import json
from context.episode_store import EpisodeStore
from context.models import Episode
from context.context_collector import ContextSnapshot

def _summarize_task(history, task, planner) -> str:
    prompt = f"Summarize this completed task in ONE sentence (max 15 words). Task: {task}\nHistory: {'; '.join(history[-10:])}"
    try:
        from google.genai import types
        config = types.GenerateContentConfig(max_output_tokens=30)
        res = planner.client.models.generate_content(
            model=planner.model,
            contents=[types.Content(role='user', parts=[types.Part(text=prompt)])],
            config=config,
        )
        return res.text.strip().strip('"')
    except:
        return task[:50]

# Terminal actions that end the loop
_TERMINAL = {'done', 'stuck'}

# Non-UI actions that don't change the screen — skip re-snapshot after these
_NO_UI_ACTIONS = {'remember', 'plan', 'ask_user'}

# Adaptive sleep: action → seconds to wait for UI to settle
_ACTION_SLEEP = {
    'tap': 0.15,
    'tap_xy': 0.15,
    'scroll': 0.2,
    'type_text': 0.2,
    'go_back': 0.2,
    'go_home': 0.2,
    'navigate':        0,    # executor already sleeps 2.5s for page load
    'dismiss_paywall': 0,    # executor already sleeps 0.5s internally
    'open_app': 0,    # executor already sleeps 1s internally
    'wait': 0,        # the wait action itself handles the delay
    'done': 0,
    'stuck': 0,
}


def _reflect_and_store(planner, episodic, task, history, failure_type, app, verbose):
    """After a failure, ask the LLM to reflect and store the lesson."""
    try:
        lesson = planner.reflect(task, history, failure_type)
        if verbose:
            print(f'  Lesson learned: {lesson}')
        episodic.add_lesson(
            task=task,
            app=app,
            lesson=lesson,
            failure_type=failure_type,
            history_summary='; '.join(history[-5:]),
        )
    except Exception as e:
        if verbose:
            print(f'  (reflection failed: {e})')


def _build_combined_memory(lessons_text: str | None, agent_memory: AgentMemory) -> str | None:
    """Combine episodic lessons and session memory into one string for the planner."""
    parts = []
    if lessons_text:
        parts.append(lessons_text)
    agent_mem_text = agent_memory.format_for_prompt()
    if agent_mem_text:
        parts.append(agent_mem_text)
    return '\n\n'.join(parts) or None


def run_agent(
    task: str,
    max_steps: int = 15,
    wda_url: str = 'http://localhost:8100',
    verbose: bool = True,
    agent_memory: AgentMemory | None = None,
    plan_steps: list[str] | None = None,
    stop_check=None,
    gate: ConfirmationGate | None = None,
    takeover: TakeoverManager | None = None,
    step_callback=None,
    ask_user_fn=None,
) -> bool:
    """Execute a natural language task on the iOS simulator.

    Args:
        task: Natural language instruction (e.g. "Turn on Dark Mode")
        max_steps: Maximum actions before timeout
        wda_url: WDA server URL
        verbose: Print each step to stdout
        agent_memory: Shared session memory (for cross-app tasks). Created if None.
        plan_steps: Pre-approved plan steps (from PlanPreview).
        stop_check: Callable returning True to stop the loop (for BackgroundRunner).
        gate: ConfirmationGate instance (injectable for WebSocket server).
        takeover: TakeoverManager instance (injectable for WebSocket server).
        step_callback: Optional callable(step, max_steps, action_name, action_input, result, current_app, ref_map, tree) per step.

    Returns:
        True if task completed (done), False if stuck or timed out
    """
    shared_client = wda.Client(wda_url)
    try:
        shared_client.http.timeout = 5
    except AttributeError:
        pass
    reader = TreeReader(wda_url, client=shared_client)
    planner = Planner()
    executor = Executor(wda_url, client=shared_client)
    detector = StuckDetector()
    episodic = EpisodicMemory()
    if gate is None:
        gate = ConfirmationGate()
    if takeover is None:
        takeover = TakeoverManager()

    if agent_memory is None:
        agent_memory = AgentMemory()

    gate.set_task(task)

    history: list[str] = []
    current_app: str = 'unknown'
    cached_snapshot: tuple | None = None
    last_action_was_no_ui = False
    prefetch_future: concurrent.futures.Future | None = None

    # Reuse a single thread pool for prefetch (avoids per-step creation overhead)
    snap_pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    # Retrieve lessons from past failures
    lessons_text = episodic.retrieve(task)
    if lessons_text and verbose:
        print(f'  {lessons_text}')

    t_start = time.monotonic()
    
    # Capture ContextSnapshot at task start for episode logging
    local_t = time.localtime(time.time())
    try:
        tmp_tree, tmp_ref_map, tmp_meta = reader.snapshot()
        start_app_id = tmp_meta.get("app_bundle_id", "unknown")
        start_labels = [el.get("label") for ref, el in tmp_ref_map.items() if el.get("label")]
    except:
        start_app_id = "unknown"
        start_labels = []
        
    start_ctx = ContextSnapshot(
        app_bundle_id=start_app_id, visible_labels=start_labels, 
        location_lat=None, location_lng=None,
        hour_of_day=local_t.tm_hour, day_of_week=local_t.tm_wday, 
        captured_at=time.time()
    )

    for step in range(1, max_steps + 1):
        # --- Stop check (for BackgroundRunner) ---
        if stop_check and stop_check():
            if verbose:
                print('  Agent stopped by external request')
            break

        # --- Observe (skip WDA round-trip if nothing changed) ---
        t_obs = time.monotonic()
        if last_action_was_no_ui and cached_snapshot is not None:
            tree, ref_map, metadata = cached_snapshot
        elif prefetch_future is not None:
            # Wait for the in-flight prefetch (started at end of previous step)
            try:
                tree, ref_map, metadata = prefetch_future.result(timeout=4.0)
                cached_snapshot = (tree, ref_map, metadata)
            except Exception:
                if cached_snapshot is not None:
                    tree, ref_map, metadata = cached_snapshot
                else:
                    prefetch_future = None
                    continue
            prefetch_future = None
        else:
            _snap_future = snap_pool.submit(reader.snapshot)
            try:
                tree, ref_map, metadata = _snap_future.result(timeout=4.0)
            except Exception:
                if cached_snapshot is not None:
                    tree, ref_map, metadata = cached_snapshot
                else:
                    continue
            cached_snapshot = (tree, ref_map, metadata)
        if verbose:
            print(f'    [timing] observe={time.monotonic()-t_obs:.2f}s')
        last_action_was_no_ui = False
        current_app = metadata.get('app_name', current_app)

        # --- Check stuck ---
        warning = detector.check()
        if warning == 'HARD_STUCK':
            if verbose:
                print(f'  Hard stuck detected — forcing done after {step} steps')
            snap_pool.shutdown(wait=False)
            elapsed = time.monotonic() - t_start
            if step_callback:
                step_callback(step, max_steps, 'done', {'summary': 'Task likely completed but agent got stuck in a loop'}, 'forced done', current_app, ref_map, tree)
            _reflect_and_store(planner, episodic, task, history, 'loop', current_app, verbose)
            return True  # assume task was completed since actions were executing

        # --- Build combined memory ---
        combined_memory = _build_combined_memory(lessons_text, agent_memory)

        # --- Think ---
        t_think = time.monotonic()
        if metadata['perception_mode'] == 'screenshot':
            if metadata.get('screenshot_b64') is None:
                action = {'name': 'stuck', 'input': {'reason': 'Lost connection to WDA on iOS Simulator (screenshot failed).'}}
            else:
                action = planner.next_action_vision(
                    screenshot_b64=metadata['screenshot_b64'],
                    tree=tree,
                    task=task,
                    history=history,
                    metadata=metadata,
                    warning=warning,
                    memory=combined_memory,
                    plan=plan_steps,
                )
        else:
            action = planner.next_action(
                tree=tree,
                task=task,
                history=history,
                metadata=metadata,
                warning=warning,
                memory=combined_memory,
                plan=plan_steps,
            )
        think_time = time.monotonic() - t_think

        action_name = action['name']
        action_input = action['input']

        if verbose:
            reasoning = action_input.get('reasoning', action_input.get('summary', action_input.get('reason', '')))
            print(f'  Step {step}: {action_name} — {reasoning}')
            print(f'    [timing] think={think_time:.2f}s')

        # --- Handle special actions ---
        if action_name == 'remember':
            key = action_input['key']
            value = action_input['value']
            agent_memory.store(key, value)
            history.append(f'Step {step}: remember {key}={value}')
            if verbose:
                print(f'    Stored: {key} = {value}')
            last_action_was_no_ui = True
            continue

        if action_name == 'plan':
            plan_steps = action_input.get('steps', [])
            history.append(f'Step {step}: plan ({len(plan_steps)} steps)')
            if verbose:
                for i, s in enumerate(plan_steps, 1):
                    print(f'    {i}. {s}')
            last_action_was_no_ui = True
            continue

        if action_name == 'handoff':
            reason = action_input.get('reason', '')
            history.append(f'Step {step}: handoff — {reason}')
            takeover.pause(reason)
            takeover.wait_for_resume()
            # Invalidate snapshots — user has been interacting with device
            cached_snapshot = None
            prefetched_snapshot = None
            continue

        if action_name == 'ask_user':
            question = action_input.get('question', '')
            options = action_input.get('options', [])
            history.append(f'Step {step}: ask_user — {question}')
            if ask_user_fn:
                answer = ask_user_fn(question, options)
            else:
                if verbose and options:
                    for i, opt in enumerate(options, 1):
                        print(f'    {i}. {opt}')
                answer = input(f'    {question}: ').strip()
            history.append(f'  User answered: {answer}')
            if verbose:
                print(f'    User: {answer}')
            last_action_was_no_ui = True
            continue

        if action_name == 'batch':
            actions = action_input.get('actions', [])
            checkpoint = action_input.get('checkpoint_reason', '')
            results = []
            for i, item in enumerate(actions):
                sub_action = item.get('action', item.get('name', ''))
                # Gate check for each sub-action in batch
                if gate.check({'name': sub_action, 'input': item}, ref_map):
                    if not gate.request_confirmation({'name': sub_action, 'input': item}, ref_map):
                        history.append(f'Step {step}: batch sub-action {sub_action} → REJECTED by user')
                        break
                result = executor.run(sub_action, item, ref_map)
                results.append(f'{sub_action} → {result}')
                if verbose:
                    print(f'    [{i+1}/{len(actions)}] {result}')
                if i < len(actions) - 1:
                    time.sleep(_ACTION_SLEEP.get(sub_action, 0.3))
            history.append(f'Step {step}: batch ({len(actions)} actions) → {"; ".join(results)}')
            if checkpoint:
                history.append(f'CHECKPOINT: verify {checkpoint}')
            if step_callback:
                detail = checkpoint or f'batch of {len(actions)} actions'
                step_callback(step, max_steps, 'batch', {'reasoning': detail}, '; '.join(results), current_app, ref_map, tree)
            detector.record(tree, 'batch', None)
            last_action_was_no_ui = False
            sleep_time = _ACTION_SLEEP.get(actions[-1].get('action', ''), 0.3) if actions else 0.3
            if sleep_time > 0:
                time.sleep(sleep_time)
            prefetch_future = snap_pool.submit(reader.snapshot)
            continue

        # --- Confirmation gate ---
        if gate.check({'name': action_name, 'input': action_input}, ref_map):
            if not gate.request_confirmation({'name': action_name, 'input': action_input}, ref_map):
                history.append(f'Step {step}: {action_name} → REJECTED by user')
                continue

        # --- Act ---
        result = executor.run(action_name, action_input, ref_map)
        history.append(f'Step {step}: {action_name} → {result}')

        if verbose:
            print(f'    → {result}')

        if step_callback:
            step_callback(step, max_steps, action_name, action_input, result, current_app, ref_map, tree)

        # On ref errors, invalidate cache+prefetch so next step gets a fresh snapshot
        if 'ref' in str(result).lower() and 'not found' in str(result).lower():
            cached_snapshot = None
            prefetch_future = None

        # Record for stuck detection
        detector.record(tree, action_name, action_input.get('ref'))

        # --- Check terminal ---
        if action_name in _TERMINAL:
            snap_pool.shutdown(wait=False)
            elapsed = time.monotonic() - t_start
            if verbose:
                print(f'  Finished in {step} steps, {elapsed:.1f}s')
            if action_name == 'stuck':
                _reflect_and_store(planner, episodic, task, history, 'stuck', current_app, verbose)
            elif action_name == 'done':
                spectra_path = getattr(planner, 'current_record_path', None)
                if not spectra_path:
                    spectra_path = os.path.expanduser(f'~/.spectra/flows/{uuid.uuid4()}.spectra')
                
                desc = _summarize_task(history, task, planner)
                ep = Episode(
                    id=str(uuid.uuid4()), task_description=desc,
                    spectra_path=spectra_path, step_count=step,
                    app_bundle_id=start_ctx.app_bundle_id, visible_labels=start_ctx.visible_labels,
                    location_lat=start_ctx.location_lat, location_lng=start_ctx.location_lng,
                    location_label=None, hour_of_day=start_ctx.hour_of_day,
                    day_of_week=start_ctx.day_of_week, created_at=start_ctx.captured_at,
                    occurrence_count=1, last_suggested_at=None, last_suggestion_accepted=None
                )
                try:
                    EpisodeStore().save_episode(ep)
                except Exception as e:
                    print(f"  [Error saving episode: {e}]")
                    
            return action_name == 'done'

        # Submit prefetch BEFORE sleep so snapshot runs in parallel with UI settle time.
        sleep_time = _ACTION_SLEEP.get(action_name, 0.3)
        prefetch_future = snap_pool.submit(reader.snapshot)
        if sleep_time > 0:
            time.sleep(sleep_time)

    snap_pool.shutdown(wait=False)
    elapsed = time.monotonic() - t_start
    if verbose:
        print(f'  Timed out after {max_steps} steps, {elapsed:.1f}s')
    _reflect_and_store(planner, episodic, task, history, 'timeout', current_app, verbose)
    agent_memory.clear()
    return False


def run_task(
    user_input: str,
    max_steps: int = 25,
    wda_url: str = 'http://localhost:8100',
    verbose: bool = True,
) -> bool:
    """Top-level entry point — routes task, previews plan, runs agent across app(s).

    Args:
        user_input: Natural language instruction from the user.
        max_steps: Maximum actions per app.
        wda_url: WDA server URL.
        verbose: Print progress to stdout.

    Returns:
        True if task completed successfully.
    """
    planner = Planner()
    executor = Executor(wda_url)
    router = TaskRouter(planner)
    preview = PlanPreview(planner)
    agent_memory = AgentMemory()

    # 1. Route task to correct app(s)
    route = router.route(user_input)
    if verbose:
        print(f'  Route: {route["category"]} → {[a["name"] for a in route["apps"]]}')

    plan_steps = None

    # 2. Generate and preview plan for complex tasks
    if route['multi_app'] or route.get('comparison'):
        plan = preview.generate_plan(route['refined_task'])
        approved, plan = preview.present_and_confirm(plan)
        if not approved:
            if verbose:
                print('  Plan rejected by user')
            return False
        plan_steps = plan

    # 3. Run agent loop for each target app
    apps = route.get('apps') or []
    if not apps:
        # No specific app — run agent directly (e.g. home screen task)
        return run_agent(
            route['refined_task'], max_steps=max_steps, wda_url=wda_url,
            verbose=verbose, agent_memory=agent_memory, plan_steps=plan_steps,
        )

    success = False
    for app in apps:
        if verbose:
            print(f'\n  Opening {app["name"]}...')
        executor.open_app(app['bundle_id'])
        success = run_agent(
            route['refined_task'], max_steps=max_steps, wda_url=wda_url,
            verbose=verbose, agent_memory=agent_memory, plan_steps=plan_steps,
        )

    agent_memory.clear()
    return success

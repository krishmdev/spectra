"""Agent loop — observe → think → act cycle tying all modules together."""

import time

from core.tree_reader import TreeReader
from core.planner import Planner
from core.executor import Executor
from core.stuck_detector import StuckDetector

# Terminal actions that end the loop
_TERMINAL = {'done', 'stuck'}

# Non-UI actions that don't change the screen — skip re-snapshot after these
_NO_UI_ACTIONS = {'remember', 'plan'}

# Adaptive sleep: action → seconds to wait for UI to settle
_ACTION_SLEEP = {
    'tap': 0.3,
    'tap_xy': 0.3,
    'scroll': 0.4,
    'type_text': 0.4,
    'go_back': 0.5,
    'go_home': 0.5,
    'wait': 0,       # the wait action itself handles the delay
    'done': 0,
    'stuck': 0,
}


def run_agent(
    task: str,
    max_steps: int = 15,
    wda_url: str = 'http://localhost:8100',
    verbose: bool = True,
) -> bool:
    """Execute a natural language task on the iOS simulator.

    Args:
        task: Natural language instruction (e.g. "Turn on Dark Mode")
        max_steps: Maximum actions before timeout
        wda_url: WDA server URL
        verbose: Print each step to stdout

    Returns:
        True if task completed (done), False if stuck or timed out
    """
    reader = TreeReader(wda_url)
    planner = Planner()
    executor = Executor(wda_url)
    detector = StuckDetector()

    history: list[str] = []
    plan_steps: list[str] | None = None
    # Snapshot cache — reused when last action didn't change the screen
    cached_snapshot: tuple | None = None
    last_action_was_no_ui = False

    t_start = time.monotonic()

    for step in range(1, max_steps + 1):
        # --- Observe (skip WDA round-trip if nothing changed) ---
        if last_action_was_no_ui and cached_snapshot is not None:
            tree, ref_map, metadata = cached_snapshot
        else:
            tree, ref_map, metadata = reader.snapshot()
            cached_snapshot = (tree, ref_map, metadata)
        last_action_was_no_ui = False

        # --- Check stuck ---
        warning = detector.check()

        # --- Think ---
        if metadata['perception_mode'] == 'screenshot':
            action = planner.next_action_vision(
                screenshot_b64=metadata['screenshot_b64'],
                tree=tree,
                task=task,
                history=history,
                metadata=metadata,
                warning=warning,
                plan=plan_steps,
            )
        else:
            action = planner.next_action(
                tree=tree,
                task=task,
                history=history,
                metadata=metadata,
                warning=warning,
                plan=plan_steps,
            )

        action_name = action['name']
        action_input = action['input']

        if verbose:
            reasoning = action_input.get('reasoning', action_input.get('summary', action_input.get('reason', '')))
            print(f'  Step {step}: {action_name} — {reasoning}')

        # --- Handle special actions ---
        if action_name == 'remember':
            key = action_input['key']
            value = action_input['value']
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
            if verbose:
                print(f'    HANDOFF: {reason}')
            return False  # For now, handoff ends the loop

        # --- Act ---
        result = executor.run(action_name, action_input, ref_map)
        history.append(f'Step {step}: {action_name} → {result}')

        if verbose:
            print(f'    → {result}')

        # Record for stuck detection
        detector.record(tree, action_name, action_input.get('ref'))

        # --- Check terminal ---
        if action_name in _TERMINAL:
            elapsed = time.monotonic() - t_start
            if verbose:
                print(f'  Finished in {step} steps, {elapsed:.1f}s')
            return action_name == 'done'

        # Wait for UI to settle — adaptive per action type
        time.sleep(_ACTION_SLEEP.get(action_name, 0.5))

    elapsed = time.monotonic() - t_start
    if verbose:
        print(f'  Timed out after {max_steps} steps, {elapsed:.1f}s')
    return False

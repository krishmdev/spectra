"""WebSocket server — bridges the iOS app and the Python agent backend."""
from __future__ import annotations

import asyncio
import json
import threading
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from core.agent import run_agent
from core.executor import Executor
from core.gates import ConfirmationGate
from core.memory import AgentMemory
from core.plan_preview import PlanPreview
from core.planner import Planner
from core.router import TaskRouter
from core.takeover import TakeoverManager

app = FastAPI(title='Spectra WebSocket Server')


# ---------------------------------------------------------------------------
# WebSocket-aware subclasses — replace CLI input() with async event signaling
# ---------------------------------------------------------------------------

class WSConfirmationGate(ConfirmationGate):
    """Sends confirm_request via WebSocket and blocks until the client responds."""

    def __init__(self, send_fn, confirm_event, confirm_result):
        super().__init__()
        self._send = send_fn            # callable(dict) → puts msg on outgoing queue
        self._event = confirm_event     # threading.Event
        self._result = confirm_result   # dict with 'approved' key, written by receiver
        self.current_app_bundle: str | None = None  # set by task runner
        self._approved_labels: set = set()  # track already-approved actions

    def request_confirmation(self, action: dict, ref_map: dict) -> bool:
        action_name = action.get('name', '')
        action_input = action.get('input', {})
        ref = action_input.get('ref')
        el = ref_map.get(ref) or ref_map.get(int(ref)) if ref is not None else None
        label = (el.get('label', '') if el else '').lower().strip()

        # Already approved this label in this task — don't ask again
        if label and label in self._approved_labels:
            print(f"[ws] Skipping confirmation for '{label}' — already approved")
            return True

        self._event.clear()
        self._send({
            'type': 'confirm_request',
            'action': action_name,
            'label': el.get('label', '') if el else '',
            'app': '',
            'detail': action_input.get('reasoning', ''),
        })
        # Timeout after 120s to prevent hanging forever
        if not self._event.wait(timeout=120):
            print("[ws] Confirmation timed out — rejecting action")
            return False

        approved = self._result.get('approved', False)

        # Remember this approval so we don't ask again for the same label
        if approved and label:
            self._approved_labels.add(label)

        # After user responds, bring the target app back to foreground
        if approved and self.current_app_bundle:
            try:
                import subprocess
                subprocess.run(
                    ['xcrun', 'simctl', 'launch', 'booted', self.current_app_bundle],
                    capture_output=True, timeout=5,
                )
                import time
                time.sleep(1)  # let the app come to foreground
                print(f"[ws] Switched back to {self.current_app_bundle} after confirmation")
            except Exception:
                pass

        return approved


class WSTakeoverManager(TakeoverManager):
    """Sends handoff_request via WebSocket and blocks until takeover_done."""

    def __init__(self, send_fn, takeover_event):
        super().__init__()
        self._send = send_fn
        self._event = takeover_event    # threading.Event

    def pause(self, reason: str) -> None:
        self._paused = True
        self._send({
            'type': 'handoff_request',
            'reason': reason,
        })

    def wait_for_resume(self) -> None:
        self._event.clear()
        if not self._event.wait(timeout=300):
            print("[ws] Takeover timed out after 5 minutes")
        self._paused = False


class WSAgentMemory(AgentMemory):
    """AgentMemory that sends memory_update messages on store()."""

    def __init__(self, send_fn):
        super().__init__()
        self._send = send_fn

    def store(self, key: str, value: str) -> str:
        result = super().store(key, value)
        self._send({
            'type': 'memory_update',
            'key': key,
            'value': value,
        })
        return result


class WSAskUser:
    """Sends ask_user via WebSocket and blocks until the user responds."""

    def __init__(self, send_fn, ask_event, ask_result):
        self._send = send_fn
        self._event = ask_event
        self._result = ask_result

    def ask(self, question: str, options: list[str]) -> str:
        self._event.clear()
        self._send({
            'type': 'ask_user',
            'question': question,
            'options': options or [],
        })
        if not self._event.wait(timeout=120):
            print("[ws] ask_user timed out — returning empty answer")
            return ''
        return self._result.get('answer', '')


# ---------------------------------------------------------------------------
# Connection state — one per WebSocket session
# ---------------------------------------------------------------------------

class ConnectionState:
    """Holds per-connection synchronization primitives and state."""

    def __init__(self, loop: asyncio.AbstractEventLoop, out_queue: asyncio.Queue):
        self.loop = loop
        self.out_queue = out_queue

        # Threading events for cross-thread sync (agent thread ↔ async WS loop)
        self.confirm_event = threading.Event()
        self.confirm_result: dict = {}
        self.plan_event = threading.Event()
        self.plan_result: dict = {}
        self.takeover_event = threading.Event()
        self.ask_event = threading.Event()
        self.ask_result: dict = {}
        self.stop_event = threading.Event()
        self.task_running = False
        self.voice_thread: threading.Thread | None = None

    def send(self, msg: dict) -> None:
        """Thread-safe: enqueue a message for the WebSocket sender."""
        self.loop.call_soon_threadsafe(self.out_queue.put_nowait, msg)


# ---------------------------------------------------------------------------
# Voice capture (runs in a background thread on the Mac)
# ---------------------------------------------------------------------------

def _voice_listen_thread(state: ConnectionState) -> None:
    """Record from the Mac's microphone and transcribe with faster-whisper."""
    try:
        from voice.listener import get_listener
        state.send({'type': 'voice_listening'})
        print('[ws] Voice: listening on Mac mic...')

        listener = get_listener()
        result = listener.listen_and_transcribe(timeout=8.0, phrase_time_limit=15.0)

        if result['success']:
            print(f'[ws] Voice transcript: {result["transcript"]}')
            state.send({'type': 'voice_result', 'transcript': result['transcript']})
        else:
            print(f'[ws] Voice error: {result["error"]}')
            state.send({'type': 'voice_error', 'error': result['error']})
    except Exception as e:
        print(f'[ws] Voice exception: {e}')
        state.send({'type': 'voice_error', 'error': str(e)})


# ---------------------------------------------------------------------------
# Agent task runner (runs in a background thread)
# ---------------------------------------------------------------------------

def _run_task_in_thread(
    task: str,
    plan_steps: list[str] | None,
    state: ConnectionState,
    wda_url: str = 'http://localhost:8100',
    max_steps: int | None = None,
) -> None:
    """Execute the full route → plan → agent flow in a thread."""
    import traceback
    print(f"[ws] Task thread started: {task!r}")
    try:
        planner = Planner()
        router = TaskRouter(planner)
        executor = Executor(wda_url)

        gate = WSConfirmationGate(state.send, state.confirm_event, state.confirm_result)
        takeover = WSTakeoverManager(state.send, state.takeover_event)
        memory = WSAgentMemory(state.send)
        ask_user = WSAskUser(state.send, state.ask_event, state.ask_result)

        # 1. Route
        print(f"[ws] Routing task...")
        route = router.route(task)
        refined = route['refined_task']
        gate.set_task(refined)

        # Decide max_steps based on task complexity
        if max_steps is None:
            task_lower = refined.lower()
            multi_part = route.get('multi_app') or route.get('comparison')
            has_conjunctions = any(w in task_lower for w in [' and ', ' then ', ' after that', ' also '])
            if multi_part or has_conjunctions:
                max_steps = 25
            else:
                max_steps = 15
        print(f"[ws] Route: {route['category']} → {[a['name'] for a in route.get('apps', [])]} (max_steps={max_steps})")

        # 2. Plan preview for complex tasks
        if plan_steps is None and (route['multi_app'] or route.get('comparison')):
            preview = PlanPreview(planner)
            steps = preview.generate_plan(refined)
            state.send({
                'type': 'plan_preview',
                'steps': steps,
                'task': refined,
            })
            # Wait for plan_approve from client
            state.plan_event.clear()
            state.plan_event.wait()
            if state.stop_event.is_set():
                return
            if not state.plan_result.get('approved', False):
                state.send({'type': 'done', 'success': False, 'summary': 'Plan rejected', 'steps': 0, 'duration': 0})
                return
            plan_steps = state.plan_result.get('modified_steps') or steps

        # 3. Step callback — sends status messages
        t_start = time.monotonic()
        step_counter = [0]

        def step_callback(step, total, action_name, action_input, result, current_app):
            step_counter[0] = step
            detail = action_input.get('reasoning', action_input.get('summary', ''))
            state.send({
                'type': 'status',
                'step': step,
                'total': total,
                'action': action_name,
                'detail': str(result) if not detail else detail,
                'app': current_app,
            })

        # 4. Run agent for each target app (or once if no specific app)
        apps = route.get('apps') or []
        success = False

        if not apps:
            success = run_agent(
                refined,
                max_steps=max_steps,
                wda_url=wda_url,
                verbose=True,
                agent_memory=memory,
                plan_steps=plan_steps,
                stop_check=state.stop_event.is_set,
                gate=gate,
                takeover=takeover,
                step_callback=step_callback,
                ask_user_fn=ask_user.ask,
            )
        else:
            for app_info in apps:
                gate.current_app_bundle = app_info['bundle_id']
                executor.open_app(app_info['bundle_id'])
                success = run_agent(
                    refined,
                    max_steps=max_steps,
                    wda_url=wda_url,
                    verbose=True,
                    agent_memory=memory,
                    plan_steps=plan_steps,
                    stop_check=state.stop_event.is_set,
                    gate=gate,
                    takeover=takeover,
                    step_callback=step_callback,
                    ask_user_fn=ask_user.ask,
                )
                if state.stop_event.is_set():
                    break

        elapsed = time.monotonic() - t_start
        memory.clear()

        # Send result FIRST so the app receives it before being brought to foreground
        if state.stop_event.is_set():
            state.send({'type': 'done', 'success': False, 'summary': 'Stopped by user', 'steps': 0, 'duration': round(elapsed, 1)})
        elif success:
            state.send({'type': 'done', 'success': True, 'summary': f'Completed: {task}', 'steps': step_counter[0], 'duration': round(elapsed, 1)})
        else:
            state.send({'type': 'stuck', 'reason': 'Agent could not complete the task'})

        # Brief pause to let the message deliver, then bring Spectra back
        time.sleep(0.5)
        try:
            import subprocess
            subprocess.run(
                ['xcrun', 'simctl', 'launch', 'booted', 'com.spectra.agent'],
                capture_output=True, timeout=5,
            )
            print("[ws] Returned to Spectra app")
        except Exception:
            pass

    except Exception as e:
        print(f"[ws] ERROR in task thread: {e}")
        traceback.print_exc()
        state.send({'type': 'error', 'message': str(e)})
    finally:
        print("[ws] Task thread finished")
        state.task_running = False


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@app.websocket('/ws')
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    print("[ws] Connection opened")
    loop = asyncio.get_event_loop()
    out_queue: asyncio.Queue = asyncio.Queue()
    state = ConnectionState(loop, out_queue)

    # Sender task — drains outgoing queue and sends JSON over the socket
    async def _sender():
        try:
            while True:
                msg = await out_queue.get()
                if msg is None:
                    break
                await ws.send_json(msg)
        except (WebSocketDisconnect, Exception):
            pass

    sender_task = asyncio.create_task(_sender())

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws.send_json({'type': 'error', 'message': 'Invalid JSON'})
                continue

            msg_type = msg.get('type')

            print(f"[ws] Received: {msg_type} — {json.dumps(msg)[:200]}")

            if msg_type == 'command':
                if state.task_running:
                    await ws.send_json({'type': 'error', 'message': 'A task is already running'})
                    continue
                state.task_running = True
                state.stop_event.clear()
                thread = threading.Thread(
                    target=_run_task_in_thread,
                    args=(msg['task'], None, state),
                    daemon=True,
                )
                thread.start()

            elif msg_type == 'voice_start':
                if state.voice_thread and state.voice_thread.is_alive():
                    await ws.send_json({'type': 'voice_error', 'error': 'Already listening'})
                    continue
                state.voice_thread = threading.Thread(
                    target=_voice_listen_thread,
                    args=(state,),
                    daemon=True,
                )
                state.voice_thread.start()

            elif msg_type == 'voice_stop':
                # Voice capture can't be interrupted mid-listen easily,
                # but we acknowledge the stop
                await ws.send_json({'type': 'voice_cancelled'})

            elif msg_type == 'confirm':
                state.confirm_result['approved'] = msg.get('approved', False)
                state.confirm_event.set()

            elif msg_type == 'plan_approve':
                state.plan_result['approved'] = msg.get('approved', False)
                state.plan_result['modified_steps'] = msg.get('modified_steps')
                state.plan_event.set()

            elif msg_type == 'takeover_done':
                state.takeover_event.set()

            elif msg_type == 'user_answer':
                state.ask_result['answer'] = msg.get('answer', '')
                state.ask_event.set()

            elif msg_type == 'stop':
                state.stop_event.set()
                # Also unblock any waiting events so threads don't hang
                state.confirm_event.set()
                state.plan_event.set()
                state.takeover_event.set()
                state.ask_event.set()

            else:
                await ws.send_json({'type': 'error', 'message': f'Unknown message type: {msg_type}'})

    except WebSocketDisconnect as e:
        print(f"[ws] Connection closed by client — code={e.code} reason={e.reason}")
        state.stop_event.set()
        state.confirm_event.set()
        state.plan_event.set()
        state.takeover_event.set()
        state.ask_event.set()
    except Exception as e:
        import traceback
        print(f"[ws] Connection error: {e}")
        traceback.print_exc()
    finally:
        print("[ws] Connection cleanup")
        await out_queue.put(None)
        sender_task.cancel()

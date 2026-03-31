"""One task from request to result: workflow cache, route, plan preview, agent loop.

This used to live inside server/ws_server.py. It is here so the WebSocket
server and the MCP server run the same pipeline and differ only in how they
talk to the user, which goes through `SessionCallbacks`.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Protocol

from core.agent import run_agent
from core.executor import Executor
from core.gates import ConfirmationGate
from core.memory import AgentMemory
from core.plan_preview import PlanPreview
from core.planner import PlannerProtocol, make_planner
from core.router import TaskRouter
from core.takeover import TakeoverManager


class SessionCallbacks(Protocol):
    def event(self, msg: dict) -> None:
        """Progress: status, memory_update, plan_preview messages (same shapes as the WS protocol)."""

    def confirm(self, action: str, label: str, detail: str) -> bool:
        """A sensitive tap or type is about to run. Return True to allow it."""

    def approve_plan(self, task: str, steps: list[str]) -> tuple[bool, list[str] | None]:
        """Approve (optionally edited) plan steps for a multi-app task."""

    def ask(self, question: str, options: list[str]) -> str:
        """The planner needs an answer from the user."""

    def handoff(self, reason: str) -> None:
        """The user has to do something on the device; return when they're done."""


@dataclass
class SessionResult:
    success: bool
    summary: str
    steps: int
    duration: float
    replayed: bool = False
    stopped: bool = False
    plan_rejected: bool = False


class CallbackGate(ConfirmationGate):
    def __init__(self, callbacks: SessionCallbacks):
        super().__init__()
        self._cb = callbacks

    def request_confirmation(self, action: dict, ref_map: dict) -> bool:
        ref = action.get('input', {}).get('ref')
        el = (ref_map.get(ref) or ref_map.get(int(ref))) if ref is not None else None
        return self._cb.confirm(action.get('name', ''), (el or {}).get('label', ''),
                                action.get('input', {}).get('reasoning', ''))


class CallbackTakeover(TakeoverManager):
    def __init__(self, callbacks: SessionCallbacks):
        super().__init__()
        self._cb = callbacks
        self._reason = ''

    def pause(self, reason: str) -> None:
        self._paused = True
        self._reason = reason

    def wait_for_resume(self) -> None:
        self._cb.handoff(self._reason)
        self._paused = False


class CallbackMemory(AgentMemory):
    def __init__(self, callbacks: SessionCallbacks):
        super().__init__()
        self._cb = callbacks

    def store(self, key: str, value: str) -> str:
        out = super().store(key, value)
        self._cb.event({'type': 'memory_update', 'key': key, 'value': value})
        return out


def _flow_path(flows_dir: str, task: str) -> str:
    safe = ''.join(c if c.isalnum() else '_' for c in task)[:40]
    return os.path.join(flows_dir, f'{int(time.time())}_{safe}.spectra')


def run_session(
    task: str,
    callbacks: SessionCallbacks,
    *,
    wda_url: str = 'http://localhost:8100',
    planner: PlannerProtocol | None = None,
    plan_steps: list[str] | None = None,
    max_steps: int | None = None,
    gate: ConfirmationGate | None = None,
    takeover: TakeoverManager | None = None,
    memory: AgentMemory | None = None,
    stop_check=None,
    flows_dir: str = 'flows',
    use_cache: bool = True,
    verbose: bool = True,
) -> SessionResult:
    from recorder.recorder import Recorder
    from recorder.replayer import Replayer
    from core.workflow_matcher import find_matching_workflow

    planner = planner or make_planner()
    gate = gate or CallbackGate(callbacks)
    takeover = takeover or CallbackTakeover(callbacks)
    memory = memory if memory is not None else CallbackMemory(callbacks)
    stop_check = stop_check or (lambda: False)
    filename = _flow_path(flows_dir, task)
    recorder = Recorder(filename, task=task)
    t_start = time.monotonic()
    try:
        # 0. Saved workflow? Replay it (through the gate) and skip the model.
        match_id = find_matching_workflow(task, planner, flows_dir, exclude=filename) if use_cache else None
        if match_id:
            callbacks.event({'type': 'status', 'step': 0, 'total': 0, 'action': 'fast_forward',
                             'detail': 'Found exact saved workflow — fast-forwarding...', 'app': 'Spectra'})

            def replay_callback(step, total, action, success, detail):
                callbacks.event({'type': 'status', 'step': step, 'total': total, 'action': action,
                                 'detail': f"{'✅' if success else '❌'} {detail}", 'app': ''})

            gate.set_task(task)
            report = Replayer(match_id, wda_url=wda_url, step_delay=0.4, gate=gate, planner=planner,
                              verbose=verbose).run(step_callback=replay_callback)
            if report.failed == 0:
                recorder.close()
                os.remove(filename)
                recorder = None
                return SessionResult(True, f'Completed via fast-forward replay: {task}', report.passed,
                                     round(report.duration, 1), replayed=True)
            callbacks.event({'type': 'status', 'step': 0, 'total': 0, 'action': 'fallback',
                             'detail': 'Screen structure shifted or drifted. Falling back to intelligent '
                                       'LLM execution...', 'app': 'Spectra'})

        # 1. Route
        route = TaskRouter(planner).route(task)
        refined = route['refined_task']
        gate.set_task(refined)
        if max_steps is None:
            lower = refined.lower()
            multi = route.get('multi_app') or route.get('comparison')
            joined = any(w in lower for w in (' and ', ' then ', ' after that', ' also '))
            max_steps = 25 if multi or joined else 15

        # 2. Plan preview for multi-app work
        if plan_steps is None and (route['multi_app'] or route.get('comparison')):
            steps = PlanPreview(planner).generate_plan(refined)
            approved, edited = callbacks.approve_plan(refined, steps)
            if stop_check():
                return SessionResult(False, 'Stopped by user', 0, 0.0, stopped=True)
            if not approved:
                return SessionResult(False, 'Plan rejected', 0, 0.0, plan_rejected=True)
            plan_steps = edited or steps

        # 3. Agent loop, once per routed app
        counter = [0]

        def step_callback(step, total, action_name, action_input, result, current_app, ref_map, tree):
            counter[0] = step
            if recorder:
                recorder.record(step, action_name, action_input, ref_map, tree)
            detail = action_input.get('reasoning', action_input.get('summary', ''))
            callbacks.event({'type': 'status', 'step': step, 'total': total, 'action': action_name,
                             'detail': str(result) if not detail else detail, 'app': current_app})

        kwargs = dict(max_steps=max_steps, wda_url=wda_url, verbose=verbose, agent_memory=memory,
                      plan_steps=plan_steps, stop_check=stop_check, gate=gate, takeover=takeover,
                      step_callback=step_callback, ask_user_fn=callbacks.ask, planner=planner)
        apps = route.get('apps') or []
        success = False
        if not apps:
            success = run_agent(refined, **kwargs)
        else:
            executor = Executor(wda_url)
            for app_info in apps:
                if hasattr(gate, 'current_app_bundle'):
                    gate.current_app_bundle = app_info['bundle_id']
                executor.open_app(app_info['bundle_id'])
                # The router's launch is part of the flow; without it a replay starts on
                # whatever screen happens to be up.
                recorder.record(0, 'open_app', {'bundle_id': app_info['bundle_id']}, {}, '')
                success = run_agent(refined, **kwargs)
                if stop_check():
                    break
        memory.clear()
        elapsed = round(time.monotonic() - t_start, 1)
        if stop_check():
            return SessionResult(False, 'Stopped by user', 0, elapsed, stopped=True)
        summary = f'Completed: {task}' if success else 'Agent could not complete the task'
        return SessionResult(success, summary, counter[0], elapsed)
    finally:
        if recorder:
            recorder.close()

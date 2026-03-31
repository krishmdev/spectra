"""Run one task through an arm's own server pipeline and write metrics as JSON.

This file is copied into each trial directory and executed there with the arm's
code on sys.path, so it must not import anything from this repo except what the
arm itself provides. It only instruments; it does not patch behaviour:

- google.genai Models.generate_content is wrapped to count calls and tokens;
- StuckDetector.check is wrapped to count loop warnings;
- a stand-in for the WebSocket connection approves plans and confirmations and
  answers ask_user with an empty string, the way a user tapping "OK" would.

It then calls server.ws_server._run_task_in_thread(), the same function the
iOS app triggers (workflow cache -> route -> plan preview -> agent loop).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import traceback


class AnswerEvent(threading.Event):
    """An Event whose answer survives a clear() that races it.

    The server sometimes sends a request and then clears the event before
    waiting (plan preview does). An answer given in between would be lost with
    a plain Event; here clear() keeps a pending answer until a wait() takes it.
    """

    def __init__(self):
        super().__init__()
        self._pending = False
        self._lock = threading.Lock()

    def answer(self) -> None:
        with self._lock:
            self._pending = True
            super().set()

    def clear(self) -> None:
        with self._lock:
            if not self._pending:
                super().clear()

    def wait(self, timeout=None) -> bool:
        ok = super().wait(timeout)
        with self._lock:
            self._pending = False
        return ok


class AutoState:
    """Duck-typed replacement for ws_server.ConnectionState."""

    def __init__(self):
        self.confirm_event = AnswerEvent()
        self.confirm_result: dict = {}
        self.plan_event = AnswerEvent()
        self.plan_result: dict = {}
        self.takeover_event = AnswerEvent()
        self.ask_event = AnswerEvent()
        self.ask_result: dict = {}
        self.stop_event = threading.Event()
        self.screen_update_event = threading.Event()
        self.screen_update_data: dict = {}
        self.task_running = True
        self.messages: list[dict] = []

    def send(self, msg: dict) -> None:
        self.messages.append(msg)
        kind = msg.get('type')
        if kind == 'confirm_request':
            self.confirm_result['approved'] = True
            self.confirm_event.answer()
        elif kind == 'plan_preview':
            self.plan_result.update(approved=True, modified_steps=None)
            self.plan_event.answer()
        elif kind == 'ask_user':
            self.ask_result['answer'] = ''
            self.ask_event.answer()
        elif kind == 'handoff_request':
            self.takeover_event.answer()


def _instrument(stats: dict) -> None:
    lock = threading.Lock()
    try:
        from google.genai import models as genai_models
    except ImportError:
        genai_models = None
    if genai_models is not None:
        orig = genai_models.Models.generate_content

        def generate_content(self, *args, **kwargs):
            t0 = time.monotonic()
            try:
                resp = orig(self, *args, **kwargs)
            except Exception as e:
                with lock:
                    stats['llm_calls'] += 1
                    stats['llm_errors'] += 1
                    stats['llm_error_samples'] = (stats['llm_error_samples'] + [str(e)[:160]])[:3]
                raise
            u = getattr(resp, 'usage_metadata', None)
            with lock:
                stats['llm_calls'] += 1
                stats['llm_seconds'] += time.monotonic() - t0
                if u is not None:
                    stats['prompt_tokens'] += u.prompt_token_count or 0
                    stats['cached_tokens'] += getattr(u, 'cached_content_token_count', 0) or 0
                    stats['output_tokens'] += u.candidates_token_count or 0
                    stats['thought_tokens'] += getattr(u, 'thoughts_token_count', 0) or 0
            return resp

        genai_models.Models.generate_content = generate_content

        try:
            from google.genai import caches as genai_caches
            orig_create = genai_caches.Caches.create

            def create(self, *args, **kwargs):
                with lock:
                    stats['cache_creates'] += 1
                return orig_create(self, *args, **kwargs)

            genai_caches.Caches.create = create
        except (ImportError, AttributeError):
            pass

    try:
        from core.scripted_planner import ScriptedPlanner
        orig_record = ScriptedPlanner._record

        def _record(self, kind, **info):
            with lock:
                stats['llm_calls'] += 1
            return orig_record(self, kind, **info)

        ScriptedPlanner._record = _record
    except ImportError:
        pass

    from core.stuck_detector import StuckDetector
    orig_check = StuckDetector.check

    def check(self):
        w = orig_check(self)
        if w:
            with lock:
                stats['stuck_warnings'] += 1
                if w == 'HARD_STUCK':
                    stats['hard_stuck'] += 1
        return w

    StuckDetector.check = check

    from core.tree_reader import TreeReader
    orig_snapshot = TreeReader.snapshot

    def snapshot(self):
        out = orig_snapshot(self)
        mode = out[2].get('perception_mode', '?')
        with lock:
            stats['perception_modes'][mode] = stats['perception_modes'].get(mode, 0) + 1
        return out

    TreeReader.snapshot = snapshot


def _egress_canary() -> dict:
    # Same check as sim/egress.py, inlined because this file runs inside old trees too.
    import socket
    opened = []
    for host, port in [('1.1.1.1', 443), ('generativelanguage.googleapis.com', 443), ('huggingface.co', 443)]:
        try:
            socket.create_connection((host, port), timeout=3).close()
            opened.append(f'{host}:{port}')
        except OSError:
            pass
    return {'ran': True, 'pid': os.getpid(), 'blocked': not opened, 'open': opened}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--task', required=True)
    ap.add_argument('--wda-url', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args(argv)

    sys.path.insert(0, os.getcwd())
    stats = {'llm_calls': 0, 'llm_errors': 0, 'llm_error_samples': [], 'llm_seconds': 0.0,
             'prompt_tokens': 0, 'cached_tokens': 0, 'output_tokens': 0, 'thought_tokens': 0,
             'cache_creates': 0, 'stuck_warnings': 0, 'hard_stuck': 0, 'perception_modes': {}}
    result: dict = {'task': args.task}
    if os.environ.get('SPECTRA_EGRESS_CANARY') == '1':
        result['egress_canary'] = _egress_canary()
        if not result['egress_canary']['blocked']:
            result['error'] = 'egress canary: external connect succeeded inside the agent process'
            with open(args.out, 'w') as f:
                json.dump(result, f, indent=2)
            return 3
    t0 = time.monotonic()
    try:
        _instrument(stats)
        import server.ws_server as ws
        state = AutoState()
        ws._run_task_in_thread(args.task, None, state, wda_url=args.wda_url)
        msgs = state.messages
        done = next((m for m in reversed(msgs) if m.get('type') == 'done'), None)
        result.update(
            agent_done=bool(done and done.get('success')),
            agent_stuck=any(m.get('type') == 'stuck' for m in msgs),
            error=next((m.get('message') for m in msgs if m.get('type') == 'error'), None),
            steps=(done or {}).get('steps') or max((m.get('step', 0) for m in msgs if m.get('type') == 'status'),
                                                   default=0),
            confirmations=sum(m.get('type') == 'confirm_request' for m in msgs),
            plan_previews=sum(m.get('type') == 'plan_preview' for m in msgs),
            replayed=any(m.get('type') == 'status' and m.get('action') == 'fast_forward' for m in msgs),
            actions=[m.get('action') for m in msgs if m.get('type') == 'status'],
        )
    except Exception as e:
        result['error'] = f'{type(e).__name__}: {e}'
        result['traceback'] = traceback.format_exc()[-2000:]
    result['wall_seconds'] = round(time.monotonic() - t0, 3)
    result.update(stats)
    with open(args.out, 'w') as f:
        json.dump(result, f, indent=2)
    return 0


if __name__ == '__main__':
    sys.exit(main())

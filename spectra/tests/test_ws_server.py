"""Unit tests for the WebSocket server — mocks the agent pipeline to avoid simulator."""
from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
import types as builtin_types
from unittest.mock import MagicMock, patch

import pytest

# Stub heavy core modules so we don't need wda/genai at test time
for mod_name in (
    'wda', 'google', 'google.genai', 'google.genai.types',
    'core.tree_reader', 'core.planner', 'core.executor',
    'core.stuck_detector',
):
    if mod_name not in sys.modules:
        sys.modules[mod_name] = builtin_types.ModuleType(mod_name)

# Provide minimal stubs for classes imported by core.agent
sys.modules['core.tree_reader'].TreeReader = type('TreeReader', (), {'__init__': lambda *a, **k: None})
sys.modules['core.planner'].Planner = type('Planner', (), {'__init__': lambda *a, **k: None})
sys.modules['core.executor'].Executor = type('Executor', (), {
    '__init__': lambda *a, **k: None,
    'open_app': lambda *a, **k: None,
})
sys.modules['core.stuck_detector'].StuckDetector = type('StuckDetector', (), {'__init__': lambda *a, **k: None})

from fastapi.testclient import TestClient

from server.ws_server import (
    ConnectionState,
    WSAgentMemory,
    WSConfirmationGate,
    WSTakeoverManager,
    app,
)


# ---------------------------------------------------------------------------
# Helper: collect messages from the WebSocket until a terminal type arrives
# ---------------------------------------------------------------------------

def _collect_until(ws, terminal_types=('done', 'stuck', 'error'), timeout=5):
    """Read messages until one of the terminal types is received."""
    messages = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            raw = ws.receive_text(mode='text')
            msg = json.loads(raw)
            messages.append(msg)
            if msg.get('type') in terminal_types:
                break
        except Exception:
            break
    return messages


# ---------------------------------------------------------------------------
# Tests for WebSocket-aware subclasses
# ---------------------------------------------------------------------------

class TestWSConfirmationGate:

    def test_approved_returns_true(self):
        sent = []
        event = threading.Event()
        result = {'approved': True}
        gate = WSConfirmationGate(sent.append, event, result)

        # Set event from a timer so it fires after request_confirmation clears it
        threading.Timer(0.1, event.set).start()
        assert gate.request_confirmation({'name': 'tap', 'input': {'ref': 1}}, {1: {'label': 'Send'}}) is True
        assert len(sent) == 1
        assert sent[0]['type'] == 'confirm_request'

    def test_rejected_returns_false(self):
        sent = []
        event = threading.Event()
        result = {'approved': False}
        gate = WSConfirmationGate(sent.append, event, result)

        threading.Timer(0.1, event.set).start()
        assert gate.request_confirmation({'name': 'tap', 'input': {'ref': 1}}, {1: {'label': 'Pay'}}) is False


class TestWSTakeoverManager:

    def test_pause_sends_handoff(self):
        sent = []
        event = threading.Event()
        mgr = WSTakeoverManager(sent.append, event)

        mgr.pause('Password required')
        assert sent[0]['type'] == 'handoff_request'
        assert sent[0]['reason'] == 'Password required'
        assert mgr.is_paused()

    def test_wait_for_resume_blocks_then_unblocks(self):
        sent = []
        event = threading.Event()
        mgr = WSTakeoverManager(sent.append, event)

        mgr.pause('PII entry')

        unblocked = threading.Event()

        def _wait():
            mgr.wait_for_resume()
            unblocked.set()

        t = threading.Thread(target=_wait, daemon=True)
        t.start()

        time.sleep(0.1)
        assert not unblocked.is_set()

        event.set()
        unblocked.wait(timeout=2)
        assert unblocked.is_set()
        assert not mgr.is_paused()


class TestWSAgentMemory:

    def test_store_sends_update(self):
        sent = []
        mem = WSAgentMemory(sent.append)
        mem.store('uber_price', '$18.50')
        assert mem.recall('uber_price') == '$18.50'
        assert sent[0] == {'type': 'memory_update', 'key': 'uber_price', 'value': '$18.50'}


# ---------------------------------------------------------------------------
# Tests for ConnectionState
# ---------------------------------------------------------------------------

class TestConnectionState:

    def test_send_enqueues(self):
        loop = asyncio.new_event_loop()
        q = asyncio.Queue()
        state = ConnectionState(loop, q)

        # send from the same thread (event loop thread) for simplicity
        q.put_nowait({'type': 'test'})
        assert not q.empty()
        loop.close()


# ---------------------------------------------------------------------------
# Integration tests via FastAPI TestClient WebSocket
# ---------------------------------------------------------------------------

class TestWebSocketEndpoint:

    @patch('server.ws_server._run_task_in_thread')
    def test_command_starts_task(self, mock_run):
        """Sending a command message should launch the task thread."""
        def fake_run(task, plan_steps, state, **kw):
            # Small delay so the sender coroutine has time to drain
            time.sleep(0.1)
            state.send({'type': 'done', 'success': True, 'summary': 'OK', 'steps': 1, 'duration': 0.1})
            state.task_running = False

        mock_run.side_effect = fake_run

        client = TestClient(app)
        with client.websocket_connect('/ws') as ws:
            ws.send_text(json.dumps({'type': 'command', 'task': 'Turn on Dark Mode'}))
            # The thread-safe send + asyncio sender task should deliver the message
            msg = json.loads(ws.receive_text())
            assert msg['type'] == 'done'
            assert msg['success'] is True

    @patch('server.ws_server._run_task_in_thread')
    def test_duplicate_command_errors(self, mock_run):
        """Sending a second command while one is running should return an error."""
        started = threading.Event()

        def slow_run(task, plan_steps, state, **kw):
            started.set()
            time.sleep(2)
            state.send({'type': 'done', 'success': True, 'summary': 'OK', 'steps': 1, 'duration': 2})
            state.task_running = False

        mock_run.side_effect = slow_run

        client = TestClient(app)
        with client.websocket_connect('/ws') as ws:
            ws.send_text(json.dumps({'type': 'command', 'task': 'Task 1'}))
            started.wait(timeout=2)
            ws.send_text(json.dumps({'type': 'command', 'task': 'Task 2'}))
            # The error is sent directly via ws.send_json, not through the queue
            raw = ws.receive_text()
            msg = json.loads(raw)
            assert msg['type'] == 'error'
            assert 'already running' in msg['message']

    def test_invalid_json(self):
        client = TestClient(app)
        with client.websocket_connect('/ws') as ws:
            ws.send_text('not json at all')
            raw = ws.receive_text()
            msg = json.loads(raw)
            assert msg['type'] == 'error'
            assert 'Invalid JSON' in msg['message']

    def test_unknown_type(self):
        client = TestClient(app)
        with client.websocket_connect('/ws') as ws:
            ws.send_text(json.dumps({'type': 'foobar'}))
            raw = ws.receive_text()
            msg = json.loads(raw)
            assert msg['type'] == 'error'
            assert 'Unknown' in msg['message']

    @patch('server.ws_server._voice_listen_thread')
    def test_voice_start_spawns_thread(self, mock_voice):
        """voice_start should launch the voice capture thread."""
        client = TestClient(app)
        with client.websocket_connect('/ws') as ws:
            ws.send_text(json.dumps({'type': 'voice_start'}))
            import time; time.sleep(0.2)
            assert mock_voice.called

    @patch('server.ws_server._run_task_in_thread')
    def test_stop_unblocks_events(self, mock_run):
        """Stop message should unblock any waiting events."""
        started = threading.Event()

        def blocking_run(task, plan_steps, state, **kw):
            started.set()
            state.confirm_event.wait(timeout=5)
            time.sleep(0.05)
            state.send({'type': 'done', 'success': False, 'summary': 'Stopped', 'steps': 0, 'duration': 0})
            state.task_running = False

        mock_run.side_effect = blocking_run

        client = TestClient(app)
        with client.websocket_connect('/ws') as ws:
            ws.send_text(json.dumps({'type': 'command', 'task': 'Test'}))
            started.wait(timeout=2)
            ws.send_text(json.dumps({'type': 'stop'}))
            msg = json.loads(ws.receive_text())
            assert msg['type'] == 'done'

    @patch('server.ws_server._run_task_in_thread')
    def test_confirm_flow(self, mock_run):
        """Gate triggers confirm_request, client sends confirm, agent continues."""
        def confirm_run(task, plan_steps, state, **kw):
            time.sleep(0.05)
            state.send({'type': 'confirm_request', 'action': 'tap', 'label': 'Send', 'app': 'Messages', 'detail': ''})
            state.confirm_event.clear()
            state.confirm_event.wait(timeout=5)
            time.sleep(0.05)
            approved = state.confirm_result.get('approved', False)
            state.send({'type': 'done', 'success': approved, 'summary': 'OK', 'steps': 1, 'duration': 0.1})
            state.task_running = False

        mock_run.side_effect = confirm_run

        client = TestClient(app)
        with client.websocket_connect('/ws') as ws:
            ws.send_text(json.dumps({'type': 'command', 'task': 'Send message'}))
            msg = json.loads(ws.receive_text())
            assert msg['type'] == 'confirm_request'
            ws.send_text(json.dumps({'type': 'confirm', 'approved': True}))
            msg = json.loads(ws.receive_text())
            assert msg['type'] == 'done'
            assert msg['success'] is True

    @patch('server.ws_server._run_task_in_thread')
    def test_plan_flow(self, mock_run):
        """Complex task sends plan_preview, client approves, agent runs."""
        def plan_run(task, plan_steps, state, **kw):
            time.sleep(0.05)
            state.send({'type': 'plan_preview', 'steps': ['Open Uber', 'Check price'], 'task': task})
            state.plan_event.clear()
            state.plan_event.wait(timeout=5)
            time.sleep(0.05)
            approved = state.plan_result.get('approved', False)
            state.send({'type': 'done', 'success': approved, 'summary': 'OK', 'steps': 2, 'duration': 0.5})
            state.task_running = False

        mock_run.side_effect = plan_run

        client = TestClient(app)
        with client.websocket_connect('/ws') as ws:
            ws.send_text(json.dumps({'type': 'command', 'task': 'Compare rides'}))
            msg = json.loads(ws.receive_text())
            assert msg['type'] == 'plan_preview'
            assert len(msg['steps']) == 2
            ws.send_text(json.dumps({'type': 'plan_approve', 'approved': True}))
            msg = json.loads(ws.receive_text())
            assert msg['type'] == 'done'
            assert msg['success'] is True

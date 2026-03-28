"""Background runner — executes agent tasks in a separate thread."""
from __future__ import annotations

import threading


class BackgroundRunner:
    """Run the agent loop in a background thread with start/stop/status controls."""

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._status = {
            'running': False,
            'task': None,
            'completed': False,
            'success': None,
        }
        self._lock = threading.Lock()

    def start(self, task: str, callback=None, **kwargs) -> None:
        """Launch run_agent in a background thread.

        Args:
            task: Natural language instruction.
            callback: Optional callable(step, action, result, status) per step (future use).
            **kwargs: Additional args passed to run_agent (max_steps, wda_url, verbose).
        """
        if self.is_running():
            raise RuntimeError('A task is already running. Call stop() first.')

        self._stop_event.clear()
        with self._lock:
            self._status = {
                'running': True,
                'task': task,
                'completed': False,
                'success': None,
            }

        def _run():
            from core.agent import run_agent
            try:
                result = run_agent(
                    task,
                    stop_check=self._stop_event.is_set,
                    **kwargs,
                )
                with self._lock:
                    self._status['success'] = result
            except Exception:
                with self._lock:
                    self._status['success'] = False
            finally:
                with self._lock:
                    self._status['running'] = False
                    self._status['completed'] = True

        self._thread = threading.Thread(target=_run, daemon=True)
        self._thread.start()

    def get_status(self) -> dict:
        """Return current execution state."""
        with self._lock:
            return dict(self._status)

    def stop(self) -> None:
        """Signal the agent loop to stop after the current step."""
        self._stop_event.set()

    def is_running(self) -> bool:
        """Check if a task is currently executing."""
        with self._lock:
            return self._status['running']

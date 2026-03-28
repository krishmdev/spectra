"""Unit tests for BackgroundRunner — mock run_agent to avoid needing simulator."""

import time
from unittest.mock import patch

import pytest

from core.background import BackgroundRunner


def _slow_agent(*args, **kwargs):
    """Simulate a slow agent run for testing."""
    time.sleep(2)
    return True


class TestBackgroundRunner:

    @patch('core.agent.run_agent', return_value=True)
    def test_completes_with_success(self, mock_run):
        runner = BackgroundRunner()
        runner.start('Test task', verbose=False)
        time.sleep(1)
        status = runner.get_status()
        assert status['completed'] is True
        assert status['success'] is True
        assert status['task'] == 'Test task'

    @patch('core.agent.run_agent', return_value=False)
    def test_failure_result(self, mock_run):
        runner = BackgroundRunner()
        runner.start('Failing task', verbose=False)
        time.sleep(1)
        status = runner.get_status()
        assert status['success'] is False

    @patch('core.agent.run_agent', side_effect=_slow_agent)
    def test_double_start_raises(self, mock_run):
        runner = BackgroundRunner()
        runner.start('Long task', verbose=False)
        time.sleep(0.1)  # let thread start
        with pytest.raises(RuntimeError):
            runner.start('Another task', verbose=False)
        runner.stop()
        time.sleep(2.5)

    def test_stop_sets_event(self):
        runner = BackgroundRunner()
        runner.stop()
        assert runner._stop_event.is_set()

    def test_initial_status(self):
        runner = BackgroundRunner()
        status = runner.get_status()
        assert status['running'] is False
        assert status['task'] is None
        assert status['completed'] is False
        assert status['success'] is None

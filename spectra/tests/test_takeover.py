"""Unit tests for TakeoverManager — mock input to avoid blocking."""

from unittest.mock import patch

from core.takeover import TakeoverManager


class TestTakeoverManager:

    def test_initial_not_paused(self):
        tm = TakeoverManager()
        assert tm.is_paused() is False

    def test_pause_sets_flag(self):
        tm = TakeoverManager()
        tm.pause('Password required')
        assert tm.is_paused() is True

    @patch('builtins.input', return_value='')
    def test_wait_for_resume_clears_flag(self, _mock_input):
        tm = TakeoverManager()
        tm.pause('Enter credentials')
        assert tm.is_paused() is True
        tm.wait_for_resume()
        assert tm.is_paused() is False

    def test_pause_prints_reason(self, capsys):
        tm = TakeoverManager()
        tm.pause('Enter your password')
        captured = capsys.readouterr()
        assert 'Enter your password' in captured.out

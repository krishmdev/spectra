"""Unit tests for ConfirmationGate — no external dependencies."""

from unittest.mock import patch

from core.gates import ConfirmationGate


def _make_ref_map(**kwargs):
    """Helper to build a ref_map with one element."""
    el = {'type': 'XCUIElementTypeButton', 'label': '', 'value': '',
           'x': 0, 'y': 0, 'width': 100, 'height': 44}
    el.update(kwargs)
    return {1: el}


class TestGateCheck:

    def test_sensitive_tap_triggers(self):
        gate = ConfirmationGate()
        ref_map = _make_ref_map(label='Send Message')
        action = {'name': 'tap', 'input': {'ref': 1}}
        assert gate.check(action, ref_map) is True

    def test_normal_tap_skips(self):
        gate = ConfirmationGate()
        ref_map = _make_ref_map(label='General')
        action = {'name': 'tap', 'input': {'ref': 1}}
        assert gate.check(action, ref_map) is False

    def test_partial_match(self):
        gate = ConfirmationGate()
        ref_map = _make_ref_map(label='Place Order Now')
        action = {'name': 'tap', 'input': {'ref': 1}}
        assert gate.check(action, ref_map) is True

    def test_case_insensitive(self):
        gate = ConfirmationGate()
        ref_map = _make_ref_map(label='SUBMIT')
        action = {'name': 'tap', 'input': {'ref': 1}}
        assert gate.check(action, ref_map) is True

    def test_secure_text_field_triggers(self):
        gate = ConfirmationGate()
        ref_map = {1: {'type': 'XCUIElementTypeSecureTextField', 'label': 'Password',
                        'value': '', 'x': 0, 'y': 0, 'width': 300, 'height': 44}}
        action = {'name': 'scroll', 'input': {'direction': 'down'}}
        assert gate.check(action, ref_map) is True

    def test_non_tap_skips_label_check(self):
        gate = ConfirmationGate()
        ref_map = _make_ref_map(label='Send')
        action = {'name': 'scroll', 'input': {'direction': 'down'}}
        assert gate.check(action, ref_map) is False

    def test_missing_ref_skips(self):
        gate = ConfirmationGate()
        ref_map = _make_ref_map(label='Send')
        action = {'name': 'tap', 'input': {'ref': 99}}
        assert gate.check(action, ref_map) is False


class TestGateConfirmation:

    @patch('builtins.input', return_value='y')
    def test_approve(self, _mock_input):
        gate = ConfirmationGate()
        ref_map = _make_ref_map(label='Send')
        action = {'name': 'tap', 'input': {'ref': 1, 'reasoning': 'test'}}
        assert gate.request_confirmation(action, ref_map) is True

    @patch('builtins.input', return_value='n')
    def test_reject(self, _mock_input):
        gate = ConfirmationGate()
        ref_map = _make_ref_map(label='Send')
        action = {'name': 'tap', 'input': {'ref': 1, 'reasoning': 'test'}}
        assert gate.request_confirmation(action, ref_map) is False

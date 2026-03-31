"""Confidence-scored matching and replay on the mock device."""
from bench.replay_heal import ApproveGate, record, v01_matcher
from core.scripted_planner import ScriptedPlanner
from recorder.matcher import Confidence, label_similarity, match
from recorder.replayer import Replayer
from sim.checks import check
from sim.script_engine import load_scenarios

SC = load_scenarios()


def _el(label, y=100, type_='XCUIElementTypeCell', **kw):
    return {'type': type_, 'label': label, 'value': '', 'x': 0, 'y': y, 'width': 402, 'height': 52, **kw}


def test_label_similarity_handles_os_rewording():
    assert label_similarity('Display & Brightness', 'Display and Brightness') >= 0.95
    assert label_similarity('Mom, Call me when you land, Yesterday', 'Mom, Did you land yet?, Tuesday') >= 0.9
    assert label_similarity('Mom, x, Yesterday', 'Dad, x, Yesterday') < 0.9


def test_position_only_match_is_low_confidence():
    target = _el('Display & Brightness', y=400)
    res = match(target, {1: _el('Control Center', y=420)})
    assert res.match_type == 'position' and res.confidence == Confidence.LOW and res.score < 0.75


def test_identifier_beats_a_renamed_label():
    target = _el('Wi-Fi', identifier='com.apple.settings.wifi')
    res = match(target, {1: _el('WLAN', identifier='com.apple.settings.wifi'), 2: _el('Wi-Fi Calling')})
    assert res.ref == 1 and res.match_type == 'exact'


def test_near_ties_are_marked_ambiguous():
    target = _el('Alex')
    res = match(target, {1: _el('Alex Chen', y=100), 2: _el('Alex Chen', y=176)})
    assert res.ref is not None
    two_fuzzy = match(_el('Alex, hi'), {1: _el('Alex, hey', y=100), 2: _el('Alex, hello', y=110)})
    assert two_fuzzy.ambiguous and two_fuzzy.score < 0.9


def _replay(mock_device, flow, seed, variant='', planner=None, matcher=None):
    mock_device.device.reset(seed, variant)
    rp = Replayer(flow, wda_url=mock_device.url, step_delay=0, verbose=False, gate=ApproveGate(),
                  planner=planner, matcher=matcher)
    return rp.run()


def test_relabeled_replay_v01_taps_wrong_thread_v02_does_not(mock_device, tmp_path):
    flow = str(tmp_path / 'mom.spectra')
    assert record(mock_device, mock_device.url, SC['messages_text_mom'], 0, flow)
    _replay(mock_device, flow, 2, 'relabel', matcher=v01_matcher())
    assert not check(SC['messages_text_mom'], mock_device.device.state())[0]
    report = _replay(mock_device, flow, 2, 'relabel')
    assert check(SC['messages_text_mom'], mock_device.device.state())[0], report.steps


def test_flow_with_runtime_values_is_not_replayed(mock_device, tmp_path):
    flow = str(tmp_path / 'stocks.spectra')
    assert record(mock_device, mock_device.url, SC['stocks_to_messages'], 0, flow)
    report = _replay(mock_device, flow, 1)
    assert report.failed == 1 and 'run time' in report.steps[0].detail
    assert mock_device.device.state()['threads']['Alex Chen'][-1]['from'] == 'them'


def test_unexpected_alert_is_handled_by_planner_fallback(mock_device, tmp_path):
    flow = str(tmp_path / 'rem.spectra')
    assert record(mock_device, mock_device.url, SC['reminders_add'], 0, flow)
    mock_device.device.reset(3)
    had_alert = 'com.apple.reminders' in mock_device.device.pending_alerts
    report = _replay(mock_device, flow, 3, planner=ScriptedPlanner())
    assert check(SC['reminders_add'], mock_device.device.state())[0], report.steps
    if had_alert:
        assert report.healed >= 1


def test_sensitive_replay_step_goes_through_the_gate(mock_device, tmp_path):
    flow = str(tmp_path / 'mom.spectra')
    assert record(mock_device, mock_device.url, SC['messages_text_mom'], 0, flow)

    class Deny(ApproveGate):
        def request_confirmation(self, action, ref_map):
            return False

    mock_device.device.reset(0)
    report = Replayer(flow, wda_url=mock_device.url, step_delay=0, verbose=False, gate=Deny()).run()
    assert report.gated >= 1
    assert all(m['from'] == 'them' for m in mock_device.device.state()['threads']['Mom'])

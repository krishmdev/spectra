"""Keyless end-to-end runs: real agent loop + ScriptedPlanner against the mock device."""
import pytest

from core.agent import run_agent
from core.gates import ConfirmationGate
from core.scripted_planner import ScriptedPlanner
from sim.checks import check
from sim.script_engine import load_scenarios

SCENARIOS = load_scenarios()


class RecordingGate(ConfirmationGate):
    def __init__(self):
        super().__init__()
        self.asked = []

    def request_confirmation(self, action, ref_map):
        self.asked.append(ref_map[action['input']['ref']]['label'])
        return True


@pytest.mark.parametrize('seed', [0, 1, 2])
@pytest.mark.parametrize('scenario_id', sorted(SCENARIOS))
def test_scenario_completes(mock_device, scenario_id, seed):
    sc = SCENARIOS[scenario_id]
    mock_device.device.reset(seed)
    gate = RecordingGate()
    planner = ScriptedPlanner()
    done = run_agent(sc['task'], wda_url=mock_device.url, verbose=False, planner=planner, gate=gate)
    state = mock_device.device.state()
    assert done
    passed, reason = check(sc, state)
    assert passed, reason
    if scenario_id in ('messages_text_mom', 'stocks_to_messages'):
        # "send" is a gated label and neither task says "send", so the user is asked once
        assert gate.asked == ['Send']
    else:
        assert gate.asked == []


def test_unknown_task_gets_stuck_not_crash(mock_device):
    ok = run_agent('Order a pizza', wda_url=mock_device.url, verbose=False, max_steps=3,
                   planner=ScriptedPlanner(), gate=RecordingGate())
    assert ok is False


def test_same_label_loop_trips_stuck_detector(mock_device):
    """A planner that keeps tapping 'Light' gets the label-history warning."""
    seen = []

    class Stubborn(ScriptedPlanner):
        def next_action(self, tree, task, history, metadata, warning=None, **kw):
            seen.append(warning)
            if metadata.get('app_name') != 'Settings':
                return {'name': 'open_app', 'input': {'bundle_id': 'com.apple.Preferences'}}
            from sim.script_engine import find_ref
            ref = find_ref(tree, label='Display & Brightness') or find_ref(tree, label='Light')
            if ref is None:
                return {'name': 'scroll', 'input': {'direction': 'down'}}
            return {'name': 'tap', 'input': {'ref': ref}}

    run_agent('Turn on Dark Mode', wda_url=mock_device.url, verbose=False, max_steps=10,
              planner=Stubborn(), gate=RecordingGate())
    assert any(w and 'times with no effect' in w for w in seen)

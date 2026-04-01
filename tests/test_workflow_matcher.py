import json

from core.workflow_matcher import _load_available_workflows, find_matching_workflow
from recorder.recorder import Recorder


def _record(path, task, actions):
    rec = Recorder(str(path), task=task)
    for i, a in enumerate(actions, 1):
        rec.record(i, a, {'summary': 'ok'} if a == 'done' else {}, {}, 'tree')
    rec.close()


class EchoPlanner:
    """Says 'match' for whatever workflow has the same task text."""

    def complete(self, prompt, max_output_tokens=200, purpose=''):
        new = prompt.split('New Task: "', 1)[1].split('"', 1)[0]
        for line in prompt.splitlines():
            if f'Task: "{new}"' in line and line.startswith('- ID:'):
                return json.dumps({'match': line.split('"')[1]})
        return '{"match": null}'


def test_in_progress_recording_is_not_offered(tmp_path):
    current = tmp_path / 'now.spectra'
    Recorder(str(current), task='Turn on Dark Mode')  # header only, still open
    assert find_matching_workflow('Turn on Dark Mode', EchoPlanner(), str(tmp_path), exclude=str(current)) is None


def test_only_finished_successful_recordings_count(tmp_path):
    _record(tmp_path / 'good.spectra', 'Turn on Dark Mode', ['tap', 'done'])
    _record(tmp_path / 'stuck.spectra', 'Add a reminder', ['tap', 'stuck'])
    _record(tmp_path / 'empty.spectra', 'Text Mom', [])
    flows = _load_available_workflows(str(tmp_path))
    assert list(flows.values()) == ['Turn on Dark Mode']
    assert find_matching_workflow('Turn on Dark Mode', EchoPlanner(), str(tmp_path)).endswith('good.spectra')


def test_model_reply_must_be_one_of_the_offered_ids(tmp_path):
    _record(tmp_path / 'good.spectra', 'Turn on Dark Mode', ['tap', 'done'])

    class Liar:
        def complete(self, prompt, max_output_tokens=200, purpose=''):
            return '{"match": "/etc/passwd"}'
    assert find_matching_workflow('Turn on Dark Mode', Liar(), str(tmp_path)) is None

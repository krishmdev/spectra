"""Contract tests for bench/run_suite.py: the per-trial state reset must be real and recorded."""
import hashlib
import json
import os
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMPTY_LESSONS = hashlib.sha256(open(os.path.join(REPO, 'bench', 'initial_state', 'lessons.json'), 'rb').read()).hexdigest()


def _has_tag(tag):
    return subprocess.run(['git', 'rev-parse', '-q', '--verify', f'refs/tags/{tag}'], cwd=REPO,
                          capture_output=True).returncode == 0


def _run(tmp_path, *args):
    out = tmp_path / 'out'
    env = {k: v for k, v in os.environ.items() if k != 'GEMINI_API_KEY'}
    env['SPECTRA_RUN_MANIFEST'] = str(tmp_path / 'no-such-tool.py')
    subprocess.run([sys.executable, '-m', 'bench.run_suite', '--out', str(out), *args], cwd=REPO, env=env,
                   check=True, capture_output=True, timeout=600)
    rows = [json.loads(line) for line in open(out / 'trials.jsonl')]
    manifest = json.load(open(out / 'manifest.json'))
    return rows, manifest


@pytest.mark.skipif(not _has_tag('v0.1-yhack'), reason='needs the v0.1-yhack tag (fetch tags)')
def test_paired_trials_start_from_identical_recorded_state(tmp_path):
    rows, manifest = _run(tmp_path, '--arm', 'v0.1-yhack=git:v0.1-yhack', '--arm', 'head=.',
                          '--seeds', '0,1', '--scenarios', 'settings_dark_mode', '--backend', 'fake')
    assert len(rows) == 4
    for r in rows:
        assert r['initial']['lessons_sha256'] == EMPTY_LESSONS
        assert r['initial']['flows_sha256'] == manifest['run']['initial_state']['flows_sha256']
    # same seed -> same device state for both arms, different seeds -> different state
    by_seed = {}
    for r in rows:
        by_seed.setdefault(r['seed'], set()).add(r['initial']['device_state_hash'])
    assert all(len(v) == 1 for v in by_seed.values())
    assert by_seed[0] != by_seed[1]
    assert {a['name'] for a in manifest['run']['arms']} == {'v0.1-yhack', 'head'}
    assert len(manifest['trial_initial_state']) == 4
    # trial N+1 does not see flows recorded by trial N
    head = [r for r in rows if r['arm'] == 'head']
    assert all(r['initial']['home_sha256'] == head[0]['initial']['home_sha256'] for r in head)


def test_learning_sequence_carries_state_between_tasks(tmp_path):
    rows, manifest = _run(tmp_path, '--arm', 'head=.', '--seeds', '0', '--experiment', 'learning',
                          '--scenarios', 'settings_dark_mode,reminders_add', '--backend', 'scripted')
    assert [r['position'] for r in rows] == [0, 1, 2, 3]
    assert rows[0]['initial']['lessons_sha256'] == EMPTY_LESSONS
    assert rows[1]['initial']['flows_sha256'] != rows[0]['initial']['flows_sha256']
    assert rows[2]['replayed'] and rows[3]['replayed']
    assert all(r['success'] for r in rows)


def test_agent_claiming_done_is_not_success(tmp_path):
    rows, _ = _run(tmp_path, '--arm', 'head=.', '--seeds', '0', '--backend', 'scripted',
                   '--scenario-dir', os.path.join(REPO, 'tests', 'fixtures', 'liar_scenarios'))
    assert rows[0]['agent_done'] is True
    assert rows[0]['success'] is False


@pytest.mark.skipif(not _has_tag('v0.1-yhack'), reason='needs the v0.1-yhack tag (fetch tags)')
def test_scripted_backend_refuses_trees_without_a_scripted_planner(tmp_path):
    proc = subprocess.run([sys.executable, '-m', 'bench.run_suite', '--arm', 'old=git:v0.1-yhack',
                           '--backend', 'scripted', '--out', str(tmp_path / 'o')], cwd=REPO,
                          capture_output=True, text=True)
    assert proc.returncode != 0 and 'scripted_planner' in proc.stderr


@pytest.mark.skipif(not _has_tag('v0.1-yhack'), reason='needs the v0.1-yhack tag (fetch tags)')
def test_cachefix_arm_is_the_tag_plus_one_patch(tmp_path):
    rows, manifest = _run(tmp_path, '--arm', 'v0.1-yhack=git:v0.1-yhack',
                          '--arm', 'v0.1-yhack+cachefix=git:v0.1-yhack@bench/patches/v0.1-cachefix.patch',
                          '--seeds', '0', '--scenarios', 'settings_dark_mode', '--backend', 'fake')
    arms = {a['name']: a for a in manifest['run']['arms']}
    assert arms['v0.1-yhack']['code_sha256'] != arms['v0.1-yhack+cachefix']['code_sha256']
    assert arms['v0.1-yhack+cachefix']['patch'] == 'bench/patches/v0.1-cachefix.patch'
    by_arm = {r['arm']: r for r in rows}
    # the fake endpoint says "match" for the same task, so only the unpatched tree fast-forwards
    assert by_arm['v0.1-yhack']['replayed'] and not by_arm['v0.1-yhack']['success']
    assert not by_arm['v0.1-yhack+cachefix']['replayed'] and by_arm['v0.1-yhack+cachefix']['success']
    assert manifest['run']['libraries']['google-genai']
    assert all('device_loops' in r for r in rows)

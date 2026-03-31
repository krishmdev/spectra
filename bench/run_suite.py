"""Eval harness: run the scenario suite against one or more agent trees.

    python -m bench.run_suite --arm v0.1-yhack=git:v0.1-yhack --arm head=. \
        --seeds 0,1,2 --backend live --out bench/results/2026-03-31-live

Arms are directories (or git refs, extracted with `git archive`) holding a
Spectra checkout; the old spectra/ subfolder layout is detected. Every trial
runs in its own subprocess against the mock device (sim/), and the success
check reads the device's ground truth, not the agent's own "done".

State contract, per trial and identical for every arm:
- a fresh copy of the arm's code, with data/lessons.json and flows/ seeded
  from bench/initial_state/ (no lessons, no cached flows) and a fresh HOME
  (~/.spectra episodes, action log, schedules);
- POST /_sim/reset with the trial's seed, same seed and scenario order for
  every arm;
- sha256 of the initial lessons, flows directory and device state recorded
  in the trial row and the manifest.

--experiment learning is the separate cross-trial measurement: one trial
directory per arm persists across an ordered scenario sequence, so lessons and
recorded flows carry over. The device is still reset before every task.

Backends: live (Gemini, needs GEMINI_API_KEY), fake (sim/fake_gemini.py, a
harness check only), scripted (ScriptedPlanner; HEAD only).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from sim.checks import check  # noqa: E402
from sim.script_engine import load_scenarios  # noqa: E402

INITIAL_STATE = os.path.join(REPO, 'bench', 'initial_state')
RUNNER = os.path.join(REPO, 'bench', 'arm_runner.py')
SIM_BIN = os.path.join(REPO, 'sim', 'bin')
COPY_IGNORE = shutil.ignore_patterns(
    '.git', '.venv', 'venv', '__pycache__', '.pytest_cache', '.ruff_cache', 'ios', 'macos', 'SpectraApp',
    'docs', 'examples', 'bench', 'tests', 'data', 'config', '*.spectra', '*.md', 'uv.lock')
LEARNING_SEQUENCE = ['settings_dark_mode', 'reminders_add', 'messages_text_mom', 'stocks_to_messages',
                     'settings_dark_mode', 'reminders_add', 'messages_text_mom', 'stocks_to_messages']


def sha256_file(path: str) -> str:
    with open(path, 'rb') as f:
        return hashlib.sha256(f.read()).hexdigest()


def sha256_dir(path: str) -> str:
    h = hashlib.sha256()
    for root, dirs, files in os.walk(path):
        dirs.sort()
        for name in sorted(files):
            p = os.path.join(root, name)
            h.update(os.path.relpath(p, path).encode() + b'\0')
            h.update(sha256_file(p).encode())
    return h.hexdigest()


def git(*args, cwd=REPO) -> str:
    return subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def free_port() -> int:
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def http_json(url: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'},
                                 method='POST' if body is not None else 'GET')
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


# --- arms ---------------------------------------------------------------------

def resolve_arm(spec: str, workdir: str) -> dict:
    name, _, where = spec.partition('=')
    if not where:
        raise SystemExit(f'--arm expects NAME=PATH or NAME=git:REF, got {spec!r}')
    if where.startswith('git:'):
        ref = where[4:]
        sha = git('rev-parse', f'{ref}^{{commit}}')
        dest = os.path.join(workdir, 'arms', name)
        os.makedirs(dest, exist_ok=True)
        archive = subprocess.run(['git', 'archive', sha], cwd=REPO, capture_output=True, check=True).stdout
        subprocess.run(['tar', '-x', '-C', dest], input=archive, check=True)
        root, source = dest, {'git_ref': ref, 'commit': sha, 'dirty': False}
    else:
        root = os.path.abspath(where)
        try:
            sha = git('rev-parse', 'HEAD', cwd=root)
            dirty = bool(git('status', '--porcelain', '--untracked-files=no', cwd=root))
        except subprocess.CalledProcessError:
            sha, dirty = None, None
        source = {'path': root, 'commit': sha, 'dirty': dirty}
    code = os.path.join(root, 'spectra') if os.path.isdir(os.path.join(root, 'spectra', 'core')) else root
    if not os.path.isfile(os.path.join(code, 'server', 'ws_server.py')):
        raise SystemExit(f'{code} does not look like a Spectra tree')
    return {'name': name, 'code': code, 'layout': 'spectra/ subfolder' if code != root else 'root', **source}


def prepare_trial(arm: dict, trial_dir: str) -> dict:
    code = os.path.join(trial_dir, 'code')
    shutil.copytree(arm['code'], code, ignore=COPY_IGNORE)
    for d in ('flows', 'data'):
        shutil.rmtree(os.path.join(code, d), ignore_errors=True)
    shutil.copytree(os.path.join(INITIAL_STATE, 'flows'), os.path.join(code, 'flows'))
    os.makedirs(os.path.join(code, 'data'))
    shutil.copy(os.path.join(INITIAL_STATE, 'lessons.json'), os.path.join(code, 'data', 'lessons.json'))
    os.makedirs(os.path.join(trial_dir, 'home'))
    shutil.copy(RUNNER, os.path.join(code, '_arm_runner.py'))
    return {'code': code, 'home': os.path.join(trial_dir, 'home')}


def state_hashes(paths: dict) -> dict:
    return {
        'lessons_sha256': sha256_file(os.path.join(paths['code'], 'data', 'lessons.json')),
        'flows_sha256': sha256_dir(os.path.join(paths['code'], 'flows')),
        'home_sha256': sha256_dir(paths['home']),
    }


# --- running ------------------------------------------------------------------

def run_trial(arm, scenario, seed, paths, env, sim_url, timeout, out_dir, tag) -> dict:
    device = http_json(f'{sim_url}/_sim/reset', {'seed': seed})
    row = {'arm': arm['name'], 'scenario': scenario['id'], 'seed': seed, 'tag': tag,
           'initial': {**state_hashes(paths), 'device_state_hash': device['hash']}}
    result_path = os.path.join(out_dir, 'raw', f'{tag}.json')
    os.makedirs(os.path.dirname(result_path), exist_ok=True)
    log_path = os.path.join(out_dir, 'logs', f'{tag}.log')
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    trial_env = dict(env, HOME=paths['home'], SPECTRA_DATA_DIR=os.path.join(paths['code'], 'data'),
                     PYTHONPATH=paths['code'], PYTHONUNBUFFERED='1')
    t0 = time.monotonic()
    with open(log_path, 'w') as log:
        try:
            subprocess.run([sys.executable, '_arm_runner.py', '--task', scenario['task'], '--wda-url', sim_url,
                            '--out', result_path], cwd=paths['code'], env=trial_env, stdout=log,
                           stderr=subprocess.STDOUT, timeout=timeout)
            with open(result_path) as f:
                res = json.load(f)
        except subprocess.TimeoutExpired:
            res = {'error': f'trial timed out after {timeout}s'}
        except (OSError, json.JSONDecodeError) as e:
            res = {'error': f'runner produced no result: {e}'}
    row['harness_seconds'] = round(time.monotonic() - t0, 2)
    final = http_json(f'{sim_url}/_sim/state')
    passed, reason = check(scenario, final)
    row.update(success=passed, check=reason, final_device_state_hash=final['hash'])
    row.update({k: res.get(k) for k in (
        'agent_done', 'agent_stuck', 'error', 'steps', 'confirmations', 'plan_previews', 'replayed',
        'llm_calls', 'llm_errors', 'llm_error_samples', 'prompt_tokens', 'cached_tokens', 'output_tokens',
        'thought_tokens', 'cache_creates', 'stuck_warnings', 'hard_stuck', 'wall_seconds', 'egress_canary')})
    row['after'] = state_hashes(paths)
    row['lessons_after'] = len(json.load(open(os.path.join(paths['code'], 'data', 'lessons.json'))))
    row['flows_after'] = len([f for f in os.listdir(os.path.join(paths['code'], 'flows')) if f.endswith('.spectra')])
    return row


def backend_env(backend: str, fake_url: str | None) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ('GOOGLE_GEMINI_BASE_URL', 'SPECTRA_PLANNER')}
    env['PATH'] = SIM_BIN + os.pathsep + env.get('PATH', '')
    if backend == 'live':
        if not env.get('GEMINI_API_KEY'):
            raise SystemExit('--backend live needs GEMINI_API_KEY in the environment')
    elif backend == 'fake':
        env['GEMINI_API_KEY'] = 'fake-key-for-local-endpoint'
        env['GOOGLE_GEMINI_BASE_URL'] = fake_url
    elif backend == 'scripted':
        env.pop('GEMINI_API_KEY', None)
        env['SPECTRA_PLANNER'] = 'scripted'
        env['SPECTRA_SCENARIOS'] = os.path.join(REPO, 'sim', 'scenarios')
    return env


def summarize(rows: list[dict]) -> dict:
    out: dict = {}
    for arm in sorted({r['arm'] for r in rows}):
        rs = [r for r in rows if r['arm'] == arm]
        per = {}
        for sid in sorted({r['scenario'] for r in rs}):
            per[sid] = _agg([r for r in rs if r['scenario'] == sid])
        out[arm] = {'overall': _agg(rs), 'by_scenario': per}
    return out


def _agg(rs: list[dict]) -> dict:
    def mean(key):
        vals = [r[key] for r in rs if isinstance(r.get(key), (int, float))]
        return round(sum(vals) / len(vals), 2) if vals else None
    return {
        'trials': len(rs),
        'successes': sum(bool(r['success']) for r in rs),
        'success_rate': round(sum(bool(r['success']) for r in rs) / len(rs), 3) if rs else None,
        'agent_claimed_done': sum(bool(r.get('agent_done')) for r in rs),
        'mean_steps': mean('steps'),
        'mean_llm_calls': mean('llm_calls'),
        'mean_prompt_tokens': mean('prompt_tokens'),
        'mean_output_tokens': mean('output_tokens'),
        'mean_wall_seconds': mean('wall_seconds'),
        'stuck_warnings': sum(r.get('stuck_warnings') or 0 for r in rs),
        'hard_stuck': sum(r.get('hard_stuck') or 0 for r in rs),
        'errors': sum(1 for r in rs if r.get('error')),
        'replayed': sum(bool(r.get('replayed')) for r in rs),
    }


def write_markdown(path: str, summary: dict, meta: dict) -> None:
    lines = [f"# {meta['experiment']} run: {meta['backend']} backend", '',
             f"Seeds {meta['seeds']}, scenarios {', '.join(meta['scenarios'])}. Generated by bench/run_suite.py.", '',
             '| arm | scenario | success | steps | LLM calls | prompt tokens | wall s | stuck warnings |',
             '|---|---|---|---|---|---|---|---|']
    for arm, s in summary.items():
        for sid, a in list(s['by_scenario'].items()) + [('all', s['overall'])]:
            lines.append(f"| {arm} | {sid} | {a['successes']}/{a['trials']} | {a['mean_steps']} | "
                         f"{a['mean_llm_calls']} | {a['mean_prompt_tokens']} | {a['mean_wall_seconds']} | "
                         f"{a['stuck_warnings']} |")
    with open(path, 'w') as f:
        f.write('\n'.join(lines) + '\n')


def run_manifest(path: str, extra: dict) -> None:
    tool = os.environ.get('SPECTRA_RUN_MANIFEST', '<local>')
    if os.path.exists(tool):
        subprocess.run([sys.executable, tool, '--out', path] + [f'{k}={v}' for k, v in extra.items()], check=False)
        with open(path) as f:
            data = json.load(f)
    else:
        import platform
        data = {'recorded_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                'host': {'os': platform.platform(), 'python': platform.python_version()}, 'extra': extra}
    return data


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--arm', action='append', required=True, help='NAME=PATH or NAME=git:REF')
    ap.add_argument('--seeds', default='0,1,2')
    ap.add_argument('--scenarios', default='', help='comma-separated ids (default: all)')
    ap.add_argument('--backend', choices=['live', 'fake', 'scripted'], default='live')
    ap.add_argument('--experiment', choices=['paired', 'learning'], default='paired')
    ap.add_argument('--timeout', type=int, default=300)
    ap.add_argument('--out', required=True)
    ap.add_argument('--keep-trials', action='store_true', help='keep the per-trial copies for debugging')
    args = ap.parse_args(argv)

    scenarios = load_scenarios(os.path.join(REPO, 'sim', 'scenarios'))
    ids = [s for s in args.scenarios.split(',') if s] or sorted(scenarios)
    seeds = [int(s) for s in args.seeds.split(',') if s]
    out_dir = os.path.abspath(args.out)
    os.makedirs(out_dir, exist_ok=True)
    work = tempfile.mkdtemp(prefix='spectra-bench-')

    arms = [resolve_arm(spec, work) for spec in args.arm]
    for arm in arms:
        arm['code_sha256'] = sha256_dir(arm['code'])

    fake = None
    if args.backend == 'fake':
        from sim.fake_gemini import serve_in_thread
        fake, fake_url = serve_in_thread(0)
    env = backend_env(args.backend, fake_url if fake else None)

    port = free_port()
    sim_url = f'http://127.0.0.1:{port}'
    sim = subprocess.Popen([sys.executable, '-m', 'sim.server', '--port', str(port)], cwd=REPO,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    env['SPECTRA_SIM_URL'] = sim_url
    for _ in range(100):
        if sim.poll() is not None:
            raise SystemExit(f'mock device exited with code {sim.returncode} (egress canary failed?)')
        try:
            http_json(f'{sim_url}/status')
            break
        except OSError:
            time.sleep(0.1)
    device_canary = http_json(f'{sim_url}/_sim/canary')

    rows: list[dict] = []
    started = time.strftime('%Y-%m-%dT%H:%M:%S%z')
    try:
        if args.experiment == 'paired':
            for i, seed in enumerate(seeds):
                for sid in ids:
                    # alternate arm order per seed so neither arm always runs first
                    order = arms if i % 2 == 0 else list(reversed(arms))
                    for arm in order:
                        trial_dir = tempfile.mkdtemp(prefix=f'{arm["name"]}-', dir=work)
                        paths = prepare_trial(arm, trial_dir)
                        tag = f'{arm["name"]}__{sid}__seed{seed}'
                        row = run_trial(arm, scenarios[sid], seed, paths, env, sim_url, args.timeout, out_dir, tag)
                        rows.append(row)
                        _progress(row)
                        if not args.keep_trials:
                            shutil.rmtree(trial_dir, ignore_errors=True)
        else:
            sequence = [s for s in LEARNING_SEQUENCE if s in ids]
            for arm in arms:
                trial_dir = tempfile.mkdtemp(prefix=f'{arm["name"]}-seq-', dir=work)
                paths = prepare_trial(arm, trial_dir)
                for pos, sid in enumerate(sequence):
                    seed = seeds[pos % len(seeds)]
                    tag = f'{arm["name"]}__seq{pos:02d}__{sid}__seed{seed}'
                    row = run_trial(arm, scenarios[sid], seed, paths, env, sim_url, args.timeout, out_dir, tag)
                    row['position'] = pos
                    rows.append(row)
                    _progress(row)
    finally:
        sim.terminate()
        sim.wait(timeout=10)
        if fake is not None:
            fake.shutdown()
        if not args.keep_trials:
            shutil.rmtree(work, ignore_errors=True)

    with open(os.path.join(out_dir, 'trials.jsonl'), 'w') as f:
        for r in rows:
            f.write(json.dumps(r) + '\n')
    summary = summarize(rows)
    meta = {
        'experiment': args.experiment, 'backend': args.backend, 'seeds': seeds, 'scenarios': ids,
        'started': started, 'finished': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
        'model': 'gemini-3-flash-preview (default in both arms)' if args.backend == 'live' else args.backend,
        'harness_commit': git('rev-parse', 'HEAD'),
        'arms': [{k: v for k, v in a.items() if k != 'code'} for a in arms],
        'scenario_sha256': {sid: sha256_file(os.path.join(REPO, 'sim', 'scenarios', f'{sid}.json')) for sid in ids},
        'initial_state': {'lessons_sha256': sha256_file(os.path.join(INITIAL_STATE, 'lessons.json')),
                          'flows_sha256': sha256_dir(os.path.join(INITIAL_STATE, 'flows'))},
        'egress_canary_device': device_canary,
        'state_contract': 'fresh code copy + seeded data/ and flows/ + fresh HOME per trial; '
                          'POST /_sim/reset {seed} before each trial' if args.experiment == 'paired' else
                          'one persistent trial dir per arm across the sequence; device reset before each task',
    }
    with open(os.path.join(out_dir, 'summary.json'), 'w') as f:
        json.dump({'meta': meta, 'summary': summary}, f, indent=2)
    manifest = run_manifest(os.path.join(out_dir, 'manifest.json'),
                            {'lease_holder': os.environ.get('COMPUTE_LEASE_HOLDER', ''),
                             'backend': args.backend, 'experiment': args.experiment})
    manifest['run'] = meta
    manifest['trial_initial_state'] = [{'tag': r['tag'], **r['initial']} for r in rows]
    with open(os.path.join(out_dir, 'manifest.json'), 'w') as f:
        json.dump(manifest, f, indent=2)
    write_markdown(os.path.join(out_dir, 'summary.md'), summary, meta)
    print(json.dumps({a: s['overall'] for a, s in summary.items()}, indent=2))
    return 0


def _progress(row: dict) -> None:
    print(f"[bench] {row['tag']}: {'PASS' if row['success'] else 'FAIL'} ({row['check']}) "
          f"llm={row.get('llm_calls')} steps={row.get('steps')} t={row.get('wall_seconds')}s"
          + (f" error={row['error']}" if row.get('error') else ''), flush=True)


if __name__ == '__main__':
    sys.exit(main())

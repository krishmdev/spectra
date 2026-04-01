"""Replay benchmark: record each scenario once, replay it under changed conditions.

    python -m bench.replay_heal --out bench/results/replay-heal

Flows are recorded with the scripted planner on the mock device (seeds 0 and 1),
then replayed with no planner in the loop under three conditions:

    same        same seed as the recording
    reshuffled  a different seed: list order, previews, an update banner that
                shifts Settings rows
    relabeled   a different seed plus variant='relabel' (an "OS update" that
                renames Display & Brightness, Send, the message field, previews)

Three replayer configurations are compared:
    v0.1 matcher        Akshay's original three-tier matcher, loaded from the tag
    v0.2 matcher        confidence scores, low-confidence steps fail instead of guessing
    v0.2 + fallback     low-confidence steps go to a planner for that one step
                        (ScriptedPlanner stands in for Gemini here)

Success is the device's ground truth after the replay. A 'silent failure' is a
replay whose report says every step passed while the device ended up wrong.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from core.agent import run_agent  # noqa: E402
from core.gates import ConfirmationGate  # noqa: E402
from core.scripted_planner import ScriptedPlanner  # noqa: E402
from recorder.recorder import Recorder  # noqa: E402
from recorder.replayer import Replayer  # noqa: E402
from sim.checks import check  # noqa: E402
from sim.script_engine import load_scenarios  # noqa: E402
from sim.server import serve_in_thread  # noqa: E402


class ApproveGate(ConfirmationGate):
    def request_confirmation(self, action, ref_map):
        return True


def v01_matcher():
    src = subprocess.run(['git', 'show', 'v0.1-yhack:spectra/recorder/matcher.py'], cwd=REPO,
                         capture_output=True, text=True, check=True).stdout
    mod = types.ModuleType('matcher_v01')
    sys.modules['matcher_v01'] = mod
    exec(compile(src, 'v0.1-yhack:spectra/recorder/matcher.py', 'exec'), mod.__dict__)
    return mod.match


def record(server, url, scenario, seed, path) -> bool:
    server.device.reset(seed)
    rec = Recorder(path, task=scenario['task'])

    def cb(step, total, name, inp, result, app, ref_map, tree):
        rec.record(step, name, inp, ref_map, tree)

    ok = run_agent(scenario['task'], wda_url=url, verbose=False, planner=ScriptedPlanner(), gate=ApproveGate(),
                   step_callback=cb)
    rec.close()
    return ok and check(scenario, server.device.state())[0]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--out', required=True)
    args = ap.parse_args(argv)

    work = tempfile.mkdtemp(prefix='spectra-replay-')
    os.environ['HOME'] = os.path.join(work, 'home')
    os.environ['SPECTRA_DATA_DIR'] = os.path.join(work, 'data')
    os.makedirs(os.environ['HOME'])
    server, url = serve_in_thread(0)
    os.environ['SPECTRA_SIM_URL'] = url
    os.environ['PATH'] = os.path.join(REPO, 'sim', 'bin') + os.pathsep + os.environ['PATH']

    configs = {
        'v0.1 matcher': dict(matcher=v01_matcher(), planner=None),
        'v0.2 matcher': dict(matcher=None, planner=None),
        'v0.2 + fallback': dict(matcher=None, planner='scripted'),
    }
    rows = []
    for sid, sc in sorted(load_scenarios().items()):
        for rec_seed in (0, 1):
            flow = os.path.join(work, f'{sid}_{rec_seed}.spectra')
            if not record(server, url, sc, rec_seed, flow):
                raise SystemExit(f'recording {sid} seed {rec_seed} failed')
            conditions = [('same', rec_seed, ''), ('reshuffled', rec_seed + 2, ''),
                          ('relabeled', rec_seed + 2, 'relabel')]
            for cond, seed, variant in conditions:
                for cname, cfg in configs.items():
                    server.device.reset(seed, variant)
                    planner = ScriptedPlanner() if cfg['planner'] else None
                    rp = Replayer(flow, wda_url=url, step_delay=0, verbose=False, gate=ApproveGate(),
                                  planner=planner, matcher=cfg['matcher'])
                    report = rp.run()
                    ok, reason = check(sc, server.device.state())
                    rows.append({
                        'scenario': sid, 'recorded_seed': rec_seed, 'condition': cond, 'replay_seed': seed,
                        'variant': variant, 'config': cname, 'success': ok, 'check': reason,
                        'report_failed': report.failed, 'report_passed': report.passed,
                        'healed': report.healed, 'fuzzy': report.fuzzy,
                        'silent_failure': (not ok) and report.failed == 0,
                        'match_types': [s.match_type for s in report.steps],
                        'scores': [s.score for s in report.steps],
                    })
    server.shutdown()

    summary: dict = {}
    for cname in configs:
        summary[cname] = {}
        for cond in ('same', 'reshuffled', 'relabeled'):
            rs = [r for r in rows if r['config'] == cname and r['condition'] == cond]
            summary[cname][cond] = {
                'replays': len(rs),
                'success': sum(r['success'] for r in rs),
                'silent_failures': sum(r['silent_failure'] for r in rs),
                'planner_steps': sum(r['healed'] for r in rs),
            }
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, 'replays.jsonl'), 'w') as f:
        for r in rows:
            f.write(json.dumps(r) + '\n')
    meta = {'head_commit': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=REPO, capture_output=True,
                                          text=True).stdout.strip(),
            'fallback_planner': 'ScriptedPlanner (fixtures), standing in for Gemini',
            'recorded_seeds': [0, 1], 'scenarios': sorted(load_scenarios())}
    with open(os.path.join(args.out, 'summary.json'), 'w') as f:
        json.dump({'meta': meta, 'summary': summary}, f, indent=2)
    from bench.run_suite import library_versions, run_manifest
    manifest = run_manifest(os.path.join(args.out, 'manifest.json'), {'benchmark': 'replay_heal'})
    manifest['run'] = {**meta, 'libraries': library_versions()}
    with open(os.path.join(args.out, 'manifest.json'), 'w') as f:
        json.dump(manifest, f, indent=2)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())

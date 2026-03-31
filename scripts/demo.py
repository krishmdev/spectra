"""Keyless demo: the four scenarios on the mock device with the scripted planner.

    make demo            # or: python scripts/demo.py
    make demo-offline    # same, under scripts/offline-run (egress blocked, canaries on)

The mock device and every agent run are separate processes; the real server
pipeline runs end to end (workflow cache, router, plan preview, agent loop,
confirmation gate, recorder). Only the model is replaced by fixtures.
"""
import json
import os
import sys
import tempfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from bench.run_suite import main as run_suite  # noqa: E402


def main() -> int:
    if os.environ.get('GEMINI_API_KEY'):
        print('note: GEMINI_API_KEY is set but the demo never uses it', file=sys.stderr)
    out = tempfile.mkdtemp(prefix='spectra-demo-')
    seeds = os.environ.get('DEMO_SEEDS', '0,1')
    run_suite(['--arm', 'head=' + REPO, '--backend', 'scripted', '--seeds', seeds, '--out', out])
    rows = [json.loads(line) for line in open(os.path.join(out, 'trials.jsonl'))]
    meta = json.load(open(os.path.join(out, 'summary.json')))['meta']
    print()
    print(f"{'scenario':<22} {'seed':>4}  {'result':<6} {'steps':>5} {'gate':>4}  check")
    for r in rows:
        print(f"{r['scenario']:<22} {r['seed']:>4}  {'PASS' if r['success'] else 'FAIL':<6} "
              f"{r['steps'] or 0:>5} {r['confirmations'] or 0:>4}  {r['check']}")
    failed = [r for r in rows if not r['success']]
    if os.environ.get('SPECTRA_EGRESS_CANARY') == '1':
        agent_ok = all((r.get('egress_canary') or {}).get('blocked') for r in rows)
        device_ok = meta['egress_canary_device'].get('blocked')
        print(f"\negress canary: device process {'blocked' if device_ok else 'OPEN'}, "
              f"agent processes {'blocked' if agent_ok else 'OPEN'}")
        if not (agent_ok and device_ok):
            return 3
    print(f'\n{len(rows) - len(failed)}/{len(rows)} passed; raw results in {out}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

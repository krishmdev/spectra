# Verification log

## 2026-03-31 (macOS 26, Apple M1 Pro, Python 3.11)

Offline, no key:
- `make lint`: ruff clean.
- `make test`: pytest with pytest-socket limiting sockets to localhost, all passing. The two
  sandbox-only canary tests are skipped outside the sandbox.
- `make e2e-offline`: the full suite and the demo under `scripts/offline-run` (sandbox-exec,
  localhost only, keys unset). All tests pass, the demo shows 8/8, and the egress canary reports
  blocked in the mock-device process and in every agent process.
- `make canary-check` (unsandboxed): the canary connects, so the blocked result above isn't
  vacuous.
- CI image built locally and run with `docker run --network none`: tests pass, demo 8/8, canaries
  blocked.
- `make bench-tree` and `make bench-replay`: results committed under `bench/results/`.
- `make bench-live-check`: the live eval command against `sim/fake_gemini.py`. This is a harness
  check only. It confirmed:
  - the unmodified v0.1 tree runs against the mock device (with `sim/bin/xcrun` on PATH);
  - v0.1 fast-forwards on its own just-opened recording when the matcher says yes;
  - the cache-fix arm and HEAD complete the tasks.

Live:
- Gemini, `gemini-3-flash-preview`: not run. The key in the project env file was rejected by the
  API (`400 API_KEY_INVALID`) when I listed models, so no live eval or live token counts exist yet.

Not verified:
- The iOS app. There is no Xcode here, so the Swift code was neither built nor run.
- A real simulator with WebDriverAgent: WDA auto-restart, timeouts and the observer pause were
  tested only with mocks.

## 2026-04-01

The manifests in `bench/results/tree-tokens/manifest.json` and
`bench/results/replay-heal/manifest.json` record `head_commit` 7894f86… and
`baseline_commit` a173a5c (`v0.1-yhack`). The result files have these sha256 hashes:

    47359e88b486b639aed4b9972ee7467939b74dd8afa31af8a9c47605eff67dbe  replay-heal/summary.json
    0ed1286f50e86967fb22f71ada744d470fcbcdac16b717d0a9fb1cc691e4f124  tree-tokens/summary.json
    3fa518abfe2160163711ba52a5354d366e64409d93e81f6c6701eabe47cd4c01  replay-heal/replays.jsonl
    cc9879d6e5da484ee9a6dbfb09aa88f164d7f617453233c5efb2713bb41fbb33  tree-tokens/screens.jsonl

Re-checked on this date: `make lint`, `make test` and `make e2e-offline` pass offline. Live
Gemini is still not run, and the iOS app and a real WebDriverAgent are still unverified.

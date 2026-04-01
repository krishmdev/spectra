# Changelog

## v0.2 (post-hackathon, Krish Maheshwari)

Measured against the mock device; see the README's "Since the hackathon" section for numbers.

Runs without a key
- `PlannerProtocol` with `GeminiPlanner` (the hackathon planner, unchanged apart from lazy imports)
  and `ScriptedPlanner` (scenario fixtures). `run_agent(planner=...)`; `SPECTRA_PLANNER` picks one.
- `sim/`: a mock WebDriverAgent device (Settings, Messages, Reminders, Stocks, home screen) with
  seeded resets and a ground-truth state endpoint.
- `make demo`: the four scenarios through the real server pipeline, no key. `make demo-offline`
  and CI run it with egress blocked and a canary in every process.

Measurement
- `bench/run_suite.py`: paired eval of v0.1-yhack, v0.1-yhack plus one cache fix, and HEAD, with a
  per-trial state contract (fresh lessons, flows, HOME and device state, all hashed into the
  manifest), plus a separate learning-sequence experiment.
- `bench/tree_tokens.py`: raw XML vs the v0.1 compact tree vs the current one.
- `bench/replay_heal.py`: recorded flows replayed after reshuffles and relabels.

Fixes
- The workflow cache offered each task its own just-opened recording as a saved match, so a "yes"
  from the model replayed zero steps and reported the task done.
- Replays skipped the confirmation gate.
- Flows recorded through the server lacked the router's app launch.
- Flows that typed a value read off the screen replayed the stale value.
- After a handoff the agent used a snapshot taken before the user touched the device.
- The stuck detector missed repeated taps on one element when its ref changed.

Features
- Replay matching extends the hackathon's three-tier matcher with confidence scores; weak steps go
  to the planner for that one step.
- Tree parser v2 keeps standalone text (alert bodies, section headers) and drops repeated labels.
- MCP server (`server/mcp_server.py`) with gated tap/type through MCP elicitation.
- `core/session.py`: the task pipeline shared by the WebSocket and MCP servers.
- Passive observer pauses during tasks; WDA restarts when `source()` gets slow (`WDA_PROJ`,
  `SIM_UDID`/`SIM_DEVICE`).
- Packaging: pyproject with pinned versions, `uv.lock`, ruff, GitHub Actions.

## Post-hackathon cleanup (August 2026, Akshay Irudayaraj)

- Flattened the project from `spectra/` to the repo root and dropped the unbacked WebDriverAgent
  submodule pointer.
- Purged the committed Xcode build cache; made `scripts/restart_all.sh` portable.
- Added the demo video to the README.

## v0.1-yhack (YHack 2026, team of four)

Tag `v0.1-yhack`, Akshay's "final" commit from Sunday night. The core agent (tree reader and
parser, Gemini planner, executor, gates, memory, WebSocket server, SwiftUI app) started in
Krish's yhack repo; the team then added the workflow cache and record/replay, context triggers
and the passive observer, the Safari agent, push notifications, and the scheduler.

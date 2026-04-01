# Spectra design notes

How the backend works as of v0.2. The iOS client is described in the README.

## The loop

`core/agent.py:run_agent` runs observe, think, act until the planner calls `done` or `stuck`, the
step budget runs out (15, or 25 for multi-part tasks), or the stuck detector declares a hard loop.

1. Observe: `TreeReader.snapshot()` asks WebDriverAgent for the foreground app
   (`/wda/activeAppInfo`) and its accessibility tree (`/source`).
   - Safari goes through a JavaScript snapshot instead.
   - If `source()` times out or fewer than three elements survive parsing, the reader sends a
     screenshot with a numbered grid overlay and the planner switches to coordinate taps
     (`tap_xy`).
   - The next snapshot is prefetched while the UI settles from the previous action.
2. Compress: `core/tree_parser.py` turns the XML into lines like `[4] Cell "General"`.
   - It keeps interactive and structural elements, skips whole status bar and keyboard subtrees,
     and treats containers as pass-through.
   - A `ref_map` keeps each ref's frame for the executor.
   - Since v0.2 it also keeps standalone text (alert bodies, section headers) as ref-less `Text`
     lines. It no longer repeats a label a parent already shows, and it skips zero-size elements.
3. Think: `GeminiPlanner` sends the tree, task, last actions, memory and any stuck warning
   to `gemini-3-flash-preview` with 18 function declarations and `mode=ANY`, so the reply is
   always a tool call. The system prompt and tools go into a context cache when the API allows it.
4. Check: before a tap or type, `ConfirmationGate` looks for sensitive labels (send, pay,
   delete, checkout, ... from `config/apps.json`) and secure text fields. It skips the prompt if
   the task itself asked for that action ("send Mom ..." doesn't ask again before Send).
   `handoff` pauses for the user; `ask_user` asks a question.
5. Act: `Executor` maps the tool call to WDA:
   - taps at the element's centre;
   - `/wda/keys` for typing;
   - drags for scrolling, and a left-edge drag for back;
   - `xcrun simctl launch` for switching apps.

The stuck detector (`core/stuck_detector.py`) is plain code, not the model. It flags a screen
unchanged three times, the same action three times, the same element label three times (refs
change every snapshot), A/B/A/B loops, and runs of scrolls. The warning goes into the next
prompt; a repeated pair three times ends the run.

## Around the loop

`core/session.py:run_session` is what a request from the iOS app (or an MCP client) actually
runs:

1. Workflow cache: `core/workflow_matcher.py` asks the model whether a finished recording in
   `flows/` is the same task. If one is, `recorder/replayer.py` replays it without the model.
2. Route: `core/router.py` classifies the task and picks apps from the registry.
3. Plan preview: for multi-app tasks, `core/plan_preview.py` drafts steps for the user to
   approve.
4. Agent loop, once per routed app, recording every step to a new `.spectra` file.

Memory has two parts:
- `AgentMemory` is a per-task key/value store filled by the `remember` tool. The typical use is
  reading a price in one app and typing it in another.
- `EpisodicMemory` persists one-sentence lessons in `data/lessons.json`. After a stuck run,
  timeout or loop, the model writes a reflection; later tasks with overlapping keywords get up to
  three of those lessons in the prompt.

## Replay and matching

Refs are regenerated every snapshot, so replay re-finds each recorded target. `recorder/matcher.py`
keeps the hackathon's three tiers and adds a score in [0, 1]:

| tier | when | score |
|---|---|---|
| exact | same type and label, or same accessibility identifier | 0.97-1.0 |
| fuzzy | same type, similar label (normalised text, list cells matched by their first segment) | 0.55-0.95 |
| position | same type within 50 px, label unrelated | 0.30-0.50 |

A match whose top two candidates are within 0.05 of each other is marked ambiguous and loses 0.15.

In the replayer:
- A step below 0.75 isn't tapped. With a planner attached, that single step goes to the planner
  and the replay continues.
- A tap that leaves the screen unchanged also gets one planner step and a retry. This is usually
  an alert the recording never saw.
- Replayed taps pass the confirmation gate.
- Flows containing a `remember` step aren't replayed, because they typed a value read at record
  time.

## Servers

- `server/ws_server.py`: FastAPI WebSocket for the iOS app. It also starts:
  - the passive observer, which watches the screen between tasks and suggests repeated
    sequences, and pauses while a task runs;
  - the context trigger loop;
  - the scheduler for "every day at 9" style tasks.
- `server/mcp_server.py`: the same pipeline for MCP clients.
  - Tools: `read_screen`, `tap`, `type_text`, `run_task`, `replay_flow`.
  - Sensitive steps are confirmed with MCP elicitation.

## Testing without a phone

- `sim/` is a mock WDA device. It builds WDA-shaped XML from a small state machine, and
  `/_sim/reset` and `/_sim/state` make trials reproducible and checkable.
- `ScriptedPlanner` answers from `sim/scenarios/*.json` using the same prompt text Gemini would
  get.
- `sim/fake_gemini.py` serves those answers over the Gemini REST API, so code that builds a real
  `genai.Client` can be exercised offline. It is only used to test the harness.

# Spectra

Spectra is an accessibility-tree-first iOS agent. It controls apps on an iPhone simulator by reading the structured accessibility tree exposed through WebDriverAgent, planning the next action with Gemini, and executing taps, typing, scrolling, and navigation through WDA.

The current codebase is split across:

- a Python backend that routes tasks, plans actions, runs the agent loop, and serves a WebSocket API
- a SwiftUI iOS client that submits tasks, shows live progress, handles approvals, and presents results
- a small voice pipeline that can capture speech on the Mac host and transcribe it locally

Unlike screenshot-only computer-use systems, Spectra uses the accessibility tree as its primary perception layer. That gives the model semantic UI elements like `Cell "Wi-Fi"` or `Button "Send"` instead of forcing it to infer everything from pixels.

## Table of Contents

1. [What It Does](#what-it-does)
2. [System Architecture](#system-architecture)
3. [Repository Layout](#repository-layout)
4. [How The Runtime Works](#how-the-runtime-works)
5. [Environment Setup](#environment-setup)
6. [Running Spectra](#running-spectra)
7. [Testing](#testing)
8. [Configuration](#configuration)
9. [Known Constraints](#known-constraints)

## What It Does

Spectra currently supports:

- natural-language task execution against iOS simulator apps
- app routing for supported domains such as Settings, Messages, rideshare, food delivery, and grocery
- multi-app workflows with shared session memory
- plan previews for more complex tasks
- confirmation gates before sensitive actions such as send, pay, purchase, delete, or checkout
- user handoff for sensitive input such as passwords or payment details
- screenshot fallback when the accessibility tree is unavailable or too sparse
- a SwiftUI control surface with live action history, memory pills, approval sheets, and result summaries
- actionable local notifications that let the user approve or deny confirmations directly from the notification banner
- host-side voice capture using the Mac microphone with local transcription via `faster-whisper`

## System Architecture

At a high level, Spectra is a three-part system:

```text
SwiftUI iOS app  <---- WebSocket ---->  FastAPI server  ---->  Agent runtime
     |                                        |                    |
     |                                        |                    |
 task input, UI,                              |                    |
 notifications, approvals                     |                    |
                                              v                    v
                                      task routing, plan      tree read -> plan -> act
                                      preview, memory,        against WebDriverAgent
                                      confirmation bridge
```

### Main runtime path

1. The iOS app sends a `command` message over WebSocket.
2. The Python server creates a task thread in [`server/ws_server.py`](server/ws_server.py).
3. The server routes the task with [`core/router.py`](core/router.py).
4. If the task is multi-app or comparative, it generates a preview plan with [`core/plan_preview.py`](core/plan_preview.py) and waits for user approval from the iOS client.
5. For each target app, the server launches the app on the simulator and calls [`core/agent.py`](core/agent.py).
6. The agent loop:
   - reads the current screen through [`core/tree_reader.py`](core/tree_reader.py)
   - compresses the raw XML into a compact tree using [`core/tree_parser.py`](core/tree_parser.py)
   - asks Gemini for the next structured tool call via [`core/planner.py`](core/planner.py)
   - checks confirmation and takeover gates
   - executes the action through [`core/executor.py`](core/executor.py)
7. Progress, approvals, memory updates, handoff requests, questions, and final results are streamed back to the iOS app over WebSocket.
8. The iOS app can surface confirmation requests either as in-app sheets or actionable notifications, and those notification actions send approval decisions back over the same socket.

### Why the accessibility tree matters

The agent does not plan from screen coordinates alone. It primarily sees a compact semantic tree such as:

```text
[1] NavBar "Settings"
[2] Cell "Wi-Fi" -> "Connected"
[3] Cell "Bluetooth" -> "On"
[4] Cell "General"
```

The planner chooses a logical target by reference number, and the executor converts that ref back into the stored coordinates from the parsed tree. When WDA cannot provide a useful tree, Spectra falls back to screenshot mode and uses coordinate-based actions instead.

### Core backend components

- [`core/tree_parser.py`](core/tree_parser.py): filters raw WDA XML down to meaningful interactive and structural elements, assigns refs, and builds the `ref_map`
- [`core/tree_reader.py`](core/tree_reader.py): reads the screen through WDA, extracts metadata, and switches to screenshot fallback when needed
- [`core/planner.py`](core/planner.py): defines the Gemini system prompt and tool schemas, then requests the next action
- [`core/executor.py`](core/executor.py): turns planner actions into WDA commands such as tap, type, scroll, go back, and go home
- [`core/agent.py`](core/agent.py): orchestrates observe -> think -> act, memory injection, stuck detection, batching, handoff, and step callbacks
- [`core/router.py`](core/router.py): classifies a task and selects app targets from [`config/apps.json`](config/apps.json)
- [`core/plan_preview.py`](core/plan_preview.py): generates high-level step plans for more complex tasks
- [`core/memory.py`](core/memory.py): provides session-scoped agent memory and persistent episodic lessons
- [`core/gates.py`](core/gates.py): intercepts potentially sensitive actions before execution, with task-aware logic to avoid redundant prompts when the user explicitly asked for that action
- [`core/takeover.py`](core/takeover.py): pauses the agent so the user can complete sensitive interaction manually
- [`core/stuck_detector.py`](core/stuck_detector.py): detects repeated screens or repeated actions
- [`server/ws_server.py`](server/ws_server.py): bridges the Python runtime and the SwiftUI client using FastAPI WebSockets

### iOS client architecture

The iOS app in [`ios/Spectra/Spectra`](ios/Spectra/Spectra) is the current user-facing control surface.

- [`SpectraApp.swift`](ios/Spectra/Spectra/SpectraApp.swift): app entry point, notification setup, WebSocket bootstrap, and actionable notification handling for approve/deny
- [`Services/WebSocketService.swift`](ios/Spectra/Spectra/Services/WebSocketService.swift): persistent WebSocket client with connection verification, stale-callback protection, ping-based liveness checks, auto-reconnect, state publishing, and protocol handling
- [`Views/HomeView.swift`](ios/Spectra/Spectra/Views/HomeView.swift): task input, task history cards, voice trigger, navigation into task execution
- [`Views/TaskRunningView.swift`](ios/Spectra/Spectra/Views/TaskRunningView.swift): live plan, memory pills, action log, stop button, approval and question sheets
- [`Views/ConfirmationSheet.swift`](ios/Spectra/Spectra/Views/ConfirmationSheet.swift): sensitive action confirmations and takeover completion UI
- [`Views/AskUserSheet.swift`](ios/Spectra/Spectra/Views/AskUserSheet.swift): user clarification prompts from the planner
- [`Views/ResultView.swift`](ios/Spectra/Spectra/Views/ResultView.swift): completion or failure summary
- [`Services/NotificationService.swift`](ios/Spectra/Spectra/Services/NotificationService.swift): local progress, approval, and completion notifications, including actionable confirmation buttons
- [`Services/SpeechService.swift`](ios/Spectra/Spectra/Services/SpeechService.swift): on-device speech recognition service. This exists in the client, although the current primary voice trigger in `HomeView` uses host-side voice capture through the server.

## Repository Layout

```text
spectra/
|-- core/                 # Agent loop, planner, parser, executor, safety, memory
|-- server/               # FastAPI WebSocket server
|-- voice/                # Host-side voice capture and transcription
|-- config/               # App registry and gate labels
|-- ios/Spectra/          # SwiftUI iOS client and Xcode project
|-- scripts/              # Convenience launch scripts
|-- tests/                # Unit and integration tests
|-- docs/                 # Product and internal implementation docs
|-- requirements.txt      # Python dependencies
`-- .env.example          # Environment variable template
```

## How The Runtime Works

### 1. Task routing

The backend does not always run a task against the current foreground app. It first classifies the request and maps it to app targets using [`config/apps.json`](config/apps.json). The default registry currently includes:

- Settings
- Messages
- Uber
- Lyft
- DoorDash
- Uber Eats
- Instacart

For example, a rideshare comparison task can route to both Uber and Lyft and run the agent loop in each app.

### 2. Perception

[`TreeReader.snapshot()`](core/tree_reader.py) returns:

- a compact accessibility tree string
- a `ref_map` mapping ref numbers to element metadata and coordinates
- metadata such as app name, keyboard visibility, alert presence, and perception mode

If WDA fails or the parsed tree contains fewer than three interactive elements, the reader switches to screenshot mode and includes a base64-encoded PNG in the metadata.

### 3. Planning

[`Planner`](core/planner.py) uses Gemini function calling with explicit tool schemas. The current action surface includes:

- `tap`
- `tap_xy`
- `type_text`
- `scroll`
- `go_back`
- `go_home`
- `wait`
- `remember`
- `handoff`
- `plan`
- `done`
- `stuck`
- `ask_user`
- `batch`

The planner sees:

- the current task
- the current screen tree
- recent action history
- alert and keyboard signals
- injected session memory
- optional approved plan steps
- optional stuck warnings

### 4. Safety and user interaction

Before execution, the runtime can pause in several ways:

- confirmation gate: used for labels such as send, delete, pay, purchase, checkout, and secure text field interactions
- handoff: used when the task requires sensitive manual input
- ask-user: used when the planner needs clarification
- plan preview: used before multi-app or comparison flows

The confirmation gate is task-aware: if the user explicitly asked for the same sensitive action, the runtime can skip an unnecessary extra prompt.

In the WebSocket flow, those pauses are surfaced in the iOS app as modal sheets and notifications. Confirmation notifications now include approve and deny actions that route directly back into the socket session.

### 5. Execution

The executor performs concrete WDA operations:

- tapping the center point of a referenced element
- tapping raw coordinates in screenshot mode
- focusing and typing into text fields
- swiping to scroll
- left-edge swipe for back navigation
- simulator home button action
- launching apps with `xcrun simctl launch`

### 6. Memory

Spectra has two memory layers:

- `AgentMemory`: per-task key/value storage for live multi-app workflows
- `EpisodicMemory`: persistent lesson storage across runs, used to inject prior failure lessons back into prompts

### 7. UI feedback

The iOS app presents the current product design:

- a minimal home screen with recent task cards and command entry
- a prominent microphone button for host-side voice capture
- a task detail screen with plan progress, memory pills, and reversed action history
- confirmation and question sheets
- completion summaries with steps, duration, and saved memory count

## Environment Setup

### Prerequisites

You need:

- macOS
- Xcode with iOS Simulator support
- a bootable iOS simulator
- Python 3.11 or newer
- a Gemini API key
- WebDriverAgent running against the simulator

Optional, but currently useful:

- microphone access on the Mac host for server-side voice capture
- notification permission on the iOS app

### 1. Clone the repository

```bash
git clone <your-fork-or-repo-url>
cd spectra
```

### 2. Create a Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
```

Set your Gemini API key in `.env`:

```bash
GEMINI_API_KEY=your-gemini-key-here
```

Then load it into the current shell:

```bash
export $(grep -v '^#' .env | xargs)
```

If you use the Python launcher in `scripts/run_server.py`, it will also load `.env` automatically before starting the server.

### 4. Boot the simulator

```bash
xcrun simctl list devices
xcrun simctl boot "iPhone 15"
open -a Simulator
```

### 5. Start WebDriverAgent

Spectra expects WDA on `http://localhost:8100`.

```bash
xcodebuild -project WebDriverAgent.xcodeproj \
  -scheme WebDriverAgentRunner \
  -destination "platform=iOS Simulator,name=iPhone 15" \
  test
```

Verify that WDA is reachable:

```bash
curl http://localhost:8100/status
```

### 6. Open the iOS project

Open the Xcode project at [`ios/Spectra/Spectra.xcodeproj`](ios/Spectra/Spectra.xcodeproj), select the same booted simulator, and build the `Spectra` app.

## Running Spectra

The current codebase is designed around the WebSocket server plus the SwiftUI client. The older README flow using `main.py` is obsolete; there is no `main.py` entrypoint in this repository.

### Recommended development workflow

Run these in separate terminals.

#### Terminal 1: WebDriverAgent

Keep WDA running on port `8100`.

#### Terminal 2: Spectra backend

```bash
source .venv/bin/activate
python scripts/run_server.py
```

This is the preferred launcher for the current codebase. It:

- loads `.env` automatically
- adds the project root to `PYTHONPATH`
- starts Uvicorn on port `8765`
- disables WebSocket ping timeouts at the server layer, which is useful for the long-lived simulator connection

Equivalent manual launch options are still available:

```bash
# simple shell wrapper
./scripts/start_server.sh

# or direct uvicorn
uvicorn server.ws_server:app --host 0.0.0.0 --port 8765
```

The iOS simulator client connects to:

```text
ws://localhost:8765/ws
```

#### Terminal 3: Xcode / iOS app

Build and run the `Spectra` app from Xcode. Once launched, the app connects to the backend automatically.

### Typical usage

1. Start WDA.
2. Start the backend server.
3. Run the SwiftUI app on the simulator.
4. Enter a task such as `Open General settings` or `Compare Uber and Lyft prices to the airport`.
5. Approve plans or sensitive actions when prompted.
6. Review the result summary in the app.

### Backend-only smoke check

If you want to exercise the runtime without the SwiftUI app, you can call the Python entrypoint directly:

```bash
source .venv/bin/activate
export $(grep -v '^#' .env | xargs)
PYTHONPATH=. python -c "from core.agent import run_task; run_task('Open General settings')"
```

This uses the terminal-based approval flow instead of the WebSocket/iOS UI.

## Testing

There are two main categories of tests in this repository.

### Fast local tests

Most unit tests do not require a simulator or Gemini, but they do expect the repo root on `PYTHONPATH`.

```bash
source .venv/bin/activate
PYTHONPATH=. pytest tests/ -q
```

### Live integration tests

The following require a booted simulator with WDA:

- [`tests/test_tree_reader.py`](tests/test_tree_reader.py)
- [`tests/test_agent.py`](tests/test_agent.py)

The following also require `GEMINI_API_KEY`:

- [`tests/test_planner.py`](tests/test_planner.py)
- parts of [`tests/test_memory.py`](tests/test_memory.py)
- parts of [`tests/test_plan_preview.py`](tests/test_plan_preview.py)
- parts of [`tests/test_router.py`](tests/test_router.py)

### Current test caveats

As of March 28, 2026, local test execution in this workspace revealed a few issues that are useful to know:

- `pytest` must be run with `PYTHONPATH=.` or imports such as `core.*` and `server.*` fail during collection
- [`tests/test_memory.py`](tests/test_memory.py) currently has a failing persistence expectation because `EpisodicMemory.add_lesson()` rejects very short lesson strings
- several WebSocket endpoint tests currently fail because the installed `httpx` / `starlette` test client combination is incompatible with `TestClient`

Those issues do not change the runtime architecture, but they do affect contributor expectations when running the suite.

### WebSocket-specific coverage

[`tests/test_ws_server.py`](tests/test_ws_server.py) exercises the current socket protocol shape, including:

- task start and duplicate-task rejection
- voice-start handling
- stop-message unblocking behavior
- confirmation request / response flow
- plan preview approval flow

## Configuration

### Environment variables

Current environment variables used directly by the code:

- `GEMINI_API_KEY`: required by [`core/planner.py`](core/planner.py)

### App registry and gate labels

[`config/apps.json`](config/apps.json) controls:

- the app routing registry
- bundle IDs used for simulator launches
- sensitive labels that trigger user confirmation

### Ports and endpoints

- WDA: `http://localhost:8100`
- Spectra WebSocket server: `ws://localhost:8765/ws`

## Known Constraints

- The main supported execution target is the iOS simulator, not a physical device.
- Spectra depends on WebDriverAgent being healthy and connected.
- Screenshot mode exists as fallback, but the architecture is optimized for accessibility-tree-first operation.
- The planner is Gemini-based in the current codebase; some older docs still reference Claude and are no longer authoritative.
- The iOS client currently uses server-side voice capture from the Mac microphone in its primary home-screen flow, even though an on-device `SpeechService` also exists in the app.
- The lightweight `scripts/start_server.sh` entrypoint does not load `.env` or alter WebSocket ping settings; for the current simulator app flow, `python scripts/run_server.py` is the more complete launcher.

## Additional Documentation

- Product and architecture notes: [`docs/Spectra_PRD_Complete.md`](docs/Spectra_PRD_Complete.md)
- Internal build guide: [`docs/AGENTS.md`](docs/AGENTS.md)

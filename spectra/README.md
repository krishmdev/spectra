# Spectra: Accessibility-Tree iOS Agent

Spectra is an iOS mobile automation agent that controls applications by interacting directly with the accessibility tree. Unlike current vision-based agents that rely on coordinate-based screenshot parsing, Spectra reads the structured data used by VoiceOver to identify and interact with UI elements reliably.

This read-based approach reduces the context window to 200-500 tokens per state (compared to 3,000-5,000 tokens for vision models), significantly decreasing latency and cost while remaining completely resilient to UI layout and coordinate changes.

## Table of Contents

1. [Project Status](#project-status)
2. [Architecture Overview](#architecture-overview)
3. [Setup and Installation](#setup-and-installation)
4. [Module Specifications](#module-specifications)
5. [Data Contracts](#data-contracts)
6. [Testing and Development](#testing-and-development)

---

## 1. Project Status

The project has concluded **Sprint 5**. 
The core text-based automation loop is complete and functional. The agent can successfully observe the accessibility tree, formulate action plans using the Gemini API, and execute actions on the iOS simulator.

**Parallel Sprints (In Progress / Upcoming):**
* **Sprint 6:** Voice input integration and Rich terminal UI.
* **Sprint 7:** Action recording and deterministic replay capabilities.
* **Sprint 8:** Final demo deployment and polish.

---

## 2. Architecture Overview

Spectra operates on a continuous **Observe-Think-Act** loop. It relies on `facebook-wda` to communicate with WebDriverAgent running on an iOS Simulator.

* **Observe:** The Tree Reader pulls the accessibility tree XML from WebDriverAgent, filters approximately 2,000 raw elements down to the interactive elements, and assigns stable reference numbers `[1]`, `[2]`, `[3]`. If the tree is sparse or broken, it automatically falls back to base64 screenshot capture.
* **Think:** The LLM Planner passes the compact tree and user task to Gemini via `tool_use`. Gemini computes a structured action JSON.
* **Act:** The Action Executor translates the tool call into a WebDriverAgent REST command, waits for UI stabilization, and returns control to the loop.

---

## 3. Quick Start (CLI Setup)

This guide assumes you are starting from a clean terminal. Copy and paste these commands.

### 3.1 Clone and Environment Setup

```bash
# 1. Clone the repository
git clone https://github.com/krishmdev/yhack.git
cd yhack/spectra

# 2. Initialize Python virtual environment
python3 -m venv venv
source venv/bin/activate

# 3. Install core dependencies
pip install -r requirements.txt

# 4. Set up environment variables
cp .env.example .env
# Open .env and add your GEMINI_API_KEY
```

### 3.2 Launching the iOS Simulator (CLI)

You can launch the simulator directly from your terminal:

```bash
# List available simulators and grab a UUID (e.g., iPhone 15)
xcrun simctl list devices | grep "iPhone 15"

# Boot the simulator
xcrun simctl boot "iPhone 15" # Or use the UUID
open -a Simulator
```

### 3.3 WebDriverAgent (WDA) CLI Initialization

WebDriverAgent is the bridge between Python and iOS. You can run it without opening the Xcode UI:

```bash
# Locate the WebDriverAgent project (usually inside your site-packages or local clone)
# Run the test session to start the server on localhost:8100
xcodebuild -project WebDriverAgent.xcodeproj \
           -scheme WebDriverAgentRunner \
           -destination "platform=iOS Simulator,name=iPhone 15" \
           test
```

### 3.4 Verify and Run

Check if the bridge is alive:
```bash
curl http://localhost:8100/status
```

If you see a JSON blob with `value: { "state": "success" ... }`, you are ready to run:
```bash
python3 main.py --task "Toggle Dark Mode"
```

---

## 4. Module Specifications


The system is highly modular. Teammates addressing specific features should reference the appropriate module below.

### Core Loop Modules

* `core/tree_parser.py`: Processes raw XML. Filters out invisible (`visible="false"`), zero-sized (`width=0` or `height=0`), and non-interactive layout elements. Generates the compact string representation for the LLM and the detailed `ref_map` dictionary for the Executor.
* `core/tree_reader.py`: Establishes the WDA connection. Detects if the tree contains fewer than three interactive elements to trigger the screenshot-based fallback mechanism. Detects keyboard (`XCUIElementTypeKeyboard`) and modal alert states.
* `core/planner.py`: Manages communication with the Gemini API. Injects the system prompt and available JSON tools (`tap`, `type_text`, `scroll`, `wait`, `go_back`, `go_home`, `remember`, `handoff`, `plan`, `done`, `stuck`). Defines the prompt caching strategy.
* `core/executor.py`: Translates Gemini's tool selections into physical WDA commands. For example, replacing a `tap` action with a calculated center-coordinate click: `x + width/2, y + height/2`.
* `core/agent.py`: Orchestrates the main While-loop. Ties all modules together, manages sleep timings between actions, and yields step-by-step progress history.

### Auxiliary Systems

* `core/stuck_detector.py`: Pure logic class. Tracks md5 hashes of previous tree states and action history to detect infinite loops (e.g., repeating the same screen state or action three times sequentially).
* `core/gates.py`: Confirmation interception. Blocks the loop and requires human CLI input before the agent executes irreversible actions (matching labels like "Send", "Buy", "Delete").
* `core/takeover.py`: Allow the agent to pause execution entirely (the `handoff` tool) when encountering sensitive areas like `SecureTextField` password inputs or payment sheets, resuming only when the user signifies completion.
* `core/memory.py`: A cross-app key-value dictionary. Enables workflows requiring data transmission across different applications (e.g., comparing a price in Uber to Lyft).
* `core/router.py`: Intent routing. Matches the natural language request to an application Bundle ID using predefined registries.
* `core/plan_preview.py`: Generates a step-by-step reasoning plan for complex tasks, allowing user approval before the agent starts its loop.
* `core/background.py`: Threading wrapper that allows the agent to run in the background while feeding live progress updates to a UI via callbacks.

---

## 5. Data Contracts

If interacting with other modules, strictly adhere to the following schemas.

### `ref_map`
Generated by `tree_parser.py` and consumed by `executor.py`. Used to map the LLM's chosen reference integer back to accurate screen coordinates.
```python
{
    1: {
        'type': 'XCUIElementTypeCell',
        'label': 'Wi-Fi',
        'value': 'Connected',
        'x': 0, 'y': 200,             
        'width': 390, 'height': 44     
    }
}
```

### `metadata`
Generated by `tree_reader.py`. Directs the `planner` on whether to utilize tree-based or vision-based prompts and warns about intercepting UI elements.
```python
{
    'app_name': 'Settings',
    'keyboard_visible': False,
    'alert_present': True,
    'perception_mode': 'tree', # values: 'tree' | 'screenshot'
    'screenshot_b64': None     # populated if perception_mode == 'screenshot'
}
```

### Tool Usage JSON Schema
The standardized structure expected from `planner.py` when evaluating the LLM's output.
```python
{
    'name': 'type_text',
    'input': { 
        'ref': 4, 
        'text': 'Hello World',
        'reasoning': 'Entering search query into the text field.' 
    }
}
```

---

## 6. Testing and Development

Before submitting pull requests, run the comprehensive test suite to verify baseline functionality:

```bash
# Run all core tests
pytest tests/
```

**Key Test Files:**
* `tests/test_tree_parser.py`: Verifies XML pruning and token compression.
* `tests/test_tree_reader.py`: Verifies WDA connection and screenshot fallback logic.
* `tests/test_planner.py`: Verifies Gemini API communication and tool-call schema.
* `tests/test_memory.py`: Verifies cross-app data persistence.
* `tests/test_gates.py`: Verifies confirmation interception for sensitive labels.
* `tests/test_router.py`: Verifies app bundle ID matching.
* `tests/test_takeover.py`: Verifies user handoff logic.


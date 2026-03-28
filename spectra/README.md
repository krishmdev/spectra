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

## 3. Setup and Installation

### Prerequisites

* macOS (required for Xcode and the iOS Simulator)
* Xcode and Command Line Tools
* Python 3.11 or higher
* Google Gemini API Key

### Environment Configuration

1. **Clone the repository and initialize the Python environment:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

2. **Configure environment variables:**
Copy the example file and append your API credentials.
```bash
cp .env.example .env
```
Inside `.env`:
```env
GEMINI_API_KEY=your_key_here
```

### Simulator Configuration

Spectra requires a running iOS Simulator with WebDriverAgent installed.

1. Launch an iOS Simulator via Xcode or `simulator` CLI.
2. Build and run WebDriverAgent (WDA) on the booted simulator. Ensure the server is reachable at `http://localhost:8100`.

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

Before submitting pull requests to core modules, verify the following baseline functionality:

1. **Parser Verification**: Run `tree_parser.py` against a standard iOS Settings view XML dump. Ensure the output token length is < 500, all refs are sequential, and zero-dimensional objects are pruned.
2. **Fallback Verification**: Pass a Canvas or OpenGL view to `tree_reader.py`. Confirm that `perception_mode` correctly toggles to `screenshot` and a valid base64 PNG string is returned.
3. **Execution Accuracy**: Within `executor.py`, verify that `scroll down` correctly executes a WDA `swipe_up()` gesture (iOS scrolling is counter-intuitive relative to gesture direction).
4. **Agent Integration**: Run `agent.py` with a simple command like *"Turn on Airplane Mode"* to confirm the full observer-think-act chain executes linearly to a `done` state.

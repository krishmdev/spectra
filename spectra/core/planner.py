"""LLM Planner — sends compact tree + task to Gemini and gets a structured action back."""

import base64
import os

from google import genai
from google.genai import types

SYSTEM_PROMPT = """You are Spectra, an iOS mobile agent. You control an iPhone by reading the accessibility tree and performing actions.

CAPABILITIES:
You receive the current screen as a compact accessibility tree. Each interactive element has a [ref] number. Use these refs to specify action targets. Refs change every turn — never reuse old refs.

iOS NAVIGATION:
- Navigation bars at top have back buttons (chevron icon or parent screen name)
- Tab bars at bottom switch between app sections
- Alerts and sheets are modal — handle them before doing anything else
- When a text field is focused, the keyboard appears
- Containers may have content below the fold — scroll to find more
- "Loading..." or spinners mean wait before acting

MEMORY:
- Use the `remember` tool to store values you'll need later (prices, names, addresses, etc.)
- Stored values appear in the MEMORY section of each turn
- Use memory when comparing information across different apps
- Memory persists across app switches within a single task
- PAST LESSONS from previous failed runs may also appear — use them to avoid repeating mistakes

SAFETY:
- NEVER enter passwords, payment details, or personal information. Use `handoff` to give control to the user for sensitive input.
- If you see a SecureTextField (password field), ALWAYS use `handoff`.
- Before tapping buttons that look like they confirm transactions or send messages, explain what you're about to do in your reasoning. The system may ask the user for confirmation.

PLANNING:
- For complex tasks involving multiple apps or more than 5 steps, use the `plan` tool first to outline your approach.
- For simple tasks (single app, < 3 steps), skip planning and act directly.
- You are not rigidly bound to a plan — adapt if the app state differs from expectations.

RULES:
1. Examine the tree carefully before acting. Identify what screen you're on and what elements are available.
2. Choose exactly ONE action per turn.
3. If the target isn't visible, try scrolling to reveal more content.
4. If you've repeated the same action 2+ times without progress, try a completely different strategy.
5. Handle alerts and permission dialogs immediately.
6. Before calling done(), verify the screen shows the expected result.
7. Keep reasoning concise — one sentence.
8. Prefer tapping visible elements over scrolling. If you can see something related to your goal, tap it.
9. Use `batch` for predictable 2-5 step sequences where you're confident about the screen transitions. Never batch past uncertain transitions or dynamic content. Always set checkpoint_reason to what should be true after the batch."""

# ---------------------------------------------------------------------------
# Tool JSON schemas (from PRD §5.3) — passed via parameters_json_schema
# ---------------------------------------------------------------------------

_TOOL_SCHEMAS = [
    {
        "name": "tap",
        "description": "Tap a UI element by its ref number from the accessibility tree",
        "schema": {
            "type": "object",
            "properties": {
                "ref": {"type": "integer", "description": "Element [ref] number"},
                "reasoning": {"type": "string", "description": "Why this action"},
            },
            "required": ["ref", "reasoning"],
        },
    },
    {
        "name": "tap_xy",
        "description": "Tap screen coordinates directly. Only use in screenshot fallback mode when no ref_map is available.",
        "schema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate"},
                "y": {"type": "integer", "description": "Y coordinate"},
                "reasoning": {"type": "string"},
            },
            "required": ["x", "y", "reasoning"],
        },
    },
    {
        "name": "type_text",
        "description": "Type text into a text field. The field will be tapped first to focus it.",
        "schema": {
            "type": "object",
            "properties": {
                "ref": {"type": "integer", "description": "Text field [ref] number"},
                "text": {"type": "string", "description": "Text to type"},
                "reasoning": {"type": "string"},
            },
            "required": ["ref", "text", "reasoning"],
        },
    },
    {
        "name": "scroll",
        "description": "Scroll the screen to reveal more content",
        "schema": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["up", "down"]},
                "reasoning": {"type": "string"},
            },
            "required": ["direction", "reasoning"],
        },
    },
    {
        "name": "go_back",
        "description": "Navigate back (tap the back button or left-edge swipe)",
        "schema": {
            "type": "object",
            "properties": {
                "reasoning": {"type": "string"},
            },
            "required": ["reasoning"],
        },
    },
    {
        "name": "go_home",
        "description": "Press the home button to return to the home screen",
        "schema": {
            "type": "object",
            "properties": {
                "reasoning": {"type": "string"},
            },
            "required": ["reasoning"],
        },
    },
    {
        "name": "wait",
        "description": "Wait for content to load",
        "schema": {
            "type": "object",
            "properties": {
                "seconds": {"type": "integer", "minimum": 1, "maximum": 5},
                "reasoning": {"type": "string"},
            },
            "required": ["seconds", "reasoning"],
        },
    },
    {
        "name": "remember",
        "description": "Store a value from the current screen for later use. Use when comparing info across apps or remembering something for a future step.",
        "schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "What this value represents (e.g. 'uber_price')"},
                "value": {"type": "string", "description": "The value to remember (e.g. '$12.50')"},
                "reasoning": {"type": "string"},
            },
            "required": ["key", "value", "reasoning"],
        },
    },
    {
        "name": "handoff",
        "description": "Pause execution and hand control to the user for sensitive input like passwords, payment details, or personal information.",
        "schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "What the user needs to do manually"},
                "resume_hint": {"type": "string", "description": "What to look for when resuming"},
            },
            "required": ["reason"],
        },
    },
    {
        "name": "plan",
        "description": "Generate a step-by-step plan for completing the task. Use FIRST for complex tasks involving multiple apps or more than 5 steps.",
        "schema": {
            "type": "object",
            "properties": {
                "steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ordered list of high-level steps",
                },
                "reasoning": {"type": "string"},
            },
            "required": ["steps", "reasoning"],
        },
    },
    {
        "name": "done",
        "description": "The task is complete. Verify the screen shows the expected result before calling.",
        "schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "What was accomplished"},
            },
            "required": ["summary"],
        },
    },
    {
        "name": "stuck",
        "description": "Cannot make progress on the task",
        "schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Why the agent is stuck"},
            },
            "required": ["reason"],
        },
    },
    {
        "name": "batch",
        "description": "Execute 2-5 actions in sequence without re-observing between them. Use for predictable navigation sequences (e.g., tap General then tap About). Do NOT batch across uncertain transitions, search results, or dynamic content.",
        "schema": {
            "type": "object",
            "properties": {
                "actions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": ["tap", "tap_xy", "type_text", "scroll", "go_back", "go_home", "wait"]},
                            "ref": {"type": "integer"},
                            "x": {"type": "integer"},
                            "y": {"type": "integer"},
                            "text": {"type": "string"},
                            "direction": {"type": "string", "enum": ["up", "down"]},
                            "seconds": {"type": "integer"},
                        },
                        "required": ["action"],
                    },
                    "minItems": 2,
                    "maxItems": 5,
                },
                "checkpoint_reason": {"type": "string", "description": "What to verify on the next screen after batch completes"},
                "reasoning": {"type": "string"},
            },
            "required": ["actions", "checkpoint_reason", "reasoning"],
        },
    },
]

# Build Gemini FunctionDeclaration objects
TOOLS = [
    types.FunctionDeclaration(
        name=t["name"],
        description=t["description"],
        parameters_json_schema=t["schema"],
    )
    for t in _TOOL_SCHEMAS
]

# Force the model to always return a function call
TOOL_CONFIG = types.ToolConfig(
    function_calling_config=types.FunctionCallingConfig(
        mode="ANY",
    )
)


# ---------------------------------------------------------------------------
# Message builder
# ---------------------------------------------------------------------------

def build_message(
    task: str,
    tree: str,
    history: list[str],
    metadata: dict,
    warning: str | None = None,
    memory: str | None = None,
    plan: list[str] | None = None,
) -> str:
    """Construct the per-turn user message."""
    parts = [f"TASK: {task}"]

    if plan:
        plan_text = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(plan))
        parts.append(f"PLAN:\n{plan_text}")

    if memory:
        parts.append(f"MEMORY:\n{memory}")

    if metadata.get("alert_present"):
        parts.append("\u26a0\ufe0f ALERT is present on screen \u2014 handle it first.")
    if metadata.get("keyboard_visible"):
        parts.append("\u2328\ufe0f Keyboard is visible.")

    parts.append(f"SCREEN ({metadata.get('app_name', 'unknown')}):")
    parts.append(tree)

    if history:
        parts.append("RECENT ACTIONS:")
        for h in history[-5:]:
            parts.append(f"  {h}")

    if warning:
        parts.append(f"WARNING: {warning}")

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

class Planner:
    """Send compact tree + task to Gemini and get back a structured action."""

    def __init__(self, model: str = "gemini-3-flash-preview"):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY environment variable is not set")
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self._cache_name = self._create_cache()

    def _create_cache(self) -> str | None:
        """Create a content cache for the system prompt + tools.

        Caching avoids resending the ~1400-token system prompt + tool defs
        on every call. Falls back to inline config if caching fails.
        """
        try:
            cache = self.client.caches.create(
                model=self.model,
                config=types.CreateCachedContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    tools=[types.Tool(function_declarations=TOOLS)],
                    tool_config=TOOL_CONFIG,
                    ttl="3600s",
                    display_name="spectra-planner",
                ),
            )
            return cache.name
        except Exception:
            return None

    def _generate(self, contents: list) -> dict:
        """Call Gemini, using content cache when available."""
        if self._cache_name:
            config = types.GenerateContentConfig(
                cached_content=self._cache_name,
                max_output_tokens=1024,
            )
        else:
            config = types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                tools=[types.Tool(function_declarations=TOOLS)],
                tool_config=TOOL_CONFIG,
                max_output_tokens=1024,
            )

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=config,
            )
            return self._extract_action(response)
        except Exception as e:
            if '429' in str(e) or 'RESOURCE_EXHAUSTED' in str(e):
                raise RuntimeError(
                    f'API rate limit hit — stopping agent. Details: {e}'
                ) from e
            raise

    def next_action(
        self,
        tree: str,
        task: str,
        history: list[str],
        metadata: dict,
        warning: str | None = None,
        memory: str | None = None,
        plan: list[str] | None = None,
    ) -> dict:
        """Tree mode (primary). Returns {'name': str, 'input': dict}."""
        message = build_message(task, tree, history, metadata, warning, memory, plan)
        contents = [types.Content(role="user", parts=[types.Part(text=message)])]
        return self._generate(contents)

    def next_action_vision(
        self,
        screenshot_b64: str,
        tree: str,
        task: str,
        history: list[str],
        metadata: dict,
        warning: str | None = None,
        memory: str | None = None,
        plan: list[str] | None = None,
    ) -> dict:
        """Screenshot fallback mode. Sends image + sparse tree to Gemini vision."""
        message = build_message(task, tree, history, metadata, warning, memory, plan)
        image_part = types.Part(
            inline_data=types.Blob(
                mime_type="image/png",
                data=base64.b64decode(screenshot_b64),
            )
        )
        text_part = types.Part(text=message)
        contents = [types.Content(role="user", parts=[image_part, text_part])]
        return self._generate(contents)

    def reflect(self, task: str, history: list[str], failure_type: str) -> str:
        """Generate a one-sentence lesson from a failed run."""
        prompt = (
            f'You are analyzing a failed mobile agent run.\n'
            f'Task: {task}\n'
            f'Failure: {failure_type}\n'
            f'Action history:\n' + '\n'.join(history[-8:]) + '\n\n'
            f'In ONE sentence, what specific lesson should the agent remember '
            f'to avoid this failure next time? Name the app, screen, and what '
            f'to do differently. Do NOT give generic advice.'
        )
        config = types.GenerateContentConfig(max_output_tokens=150)
        response = self.client.models.generate_content(
            model=self.model,
            contents=[types.Content(role='user', parts=[types.Part(text=prompt)])],
            config=config,
        )
        return response.text.strip()

    @staticmethod
    def _extract_action(response) -> dict:
        """Pull the function call from the Gemini response."""
        for candidate in response.candidates:
            for part in candidate.content.parts:
                if part.function_call:
                    fc = part.function_call
                    return {"name": fc.name, "input": dict(fc.args)}
        raise RuntimeError(f"Gemini returned no function call: {response}")

"""LLM Planner — sends compact tree + task to Gemini and gets a structured action back."""
from __future__ import annotations

import base64
import os

from google import genai
from google.genai import types

SYSTEM_PROMPT = """You are Spectra, an iOS mobile agent. You control an iPhone by reading the accessibility tree and performing actions.

CAPABILITIES:
You receive the current screen as a compact accessibility tree. Each interactive element has a [ref] number. Use these refs to specify action targets. Refs change every turn — never reuse old refs.

ALREADY DONE — CHECK EVERY STEP:
- BEFORE choosing an action, read the RECENT ACTIONS history and the current screen.
- If the screen already shows the desired end state, call done() immediately. Do NOT re-do completed work.
- If your history shows you already performed the key action (typed text, tapped save/done/confirm, deleted something), and the screen now reflects that result — call done() immediately.
- Do NOT repeat an action you already performed. If you typed text and tapped Done/Save, the task IS complete.

SPEED — BE DECISIVE:
- Act immediately on what you see. Do NOT scroll or explore unless the target truly isn't on screen.
- Use `batch` aggressively for predictable navigation (e.g., Settings → General → About = one batch).
- If you see the target element, tap it NOW. Don't plan, don't scroll, don't think twice.
- Aim to complete tasks in 3-8 steps. If you're past 10 steps, you're doing something wrong.
- NEVER use go_home to navigate to an app. Use open_app with the bundle ID instead — it's 10x faster. go_home should ONLY be used if you literally need to see the home screen itself.
- When in a detail/edit screen that likely has more content below, combine scroll + tap in a batch rather than separate steps.

ADAPTABILITY — USE WHAT'S ON SCREEN:
- Match by MEANING, not exact text. Users say things casually. The closest semantic match IS correct.
- The exact button you expect may not exist. Think about the user's GOAL, not a specific label.
- After ONE failed scroll looking for something, STOP. Re-examine every element on screen and ask: "Does any of these achieve the user's goal?" If yes, tap it. If the goal is already achieved, call done().
- NEVER scroll more than twice looking for the same thing. After 2 scrolls, use the best available option or call done().
- Only use `ask_user` as a last resort when you truly cannot determine how to proceed.

iOS NAVIGATION:
- Navigation bars at top have back buttons (chevron icon or parent screen name)
- Tab bars at bottom switch between app sections
- Alerts and sheets are modal — handle them before doing anything else
- When a text field is focused, the keyboard appears
- Containers may have content below the fold — scroll to find more

MEMORY:
- Use `remember` to store values for cross-app comparison
- PAST LESSONS from previous runs may appear — follow them

SAFETY:
- NEVER enter passwords or payment details. Use `handoff` for sensitive input.
- If you see a SecureTextField (password field), ALWAYS use `handoff`.

RULES:
1. Examine the tree. Identify the screen and available elements.
2. Choose exactly ONE action per turn (or use `batch` for predictable sequences).
3. If the target isn't visible, scroll ONCE. If still not found, adapt.
4. Same action twice with no progress → completely different strategy.
5. Handle alerts and permission dialogs immediately.
6. Before done(), verify the screen shows the expected result.
7. Keep reasoning to one sentence.
8. Prefer tapping visible elements over scrolling.
9. Use `batch` for 2-5 step predictable sequences. Never batch past uncertain transitions.
10. After completing ALL parts of a multi-part task, call done() IMMEDIATELY. Do NOT re-verify by searching again — if you just saw the confirmation (e.g. deletion alert dismissed, contact saved), that IS your verification. Call done() with a summary of everything accomplished.
11. NEVER repeat a create/type/save action. If RECENT ACTIONS shows you already typed text and tapped Done/Save/Add, the task is COMPLETE — call done() now."""

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
        "description": "Press the home button to return to the home screen. AVOID THIS — use open_app instead whenever you need to switch apps.",
        "schema": {
            "type": "object",
            "properties": {
                "reasoning": {"type": "string"},
            },
            "required": ["reasoning"],
        },
    },
    {
        "name": "open_app",
        "description": "Launch an app directly by bundle ID. MUCH faster than go_home + tap icon. Use this whenever you need to open or switch to an app. Common bundle IDs: com.apple.MobileAddressBook (Contacts), com.apple.Preferences (Settings), com.apple.mobilesafari (Safari), com.apple.MobileSMS (Messages), com.apple.mobilephone (Phone), com.apple.mobilecal (Calendar), com.apple.mobilemail (Mail), com.apple.Maps (Maps), com.apple.mobilenotes (Notes), com.apple.reminders (Reminders), com.apple.camera (Camera), com.apple.Photos (Photos), com.apple.Health (Health), com.apple.weather (Weather), com.apple.clock (Clock), com.apple.calculator (Calculator), com.apple.AppStore (App Store), com.apple.Music (Music), com.apple.news (News), com.apple.iBooks (Books), com.apple.Fitness (Fitness), com.apple.findmy (Find My), com.apple.DocumentsApp (Files), com.apple.shortcuts (Shortcuts), com.apple.Translate (Translate), com.apple.VoiceMemos (Voice Memos), com.apple.Magnifier (Magnifier), com.apple.tips (Tips), com.apple.tv (TV), com.apple.podcasts (Podcasts), com.apple.stocks (Stocks), com.apple.compass (Compass), com.apple.measure (Measure), com.apple.facetime (FaceTime).",
        "schema": {
            "type": "object",
            "properties": {
                "bundle_id": {"type": "string", "description": "The app's bundle ID (e.g. com.apple.MobileAddressBook)"},
                "reasoning": {"type": "string"},
            },
            "required": ["bundle_id", "reasoning"],
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
        "name": "ask_user",
        "description": "Ask the user a question when you need clarification — e.g., a requested element doesn't exist, there are multiple similar options, or the task is ambiguous. Only use for decisions you cannot make yourself.",
        "schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The question to ask the user"},
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of choices the user can pick from",
                },
                "reasoning": {"type": "string"},
            },
            "required": ["question", "reasoning"],
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

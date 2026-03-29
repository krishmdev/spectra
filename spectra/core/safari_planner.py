"""Safari web planner — Gemini with web-specific tools and system prompt."""
from __future__ import annotations

import os

from google import genai
from google.genai import types

WEB_SYSTEM_PROMPT = """You are Spectra, a web browser agent controlling Safari on macOS. You read the webpage accessibility tree and perform actions to complete tasks.

CAPABILITIES:
You receive the current page as a compact accessibility tree. Each interactive element has a [ref] number. Use refs for action targets. Refs change every step — never reuse old refs.

NAVIGATION — MOST IMPORTANT:
- Use `navigate(url)` to go to any website. This is instant — one step, no typing.
- NEVER tap the address bar and type a URL. Use `navigate` always.
- When the task requires a different site than the current URL, call `navigate` as step 1.
- Always include the full URL: https://www.example.com

PAYWALLS & OVERLAYS:
- On macOS Safari: paywalls are auto-dismissed before you see the snapshot. If content is still blocked, the dismissal may have missed a variant — try scrolling or navigate away.
- If PAGE_ALERTS still mentions a cookie/consent banner after auto-dismissal: call `dismiss_paywall` which re-runs the JS removal.
- After any dismissal, the next snapshot will show the full page content.

PAGE UNDERSTANDING:
- PAGE_ARTICLES lists article headlines visible on the page — use to identify what to tap.
- PAGE_HEADINGS shows main headings for orientation.
- Current URL is always shown — use it to confirm you're on the right site.

ALREADY DONE:
- Read RECENT ACTIONS before every step. If the URL shows you already navigated there, don't navigate again.
- If the screen already shows the desired result, call done() immediately.

SPEED:
- Complete tasks in 3–8 steps. If you're at step 10+, rethink.
- Tap visible elements directly — only scroll if the target genuinely isn't visible.
- Use `batch` for 2–5 predictable actions (e.g., dismiss banner then click article).
- Never scroll more than twice looking for the same thing.

SCROLLING:
- Before scrolling, check PAGE_ARTICLES — the article you want may already be listed.
- After 2 failed scrolls for the same target, use the closest available option or call done().

RULES:
1. Check current URL first. Only call `navigate` if you're on the wrong site.
2. Dismiss paywalls and overlays before trying to interact with page content.
3. Match elements by meaning — exact label text may differ from the user's words.
4. Never repeat a successful action.
5. call done() immediately once the task is complete — don't re-verify.
6. After 3 failed attempts at different approaches, call stuck() with the reason.
7. NEVER type in the Safari address bar — always use navigate().
8. For NYT and other subscription sites: look for free article signals or dismiss paywalls."""

_TOOL_SCHEMAS = [
    {
        "name": "tap",
        "description": "Tap a UI element by its ref number from the accessibility tree.",
        "schema": {
            "type": "object",
            "properties": {
                "ref": {"type": "integer", "description": "Element [ref] number"},
                "reasoning": {"type": "string"},
            },
            "required": ["ref", "reasoning"],
        },
    },
    {
        "name": "type_text",
        "description": "Type text into a focused text field (search boxes, forms).",
        "schema": {
            "type": "object",
            "properties": {
                "ref": {"type": "integer"},
                "text": {"type": "string"},
                "reasoning": {"type": "string"},
            },
            "required": ["ref", "text", "reasoning"],
        },
    },
    {
        "name": "scroll",
        "description": "Scroll the page to reveal more content. Max 2 scrolls per target.",
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
        "name": "dismiss_paywall",
        "description": "Remove paywall/subscription/cookie overlays via JavaScript. Use if page content is still blocked after auto-dismissal.",
        "schema": {
            "type": "object",
            "properties": {
                "reasoning": {"type": "string"},
            },
            "required": ["reasoning"],
        },
    },
    {
        "name": "navigate",
        "description": "Navigate Safari to a URL directly. ALWAYS use this instead of typing in the address bar. Include full URL with https://.",
        "schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Full URL e.g. https://www.reuters.com"},
                "reasoning": {"type": "string"},
            },
            "required": ["url", "reasoning"],
        },
    },
    {
        "name": "go_back",
        "description": "Navigate back to the previous page (browser back button).",
        "schema": {
            "type": "object",
            "properties": {
                "reasoning": {"type": "string"},
            },
            "required": ["reasoning"],
        },
    },
    {
        "name": "batch",
        "description": "Execute 2–5 actions in sequence without re-observing. Use for predictable sequences only (e.g., dismiss cookie banner then tap article).",
        "schema": {
            "type": "object",
            "properties": {
                "actions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "action": {"type": "string", "enum": ["tap", "type_text", "scroll", "navigate", "go_back"]},
                            "ref": {"type": "integer"},
                            "text": {"type": "string"},
                            "url": {"type": "string"},
                            "direction": {"type": "string", "enum": ["up", "down"]},
                        },
                        "required": ["action"],
                    },
                    "minItems": 2,
                    "maxItems": 5,
                },
                "checkpoint_reason": {"type": "string"},
                "reasoning": {"type": "string"},
            },
            "required": ["actions", "checkpoint_reason", "reasoning"],
        },
    },
    {
        "name": "done",
        "description": "Task is complete.",
        "schema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
            },
            "required": ["summary"],
        },
    },
    {
        "name": "stuck",
        "description": "Cannot complete the task after multiple approaches.",
        "schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string"},
            },
            "required": ["reason"],
        },
    },
]

TOOLS = [
    types.FunctionDeclaration(
        name=t["name"],
        description=t["description"],
        parameters_json_schema=t["schema"],
    )
    for t in _TOOL_SCHEMAS
]

TOOL_CONFIG = types.ToolConfig(
    function_calling_config=types.FunctionCallingConfig(mode="ANY")
)


def build_web_message(
    task: str,
    screen: dict,
    history: list[str],
    warning: str | None = None,
) -> str:
    """Construct the per-turn message for the web agent."""
    parts = [f"TASK: {task}"]

    url   = screen.get("url", "")
    title = screen.get("page_title", "")
    tree  = screen.get("tree", "")

    parts.append(f"CURRENT URL: {url}")
    if title:
        parts.append(f"PAGE TITLE: {title}")

    if screen.get("paywall_detected"):
        parts.append(f"⚠️ PAYWALL_DETECTED ({screen.get('paywall_type', 'unknown')}) — dismiss before interacting with content.")

    alerts = screen.get("page_alerts", [])
    if alerts:
        parts.append("PAGE_ALERTS:\n" + "\n".join(f"  • {a[:120]}" for a in alerts))

    articles = screen.get("page_articles", [])
    if articles:
        parts.append("PAGE_ARTICLES (visible headlines):\n" + "\n".join(f"  {i+1}. {a}" for i, a in enumerate(articles)))

    headings = screen.get("page_headings", [])
    if headings:
        parts.append("PAGE_HEADINGS: " + " | ".join(headings[:5]))

    parts.append("ACCESSIBILITY TREE (interactive elements):")
    parts.append(tree if tree else "(empty — page may still be loading)")

    if history:
        parts.append("RECENT ACTIONS:")
        for h in history[-6:]:
            parts.append(f"  {h}")

    if warning:
        parts.append(f"WARNING: {warning}")

    return "\n\n".join(parts)


class SafariPlanner:
    """Web-aware planner for Safari browser tasks."""

    def __init__(self, model: str = "gemini-2.5-flash-preview-04-17"):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY not set")
        self.client = genai.Client(api_key=api_key)
        self.model  = model
        self._cache_name = self._create_cache()

    def _create_cache(self) -> str | None:
        try:
            cache = self.client.caches.create(
                model=self.model,
                config=types.CreateCachedContentConfig(
                    system_instruction=WEB_SYSTEM_PROMPT,
                    tools=[types.Tool(function_declarations=TOOLS)],
                    tool_config=TOOL_CONFIG,
                    ttl="3600s",
                    display_name="spectra-safari-planner",
                ),
            )
            return cache.name
        except Exception:
            return None

    def next_action(self, screen: dict, task: str, history: list[str], warning: str | None = None) -> dict:
        message = build_web_message(task, screen, history, warning)
        contents = [types.Content(role="user", parts=[types.Part(text=message)])]

        if self._cache_name:
            config = types.GenerateContentConfig(
                cached_content=self._cache_name,
                max_output_tokens=512,
            )
        else:
            config = types.GenerateContentConfig(
                system_instruction=WEB_SYSTEM_PROMPT,
                tools=[types.Tool(function_declarations=TOOLS)],
                tool_config=TOOL_CONFIG,
                max_output_tokens=512,
            )

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=config,
            )
            return self._extract_action(response)
        except Exception as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                raise RuntimeError(f"API rate limit: {e}") from e
            raise

    def reflect(self, task: str, history: list[str], failure_type: str) -> str:
        prompt = (
            f"You are analyzing a failed web browser agent run.\n"
            f"Task: {task}\nFailure: {failure_type}\n"
            f"Actions:\n" + "\n".join(history[-8:]) + "\n\n"
            f"In ONE sentence, what specific lesson should be remembered to avoid this next time? "
            f"Name the site and what to do differently."
        )
        config = types.GenerateContentConfig(max_output_tokens=100)
        response = self.client.models.generate_content(
            model=self.model,
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
            config=config,
        )
        return response.text.strip()

    @staticmethod
    def _extract_action(response) -> dict:
        for candidate in response.candidates:
            for part in candidate.content.parts:
                if part.function_call:
                    fc = part.function_call
                    return {"name": fc.name, "input": dict(fc.args)}
        raise RuntimeError(f"Gemini returned no function call: {response}")

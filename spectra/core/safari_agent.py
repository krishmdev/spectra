"""Safari agent loop — observe (via WebSocket screen_update) → think → act."""
from __future__ import annotations

import threading
import time
from typing import Callable

from core.safari_planner import SafariPlanner
from core.stuck_detector import StuckDetector
from core.memory import EpisodicMemory

# Terminal actions
_TERMINAL = {"done", "stuck"}

# How long to wait for a screen_update after each action type
_SCREEN_TIMEOUT: dict[str, float] = {
    "navigate":        6.0,   # full page load
    "go_back":         4.0,
    "tap":             4.0,   # may trigger navigation
    "type_text":       2.0,
    "scroll":          1.5,
    "dismiss_paywall": 1.5,   # DOM removal + scroll restore
}


def run_safari_agent(
    task: str,
    initial_screen: dict,
    send_fn: Callable[[dict], None],
    screen_update_event: threading.Event,
    screen_update_data: dict,           # mutated in-place by the WS handler
    stop_event: threading.Event,
    step_callback: Callable | None = None,
    max_steps: int = 20,
    verbose: bool = True,
) -> bool:
    """
    Safari observe → think → act loop.

    send_fn         — sends a dict as a WebSocket message to the Swift client
    screen_update_event — set by the WS handler when a screen_update arrives
    screen_update_data  — populated with the latest screen dict before the event is set
    """
    planner  = SafariPlanner()
    detector = StuckDetector()
    episodic = EpisodicMemory()

    lessons = episodic.retrieve(task)
    if lessons and verbose:
        print(f"  [safari] Past lessons: {lessons}")

    history: list[str] = []
    current_screen = initial_screen
    t_start = time.monotonic()

    for step in range(1, max_steps + 1):
        if stop_event.is_set():
            break

        url   = current_screen.get("url", "")
        tree  = current_screen.get("tree", "")
        title = current_screen.get("page_title", "")

        # --- Stuck detection ---
        stuck_signal = detector.check()
        warning: str | None = None
        if stuck_signal == "HARD_STUCK":
            if verbose:
                print(f"  [safari] Hard stuck at step {step} — forcing done")
            send_fn({"type": "done", "success": True,
                     "summary": "Task likely completed (loop detected)", "steps": step,
                     "duration": round(time.monotonic() - t_start, 1)})
            return True

        # Build warning from paywall / alerts
        if current_screen.get("paywall_detected"):
            pw_type = current_screen.get("paywall_type", "unknown")
            warning = f"PAYWALL active ({pw_type}) — dismiss it before accessing content."
        alerts = current_screen.get("page_alerts", [])
        if alerts:
            alert_str = "; ".join(a[:80] for a in alerts[:3])
            warning = (warning + " | " if warning else "") + f"PAGE ALERTS: {alert_str}"
        if lessons:
            warning = (warning + " | " if warning else "") + lessons

        # --- Think ---
        t_think = time.monotonic()
        try:
            action = planner.next_action(current_screen, task, history, warning=warning)
        except Exception as e:
            if verbose:
                print(f"  [safari] Planner error: {e}")
            send_fn({"type": "error", "message": str(e)})
            return False
        think_ms = int((time.monotonic() - t_think) * 1000)

        action_name  = action["name"]
        action_input = action["input"]
        reasoning    = action_input.get("reasoning", action_input.get("summary", action_input.get("reason", "")))

        if verbose:
            print(f"  [safari] Step {step}: {action_name} — {reasoning}  ({think_ms}ms)")

        if step_callback:
            step_callback(step, max_steps, action_name, action_input, "", "Safari", {}, tree)

        # --- Terminal ---
        if action_name == "done":
            elapsed = round(time.monotonic() - t_start, 1)
            send_fn({"type": "done", "success": True,
                     "summary": action_input.get("summary", task),
                     "steps": step, "duration": elapsed})
            return True

        if action_name == "stuck":
            elapsed = round(time.monotonic() - t_start, 1)
            reason = action_input.get("reason", "Unknown")
            send_fn({"type": "stuck", "reason": reason})
            try:
                lesson = planner.reflect(task, history, "stuck")
                episodic.add_lesson(task=task, app="Safari", lesson=lesson,
                                    failure_type="stuck", history_summary="; ".join(history[-5:]))
                if verbose:
                    print(f"  [safari] Lesson: {lesson}")
            except Exception:
                pass
            return False

        # --- Batch: send each sub-action individually ---
        if action_name == "batch":
            sub_actions = action_input.get("actions", [])
            for i, sub in enumerate(sub_actions):
                sub_name = sub.get("action", "")
                _send_ax_action(send_fn, sub_name, sub)
                history.append(f"Step {step}.{i+1}: {sub_name}")
                detector.record(tree, sub_name, sub.get("ref"))
                # Wait for screen to settle after each sub-action
                timeout = _SCREEN_TIMEOUT.get(sub_name, 3.0)
                screen_update_event.clear()
                if screen_update_event.wait(timeout=timeout):
                    current_screen = dict(screen_update_data)
                    tree = current_screen.get("tree", tree)
            history.append(f"Step {step}: batch ({len(sub_actions)} actions)")
            continue

        # --- Single action ---
        _send_ax_action(send_fn, action_name, action_input)
        history.append(f"Step {step}: {action_name} {_summarize_input(action_input)}")
        detector.record(tree, action_name, action_input.get("ref"))

        # --- Wait for screen update ---
        timeout = _SCREEN_TIMEOUT.get(action_name, 3.0)
        screen_update_event.clear()
        if screen_update_event.wait(timeout=timeout):
            current_screen = dict(screen_update_data)
        else:
            if verbose:
                print(f"  [safari] Step {step}: screen_update timeout ({timeout}s) — using last known state")

    # Max steps reached
    elapsed = round(time.monotonic() - t_start, 1)
    send_fn({"type": "stuck", "reason": f"Reached max steps ({max_steps})"})
    try:
        lesson = planner.reflect(task, history, "timeout")
        episodic.add_lesson(task=task, app="Safari", lesson=lesson,
                            failure_type="timeout", history_summary="; ".join(history[-5:]))
    except Exception:
        pass
    return False


def _send_ax_action(send_fn: Callable, action_name: str, action_input: dict) -> None:
    """Send a single ax_action message to the Swift client."""
    send_fn({
        "type":   "ax_action",
        "action": action_name,
        "ref":    action_input.get("ref"),
        "params": action_input,
    })


def _summarize_input(inp: dict) -> str:
    """Compact one-liner for history logging."""
    if "url" in inp:
        return f"url={inp['url']}"
    if "ref" in inp:
        label = inp.get("text") or inp.get("reasoning", "")[:40]
        return f"ref={inp['ref']} {label}"
    return str(inp)[:60]

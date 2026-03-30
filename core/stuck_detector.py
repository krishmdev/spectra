"""Deterministic loop and stuck detection outside the LLM."""
from __future__ import annotations

import hashlib


class StuckDetector:
    """Track action history and detect when the agent is stuck in a loop."""

    def __init__(self):
        self.tree_hashes: list[str] = []
        self.action_history: list[tuple[str, int | None]] = []

    def record(self, tree_text: str, action: str, ref: int | None = None):
        """Record a step for analysis."""
        h = hashlib.md5(tree_text.encode()).hexdigest()[:8]
        self.tree_hashes.append(h)
        self.action_history.append((action, ref))

    def check(self) -> str | None:
        """Return a warning string if stuck, None otherwise."""
        # Same screen 3x
        if len(self.tree_hashes) >= 3:
            if len(set(self.tree_hashes[-3:])) == 1:
                return 'Screen unchanged for 3 actions. Try scrolling or a different element.'

        # Same action+ref 3x
        if len(self.action_history) >= 3:
            if len(set(self.action_history[-3:])) == 1:
                return 'Same action repeated 3 times. Try a completely different approach.'

        # Alternating 2-action loop (A→B→A→B = 4 actions)
        if len(self.action_history) >= 4:
            a, b, c, d = self.action_history[-4:]
            if a == c and b == d and a != b:
                return (
                    'You are stuck in an alternating loop repeating the same 2 actions. '
                    'STOP and call done() if the task is actually complete, or try a '
                    'completely different approach. Do NOT open_app again.'
                )

        # Hard stuck: same 2-action pair repeated 3x (6 actions) — unrecoverable
        if len(self.action_history) >= 6:
            pairs = [(self.action_history[i], self.action_history[i+1])
                     for i in range(-6, -1, 2)]
            if len(set(pairs)) == 1:
                return 'HARD_STUCK'

        # Excessive scrolling — 3+ scrolls in last 5 actions means the target doesn't exist
        if len(self.action_history) >= 5:
            recent = self.action_history[-5:]
            scroll_count = sum(1 for a in recent if a[0] == 'scroll')
            if scroll_count >= 3:
                return (
                    'You have scrolled 3+ times recently. The element you want DOES NOT EXIST. '
                    'STOP scrolling. The action you need is already on screen under a different name, '
                    'or the task is already complete. Use what is visible or call done().'
                )

        # Navigation spam — 4 consecutive non-tap actions
        nav_actions = {'scroll', 'swipe', 'wait', 'go_back', 'open_app', 'go_home'}
        if len(self.action_history) >= 4:
            if all(a[0] in nav_actions for a in self.action_history[-4:]):
                return '4 consecutive navigation actions without tapping. Interact with a specific element.'

        return None

    def reset(self):
        """Clear all recorded history."""
        self.tree_hashes.clear()
        self.action_history.clear()

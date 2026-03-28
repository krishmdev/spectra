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

        # Navigation spam — 4 consecutive non-tap actions
        nav_actions = {'scroll', 'swipe', 'wait', 'go_back'}
        if len(self.action_history) >= 4:
            if all(a[0] in nav_actions for a in self.action_history[-4:]):
                return '4 consecutive navigation actions without tapping. Interact with a specific element.'

        return None

    def reset(self):
        """Clear all recorded history."""
        self.tree_hashes.clear()
        self.action_history.clear()

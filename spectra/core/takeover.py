"""User takeover — pauses the agent loop so the user can interact with the device manually."""


class TakeoverManager:
    """Handle handoff actions by pausing the agent and waiting for the user."""

    def __init__(self):
        self._paused = False

    def pause(self, reason: str) -> None:
        """Pause the agent loop and notify the user they have control.

        Args:
            reason: Why control is being handed over (e.g. "Password entry required").
        """
        self._paused = True
        print(f'\n🤚 Your turn: {reason}')
        print('   The agent is paused. Interact with the device as needed.')

    def wait_for_resume(self) -> None:
        """Block until the user signals they're done (presses Enter)."""
        input('   Press Enter when done...')
        self._paused = False

    def is_paused(self) -> bool:
        """Check if agent is currently paused for user takeover."""
        return self._paused

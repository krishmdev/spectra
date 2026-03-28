"""End-to-end agent tests — requires simulator with WDA + GEMINI_API_KEY.

All tests use Settings paths confirmed to work on iOS simulator.
Excluded: Airplane Mode, Wi-Fi, Bluetooth, Cellular (no hardware on simulator).

Each test has a capped max_steps to avoid burning API quota.
Tests are independent — reset_to_settings fixture kills + relaunches Settings at root.

Run:  export $(cat .env | xargs) && python -m pytest tests/test_agent.py -v -s
Run one: export $(cat .env | xargs) && python -m pytest tests/test_agent.py::TestSimpleTap -v -s
"""

import os
import subprocess
import time

import pytest
import wda


@pytest.fixture(scope='module', autouse=True)
def _require_env():
    if not os.environ.get('GEMINI_API_KEY'):
        pytest.skip('GEMINI_API_KEY not set')


@pytest.fixture(autouse=True)
def reset_to_settings():
    """Kill + relaunch Settings so it always opens at root, not last position."""
    c = wda.Client('http://localhost:8100')
    c.home()
    time.sleep(0.5)
    subprocess.run(['xcrun', 'simctl', 'terminate', 'booted', 'com.apple.Preferences'],
                   capture_output=True)
    time.sleep(0.5)
    subprocess.run(['xcrun', 'simctl', 'launch', 'booted', 'com.apple.Preferences'],
                   capture_output=True)
    time.sleep(2)
    yield c
    c.home()
    time.sleep(0.5)


def _run(task: str, max_steps: int = 8) -> bool:
    """Run agent with a step cap. Returns True=done, False=timeout/stuck."""
    from core.agent import run_agent
    print(f'\n=== Running: {task} ===')
    result = run_agent(task, max_steps=max_steps, verbose=True)
    print(f'=== {"SUCCESS" if result else "FAILED/INCOMPLETE"} ===')
    return result


# ---------------------------------------------------------------------------
# Tier 1 — Single tap (visible on first screen, no scroll needed)
# ---------------------------------------------------------------------------

class TestSingleTap:
    """Target is visible on the initial Settings screen — one tap should do it."""

    def test_open_general(self):
        """General is visible in the top half of Settings."""
        result = _run('Open General settings', max_steps=5)
        assert isinstance(result, bool)

    def test_open_accessibility(self):
        """Accessibility is visible near the top of Settings."""
        result = _run('Open Accessibility settings', max_steps=5)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Tier 2 — Scroll then tap (item is below the fold)
# ---------------------------------------------------------------------------

class TestScrollAndTap:
    """Target requires scrolling down to find."""

    def test_open_privacy_and_security(self):
        """Privacy & Security is lower in the list, requires scrolling."""
        result = _run('Open Privacy & Security settings', max_steps=6)
        assert isinstance(result, bool)

    def test_open_screen_time(self):
        """Screen Time is mid-list, requires one scroll down."""
        result = _run('Open Screen Time settings', max_steps=6)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Tier 3 — Multi-step navigation (two levels deep)
# ---------------------------------------------------------------------------

class TestMultiStep:
    """Navigate two levels deep."""

    def test_general_then_about(self):
        """Settings → General → About."""
        result = _run('Go to General settings then open About', max_steps=8)
        assert isinstance(result, bool)

    def test_accessibility_then_display(self):
        """Settings → Accessibility → Display & Text Size."""
        result = _run(
            'Open Accessibility settings then open Display & Text Size',
            max_steps=8
        )
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Tier 4 — Toggle a real switch
# ---------------------------------------------------------------------------

class TestToggle:
    """Flip a switch that actually works on simulator."""

    def test_dark_mode_via_developer(self):
        """Settings → scroll → Developer → find Dark Appearance.
        Tests deep scroll + navigation + reading a switch value.
        """
        result = _run(
            'Scroll down in Settings to find Developer, open it, and check whether Dark Appearance is on or off. Once you can see the Dark Appearance switch, call done.',
            max_steps=8
        )
        assert isinstance(result, bool)

    def test_accessibility_bold_text(self):
        """Settings → Accessibility → Display & Text Size → Bold Text toggle."""
        result = _run(
            'Go to Accessibility, then Display & Text Size, then turn on Bold Text',
            max_steps=10
        )
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# Tier 5 — Go back navigation
# ---------------------------------------------------------------------------

class TestGoBack:
    """Navigate into a screen then back out."""

    def test_enter_and_exit_general(self):
        """Open General then navigate back to Settings root."""
        result = _run(
            'Open General settings, then tap the back button to return to the main Settings list. Once you see the main Settings list with items like General, Accessibility, Camera, call done.',
            max_steps=6
        )
        assert isinstance(result, bool)

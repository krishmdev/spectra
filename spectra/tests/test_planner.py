"""Tests for core.planner — Gemini function-calling planner.

Requires GEMINI_API_KEY in the environment.
Run:  python -m pytest tests/test_planner.py -v -s
"""

import os
import pytest
from core.planner import Planner, build_message, TOOLS, _TOOL_SCHEMAS

# ---------------------------------------------------------------------------
# Unit tests (no API call needed)
# ---------------------------------------------------------------------------

VALID_TOOL_NAMES = {t["name"] for t in _TOOL_SCHEMAS}


class TestBuildMessage:

    def test_basic_format(self):
        msg = build_message(
            task="Open Settings",
            tree='[1] NavBar "Settings"\n[2] Cell "General"',
            history=[],
            metadata={"app_name": "Settings"},
        )
        assert "TASK: Open Settings" in msg
        assert "SCREEN (Settings):" in msg
        assert '[1] NavBar "Settings"' in msg

    def test_includes_plan(self):
        msg = build_message(
            task="Compare prices",
            tree="[1] Button",
            history=[],
            metadata={"app_name": "App"},
            plan=["Open Uber", "Check price", "Open Lyft"],
        )
        assert "PLAN:" in msg
        assert "1. Open Uber" in msg
        assert "3. Open Lyft" in msg

    def test_includes_memory(self):
        msg = build_message(
            task="Check",
            tree="[1] Button",
            history=[],
            metadata={"app_name": "App"},
            memory='  uber_price: "$12.50"',
        )
        assert "MEMORY:" in msg
        assert "$12.50" in msg

    def test_alert_warning(self):
        msg = build_message(
            task="Do thing",
            tree="[1] Alert",
            history=[],
            metadata={"app_name": "App", "alert_present": True},
        )
        assert "ALERT" in msg

    def test_keyboard_warning(self):
        msg = build_message(
            task="Type",
            tree="[1] TextField",
            history=[],
            metadata={"app_name": "App", "keyboard_visible": True},
        )
        assert "Keyboard" in msg

    def test_history_last_five(self):
        history = [f"Step {i}: action {i}" for i in range(1, 8)]
        msg = build_message(
            task="Go",
            tree="[1] Button",
            history=history,
            metadata={"app_name": "App"},
        )
        assert "Step 3:" in msg  # 3 through 7 = last 5
        assert "Step 1:" not in msg
        assert "Step 2:" not in msg

    def test_warning_appended(self):
        msg = build_message(
            task="Go",
            tree="[1] Button",
            history=[],
            metadata={"app_name": "App"},
            warning="You seem stuck — try a different approach.",
        )
        assert "WARNING:" in msg
        assert "stuck" in msg


class TestToolDefinitions:

    def test_twelve_tools(self):
        assert len(TOOLS) == 12

    def test_all_have_names(self):
        for tool in TOOLS:
            assert tool.name
            assert tool.name in VALID_TOOL_NAMES


# ---------------------------------------------------------------------------
# Live integration tests (hit Gemini API)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def planner():
    if not os.environ.get("GEMINI_API_KEY"):
        pytest.skip("GEMINI_API_KEY not set")
    return Planner()


class TestNextAction:

    def test_returns_valid_action(self, planner):
        """Given a Settings screen, the planner should return a valid tool call."""
        tree = (
            '[1] NavBar "Settings"\n'
            '[2] Cell "General"\n'
            '[3] Cell "Accessibility"\n'
            '[4] Cell "Camera"\n'
            '[5] SearchField "Search"'
        )
        metadata = {
            "app_name": "Settings",
            "keyboard_visible": False,
            "alert_present": False,
            "perception_mode": "tree",
        }
        result = planner.next_action(
            tree=tree,
            task="Open General settings",
            history=[],
            metadata=metadata,
        )
        print(f"\n=== Planner result ===\n{result}")
        assert "name" in result
        assert "input" in result
        assert result["name"] in VALID_TOOL_NAMES

    def test_tap_action_has_ref(self, planner):
        """For a simple tap task, we expect a tap with a ref number."""
        tree = (
            '[1] NavBar "Settings"\n'
            '[2] Cell "Wi-Fi"\n'
            '[3] Cell "Bluetooth"'
        )
        metadata = {
            "app_name": "Settings",
            "keyboard_visible": False,
            "alert_present": False,
            "perception_mode": "tree",
        }
        result = planner.next_action(
            tree=tree,
            task="Open Wi-Fi settings",
            history=[],
            metadata=metadata,
        )
        print(f"\n=== Tap result ===\n{result}")
        # Should tap ref 2 (Wi-Fi)
        if result["name"] == "tap":
            assert "ref" in result["input"]
            assert isinstance(result["input"]["ref"], (int, float))

    def test_done_on_completed_task(self, planner):
        """If the screen shows the task is done, expect done()."""
        tree = (
            '[1] NavBar "Wi-Fi"\n'
            '[2] Switch "Wi-Fi" \u2192 "1"\n'
            '[3] Cell "MyNetwork" [selected]'
        )
        metadata = {
            "app_name": "Settings",
            "keyboard_visible": False,
            "alert_present": False,
            "perception_mode": "tree",
        }
        result = planner.next_action(
            tree=tree,
            task="Open Wi-Fi settings",
            history=["Step 1: tap [2] \u2192 Tapped Wi-Fi"],
            metadata=metadata,
        )
        print(f"\n=== Done result ===\n{result}")
        assert result["name"] in VALID_TOOL_NAMES


class TestNextActionVision:

    def test_vision_returns_action(self, planner):
        """Screenshot mode should return a valid action (likely tap_xy or plan)."""
        # Tiny 1x1 white PNG for testing — real usage sends a full screenshot
        import struct, zlib
        raw = b"\x00\xff\xff\xff"
        def _png():
            def chunk(ctype, data):
                c = ctype + data
                return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xffffffff)
            return (
                b"\x89PNG\r\n\x1a\n"
                + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw))
                + chunk(b"IEND", b"")
            )
        screenshot_b64 = __import__("base64").b64encode(_png()).decode()

        metadata = {
            "app_name": "Springboard",
            "keyboard_visible": False,
            "alert_present": False,
            "perception_mode": "screenshot",
        }
        result = planner.next_action_vision(
            screenshot_b64=screenshot_b64,
            tree="[screenshot mode - tree unavailable]",
            task="Open the Settings app",
            history=[],
            metadata=metadata,
        )
        print(f"\n=== Vision result ===\n{result}")
        assert "name" in result
        assert result["name"] in VALID_TOOL_NAMES

"""Wrap WDA connection, tree extraction, and screenshot fallback into a single snapshot() call."""
from __future__ import annotations

import base64
import xml.etree.ElementTree as ET

import wda

from core.tree_parser import parse_tree


class TreeReader:
    """Observe the iOS screen via WDA and return a compact tree or screenshot fallback."""

    def __init__(self, wda_url: str = 'http://localhost:8100'):
        self.client = wda.Client(wda_url)

    def snapshot(self) -> tuple[str, dict, dict]:
        """Capture the current screen state.

        Returns:
            compact_tree: Ref-tagged text from parse_tree(), or a fallback message.
            ref_map: Dict mapping ref number -> element info, or empty dict in screenshot mode.
            metadata: Dict with app_name, keyboard_visible, alert_present,
                      perception_mode ('tree' or 'screenshot'), and screenshot_b64.
        """
        try:
            raw = self.client.source()
        except Exception:
            # WDA failure — full screenshot fallback
            screenshot_b64 = self._try_screenshot()
            metadata = {
                'app_name': '',
                'keyboard_visible': False,
                'alert_present': False,
                'perception_mode': 'screenshot',
                'screenshot_b64': screenshot_b64,
            }
            return '[screenshot mode - tree unavailable]', {}, metadata

        # Extract metadata from the raw XML before parsing
        app_name = self._extract_app_name(raw)
        keyboard_visible = 'XCUIElementTypeKeyboard' in raw
        alert_present = 'XCUIElementTypeAlert' in raw

        compact, ref_map = parse_tree(raw)

        # Sparse tree fallback: fewer than 3 interactive elements
        if len(ref_map) < 3:
            screenshot_b64 = self._try_screenshot()
            metadata = {
                'app_name': app_name,
                'keyboard_visible': keyboard_visible,
                'alert_present': alert_present,
                'perception_mode': 'screenshot',
                'screenshot_b64': screenshot_b64,
                'sparse_tree': compact,
            }
            return compact, ref_map, metadata

        metadata = {
            'app_name': app_name,
            'keyboard_visible': keyboard_visible,
            'alert_present': alert_present,
            'perception_mode': 'tree',
            'screenshot_b64': None,
        }
        return compact, ref_map, metadata

    def _try_screenshot(self) -> str | None:
        """Capture a PNG screenshot as base64, or None if WDA is unreachable."""
        try:
            png_data = self.client.screenshot(format='raw')
            return base64.b64encode(png_data).decode('utf-8')
        except Exception:
            return None

    @staticmethod
    def _extract_app_name(xml_string: str) -> str:
        """Pull the app name from the root XCUIElementTypeApplication element."""
        try:
            root = ET.fromstring(xml_string)
            return root.get('name', '') or root.get('label', '') or ''
        except ET.ParseError:
            return ''

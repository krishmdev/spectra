"""Wrap WDA connection, tree extraction, and screenshot fallback into a single snapshot() call."""
from __future__ import annotations

import base64
import wda
import threading
from core.tree_parser import parse_tree

_WDA_SOURCE_TIMEOUT = 2.5

def _source_with_timeout(client, timeout=_WDA_SOURCE_TIMEOUT):
    """Enforce a hard wall-clock timeout on WDA client.source()."""
    result = [None]
    exc = [None]
    def _call():
        try:
            result[0] = client.source()
        except Exception as e:
            exc[0] = e
    t = threading.Thread(target=_call, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f'WDA source() timed out after {timeout}s - WDA may be degraded')
    if exc[0]:
        raise exc[0]
    return result[0]


class TreeReader:
    """Observe the iOS screen via WDA and return a compact tree or screenshot fallback."""

    def __init__(self, wda_url='http://localhost:8100', client=None):
        self.client = client if client is not None else wda.Client(wda_url)
        if client is None:
            try:
                self.client.http.timeout = 5
            except AttributeError:
                pass
        self._degraded_count = 0

    def snapshot(self) -> tuple[str, dict, dict]:
        """Capture the current screen state.

        Returns:
            compact_tree: Ref-tagged text from parse_tree(), or a fallback message.
            ref_map: Dict mapping ref number -> element info, or empty dict in screenshot mode.
            metadata: Dict with app_name, keyboard_visible, alert_present,
                      perception_mode ('tree' or 'screenshot'), and screenshot_b64.
        """
        try:
            raw = _source_with_timeout(self.client)
            self._degraded_count = 0
        except Exception:
            # WDA failure — full screenshot fallback
            self._degraded_count += 1
            if self._degraded_count >= 2:
                print('[WDA] source() timed out repeatedly — consider restarting WDA')
                self._degraded_count = 0
            
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
        keyboard_visible = 'XCUIElementTypeKeyboard' in raw
        alert_present = 'XCUIElementTypeAlert' in raw

        compact, ref_map, app_name = parse_tree(raw)

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

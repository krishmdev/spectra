"""Translate tool calls from the LLM Planner into WDA commands."""

import subprocess
import time

import wda


class Executor:
    """Execute actions on the iOS simulator via WDA."""

    def __init__(self, wda_url='http://localhost:8100', client=None):
        self.client = client if client is not None else wda.Client(wda_url)
        if client is None:
            try:
                self.client.http.timeout = 5
            except AttributeError:
                pass

    def run(self, action: str, params: dict, ref_map: dict) -> str:
        """Dispatch a planner action to the appropriate WDA command.

        Returns a human-readable result string for the action history.
        """
        if action == 'tap':
            return self._tap(params['ref'], ref_map)
        elif action == 'tap_xy':
            return self._tap_xy(params['x'], params['y'])
        elif action == 'type_text':
            return self._type(params['ref'], params['text'], ref_map)
        elif action == 'scroll':
            return self._scroll(params['direction'])
        elif action == 'go_back':
            return self._go_back()
        elif action == 'go_home':
            return self._go_home()
        elif action == 'open_app':
            return self.open_app(params['bundle_id'])
        elif action == 'wait':
            secs = params.get('seconds', 2)
            time.sleep(secs)
            return f'Waited {secs}s'
        elif action == 'done':
            return f"DONE: {params['summary']}"
        elif action == 'stuck':
            return f"STUCK: {params['reason']}"
        elif action == 'remember':
            return 'REMEMBER: handled by agent loop'
        elif action == 'handoff':
            return 'HANDOFF: handled by agent loop'
        elif action == 'plan':
            return 'PLAN: handled by agent loop'
        return f'Unknown action: {action}'

    def _tap(self, ref: int, ref_map: dict) -> str:
        el = ref_map.get(ref)
        if not el:
            return f'Error: ref [{ref}] not found'
        x = el['x'] + el['width'] // 2
        y = el['y'] + el['height'] // 2
        self.client.tap(x, y)
        return f"Tapped [{ref}] '{el.get('label', '')}' at ({x},{y})"

    def _tap_xy(self, x: int, y: int) -> str:
        self.client.tap(x, y)
        return f'Tapped coordinates ({x},{y})'

    def _type(self, ref: int, text: str, ref_map: dict) -> str:
        self._tap(ref, ref_map)
        time.sleep(0.1)
        self.client.send_keys(text)
        return f"Typed '{text}' into [{ref}]"

    def _scroll(self, direction: str) -> str:
        if direction == 'down':
            self.client.swipe_up()   # swipe up = content scrolls down
        else:
            self.client.swipe_down()  # swipe down = content scrolls up
        return f'Scrolled {direction}'

    def _go_back(self) -> str:
        self.client.swipe(0.05, 0.5, 0.8, 0.5, duration=0.3)
        return 'Navigated back'

    def _go_home(self) -> str:
        self.client.home()
        return 'Pressed home'

    def open_app(self, bundle_id: str) -> str:
        """Launch an app by bundle ID via simctl. Skips if already in foreground."""
        try:
            current = self.client.app_current()
            if current.get('bundleId') == bundle_id:
                return f'{bundle_id} already in foreground'
        except Exception:
            pass
        result = subprocess.run(['xcrun', 'simctl', 'launch', 'booted', bundle_id],
                               capture_output=True, text=True)
        if result.returncode != 0:
            return f'Error: {bundle_id} is not installed on this device. Use Safari or another installed app instead.'
        time.sleep(1)
        return f'Opened {bundle_id}'

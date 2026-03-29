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
        elif action == 'navigate':
            return self._navigate(params.get('url', ''))
        elif action == 'dismiss_paywall':
            return self._dismiss_paywall()
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
        # JS-sourced elements: click via JS instead of coordinates
        if 'js_index' in el:
            return self._js_click(el['js_index'], el.get('label', ''))
        x = el['x'] + el['width'] // 2
        y = el['y'] + el['height'] // 2
        self.client.tap(x, y)
        return f"Tapped [{ref}] '{el.get('label', '')}' at ({x},{y})"

    def _js_click(self, js_index: int, label: str = '') -> str:
        """Click a web element by its JS snapshot index — no coordinate math needed."""
        js = (
            "(function(){{"
            "var sel='a[href],button,input:not([type=hidden]),select,textarea,"
            "[role=button],[role=link],[role=menuitem],[role=tab],[role=checkbox],[role=radio]';"
            "var visible=Array.from(document.querySelectorAll(sel)).filter(function(el){{"
            "var r=el.getBoundingClientRect();"
            "if(r.width<5||r.height<5)return false;"
            "var s=window.getComputedStyle(el);"
            "return s.display!=='none'&&s.visibility!=='hidden'&&parseFloat(s.opacity)>=0.1"
            "&&r.bottom>-10&&r.top<window.innerHeight+10;"
            "}});"
            f"var el=visible[{js_index}];"
            "if(!el)return 'not found';"
            "el.click();return 'clicked';"
            "}})();"
        )
        from core.tree_reader import _run_js
        result = _run_js(self.client, js, timeout=4.0)
        if result == 'clicked' or (isinstance(result, str) and 'clicked' in result):
            return f"JS click '{label}'"
        # Fallback: coordinate tap if JS click failed
        return f"JS click failed ({result}) for '{label}'"

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

    def _navigate(self, url: str) -> str:
        """Navigate Safari to a URL using the WebDriver /url endpoint."""
        if not url:
            return 'Error: no URL provided'
        try:
            self.client.open_url(url)
            time.sleep(2.5)  # allow page to load
            return f'Navigated to {url}'
        except Exception as e:
            return f'Navigate error: {e}'

    def _dismiss_paywall(self) -> str:
        """Remove paywall/subscription overlays via JavaScript injection.

        Tries WDA execute_script directly, then falls back to switching
        into the WEBVIEW context if the direct call is rejected.
        """
        js = (
            "(function(){"
            "var n=0;"
            "var sel='[class*=paywall],[id*=paywall],[class*=piano-],[class*=tp-modal],"
            "[class*=Paywall],[class*=SubscribeOverlay],[class*=RegwallModal],"
            "[class*=gate-body],[class*=css-offers],[class*=SignupModal],"
            "[class*=subscription-modal],[class*=meter-modal]';"
            "document.querySelectorAll(sel).forEach(function(e){e.remove();n++;});"
            "document.querySelectorAll('[role=dialog],[role=alertdialog]').forEach(function(e){"
            "var t=e.textContent.toLowerCase();"
            "if(t.indexOf('subscri')>=0||t.indexOf('sign in')>=0||"
            "t.indexOf('register')>=0||t.indexOf('continue reading')>=0){e.remove();n++;}"
            "});"
            "document.querySelectorAll('[class*=backdrop],[class*=Overlay],[class*=overlay]').forEach(function(e){"
            "var s=window.getComputedStyle(e);"
            "if(s.position==='fixed'&&parseFloat(s.zIndex)>100){e.remove();n++;}"
            "});"
            "document.body.style.overflow='';"
            "document.body.style.position='';"
            "document.documentElement.style.overflow='';"
            "document.body.classList.remove('overflow-hidden','noscroll','modal-open');"
            "return n;"
            "})()"
        )
        # Attempt 1: direct execute_script (works if WDA is already in web context)
        try:
            result = self.client.execute_script(js)
            time.sleep(0.5)
            return f'Paywall dismissed ({result} elements removed)'
        except Exception:
            pass

        # Attempt 2: switch to WEBVIEW context, run JS, switch back
        try:
            contexts = self.client.contexts()
            web = [c for c in contexts if 'WEBVIEW' in str(c).upper()]
            if web:
                self.client.set_context(web[0])
                result = self.client.execute_script(js)
                self.client.set_context('NATIVE_APP')
                time.sleep(0.5)
                return f'Paywall dismissed via web ctx ({result} elements removed)'
        except Exception as e:
            pass

        return 'Paywall dismiss attempted (JS execution not available in this context)'

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

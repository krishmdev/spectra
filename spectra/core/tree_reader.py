"""Wrap WDA connection, tree extraction, and screenshot fallback into a single snapshot() call."""
from __future__ import annotations

import base64
import json
import re
import threading
import wda

from core.tree_parser import parse_tree

# Timeout for native apps — 20s from upstream (Safari uses JS path, not this)
_WDA_SOURCE_TIMEOUT = 20.0

# ---------------------------------------------------------------------------
# JS executed inside the Safari web view — returns visible interactive
# elements + page context in one round-trip.
# ---------------------------------------------------------------------------
_SAFARI_PAGE_JS = (
    "(function(){"
    # ---- paywall detection ----
    "var pwSel='[class*=paywall],[id*=paywall],[class*=piano-],[class*=tp-modal],"
    "[class*=Paywall],[class*=SubscribeOverlay],[class*=RegwallModal],"
    "[class*=gate-body],[class*=css-offers],[class*=SignupModal],[class*=meter-modal]';"
    "var pw=document.querySelector(pwSel);"
    "var pwDetected=!!(pw&&window.getComputedStyle(pw).display!='none'&&window.getComputedStyle(pw).visibility!='hidden');"
    # ---- article headlines (context for LLM) ----
    "var seen={};var articles=[];"
    "document.querySelectorAll('article h2,article h3,[class*=headline] a,[data-testid*=headline],h2 a,h3 a').forEach(function(el,i){"
    "if(i<15){var t=el.textContent.trim().slice(0,100);if(t.length>10&&!seen[t]){seen[t]=1;articles.push(t);}}"
    "});"
    # ---- visible interactive elements ----
    "var sel='a[href],button,input:not([type=hidden]),select,textarea,"
    "[role=button],[role=link],[role=menuitem],[role=tab],[role=checkbox],[role=radio]';"
    "var els=[];var n=0;"
    "document.querySelectorAll(sel).forEach(function(el){"
    "if(n>=60)return;"
    "var rect=el.getBoundingClientRect();"
    "if(rect.width<5||rect.height<5)return;"
    "var s=window.getComputedStyle(el);"
    "if(s.display==='none'||s.visibility==='hidden'||parseFloat(s.opacity)<0.1)return;"
    "if(rect.bottom<-10||rect.top>window.innerHeight+10)return;"  # skip off-screen
    "var text=(el.getAttribute('aria-label')||el.textContent||el.value||el.placeholder||'').trim().replace(/\\s+/g,' ').slice(0,80);"
    "var role=el.tagName==='A'?'link':el.tagName==='BUTTON'?'button':"
    "(el.getAttribute('role')||el.tagName.toLowerCase());"
    "var href=el.href||'';"
    "els.push({i:n,role:role,text:text,href:href.slice(0,120),"
    "x:Math.round(rect.left),y:Math.round(rect.top),"
    "w:Math.round(rect.width),h:Math.round(rect.height)});"
    "n++;"
    "});"
    "return JSON.stringify({"
    "url:window.location.href,title:document.title,"
    "paywallDetected:pwDetected,articles:articles,elements:els"
    "});"
    "})()"
)

# JS used to click an element by its index in the same query used at snapshot time
_SAFARI_CLICK_JS_TMPL = (
    "(function(){{"
    "var sel='a[href],button,input:not([type=hidden]),select,textarea,"
    "[role=button],[role=link],[role=menuitem],[role=tab],[role=checkbox],[role=radio]';"
    "var visible=Array.from(document.querySelectorAll(sel)).filter(function(el){{"
    "var rect=el.getBoundingClientRect();"
    "if(rect.width<5||rect.height<5)return false;"
    "var s=window.getComputedStyle(el);"
    "return s.display!=='none'&&s.visibility!=='hidden'&&parseFloat(s.opacity)>=0.1"
    "&&rect.bottom>-10&&rect.top<window.innerHeight+10;"
    "}});"
    "var el=visible[{index}];"
    "if(!el)return 'not found';"
    "el.click();return 'clicked:'+el.textContent.trim().slice(0,40);"
    "}})()"
)


def _run_js(client, js: str, timeout: float = 4.0) -> dict | str | None:
    """Execute JS in the Safari web view via WDA.

    Tries direct execute_script first (works if WDA is already in web context),
    then switches to the WEBVIEW context and retries.
    Returns parsed JSON if the result is a JSON string, raw string otherwise.
    """
    for attempt in range(2):
        try:
            if attempt == 1:
                contexts = client.contexts()
                web = [c for c in contexts if 'WEBVIEW' in str(c).upper()]
                if not web:
                    break
                client.set_context(web[0])

            result = [None]
            exc = [None]
            def _call():
                try:
                    result[0] = client.execute_script(js)
                except Exception as e:
                    exc[0] = e
            t = threading.Thread(target=_call, daemon=True)
            t.start()
            t.join(timeout)

            if attempt == 1:
                try:
                    client.set_context('NATIVE_APP')
                except Exception:
                    pass

            if t.is_alive() or exc[0]:
                continue

            raw = result[0]
            if raw is None:
                continue
            if isinstance(raw, str):
                try:
                    return json.loads(raw)
                except Exception:
                    return raw
            return raw  # already parsed by wda library
        except Exception:
            pass
    return None


def _source_with_timeout(client, timeout: float = _WDA_SOURCE_TIMEOUT) -> str:
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
        raise TimeoutError(f'WDA source() timed out after {timeout}s')
    if exc[0]:
        raise exc[0]
    return result[0]


def _extract_safari_url(xml_raw: str) -> str | None:
    """Pull the current URL from Safari's address bar in the WDA XML."""
    if 'com.apple.mobilesafari' not in xml_raw and 'name="Safari"' not in xml_raw:
        return None
    match = re.search(
        r'XCUIElementTypeTextField[^>]*name="Address"[^>]*value="([^"]+)"',
        xml_raw,
    )
    if match:
        val = match.group(1).strip()
        if val and val != 'Search or enter website name':
            return val if val.startswith('http') else f'https://{val}'
    return None


class TreeReader:
    """Observe the iOS screen via WDA.

    For Safari: uses JS execution — single fast round-trip, no XML serialization.
    For native apps: uses WDA source() XML as before.
    """

    def __init__(self, wda_url: str = 'http://localhost:8100', client=None):
        self.client = client if client is not None else wda.Client(wda_url)
        if client is None:
            try:
                self.client.http.timeout = 12
            except AttributeError:
                pass
        self._in_safari = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def snapshot(self) -> tuple[str, dict, dict]:
        """Capture the current screen state.

        Returns:
            compact_tree: Ref-tagged text.
            ref_map: {ref → element info dict}.
            metadata: {app_name, keyboard_visible, alert_present,
                       perception_mode, current_url, ...}
        """
        # Fast check: which app is in foreground?
        try:
            app_info = self.client.app_current()
            self._in_safari = app_info.get('bundleId', '') == 'com.apple.mobilesafari'
        except Exception:
            pass  # keep cached value

        if self._in_safari:
            return self._safari_js_snapshot()
        return self._native_snapshot()

    # ------------------------------------------------------------------
    # Safari path — JS first, screenshot fallback
    # ------------------------------------------------------------------

    def _safari_js_snapshot(self) -> tuple[str, dict, dict]:
        """Get page state via JS execution — fast, no XML."""
        page = _run_js(self.client, _SAFARI_PAGE_JS, timeout=5.0)

        if page and isinstance(page, dict) and page.get('elements'):
            tree, ref_map = _build_tree_from_js(page)
            metadata = {
                'app_name':         'Safari',
                'keyboard_visible': False,
                'alert_present':    False,
                'perception_mode':  'js_tree',
                'screenshot_b64':   None,
                'current_url':      page.get('url', ''),
                'paywall_detected': page.get('paywallDetected', False),
                'page_articles':    page.get('articles', []),
            }
            return tree, ref_map, metadata

        # JS failed — screenshot fallback
        print('[TreeReader] Safari JS snapshot failed — screenshot fallback')
        screenshot_b64 = self._try_screenshot()
        url = page.get('url', '') if isinstance(page, dict) else ''
        articles = page.get('articles', []) if isinstance(page, dict) else []
        tree_msg = '[screenshot mode — JS unavailable]'
        if articles:
            tree_msg += '\nPAGE_ARTICLES:\n' + '\n'.join(f'  - {a}' for a in articles[:8])
        metadata = {
            'app_name':         'Safari',
            'keyboard_visible': False,
            'alert_present':    False,
            'perception_mode':  'screenshot',
            'screenshot_b64':   screenshot_b64,
            'current_url':      url,
            'paywall_detected': False,
            'page_articles':    articles,
        }
        return tree_msg, {}, metadata

    # ------------------------------------------------------------------
    # Native app path — WDA source() XML
    # ------------------------------------------------------------------

    def _native_snapshot(self) -> tuple[str, dict, dict]:
        try:
            raw = _source_with_timeout(self.client, timeout=_WDA_SOURCE_TIMEOUT)
        except Exception:
            print('[TreeReader] WDA source() timed out')
            screenshot_b64 = self._try_screenshot()
            metadata = {
                'app_name': '', 'keyboard_visible': False, 'alert_present': False,
                'perception_mode': 'screenshot', 'screenshot_b64': screenshot_b64,
            }
            return '[screenshot mode - tree unavailable]', {}, metadata

        keyboard_visible = 'XCUIElementTypeKeyboard' in raw
        alert_present    = 'XCUIElementTypeAlert'    in raw
        app_bundle_id    = self._extract_bundle_id(raw)
        current_url      = _extract_safari_url(raw)

        compact, ref_map, app_name = parse_tree(raw)

        if len(ref_map) < 3:
            screenshot_b64 = self._try_screenshot()
            metadata = {
                'app_name': app_name, 'app_bundle_id': app_bundle_id,
                'keyboard_visible': keyboard_visible, 'alert_present': alert_present,
                'current_url': current_url,
                'perception_mode': 'screenshot', 'screenshot_b64': screenshot_b64,
                'sparse_tree': compact,
            }
            return compact, ref_map, metadata

        metadata = {
            'app_name': app_name, 'app_bundle_id': app_bundle_id,
            'keyboard_visible': keyboard_visible,
            'alert_present': alert_present, 'current_url': current_url,
            'perception_mode': 'tree', 'screenshot_b64': None,
        }
        return compact, ref_map, metadata

    @staticmethod
    def _extract_bundle_id(xml_string: str) -> str:
        """Pull the bundleId from the root XCUIElementTypeApplication element."""
        try:
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml_string)
            return root.get('bundleId', '') or ''
        except Exception:
            return ''

    def _try_screenshot(self) -> str | None:
        try:
            png_data = self.client.screenshot(format='raw')
            return base64.b64encode(png_data).decode('utf-8')
        except Exception:
            return None


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _build_tree_from_js(page: dict) -> tuple[str, dict]:
    """Convert JS page data into a compact tree string + ref_map.

    The ref_map entries have a 'js_index' field so the executor can
    click elements via JS instead of screen coordinates.
    """
    elements = page.get('elements', [])
    lines = []
    ref_map = {}

    for el in elements:
        ref = el['i'] + 1        # 1-based ref matching JS index
        js_idx = el['i']
        role  = el.get('role', 'link')
        text  = el.get('text', '').strip()
        href  = el.get('href', '')

        label = text or href.split('/')[-1] or role
        label = label[:70]

        y = el.get('y', 0)
        # Show a short URL path for links so the LLM can infer content type
        # (e.g. /article/... vs / vs /world — useful for "first article" reasoning)
        path = ''
        if role == 'link' and href:
            try:
                from urllib.parse import urlparse
                p = urlparse(href).path
                if p and p != '/':
                    path = p[:40]
            except Exception:
                pass

        line = f'[{ref}] {role}'
        if label:
            line += f' "{label}"'
        if path:
            line += f' ({path})'
        if y > 0:
            line += f' @y:{y}'
        lines.append(line)

        ref_map[ref] = {
            'type':     role,
            'label':    label,
            'value':    href[:80] if role == 'link' else '',
            'x':        el.get('x', 0),
            'y':        el.get('y', 0),
            'width':    el.get('w', 0),
            'height':   el.get('h', 0),
            'js_index': js_idx,   # used by executor for JS click
        }

    return '\n'.join(lines), ref_map

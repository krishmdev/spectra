"""HTTP front end for the mock device, speaking the subset of the WDA protocol
that facebook-wda (and therefore Spectra's reader/executor) uses.

    python -m sim.server --port 8100 --seed 0

Extra endpoints under /_sim/ are for tests and the eval harness:
    POST /_sim/reset   {"seed": int}      -> fresh device state
    GET  /_sim/state                      -> ground truth (appearance, reminders, messages, ...)
    GET  /_sim/events                     -> every tap/keys/launch the device received
    POST /_sim/launch  {"bundle_id": str} -> what `xcrun simctl launch` does (see sim/bin/xcrun)
    GET  /_sim/canary                     -> egress check run inside this process
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from sim.device import APP_NAMES, Device
from sim.ui import SCREEN_H, SCREEN_W

SESSION_ID = 'SIM-SESSION'
_SESSION_RE = re.compile(r'^/session/[^/]+')
_png_cache: dict[str, str] = {}


def _screenshot_b64(screen: str) -> str:
    """A flat 3x PNG whose colour depends on the screen, so hashes differ per screen."""
    if screen not in _png_cache:
        from PIL import Image
        seed = sum(screen.encode()) % 200
        img = Image.new('RGB', (SCREEN_W * 3, SCREEN_H * 3), (40 + seed // 2, 40 + seed % 90, 60 + seed // 3))
        buf = io.BytesIO()
        img.save(buf, format='PNG', optimize=True)
        _png_cache[screen] = base64.b64encode(buf.getvalue()).decode()
    return _png_cache[screen]


class Handler(BaseHTTPRequestHandler):
    device: Device
    canary: dict | None = None
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):  # quiet by default
        if os.environ.get('SPECTRA_SIM_VERBOSE'):
            sys.stderr.write('[sim] ' + fmt % args + '\n')

    def _body(self) -> dict:
        n = int(self.headers.get('Content-Length') or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n) or b'{}')
        except json.JSONDecodeError:
            return {}

    def _send(self, value=None, status: int = 200, raw: dict | None = None) -> None:
        payload = raw if raw is not None else {'value': value, 'sessionId': SESSION_ID, 'status': 0}
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _error(self, message: str, status: int = 404) -> None:
        self._send({'error': 'unknown command', 'message': message}, status=status)

    def do_GET(self):
        self._route('GET')

    def do_POST(self):
        self._route('POST')

    def do_DELETE(self):
        self._route('DELETE')

    def _route(self, method: str) -> None:
        path = urlparse(self.path).path
        path = _SESSION_RE.sub('', path) or '/'
        path = path.rstrip('/') or '/'
        body = self._body() if method in ('POST', 'DELETE') else {}
        d = self.device

        if path == '/status':
            return self._send(raw={'value': {'ready': True, 'state': 'success', 'message': 'WDA mock ready',
                                             'build': {'productBundleIdentifier': 'spectra.sim'}},
                                   'sessionId': SESSION_ID, 'status': 0})
        if path == '/session' and method == 'POST':
            return self._send({'sessionId': SESSION_ID, 'capabilities': {'device': 'iphone'}})
        if path == '/' and method == 'DELETE':
            return self._send(None)
        if path == '/source':
            return self._send(d.source())
        if path == '/wda/activeAppInfo':
            return self._send(d.active_app())
        if path == '/screenshot':
            return self._send(_screenshot_b64(d.screen_id()))
        if path == '/window/size':
            return self._send({'width': SCREEN_W, 'height': SCREEN_H})
        if path == '/wda/screen':
            return self._send({'scale': 3, 'statusBarSize': {'width': SCREEN_W, 'height': 54}})
        if path == '/orientation':
            return self._send('PORTRAIT')
        if path in ('/wda/tap', '/wda/tap/0') and method == 'POST':
            d.tap(float(body.get('x', 0)), float(body.get('y', 0)))
            return self._send(None)
        if path == '/wda/keys' and method == 'POST':
            value = body.get('value', '')
            text = ''.join(value) if isinstance(value, list) else str(value)
            if not d.keys(text):
                return self._send({'error': 'invalid element state',
                                   'message': 'Keyboard is not present'}, status=400)
            return self._send(None)
        if path == '/wda/dragfromtoforduration' and method == 'POST':
            d.drag(float(body.get('fromX', 0)), float(body.get('fromY', 0)),
                   float(body.get('toX', 0)), float(body.get('toY', 0)))
            return self._send(None)
        if path == '/wda/homescreen' and method == 'POST':
            d.home()
            return self._send(None)
        if path == '/wda/apps/launch' and method == 'POST':
            if not d.launch(body.get('bundleId', '')):
                return self._error(f"app {body.get('bundleId')} is not installed", status=500)
            return self._send(None)
        if path == '/url' and method == 'POST':
            d.open_url(body.get('url', ''))
            return self._error('Safari is not part of the mock device', status=500)
        if path == '/wda/apps/list':
            return self._send([{'bundleId': b, 'name': n} for b, n in APP_NAMES.items()])

        if path == '/_sim/reset' and method == 'POST':
            d.reset(int(body.get('seed', 0)))
            return self._send(raw=d.state())
        if path == '/_sim/state':
            return self._send(raw=d.state())
        if path == '/_sim/events':
            with d.lock:
                return self._send(raw={'events': list(d.events)})
        if path == '/_sim/launch' and method == 'POST':
            ok = d.launch(body.get('bundle_id', ''))
            return self._send(raw={'ok': ok}, status=200 if ok else 404)
        if path == '/_sim/canary':
            return self._send(raw=self.canary or {'ran': False})

        return self._error(f'{method} {path} is not implemented by the mock device')


def make_server(port: int = 8100, seed: int = 0, host: str = '127.0.0.1') -> ThreadingHTTPServer:
    device = Device()
    device.reset(seed)
    handler = type('BoundHandler', (Handler,), {'device': device})
    server = ThreadingHTTPServer((host, port), handler)
    server.daemon_threads = True
    server.device = device
    return server


def serve_in_thread(port: int = 0, seed: int = 0) -> tuple[ThreadingHTTPServer, str]:
    """Start a server on a background thread; returns (server, base_url). Port 0 picks a free one."""
    server = make_server(port, seed)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server, f'http://127.0.0.1:{server.server_address[1]}'


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description='Mock WebDriverAgent device')
    ap.add_argument('--port', type=int, default=8100)
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--canary', action='store_true',
                    help='run the egress canary at startup and refuse to serve if egress is open')
    args = ap.parse_args(argv)
    server = make_server(args.port, args.seed)
    if args.canary or os.environ.get('SPECTRA_EGRESS_CANARY') == '1':
        from sim.egress import check_egress
        result = check_egress()
        server.RequestHandlerClass.canary = result
        print(f"[sim] egress canary: {'blocked' if result['blocked'] else 'OPEN ' + ', '.join(result['open'])}",
              flush=True)
        if not result['blocked']:
            return 3
    print(f'[sim] mock WDA listening on http://127.0.0.1:{args.port} (seed {args.seed})', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())

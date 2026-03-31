"""A local stand-in for the Gemini REST API, answering from the scenario scripts.

Point any google-genai client at it with GOOGLE_GEMINI_BASE_URL=http://127.0.0.1:PORT
(and any non-empty GEMINI_API_KEY). That lets the eval harness run code that
constructs a real genai.Client, including the untouched v0.1 tree, with no key
and no network. It is a harness check, not a model: results produced against
it say nothing about planning quality.

    python -m sim.fake_gemini --port 8787
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sim.script_engine import ScriptEngine


def _text_of(req: dict) -> str:
    chunks = []
    for content in req.get('contents', []):
        for part in content.get('parts', []):
            if 'text' in part:
                chunks.append(part['text'])
    return '\n'.join(chunks)


class Handler(BaseHTTPRequestHandler):
    engine: ScriptEngine
    stats: dict
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        pass

    def _reply(self, payload: dict, status: int = 200) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        n = int(self.headers.get('Content-Length') or 0)
        req = json.loads(self.rfile.read(n) or b'{}')
        path = self.path.split('?')[0]
        if path.endswith('/cachedContents'):
            # Behave like a model/tier without context caching; callers fall back to inline config.
            return self._reply({'error': {'code': 400, 'status': 'INVALID_ARGUMENT',
                                          'message': 'caching is not supported by the fake endpoint'}}, 400)
        m = re.search(r'/models/([^/:]+):(generateContent|countTokens)$', path)
        if not m:
            return self._reply({'error': {'code': 404, 'status': 'NOT_FOUND', 'message': path}}, 404)
        text = _text_of(req)
        prompt_tokens = max(1, len(text) // 4)
        if m.group(2) == 'countTokens':
            return self._reply({'totalTokens': prompt_tokens})
        wants_tool = bool(req.get('tools') or req.get('cachedContent')) or text.startswith('TASK: ')
        with self.stats['lock']:
            self.stats['calls'] += 1
        if wants_tool:
            action = self.engine.decide(text)
            part = {'functionCall': {'name': action['name'], 'args': action['input']}}
            out_tokens = 20
        else:
            answer = self.engine.complete(text)
            part = {'text': answer}
            out_tokens = max(1, len(answer) // 4)
        return self._reply({
            'candidates': [{'content': {'role': 'model', 'parts': [part]}, 'finishReason': 'STOP', 'index': 0}],
            'usageMetadata': {'promptTokenCount': prompt_tokens, 'candidatesTokenCount': out_tokens,
                              'totalTokenCount': prompt_tokens + out_tokens},
            'modelVersion': 'fake-gemini-scripted',
        })


def serve_in_thread(port: int = 0, engine: ScriptEngine | None = None):
    handler = type('BoundFakeGemini', (Handler,), {
        'engine': engine or ScriptEngine(),
        'stats': {'calls': 0, 'lock': threading.Lock()},
    })
    server = ThreadingHTTPServer(('127.0.0.1', port), handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    server.stats = handler.stats
    return server, f'http://127.0.0.1:{server.server_address[1]}'


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--port', type=int, default=8787)
    args = ap.parse_args(argv)
    handler = type('BoundFakeGemini', (Handler,), {
        'engine': ScriptEngine(), 'stats': {'calls': 0, 'lock': threading.Lock()}})
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler)
    print(f'[fake-gemini] listening on http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())

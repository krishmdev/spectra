"""The egress canary must fail closed under the sandbox and connect without it.

Under scripts/offline-run (SPECTRA_OFFLINE=1) the first two tests check the
test process and a separately spawned mock-device process. The companion
test only runs when SPECTRA_NETWORK_TESTS=1 (make canary-check), so a
canary that can never connect doesn't pass as 'blocked'.
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request

import pytest

from sim.egress import check_egress

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
offline = pytest.mark.skipif(os.environ.get('SPECTRA_OFFLINE') != '1', reason='only meaningful under offline-run')


@offline
def test_canary_blocked_in_test_process():
    result = check_egress(timeout=2)
    assert result['blocked'], result


@offline
def test_canary_blocked_in_mock_device_process():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen([sys.executable, '-m', 'sim.server', '--port', str(port), '--canary'], cwd=REPO)
    try:
        for _ in range(200):
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/_sim/canary', timeout=2) as r:
                    data = json.loads(r.read())
                break
            except OSError:
                assert proc.poll() is None, 'mock device exited: egress canary saw an open connection'
                time.sleep(0.1)
        assert data['ran'] and data['blocked'] and data['pid'] != os.getpid(), data
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.mark.skipif(os.environ.get('SPECTRA_NETWORK_TESTS') != '1', reason='set SPECTRA_NETWORK_TESTS=1')
def test_canary_connects_when_not_sandboxed():
    result = check_egress(timeout=5)
    assert not result['blocked'], result

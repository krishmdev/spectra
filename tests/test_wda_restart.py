import server.ws_server as ws


class _FakeResp:
    def read(self):
        return b'<xml/>'


def _slow_then_ready(monkeypatch):
    calls = {'n': 0}

    def urlopen(url, timeout=None):
        calls['n'] += 1
        if url.endswith('/source'):
            raise TimeoutError('slow')
        return _FakeResp()

    monkeypatch.setattr('urllib.request.urlopen', urlopen)
    monkeypatch.setattr(ws.time, 'sleep', lambda s: None)
    return calls


def test_healthy_wda_is_left_alone(monkeypatch):
    monkeypatch.setattr('urllib.request.urlopen', lambda url, timeout=None: _FakeResp())
    spawned = []
    monkeypatch.setattr('subprocess.Popen', lambda *a, **k: spawned.append(a))
    assert ws._check_and_restart_wda('http://127.0.0.1:1') is False
    assert spawned == []


def test_missing_wda_project_skips_restart(monkeypatch, tmp_path):
    _slow_then_ready(monkeypatch)
    monkeypatch.setenv('WDA_PROJ', str(tmp_path / 'nope.xcodeproj'))
    spawned = []
    monkeypatch.setattr('subprocess.Popen', lambda *a, **k: spawned.append(a))
    monkeypatch.setattr('subprocess.run', lambda *a, **k: None)
    assert ws._check_and_restart_wda('http://127.0.0.1:1') is False
    assert spawned == []


def test_restart_uses_configured_project_and_device(monkeypatch, tmp_path):
    _slow_then_ready(monkeypatch)
    proj = tmp_path / 'WebDriverAgent.xcodeproj'
    proj.mkdir()
    monkeypatch.setenv('WDA_PROJ', str(proj))
    monkeypatch.delenv('SIM_UDID', raising=False)
    monkeypatch.setenv('SIM_DEVICE', 'iPhone 16')
    spawned, killed = [], []
    monkeypatch.setattr('subprocess.Popen', lambda cmd, **k: spawned.append(cmd))
    monkeypatch.setattr('subprocess.run', lambda cmd, **k: killed.append(cmd))
    assert ws._check_and_restart_wda('http://127.0.0.1:1') is True
    cmd = spawned[0]
    assert cmd[cmd.index('-project') + 1] == str(proj)
    assert cmd[cmd.index('-destination') + 1] == 'platform=iOS Simulator,name=iPhone 16'
    assert killed[0] == ['pkill', '-f', 'xcodebuild.*WebDriverAgentRunner']


def test_sim_udid_wins_over_device_name(monkeypatch):
    monkeypatch.setenv('SIM_UDID', 'ABC-123')
    monkeypatch.setenv('SIM_DEVICE', 'iPhone 16')
    assert ws._wda_destination() == 'id=ABC-123'

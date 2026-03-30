import os

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def mock_device(tmp_path, monkeypatch):
    """A mock WDA device on a free localhost port, with isolated runtime state.

    HOME, SPECTRA_DATA_DIR and the working directory point into tmp_path so
    lessons, flows, episodes and hooks never touch the checkout or ~/.spectra.
    sim/bin goes first on PATH so `xcrun simctl launch` reaches the mock.
    """
    from sim.server import serve_in_thread
    server, url = serve_in_thread(0, seed=0)
    (tmp_path / 'home').mkdir()
    (tmp_path / 'flows').mkdir()
    monkeypatch.setenv('HOME', str(tmp_path / 'home'))
    monkeypatch.setenv('SPECTRA_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('SPECTRA_SIM_URL', url)
    monkeypatch.setenv('PATH', os.path.join(REPO, 'sim', 'bin') + os.pathsep + os.environ['PATH'])
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.chdir(tmp_path)
    server.url = url
    yield server
    server.shutdown()
    server.server_close()

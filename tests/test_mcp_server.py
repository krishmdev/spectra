"""MCP tools against the mock device, with an in-memory MCP client."""
import anyio
import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import ElicitResult

from core.scripted_planner import ScriptedPlanner
from server.mcp_server import build_server


def _text(result):
    return result.content[0].text


def _run(mock_device, body, approve=True):
    asked = []

    async def elicit(context, params):
        asked.append(params.message)
        return ElicitResult(action='accept', content={'approve': approve})

    async def go():
        server = build_server(mock_device.url, planner_factory=ScriptedPlanner)
        async with create_connected_server_and_client_session(server, elicitation_callback=elicit) as client:
            return await body(client)

    return anyio.run(go), asked


def test_tools_are_listed(mock_device):
    async def body(client):
        return sorted(t.name for t in (await client.list_tools()).tools)
    names, _ = _run(mock_device, body)
    assert names == ['read_screen', 'replay_flow', 'run_task', 'tap', 'type_text']


def test_read_then_tap(mock_device):
    async def body(client):
        screen = _text(await client.call_tool('read_screen', {}))
        ref = next(line.split(']')[0].strip('[ ') for line in screen.splitlines() if '"Settings"' in line)
        tapped = _text(await client.call_tool('tap', {'ref': int(ref)}))
        return screen, tapped
    (screen, tapped), asked = _run(mock_device, body)
    assert 'SpringBoard' in screen and 'Tapped' in tapped and asked == []
    assert mock_device.device.foreground == 'com.apple.Preferences'


def test_tap_without_a_read_is_refused(mock_device):
    async def body(client):
        return _text(await client.call_tool('tap', {'ref': 1}))
    out, _ = _run(mock_device, body)
    assert 'read_screen first' in out


@pytest.mark.parametrize('approve', [True, False])
def test_run_task_confirms_the_send_through_elicitation(mock_device, approve):
    async def body(client):
        return _text(await client.call_tool('run_task', {'task': "Text Mom that I'm running about 10 minutes late"}))
    out, asked = _run(mock_device, body, approve=approve)
    sent = [m for m in mock_device.device.state()['threads']['Mom'] if m['from'] == 'me']
    assert any('Send' in q for q in asked)
    if approve:
        assert out.startswith('done') and len(sent) == 1
    else:
        assert sent == []


def test_stdio_transport_survives_agent_prints(mock_device):
    import os
    import sys

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    params = StdioServerParameters(command=sys.executable, args=['-m', 'server.mcp_server', '--transport', 'stdio'],
                                   cwd=repo, env={**os.environ, 'SPECTRA_WDA_URL': mock_device.url,
                                                  'PYTHONPATH': repo})

    async def go():
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                # the tree reader prints on some paths; the session must still parse replies
                screen = await s.call_tool('read_screen', {})
                return screen.content[0].text

    assert 'SpringBoard' in anyio.run(go)

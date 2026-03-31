"""MCP server: drive the phone (or the mock device) from an MCP client.

    python -m server.mcp_server                      # streamable HTTP on 127.0.0.1:8766/mcp
    python -m server.mcp_server --transport stdio    # for clients that spawn the server

Tools: read_screen, tap, type_text, run_task, replay_flow. Taps and typing go
through the same ConfirmationGate as the agent; when it trips, the server asks
the client to confirm with MCP elicitation, and treats "no answer" as no.

Configuration comes from the environment: SPECTRA_WDA_URL (default
http://localhost:8100) and SPECTRA_PLANNER for run_task (gemini or scripted).
The agent prints progress to stdout, which would corrupt a stdio transport,
so in stdio mode print output is sent to stderr.
"""
from __future__ import annotations

import argparse
import io
import os
import sys

import anyio
from mcp.server.fastmcp import Context, FastMCP
from pydantic import BaseModel

from core.executor import Executor
from core.gates import ConfirmationGate
from core.tree_reader import TreeReader


class Approval(BaseModel):
    approve: bool


class _Device:
    """The last snapshot, so tap/type_text can resolve refs the client saw."""

    def __init__(self, wda_url: str):
        self.wda_url = wda_url
        self.reader = TreeReader(wda_url)
        self.executor = Executor(wda_url)
        self.gate = ConfirmationGate()
        self.ref_map: dict = {}

    def snapshot(self) -> tuple[str, dict]:
        tree, ref_map, meta = self.reader.snapshot()
        self.ref_map = ref_map
        return tree, meta


async def _confirm(ctx: Context, action: str, label: str, detail: str = '') -> bool:
    message = f'Spectra wants to {action.replace("_", " ")} "{label}".'
    if detail:
        message += f' {detail}'
    try:
        result = await ctx.elicit(message=message + ' Allow it?', schema=Approval)
    except Exception:
        return False  # client can't elicit: fail closed
    return result.action == 'accept' and bool(result.data and result.data.approve)


class _ElicitCallbacks:
    """SessionCallbacks for run_task, bridging the worker thread back to the MCP session."""

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.events: list[dict] = []

    def event(self, msg: dict) -> None:
        self.events.append(msg)

    def confirm(self, action: str, label: str, detail: str) -> bool:
        return anyio.from_thread.run(_confirm, self.ctx, action, label, detail)

    def approve_plan(self, task: str, steps: list[str]):
        plan = '; '.join(f'{i}. {s}' for i, s in enumerate(steps, 1))
        ok = anyio.from_thread.run(_confirm, self.ctx, 'run this plan for', task, plan)
        return ok, None

    def ask(self, question: str, options: list[str]) -> str:
        return ''

    def handoff(self, reason: str) -> None:
        anyio.from_thread.run(_confirm, self.ctx, 'hand over to you:', reason,
                              'Accept when you have finished on the device.')


def build_server(wda_url: str | None = None, planner_factory=None, flows_dir: str = 'flows') -> FastMCP:
    wda_url = wda_url or os.environ.get('SPECTRA_WDA_URL', 'http://localhost:8100')
    device = _Device(wda_url)
    mcp = FastMCP('spectra', host='127.0.0.1', port=int(os.environ.get('SPECTRA_MCP_PORT', '8766')))

    @mcp.tool()
    def read_screen() -> str:
        """Current screen as Spectra's compact accessibility tree. Refs are valid until the next read."""
        tree, meta = device.snapshot()
        return f"app: {meta.get('app_name', '?')} ({meta.get('perception_mode')})\n{tree}"

    async def _act(ctx: Context, name: str, params: dict) -> str:
        if not device.ref_map:
            return 'Error: call read_screen first; refs come from the last snapshot'
        action = {'name': name, 'input': params}
        if device.gate.check(action, device.ref_map):
            label = device.ref_map.get(params['ref'], {}).get('label', '')
            if not await _confirm(ctx, name, label):
                return f'Not done: the user did not confirm {name} on "{label}"'
        result = await anyio.to_thread.run_sync(device.executor.run, name, params, device.ref_map)
        device.ref_map = {}  # the screen changed; force a fresh read
        return result

    @mcp.tool()
    async def tap(ref: int, ctx: Context) -> str:
        """Tap the element with this ref from the last read_screen."""
        return await _act(ctx, 'tap', {'ref': ref})

    @mcp.tool()
    async def type_text(ref: int, text: str, ctx: Context) -> str:
        """Focus the text field with this ref and type text into it."""
        return await _act(ctx, 'type_text', {'ref': ref, 'text': text})

    @mcp.tool()
    async def run_task(task: str, ctx: Context) -> str:
        """Hand a natural-language task to the Spectra agent and wait for it to finish."""
        from core.planner import make_planner
        from core.session import run_session
        callbacks = _ElicitCallbacks(ctx)
        planner = (planner_factory or make_planner)()
        result = await anyio.to_thread.run_sync(
            lambda: run_session(task, callbacks, wda_url=wda_url, planner=planner, flows_dir=flows_dir,
                                verbose=False))
        device.ref_map = {}
        how = 'replayed a saved flow' if result.replayed else f'{result.steps} steps'
        return f"{'done' if result.success else 'failed'}: {result.summary} ({how}, {result.duration}s)"

    @mcp.tool()
    async def replay_flow(path: str, ctx: Context) -> str:
        """Replay a recorded .spectra flow without the model (sensitive steps still ask)."""
        from recorder.replayer import Replayer

        class _Gate(ConfirmationGate):
            def request_confirmation(self, action, ref_map):
                label = ref_map.get(action['input'].get('ref'), {}).get('label', '')
                return anyio.from_thread.run(_confirm, ctx, action['name'], label, '')

        report = await anyio.to_thread.run_sync(
            lambda: Replayer(path, wda_url=wda_url, step_delay=0.3, verbose=False, gate=_Gate()).run())
        device.ref_map = {}
        return (f'{report.passed} passed, {report.fuzzy} fuzzy, {report.healed} healed, '
                f'{report.failed} failed of {report.total}')

    return mcp


def _run_stdio(mcp: FastMCP) -> None:
    from mcp.server.stdio import stdio_server
    real_stdout = io.TextIOWrapper(os.fdopen(os.dup(1), 'wb'), encoding='utf-8')
    sys.stdout = sys.stderr  # print() from the agent must not land on the protocol stream

    async def main():
        async with stdio_server(stdout=anyio.wrap_file(real_stdout)) as (read, write):
            await mcp._mcp_server.run(read, write, mcp._mcp_server.create_initialization_options())

    anyio.run(main)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description='Spectra MCP server')
    ap.add_argument('--transport', choices=['streamable-http', 'stdio'], default='streamable-http')
    args = ap.parse_args(argv)
    mcp = build_server()
    if args.transport == 'stdio':
        _run_stdio(mcp)
    else:
        mcp.run('streamable-http')
    return 0


if __name__ == '__main__':
    sys.exit(main())

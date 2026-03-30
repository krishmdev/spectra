"""Keyless planner that replays scenario fixtures (sim/scenarios/*.json).

It gets exactly the per-turn message Gemini would get (build_message) and picks
the first matching rule for the current screen, so the real agent loop, tree
parser, gates, memory and stuck detector all run. Used by `make demo`, the
integration tests, and the MCP server when SPECTRA_PLANNER=scripted.
"""
from __future__ import annotations

from core.planner import build_message
from sim.script_engine import ScriptEngine


class ScriptedPlanner:
    model = 'scripted'
    client = None

    def __init__(self, engine: ScriptEngine | None = None, scenarios_dir: str | None = None):
        if engine is None:
            from sim.script_engine import load_scenarios
            engine = ScriptEngine(load_scenarios(scenarios_dir))
        self.engine = engine
        self.calls: list[dict] = []

    def _record(self, kind: str, **info) -> None:
        self.calls.append({'kind': kind, **info})

    def next_action(self, tree, task, history, metadata, warning=None, memory=None, plan=None,
                    prev_trees=None) -> dict:
        message = build_message(task, tree, history, metadata, warning, memory, plan, prev_trees=prev_trees)
        action = self.engine.decide(message)
        self._record('action', step=len(history) + 1, action=action['name'])
        return action

    def next_action_vision(self, screenshot_b64, tree, task, history, metadata, warning=None, memory=None,
                           plan=None, prev_trees=None) -> dict:
        # Screenshots carry no information for a script; decide from the sparse tree.
        return self.next_action(tree, task, history, metadata, warning, memory, plan, prev_trees)

    def reflect(self, task, history, failure_type) -> str:
        self._record('reflect')
        return self.engine.reflect(task, failure_type)

    def complete(self, prompt: str, max_output_tokens: int = 200, purpose: str = '') -> str:
        self._record('complete', purpose=purpose)
        return self.engine.complete(prompt)

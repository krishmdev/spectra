"""Deterministic stand-in for the LLM, driven by the scenario files in sim/scenarios/.

A scenario's policy is an ordered list of rules keyed by screen signature
("App/NavBar title", "SpringBoard/", or "alert"), with optional conditions on
the current tree and on session memory. The engine only looks at what a real
model would see: the per-turn message built by core.planner.build_message.
That keeps ScriptedPlanner (in-process) and sim/fake_gemini.py (over HTTP)
answering identically.
"""
from __future__ import annotations

import glob
import json
import os
import re

SCENARIO_DIR = os.path.join(os.path.dirname(__file__), 'scenarios')

_REF_LINE = re.compile(r'^\s*\[(\d+)\] (\w+)(?: "((?:[^"\\]|\\.)*)")?')
_MEM_LINE = re.compile(r'^\s+([A-Za-z0-9_]+): "(.*)"$', re.M)


def load_scenarios(directory: str | None = None) -> dict[str, dict]:
    directory = directory or os.environ.get('SPECTRA_SCENARIOS') or SCENARIO_DIR
    out = {}
    for path in sorted(glob.glob(os.path.join(directory, '*.json'))):
        with open(path) as f:
            sc = json.load(f)
        out[sc['id']] = sc
    return out


def normalize(task: str) -> str:
    return re.sub(r'[^a-z0-9 ]', '', task.lower()).strip()


def parse_message(message: str) -> dict:
    """Split a build_message() string back into its parts."""
    task = ''
    m = re.match(r'TASK: (.*)', message)
    if m:
        task = m.group(1).strip()
    app, tree = '', ''
    m = re.search(r'CURRENT SCREEN \((.*?)\):\n\n(.*?)(?:\n\nRECENT ACTIONS:|\n\nWARNING:|\Z)', message, re.S)
    if m:
        app, tree = m.group(1), m.group(2)
    memory = {}
    if 'AGENT MEMORY:' in message:
        block = message.split('AGENT MEMORY:', 1)[1].split('\n\n', 1)[0]
        memory = dict(_MEM_LINE.findall(block))
    warning = None
    m = re.search(r'\n\nWARNING: (.*)\Z', message, re.S)
    if m:
        warning = m.group(1)
    return {'task': task, 'app': app, 'tree': tree, 'memory': memory, 'warning': warning}


def screen_signature(app: str, tree: str) -> str:
    if re.search(r'^\s*\[\d+\] Alert\b', tree, re.M):
        return 'alert'
    m = re.search(r'^\s*\[\d+\] NavBar "([^"]*)"', tree, re.M)
    return f'{app}/{m.group(1) if m else ""}'


def find_ref(tree: str, label: str | None = None, prefix: str | None = None) -> int | None:
    for line in tree.splitlines():
        m = _REF_LINE.match(line)
        if not m:
            continue
        el_label = (m.group(3) or '').replace('\\"', '"')
        if (label is not None and el_label == label) or (prefix is not None and el_label.startswith(prefix)):
            return int(m.group(1))
    return None


class ScriptEngine:
    def __init__(self, scenarios: dict[str, dict] | None = None):
        self.scenarios = scenarios if scenarios is not None else load_scenarios()
        self._by_task = {}
        for sc in self.scenarios.values():
            for t in [sc['task'], sc.get('route', {}).get('refined_task', ''), *sc.get('aliases', [])]:
                if t:
                    self._by_task[normalize(t)] = sc

    def scenario_for(self, task: str) -> dict | None:
        return self._by_task.get(normalize(task))

    # --- the per-step decision -------------------------------------------------

    def decide(self, message: str) -> dict:
        parts = parse_message(message)
        sc = self.scenario_for(parts['task'])
        if sc is None:
            return {'name': 'stuck', 'input': {'reason': f'no script for task {parts["task"]!r}'}}
        sig = screen_signature(parts['app'], parts['tree'])
        memory = parts['memory']
        for rule in sc['policy']:
            if not _screen_matches(rule['screen'], sig):
                continue
            if 'if_memory' in rule and rule['if_memory'] not in memory:
                continue
            if 'unless_memory' in rule and rule['unless_memory'] in memory:
                continue
            if 'if_tree' in rule and not re.search(_fill(rule['if_tree'], memory, regex=True), parts['tree']):
                continue
            if 'unless_tree' in rule and re.search(_fill(rule['unless_tree'], memory, regex=True), parts['tree']):
                continue
            action = self._materialize(rule['do'], parts['tree'], memory)
            if action is not None:
                action['input'].setdefault('reasoning', f'scripted: {sc["id"]} on {sig}')
                return action
        return {'name': 'stuck', 'input': {'reason': f'scripted planner has no rule for screen {sig!r}'}}

    def _materialize(self, do: dict, tree: str, memory: dict) -> dict | None:
        name = do['name']
        inp = {k: _fill(v, memory) if isinstance(v, str) else v for k, v in do.get('input', {}).items()}
        if 'target' in do or 'target_prefix' in do:
            ref = find_ref(tree, label=do.get('target'), prefix=do.get('target_prefix'))
            if ref is None:
                return None
            inp['ref'] = ref
        if 'value_from' in do:
            m = re.search(do['value_from'], tree)
            if not m:
                return None
            inp['value'] = m.group(1)
        return {'name': name, 'input': inp}

    # --- the auxiliary text calls (router, plan preview, workflow cache, ...) ---

    def route(self, task: str) -> str:
        sc = self.scenario_for(task)
        route = sc['route'] if sc else {'category': 'general', 'apps': [], 'multi_app': False,
                                        'comparison': False, 'refined_task': task}
        return json.dumps(route)

    def plan(self, task: str) -> str:
        sc = self.scenario_for(task)
        steps = (sc or {}).get('plan') or ['Open the target app', 'Complete the task', 'Confirm the result']
        return '\n'.join(f'{i}. {s}' for i, s in enumerate(steps, 1))

    def match_workflow(self, prompt: str) -> str:
        m = re.search(r'New Task: "(.*?)"\n', prompt)
        new = self.scenario_for(m.group(1)) if m else None
        if new is not None:
            for path, saved in re.findall(r'- ID: "(.*?)" \| Task: "(.*?)"', prompt):
                if self.scenario_for(saved) is new:
                    return json.dumps({'match': path})
        return json.dumps({'match': None})

    def summarize(self, task: str) -> str:
        sc = self.scenario_for(task)
        return (sc or {}).get('summary') or task[:50]

    def reflect(self, task: str, failure_type: str) -> str:
        sc = self.scenario_for(task)
        name = sc['id'] if sc else 'this task'
        return (f'For {name}, the run ended with {failure_type}; check the current screen title '
                f'before repeating the previous action.')

    def complete(self, prompt: str) -> str:
        """Answer one of the free-text prompts the runtime sends, by recognising which one it is."""
        if 'Classify this mobile task' in prompt:
            m = re.search(r'Task: "(.*?)"\n', prompt)
            return self.route(m.group(1) if m else '')
        if 'You are planning steps for a mobile agent' in prompt:
            m = re.search(r'Task: (.*)\n', prompt)
            return self.plan(m.group(1) if m else '')
        if 'is EXACTLY the same as a previously completed task' in prompt:
            return self.match_workflow(prompt)
        if 'Summarize this completed task' in prompt:
            m = re.search(r'Task: (.*)\nHistory:', prompt)
            return self.summarize(m.group(1) if m else '')
        if 'You are analyzing a failed mobile agent run' in prompt:
            task = re.search(r'Task: (.*)\n', prompt)
            failure = re.search(r'Failure: (.*)\n', prompt)
            return self.reflect(task.group(1) if task else '', failure.group(1) if failure else 'failure')
        return ''


def _screen_matches(pattern: str, sig: str) -> bool:
    if pattern == '*':
        return sig != 'alert'
    if pattern.endswith('/*'):
        return sig.startswith(pattern[:-1])
    return pattern == sig


def _fill(text: str, memory: dict, regex: bool = False) -> str:
    def sub(m):
        v = memory.get(m.group(1), m.group(0))
        return re.escape(v) if regex else v
    return re.sub(r'\{([a-z0-9_]+)\}', sub, text)

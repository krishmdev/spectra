"""Replay a .spectra JSONL recording deterministically — zero LLM calls.

Loads a recorded flow, snapshots the live screen for each step, uses the
Matcher to re-identify the target element, and executes through the Executor.

Usage::

    from recorder.replayer import Replayer

    replayer = Replayer('flows/dark_mode.spectra')
    report = replayer.run()          # returns ReplayReport
    report.print_summary()
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

from core.executor import Executor
from core.tree_reader import TreeReader
from recorder.matcher import Confidence, match


@dataclass
class StepResult:
    """Outcome of replaying a single step."""
    step: int
    action: str
    match_type: str       # 'exact', 'fuzzy', 'position', 'none', 'n/a'
    confidence: str       # Confidence enum value
    success: bool
    detail: str


@dataclass
class ReplayReport:
    """Summary of a full replay run."""
    flow_file: str
    task: str = ''
    total: int = 0
    passed: int = 0
    fuzzy: int = 0
    failed: int = 0
    skipped: int = 0
    steps: list[StepResult] = field(default_factory=list)
    duration: float = 0.0

    def print_summary(self) -> None:
        """Print a human-readable summary to stdout."""
        print(f'\n{"=" * 50}')
        print(f'  Replay: {self.flow_file}')
        if self.task:
            print(f'  Task:   {self.task}')
        print(f'{"=" * 50}')
        for s in self.steps:
            icon = '✅' if s.success else '❌'
            conf = f' [{s.match_type}]' if s.match_type not in ('n/a', 'none') else ''
            print(f'  {icon} Step {s.step}: {s.action}{conf} — {s.detail}')
        print(f'{"─" * 50}')
        print(f'  Total: {self.total} | Passed: {self.passed} | Fuzzy: {self.fuzzy} | Failed: {self.failed} | Skipped: {self.skipped}')
        print(f'  Duration: {self.duration:.1f}s')
        status = '🎉 ALL PASSED' if self.failed == 0 else f'⚠️  {self.failed} FAILED'
        print(f'  {status}')
        print(f'{"=" * 50}\n')


# Actions that don't interact with the screen — skip matching
_NO_MATCH_ACTIONS = {'scroll', 'go_back', 'go_home', 'wait', 'done', 'stuck',
                     'remember', 'handoff', 'plan', 'open_app'}

# Actions that should not be replayed (meta-only)
_SKIP_ACTIONS = {'done', 'stuck', 'remember', 'handoff', 'plan'}


class Replayer:
    """Load and replay a .spectra recording file."""

    def __init__(
        self,
        filepath: str,
        wda_url: str = 'http://localhost:8100',
        step_delay: float = 0.5,
        verbose: bool = True,
    ):
        self._filepath = filepath
        self._wda_url = wda_url
        self._step_delay = step_delay
        self._verbose = verbose

        # Load steps from JSONL
        self._task, self._steps = self._load(filepath)

    @staticmethod
    def _load(filepath: str) -> tuple[str, list[dict]]:
        """Parse .spectra JSONL into (task, [step_entries])."""
        task = ''
        steps: list[dict] = []
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                entry = json.loads(line)
                if entry.get('type') == 'header':
                    task = entry.get('task', '')
                elif entry.get('type') == 'step':
                    steps.append(entry)
                # Skip footer and unknown types
        return task, steps

    def run(self, step_callback=None) -> ReplayReport:
        """Execute the full replay and return a report.
        
        Args:
            step_callback: Optional callable(step, total, action, success, detail)
        """
        reader = TreeReader(self._wda_url)
        executor = Executor(self._wda_url)

        report = ReplayReport(flow_file=self._filepath, task=self._task, total=len(self._steps))
        t_start = time.monotonic()

        for entry in self._steps:
            step_num = entry['step']
            action = entry['action']
            params = entry.get('params', {})
            target = entry.get('target')

            # ── Skip meta actions ──
            if action in _SKIP_ACTIONS:
                report.skipped += 1
                sr = StepResult(step_num, action, 'n/a', 'n/a', True, 'Skipped (meta action)')
                report.steps.append(sr)
                if step_callback:
                    step_callback(step_num, report.total, action, sr.success, sr.detail)
                if self._verbose:
                    print(f'  ⏭  Step {step_num}: {action} — skipped')
                continue

            # ── Snapshot the current screen ──
            try:
                _tree, ref_map, _metadata = reader.snapshot()
            except Exception as e:
                report.failed += 1
                sr = StepResult(step_num, action, 'none', 'none', False, f'Snapshot failed: {e}')
                report.steps.append(sr)
                if step_callback:
                    step_callback(step_num, report.total, action, sr.success, sr.detail)
                if self._verbose:
                    print(f'  ❌ Step {step_num}: {action} — snapshot failed')
                continue

            # ── Actions that don't need element matching ──
            if action in _NO_MATCH_ACTIONS:
                try:
                    result = executor.run(action, params, ref_map)
                    report.passed += 1
                    sr = StepResult(step_num, action, 'n/a', 'n/a', True, result)
                except Exception as e:
                    report.failed += 1
                    sr = StepResult(step_num, action, 'n/a', 'n/a', False, str(e))
                report.steps.append(sr)
                if step_callback:
                    step_callback(step_num, report.total, action, sr.success, sr.detail)
                if self._verbose:
                    icon = '✅' if sr.success else '❌'
                    print(f'  {icon} Step {step_num}: {action} — {sr.detail}')
                time.sleep(self._step_delay)
                continue

            # ── Element matching for tap / type_text / tap_xy ──
            if action == 'tap_xy':
                # tap_xy uses raw coordinates — replay as-is
                try:
                    result = executor.run(action, params, ref_map)
                    report.passed += 1
                    sr = StepResult(step_num, action, 'n/a', 'n/a', True, result)
                except Exception as e:
                    report.failed += 1
                    sr = StepResult(step_num, action, 'n/a', 'n/a', False, str(e))
                report.steps.append(sr)
                if step_callback:
                    step_callback(step_num, report.total, action, sr.success, sr.detail)
                if self._verbose:
                    icon = '✅' if sr.success else '❌'
                    print(f'  {icon} Step {step_num}: {action} — {sr.detail}')
                time.sleep(self._step_delay)
                continue

            # For tap / type_text — need to re-match the element
            if target is None:
                report.failed += 1
                sr = StepResult(step_num, action, 'none', 'none', False, 'No target recorded')
                report.steps.append(sr)
                if step_callback:
                    step_callback(step_num, report.total, action, sr.success, sr.detail)
                if self._verbose:
                    print(f'  ❌ Step {step_num}: {action} — no target recorded')
                continue

            match_result = match(target, ref_map)

            if match_result.confidence == Confidence.NONE:
                report.failed += 1
                sr = StepResult(step_num, action, 'none', 'none', False, match_result.detail)
                report.steps.append(sr)
                if step_callback:
                    step_callback(step_num, report.total, action, sr.success, sr.detail)
                if self._verbose:
                    print(f'  ❌ Step {step_num}: {action} — {match_result.detail}')
                continue

            # Build new params with the matched ref
            replay_params = dict(params)
            replay_params['ref'] = match_result.ref

            try:
                result = executor.run(action, replay_params, ref_map)
                report.passed += 1
                if match_result.confidence == Confidence.MEDIUM:
                    report.fuzzy += 1
                sr = StepResult(
                    step_num, action, match_result.match_type,
                    match_result.confidence.value, True,
                    f'{result} ({match_result.detail})',
                )
            except Exception as e:
                report.failed += 1
                sr = StepResult(
                    step_num, action, match_result.match_type,
                    match_result.confidence.value, False, str(e),
                )

            report.steps.append(sr)
            if step_callback:
                step_callback(step_num, report.total, action, sr.success, sr.detail)
            if self._verbose:
                icon = '✅' if sr.success else '❌'
                conf_tag = f' [{match_result.match_type}]' if match_result.match_type != 'exact' else ''
                print(f'  {icon} Step {step_num}: {action}{conf_tag} — {sr.detail}')

            time.sleep(self._step_delay)

        report.duration = time.monotonic() - t_start
        return report

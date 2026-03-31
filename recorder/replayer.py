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
import os
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
    match_type: str       # 'exact', 'fuzzy', 'position', 'none', 'n/a', 'planner'
    confidence: str       # Confidence enum value
    success: bool
    detail: str
    score: float | None = None


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
    healed: int = 0       # low-confidence steps handed to the planner
    gated: int = 0        # steps that needed user confirmation
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
        print(f'  Total: {self.total} | Passed: {self.passed} | Fuzzy: {self.fuzzy} | Healed: {self.healed} '
              f'| Failed: {self.failed} | Skipped: {self.skipped}')
        print(f'  Duration: {self.duration:.1f}s')
        status = '🎉 ALL PASSED' if self.failed == 0 else f'⚠️  {self.failed} FAILED'
        print(f'  {status}')
        print(f'{"=" * 50}\n')


# Actions that don't interact with the screen — skip matching
_NO_MATCH_ACTIONS = {'scroll', 'go_back', 'go_home', 'wait', 'done', 'stuck',
                     'remember', 'handoff', 'plan', 'open_app'}

# Actions that should not be replayed (meta-only)
_SKIP_ACTIONS = {'done', 'stuck', 'remember', 'handoff', 'plan'}


def replayable(steps: list[dict]) -> bool:
    return not any(e.get('action') == 'remember' for e in steps)


class Replayer:
    """Load and replay a .spectra recording file."""

    def __init__(
        self,
        filepath: str,
        wda_url: str = 'http://localhost:8100',
        step_delay: float = 0.5,
        verbose: bool = True,
        gate=None,
        planner=None,
        min_confidence: float | None = None,
        matcher=None,
    ):
        """
        gate: ConfirmationGate; sensitive taps in a replay ask the user like live runs do.
        planner: if set, steps whose best match scores below min_confidence are handed
            to the planner for that one step instead of failing (or tapping a guess).
        matcher: override recorder.matcher.match (the benchmark uses this to compare versions).
        """
        self._filepath = filepath
        self._wda_url = wda_url
        self._step_delay = step_delay
        self._verbose = verbose
        self._gate = gate
        self._planner = planner
        self._match = matcher or match
        if min_confidence is None:
            min_confidence = float(os.environ.get('SPECTRA_REPLAY_MIN_CONFIDENCE', '0.75'))
        self._min_confidence = min_confidence

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
        self._reader = reader

        if not replayable(self._steps):
            # A `remember` step means later steps typed a value read off the screen at
            # record time (a price, a code). Replaying would send the stale value.
            report.failed = 1
            report.steps.append(StepResult(0, 'remember', 'n/a', 'n/a', False,
                                           'Flow uses values read at run time; not replaying'))
            report.duration = time.monotonic() - t_start
            return report

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

            match_result = self._match(target, ref_map)
            score = getattr(match_result, 'score', None)
            weak = match_result.confidence == Confidence.NONE or (
                score is not None and score < self._min_confidence)

            if weak and self._planner is not None:
                sr = self._heal(step_num, action, target, _tree, ref_map, _metadata, executor, report)
            elif weak:
                report.failed += 1
                sr = StepResult(step_num, action, match_result.match_type, match_result.confidence.value, False,
                                match_result.detail, score)
            else:
                replay_params = dict(params)
                replay_params['ref'] = match_result.ref
                sr = self._execute(step_num, action, replay_params, ref_map, executor, report,
                                   match_result.match_type, match_result.confidence.value,
                                   match_result.detail, score)
                if sr.success and action == 'tap' and self._planner is not None and self._no_effect(_tree):
                    # Something the recording never saw (a permission alert, a sheet) ate the
                    # tap. Let the planner deal with the screen, then try the step once more.
                    self._heal(step_num, action, target, *self._snap(), executor, report)
                    tree2, ref_map2, _ = self._snap()
                    retry = self._match(target, ref_map2)
                    if retry.ref is not None and (retry.score or 0) >= self._min_confidence:
                        replay_params['ref'] = retry.ref
                        executor.run(action, replay_params, ref_map2)
                if sr.success and match_result.confidence == Confidence.MEDIUM:
                    report.fuzzy += 1

            report.steps.append(sr)
            if step_callback:
                step_callback(step_num, report.total, action, sr.success, sr.detail)
            if self._verbose:
                icon = '✅' if sr.success else '❌'
                conf_tag = f' [{sr.match_type}]' if sr.match_type != 'exact' else ''
                print(f'  {icon} Step {step_num}: {action}{conf_tag} — {sr.detail}')

            time.sleep(self._step_delay)

        report.duration = time.monotonic() - t_start
        return report

    def _snap(self):
        return self._reader.snapshot()

    def _no_effect(self, before: str) -> bool:
        time.sleep(0.2)
        try:
            after, _, _ = self._snap()
        except Exception:
            return False
        return after == before

    def _execute(self, step_num, action, params, ref_map, executor, report, match_type, confidence,
                 detail, score) -> StepResult:
        """Run one matched step, through the confirmation gate like a live step."""
        if self._gate is not None and self._gate.check({'name': action, 'input': params}, ref_map):
            report.gated += 1
            if not self._gate.request_confirmation({'name': action, 'input': params}, ref_map):
                report.failed += 1
                return StepResult(step_num, action, match_type, confidence, False, 'Rejected by user', score)
        try:
            result = executor.run(action, params, ref_map)
        except Exception as e:
            report.failed += 1
            return StepResult(step_num, action, match_type, confidence, False, str(e), score)
        report.passed += 1
        return StepResult(step_num, action, match_type, confidence, True, f'{result} ({detail})', score)

    def _heal(self, step_num, action, target, tree, ref_map, metadata, executor, report) -> StepResult:
        """Ask the planner for this one step when the recorded element can't be found confidently."""
        label = (target or {}).get('label', '')
        history = [f'Replaying a saved flow for this task. Step {step_num} was {action} on "{label}", '
                   f'which is not on screen under that name. Do the equivalent action now.']
        try:
            decision = self._planner.next_action(tree=tree, task=self._task, history=history, metadata=metadata)
        except Exception as e:
            report.failed += 1
            return StepResult(step_num, action, 'planner', 'none', False, f'Planner fallback failed: {e}')
        if decision['name'] not in ('tap', 'type_text', 'tap_xy', 'scroll', 'go_back', 'open_app'):
            report.failed += 1
            return StepResult(step_num, action, 'planner', 'none', False,
                              f'Planner fallback returned {decision["name"]}')
        report.healed += 1
        return self._execute(step_num, decision['name'], decision['input'], ref_map, executor, report,
                             'planner', 'n/a', f'planner chose {decision["name"]} {decision["input"]}', None)

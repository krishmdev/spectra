"""Record agent actions to .spectra JSONL files during live execution."""
from __future__ import annotations

import hashlib
import json
import os
import time


class Recorder:
    """Append each agent action to a .spectra JSONL file in real time.

    Usage — inject into the agent loop's step_callback::

        recorder = Recorder('flows/dark_mode.spectra', task='Turn on Dark Mode')

        def on_step(step, total, action_name, action_input, result, app):
            recorder.record(step, action_name, action_input, ref_map, tree)

        run_agent(task, step_callback=on_step)
        recorder.close()
    """

    def __init__(self, filepath: str, task: str = ''):
        self._filepath = filepath
        self._task = task
        self._step = 0

        # Ensure parent directory exists
        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)

        # Open file for appending — one JSON line per action
        self._fp = open(filepath, 'a')

        # Write a header line with metadata (type=header so replayer can skip it)
        header = {
            'type': 'header',
            'task': task,
            'started_at': time.time(),
            'version': 1,
        }
        self._fp.write(json.dumps(header) + '\n')
        self._fp.flush()

    def record(
        self,
        step: int,
        action: str,
        params: dict,
        ref_map: dict,
        tree_text: str = '',
    ) -> None:
        """Record a single action step.

        Args:
            step: Step number (1-indexed).
            action: Tool name (tap, type_text, scroll, etc.).
            params: Tool parameters from the planner.
            ref_map: Current ref_map from TreeReader.
            tree_text: Current compact tree text (used for tree_hash).
        """
        self._step = step

        # Resolve target element details from ref_map when the action uses a ref
        target = None
        ref = params.get('ref')
        if ref is not None and ref_map:
            el = ref_map.get(int(ref))
            if el:
                target = {
                    'label': el.get('label', ''),
                    'type': el.get('type', ''),
                    'value': el.get('value', ''),
                    'x': el.get('x', 0),
                    'y': el.get('y', 0),
                    'width': el.get('width', 0),
                    'height': el.get('height', 0),
                }

        # Build clean params (strip reasoning — not needed for replay)
        replay_params = {k: v for k, v in params.items() if k != 'reasoning'}

        entry = {
            'type': 'step',
            'step': step,
            'action': action,
            'params': replay_params,
            'target': target,
            'tree_hash': hashlib.md5(tree_text.encode()).hexdigest()[:8] if tree_text else None,
            'timestamp': time.time(),
        }

        self._fp.write(json.dumps(entry) + '\n')
        self._fp.flush()

    def close(self) -> None:
        """Flush and close the recording file."""
        if self._fp and not self._fp.closed:
            # Write a footer
            footer = {
                'type': 'footer',
                'total_steps': self._step,
                'finished_at': time.time(),
            }
            self._fp.write(json.dumps(footer) + '\n')
            self._fp.flush()
            self._fp.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

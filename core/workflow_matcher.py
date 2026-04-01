"""Workflow matcher — find semantically identical saved workflows."""
from __future__ import annotations

import glob
import json
import os
import re

PROMPT = """You are evaluating if a new task is EXACTLY the same as a previously completed task.

New Task: "{task}"

Previously Completed Tasks:
{workflows}

Constraints for a match:
1. It must require the EXACT same apps, menus, buttons, and type the EXACT same data inputs.
2. If the user asks for a different parameter (e.g. "directions to B" instead of "directions to A"), it is NOT a match because replaying it will type "A".
3. Different phrasing for the identical goal is a match (e.g. "turn on dark mode" == "switch to dark mode").

If no task is an exact match, output: {{"match": null}}
If there is an exact match, output its ID: {{"match": "id_string"}}

Respond with ONLY valid JSON.
"""

def _load_available_workflows(flows_dir: str, exclude: str | None = None) -> dict[str, str]:
    """Return {filepath: task} for recordings that finished with at least one step.

    `exclude` is the recording the server just opened for the current task. Its
    header is already on disk, so without this every task matched itself and
    "replayed" zero steps.
    """
    workflows = {}
    if not os.path.isdir(flows_dir):
        return workflows
    skip = os.path.abspath(exclude) if exclude else None

    for path in glob.glob(os.path.join(flows_dir, '*.spectra')):
        if skip and os.path.abspath(path) == skip:
            continue
        try:
            with open(path) as f:
                entries = [json.loads(line) for line in f if line.strip()]
        except Exception:
            continue
        if not entries or entries[0].get('type') != 'header' or not entries[0].get('task'):
            continue
        steps = [e for e in entries if e.get('type') == 'step']
        finished = any(e.get('type') == 'footer' for e in entries)
        if any(e.get('action') == 'remember' for e in steps):
            continue  # typed values read at run time; a replay would reuse stale ones
        if steps and finished and steps[-1].get('action') == 'done':
            workflows[path] = entries[0]['task']
    return workflows

def find_matching_workflow(task: str, planner, flows_dir: str = 'flows', exclude: str | None = None) -> str | None:
    """Returns the filepath of an exact matching workflow, or None.
    
    Args:
        task: The user's requested task.
        planner: Any core.planner.PlannerProtocol implementation.
        flows_dir: Directory containing .spectra files.
    """
    workflows = _load_available_workflows(flows_dir, exclude=exclude)
    if not workflows:
        return None
        
    workflows_text = ""
    for path, saved_task in workflows.items():
        workflows_text += f'- ID: "{path}" | Task: "{saved_task}"\n'
        
    prompt = PROMPT.format(task=task, workflows=workflows_text)
    
    try:
        text = planner.complete(prompt, max_output_tokens=100, purpose='match_workflow')
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            match = data.get('match')
            # The reply is used as a path; only accept one of the IDs we offered.
            return match if match in workflows else None
    except Exception as e:
        print(f"[WorkflowMatcher] Error checking flows: {e}")
        
    return None

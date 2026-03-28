"""Workflow matcher — find semantically identical saved workflows."""
from __future__ import annotations

import glob
import json
import os
import re

from google.genai import types

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

def _load_available_workflows(flows_dir: str) -> dict[str, str]:
    """Return dict of {filepath: task_string}."""
    workflows = {}
    if not os.path.isdir(flows_dir):
        return workflows
        
    for path in glob.glob(os.path.join(flows_dir, '*.spectra')):
        try:
            with open(path) as f:
                first_line = f.readline().strip()
                if not first_line:
                    continue
                data = json.loads(first_line)
                if data.get('type') == 'header' and data.get('task'):
                    workflows[path] = data['task']
        except Exception:
            pass
    return workflows

def find_matching_workflow(task: str, planner, flows_dir: str = 'flows') -> str | None:
    """Returns the filepath of an exact matching workflow, or None.
    
    Args:
        task: The user's requested task.
        planner: An instantiated Planner object (to reuse the Gemini client).
        flows_dir: Directory containing .spectra files.
    """
    workflows = _load_available_workflows(flows_dir)
    if not workflows:
        return None
        
    workflows_text = ""
    for path, saved_task in workflows.items():
        workflows_text += f'- ID: "{path}" | Task: "{saved_task}"\n'
        
    prompt = PROMPT.format(task=task, workflows=workflows_text)
    
    try:
        config = types.GenerateContentConfig(max_output_tokens=100)
        response = planner.client.models.generate_content(
            model=planner.model,
            contents=[types.Content(role='user', parts=[types.Part(text=prompt)])],
            config=config,
        )
        text = response.text
        json_match = re.search(r'\{.*\}', text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            return data.get('match')
    except Exception as e:
        print(f"[WorkflowMatcher] Error checking flows: {e}")
        
    return None

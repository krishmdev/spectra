"""Action plan preview — generates and presents a step plan for complex tasks before execution."""

import re

from google.genai import types


class PlanPreview:
    """Ask Gemini to generate a high-level plan and present it for user approval."""

    def __init__(self, planner):
        """Initialize with a Planner instance (reuses its Gemini client).

        Args:
            planner: A core.planner.Planner instance.
        """
        self.client = planner.client
        self.model = planner.model

    def generate_plan(self, task: str) -> list[str]:
        """Ask Gemini to generate a numbered step plan without executing.

        Args:
            task: Natural language instruction.

        Returns:
            List of planned steps as human-readable strings.
        """
        prompt = (
            f'You are planning steps for a mobile agent to complete a task on an iPhone.\n'
            f'Task: {task}\n\n'
            f'Generate a numbered list of 3-8 high-level steps the agent should take.\n'
            f'Each step should be one clear action (e.g. "Open Uber app", "Enter destination: Airport").\n'
            f'Only include steps the agent can actually perform (tap, type, scroll, switch apps).\n'
            f'Do NOT include steps like "wait for user" unless sensitive input is needed.'
        )
        config = types.GenerateContentConfig(max_output_tokens=300)
        response = self.client.models.generate_content(
            model=self.model,
            contents=[types.Content(role='user', parts=[types.Part(text=prompt)])],
            config=config,
        )
        return self._parse_steps(response.text)

    def present_and_confirm(self, plan: list[str]) -> tuple[bool, list[str]]:
        """Display plan to user and wait for confirmation.

        Returns:
            (approved, plan) — approved is True if user accepts, plan may be unchanged.
        """
        print('\n📋 Proposed plan:')
        for i, step in enumerate(plan, 1):
            print(f'   {i}. {step}')
        print()

        response = input('   Approve plan? [Enter=yes / n=reject]: ').strip().lower()
        approved = response not in ('n', 'no')
        return approved, plan

    @staticmethod
    def _parse_steps(text: str) -> list[str]:
        """Parse a numbered list from LLM output into a list of step strings."""
        steps = []
        for line in text.strip().splitlines():
            match = re.match(r'^\d+[\.\)]\s*(.+)', line.strip())
            if match:
                steps.append(match.group(1).strip())
        # Fallback: if no numbered lines found, treat entire text as one step
        if not steps:
            steps = [text.strip()]
        return steps

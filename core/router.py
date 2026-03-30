"""Task router — classifies user intent and determines target app(s)."""
from __future__ import annotations

import json
import os
import re
import subprocess

from google.genai import types

_CONFIG_PATH = os.path.join(os.path.dirname(__file__), '..', 'config', 'apps.json')

# Default registry — only used to seed config/apps.json if it doesn't exist
_DEFAULT_CONFIG = {
    'apps': {
        'rideshare': [
            {'name': 'Uber', 'bundle_id': 'com.ubercab.UberClient'},
            {'name': 'Lyft', 'bundle_id': 'com.zimride.instant'},
        ],
        'food_delivery': [
            {'name': 'DoorDash', 'bundle_id': 'com.doordash.DriverApp'},
            {'name': 'Uber Eats', 'bundle_id': 'com.ubercab.UberEats'},
        ],
        'grocery': [
            {'name': 'Instacart', 'bundle_id': 'com.instacart.client'},
        ],
        'messaging': [
            {'name': 'Messages', 'bundle_id': 'com.apple.MobileSMS'},
        ],
        'settings': [
            {'name': 'Settings', 'bundle_id': 'com.apple.Preferences'},
        ],
    },
    'gates': {
        'sensitive_labels': [
            'send', 'submit', 'place order', 'confirm order', 'pay',
            'purchase', 'buy now', 'delete', 'remove', 'book ride',
            'confirm booking', 'checkout',
        ],
    },
}

ROUTING_PROMPT = """Classify this mobile task into a category and identify the target app(s).

Available categories: {categories}

App registry:
{registry}

Task: "{task}"

Respond with ONLY a JSON object (no markdown, no explanation):
{{"category": "...", "apps": ["AppName1"], "multi_app": false, "comparison": false, "refined_task": "..."}}

Rules:
- "refined_task" should be a clear instruction for the agent
- Set "multi_app": true if the task requires switching between multiple apps
- Set "comparison": true if the task involves comparing info across apps
- For comparison tasks, list ALL apps to compare in "apps"
- "apps" should contain app names from the registry
- For unknown apps, set category to "general" and apps to []"""


def load_config() -> dict:
    """Load config from config/apps.json. Creates default if missing."""
    try:
        with open(_CONFIG_PATH) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        os.makedirs(os.path.dirname(_CONFIG_PATH), exist_ok=True)
        with open(_CONFIG_PATH, 'w') as f:
            json.dump(_DEFAULT_CONFIG, f, indent=2)
        return dict(_DEFAULT_CONFIG)


class TaskRouter:
    """Classify user intent and determine which app(s) to target."""

    def __init__(self, planner):
        """Initialize with a Planner instance (reuses its Gemini client).

        Args:
            planner: A core.planner.Planner instance.
        """
        self.client = planner.client
        self.model = planner.model
        config = load_config()
        self.registry: dict = config.get('apps', {})

    def route(self, task: str) -> dict:
        """Classify user intent and determine target app(s).

        Returns:
            {
                'category': str,
                'apps': list[dict],     # [{name, bundle_id}, ...]
                'refined_task': str,
                'multi_app': bool,
                'comparison': bool,
            }
        """
        categories = ', '.join(self.registry.keys()) + ', general'
        registry_text = '\n'.join(
            f'  {cat}: {", ".join(a["name"] for a in apps)}'
            for cat, apps in self.registry.items()
        )
        prompt = ROUTING_PROMPT.format(
            categories=categories, registry=registry_text, task=task,
        )

        config = types.GenerateContentConfig(max_output_tokens=200)
        response = self.client.models.generate_content(
            model=self.model,
            contents=[types.Content(role='user', parts=[types.Part(text=prompt)])],
            config=config,
        )
        return self._parse_route(response.text, task)

    def _parse_route(self, text: str, original_task: str) -> dict:
        """Parse the LLM routing response into a structured dict."""
        json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if not json_match:
            return self._default_route(original_task)

        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError:
            return self._default_route(original_task)

        category = data.get('category', 'general')
        app_names = data.get('apps', [])
        multi_app = data.get('multi_app', False)
        comparison = data.get('comparison', False)
        refined_task = data.get('refined_task', original_task)

        apps = []
        for name in app_names:
            app = self._find_app(name)
            if app:
                apps.append(app)

        return {
            'category': category,
            'apps': apps,
            'refined_task': refined_task,
            'multi_app': multi_app,
            'comparison': comparison,
        }

    def _find_app(self, name: str) -> dict | None:
        """Look up an app by name in the loaded registry."""
        name_lower = name.lower()
        for apps in self.registry.values():
            for app in apps:
                if app['name'].lower() == name_lower:
                    return dict(app)
        return None

    @staticmethod
    def _default_route(task: str) -> dict:
        """Fallback route when parsing fails."""
        return {
            'category': 'general',
            'apps': [],
            'refined_task': task,
            'multi_app': False,
            'comparison': False,
        }

    @staticmethod
    def detect_installed_apps() -> list[str]:
        """Query the simulator for installed app bundle IDs."""
        try:
            result = subprocess.run(
                ['xcrun', 'simctl', 'listapps', 'booted'],
                capture_output=True, text=True, timeout=10,
            )
            try:
                data = json.loads(result.stdout)
                if isinstance(data, dict):
                    return list(data.keys())
                return []
            except json.JSONDecodeError:
                pass
            return re.findall(r'CFBundleIdentifier.*?=\s*"?([a-zA-Z0-9.\-]+)"?', result.stdout)
        except Exception:
            return []

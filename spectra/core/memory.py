"""Memory modules — session-scoped AgentMemory + cross-session EpisodicMemory."""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone

_DEFAULT_PATH = os.path.join(os.path.dirname(__file__), '..', 'data', 'lessons.json')
MAX_LESSONS = 50
MAX_INJECTED = 3
_SCORE_THRESHOLD = 2

_STOP_WORDS = frozenset({
    'the', 'a', 'an', 'to', 'in', 'on', 'and', 'or', 'then', 'open', 'go',
    'turn', 'set', 'find', 'check', 'is', 'it', 'of', 'for', 'from', 'with',
    'my', 'me', 'i', 'this', 'that', 'if', 'at', 'by', 'up', 'down',
})


def _extract_keywords(text: str) -> set[str]:
    """Extract lowercase keywords from text, removing stop words."""
    words = set(re.findall(r'[a-z]+', text.lower()))
    return words - _STOP_WORDS


class EpisodicMemory:
    """Persistent lesson store — learns from agent failures across sessions."""

    def __init__(self, path: str = _DEFAULT_PATH):
        self.path = os.path.abspath(path)
        self.lessons: list[dict] = self._load()

    def _load(self) -> list[dict]:
        try:
            with open(self.path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return []

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, 'w') as f:
            json.dump(self.lessons, f, indent=2)

    def add_lesson(
        self,
        task: str,
        app: str,
        lesson: str,
        failure_type: str,
        history_summary: str,
    ) -> None:
        """Store a lesson from a failed run. Rejects vague or truncated lessons."""
        if not lesson or len(lesson) < 30 or lesson.rstrip()[-1] not in '.!?")\u2019':
            return  # reject truncated or vague lessons
        entry = {
            'id': str(uuid.uuid4())[:8],
            'task': task,
            'app': app,
            'keywords': sorted(_extract_keywords(task)),
            'lesson': lesson,
            'failure_type': failure_type,
            'history_summary': history_summary,
            'created_at': datetime.now(timezone.utc).isoformat(),
            'hit_count': 0,
            'last_hit': None,
        }
        self.lessons.append(entry)
        self._prune()
        self._save()

    def retrieve(self, task: str, app: str | None = None) -> str | None:
        """Find relevant lessons for a task. Returns formatted text or None."""
        if not self.lessons:
            return None

        task_kw = _extract_keywords(task)
        if not task_kw:
            return None

        scored: list[tuple[float, dict]] = []
        for lesson in self.lessons:
            lesson_kw = set(lesson.get('keywords', []))
            overlap = len(task_kw & lesson_kw)
            score = overlap
            if app and lesson.get('app', '').lower() == app.lower():
                score += 2
            if score >= _SCORE_THRESHOLD:
                scored.append((score, lesson))

        if not scored:
            return None

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:MAX_INJECTED]

        # Update hit counts
        now = datetime.now(timezone.utc).isoformat()
        for _, lesson in top:
            lesson['hit_count'] = lesson.get('hit_count', 0) + 1
            lesson['last_hit'] = now
        self._save()

        lines = ['PAST LESSONS (from previous runs):']
        for i, (_, lesson) in enumerate(top, 1):
            lines.append(f'  {i}. [{lesson["app"]}] {lesson["lesson"]}')
        return '\n'.join(lines)

    def _prune(self) -> None:
        """Keep top MAX_LESSONS by hit_count (desc), then created_at (desc)."""
        if len(self.lessons) <= MAX_LESSONS:
            return
        self.lessons.sort(
            key=lambda x: (x.get('hit_count', 0), x.get('created_at', '')),
            reverse=True,
        )
        self.lessons = self.lessons[:MAX_LESSONS]


# ---------------------------------------------------------------------------
# Session-scoped memory (PRD §5.9) — key-value store for cross-app comparison
# ---------------------------------------------------------------------------


class AgentMemory:
    """In-memory key-value store for a single task session.

    Used to remember values across app switches (e.g. store Uber price,
    switch to Lyft, compare). Cleared at end of task.
    """

    def __init__(self):
        self._store: dict[str, str] = {}

    def store(self, key: str, value: str) -> str:
        """Store a value. Returns confirmation string."""
        self._store[key] = value
        return f'Stored {key}={value}'

    def recall(self, key: str) -> str | None:
        """Retrieve a stored value. Returns None if key doesn't exist."""
        return self._store.get(key)

    def recall_all(self) -> dict[str, str]:
        """Return all stored key-value pairs."""
        return dict(self._store)

    def clear(self) -> None:
        """Clear all memory (called at end of task)."""
        self._store.clear()

    def format_for_prompt(self) -> str:
        """Format stored values for injection into the LLM prompt."""
        if not self._store:
            return ''
        lines = [f'  {k}: "{v}"' for k, v in self._store.items()]
        return 'AGENT MEMORY:\n' + '\n'.join(lines)

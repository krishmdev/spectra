from __future__ import annotations
"""Always-on action logger.

Polls the accessibility tree via the PassiveObserver's buffer and diffs
consecutive snapshots to produce natural-language action descriptions.
Stores every action in a SQLite table (action_log) and feeds the
SequenceDetector for pattern matching.
"""
import sqlite3
import json
import os
import time
import uuid
from dataclasses import dataclass


@dataclass
class ActionEntry:
    id: str
    timestamp: float
    app_bundle_id: str
    action_nl: str          # e.g. "Tapped 'Directions' button in Maps"
    screen_labels: list[str]  # visible labels at time of action


class ActionLog:
    def __init__(self):
        db_path = os.path.expanduser('~/.spectra/actions.db')
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        c = self.conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS action_log (
                id TEXT PRIMARY KEY,
                timestamp REAL NOT NULL,
                app_bundle_id TEXT NOT NULL,
                action_nl TEXT NOT NULL,
                screen_labels TEXT NOT NULL
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS action_sequences (
                id TEXT PRIMARY KEY,
                actions_json TEXT NOT NULL,
                occurrence_count INT NOT NULL DEFAULT 1,
                last_triggered_at REAL,
                created_at REAL NOT NULL
            )
        ''')
        self.conn.commit()

    def append(self, app_bundle_id: str, action_nl: str, screen_labels: list[str]) -> ActionEntry:
        entry = ActionEntry(
            id=str(uuid.uuid4()),
            timestamp=time.time(),
            app_bundle_id=app_bundle_id,
            action_nl=action_nl,
            screen_labels=screen_labels,
        )
        c = self.conn.cursor()
        c.execute(
            'INSERT INTO action_log (id, timestamp, app_bundle_id, action_nl, screen_labels) VALUES (?, ?, ?, ?, ?)',
            (entry.id, entry.timestamp, entry.app_bundle_id, entry.action_nl, json.dumps(screen_labels)),
        )
        self.conn.commit()
        return entry

    def get_recent(self, limit: int = 50) -> list[ActionEntry]:
        c = self.conn.cursor()
        c.execute('SELECT * FROM action_log ORDER BY timestamp DESC LIMIT ?', (limit,))
        return [self._row_to_entry(r) for r in c.fetchall()]

    def get_tail(self, n: int) -> list[ActionEntry]:
        """Return the last n actions in chronological order."""
        c = self.conn.cursor()
        c.execute('SELECT * FROM action_log ORDER BY timestamp DESC LIMIT ?', (n,))
        rows = c.fetchall()
        return [self._row_to_entry(r) for r in reversed(rows)]

    def get_all(self) -> list[ActionEntry]:
        c = self.conn.cursor()
        c.execute('SELECT * FROM action_log ORDER BY timestamp DESC')
        return [self._row_to_entry(r) for r in c.fetchall()]

    # --- Sequence storage ---

    def save_sequence(self, actions: list[str], occurrence_count: int = 1) -> str:
        seq_id = str(uuid.uuid4())
        c = self.conn.cursor()
        c.execute(
            'INSERT INTO action_sequences (id, actions_json, occurrence_count, created_at) VALUES (?, ?, ?, ?)',
            (seq_id, json.dumps(actions), occurrence_count, time.time()),
        )
        self.conn.commit()
        return seq_id

    def increment_sequence(self, seq_id: str):
        c = self.conn.cursor()
        c.execute('UPDATE action_sequences SET occurrence_count = occurrence_count + 1 WHERE id = ?', (seq_id,))
        self.conn.commit()

    def mark_sequence_triggered(self, seq_id: str):
        c = self.conn.cursor()
        c.execute('UPDATE action_sequences SET last_triggered_at = ? WHERE id = ?', (time.time(), seq_id))
        self.conn.commit()

    def get_all_sequences(self) -> list[dict]:
        c = self.conn.cursor()
        c.execute('SELECT * FROM action_sequences ORDER BY occurrence_count DESC')
        results = []
        for r in c.fetchall():
            results.append({
                'id': r['id'],
                'actions': json.loads(r['actions_json']),
                'occurrence_count': r['occurrence_count'],
                'last_triggered_at': r['last_triggered_at'],
                'created_at': r['created_at'],
            })
        return results

    def _row_to_entry(self, row) -> ActionEntry:
        return ActionEntry(
            id=row['id'],
            timestamp=row['timestamp'],
            app_bundle_id=row['app_bundle_id'],
            action_nl=row['action_nl'],
            screen_labels=json.loads(row['screen_labels']),
        )

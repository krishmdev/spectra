import sqlite3
import json
import os
import time
import uuid
from context.models import Episode, ContextSnapshot, EpisodeMatch

class EpisodeStore:
    def __init__(self):
        db_path = os.path.expanduser('~/.spectra/episodes.db')
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        c = self.conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS episodes (
                id TEXT PRIMARY KEY,
                task_description TEXT NOT NULL,
                spectra_path TEXT NOT NULL,
                step_count INT NOT NULL,
                app_bundle_id TEXT NOT NULL,
                visible_labels TEXT NOT NULL,
                location_lat REAL,
                location_lng REAL,
                location_label TEXT,
                hour_of_day INT NOT NULL,
                day_of_week INT NOT NULL,
                created_at REAL NOT NULL,
                occurrence_count INT NOT NULL DEFAULT 1,
                last_suggested_at REAL,
                last_suggestion_accepted INT
            )
        ''')
        c.execute('''
            CREATE TABLE IF NOT EXISTS suggestion_log (
                id TEXT PRIMARY KEY,
                episode_id TEXT NOT NULL,
                suggested_at REAL NOT NULL,
                accepted INT
            )
        ''')
        self.conn.commit()

    def save_episode(self, episode: Episode) -> str:
        c = self.conn.cursor()
        c.execute('''
            INSERT INTO episodes (
                id, task_description, spectra_path, step_count, app_bundle_id,
                visible_labels, location_lat, location_lng, location_label,
                hour_of_day, day_of_week, created_at, occurrence_count,
                last_suggested_at, last_suggestion_accepted
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            episode.id, episode.task_description, episode.spectra_path,
            episode.step_count, episode.app_bundle_id,
            json.dumps(episode.visible_labels), episode.location_lat,
            episode.location_lng, episode.location_label, episode.hour_of_day,
            episode.day_of_week, episode.created_at, episode.occurrence_count,
            episode.last_suggested_at,
            (1 if episode.last_suggestion_accepted else 0) if episode.last_suggestion_accepted is not None else None
        ))
        self.conn.commit()
        return episode.id

    def increment_occurrence(self, episode_id: str) -> None:
        c = self.conn.cursor()
        c.execute('UPDATE episodes SET occurrence_count = occurrence_count + 1 WHERE id = ?', (episode_id,))
        self.conn.commit()

    def find_matching_episodes(self, ctx: ContextSnapshot) -> list[EpisodeMatch]:
        from context.matcher import score_episode
        episodes = self.get_all_episodes()
        matches = []
        for ep in episodes:
            match = score_episode(ep, ctx)
            if match:
                matches.append(match)
        matches.sort(key=lambda x: x.score, reverse=True)
        return matches

    def log_suggestion(self, episode_id: str) -> str:
        log_id = str(uuid.uuid4())
        now = time.time()
        c = self.conn.cursor()
        c.execute('INSERT INTO suggestion_log (id, episode_id, suggested_at, accepted) VALUES (?, ?, ?, NULL)',
                  (log_id, episode_id, now))
        c.execute('UPDATE episodes SET last_suggested_at = ? WHERE id = ?', (now, episode_id))
        self.conn.commit()
        return log_id

    def mark_suggestion_responded(self, log_id: str, accepted: bool) -> None:
        accepted_int = 1 if accepted else 0
        c = self.conn.cursor()
        c.execute('UPDATE suggestion_log SET accepted = ? WHERE id = ?', (accepted_int, log_id))
        c.execute('''
            UPDATE episodes SET last_suggestion_accepted = ? 
            WHERE id = (SELECT episode_id FROM suggestion_log WHERE id = ?)
        ''', (accepted_int, log_id))
        if accepted:
            c.execute('''
                UPDATE episodes SET occurrence_count = occurrence_count + 1 
                WHERE id = (SELECT episode_id FROM suggestion_log WHERE id = ?)
            ''', (log_id,))
        self.conn.commit()

    def get_all_episodes(self) -> list[Episode]:
        c = self.conn.cursor()
        c.execute('SELECT * FROM episodes ORDER BY created_at DESC')
        rows = c.fetchall()
        episodes = []
        for row in rows:
            acc = row['last_suggestion_accepted']
            episodes.append(Episode(
                id=row['id'],
                task_description=row['task_description'],
                spectra_path=row['spectra_path'],
                step_count=row['step_count'],
                app_bundle_id=row['app_bundle_id'],
                visible_labels=json.loads(row['visible_labels']),
                location_lat=row['location_lat'],
                location_lng=row['location_lng'],
                location_label=row['location_label'],
                hour_of_day=row['hour_of_day'],
                day_of_week=row['day_of_week'],
                created_at=row['created_at'],
                occurrence_count=row['occurrence_count'],
                last_suggested_at=row['last_suggested_at'],
                last_suggestion_accepted=bool(acc) if acc is not None else None
            ))
        return episodes

    def delete_episode(self, episode_id: str) -> None:
        c = self.conn.cursor()
        c.execute('DELETE FROM episodes WHERE id = ?', (episode_id,))
        self.conn.commit()

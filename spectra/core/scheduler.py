"""Time-based hooks scheduler.

Single source of truth for all scheduled/recurring tasks.
The scheduler is an engine: it checks what's due, dispatches execution
asynchronously, and updates lifecycle state. It never blocks.

State machine:
  create → active
  active → running (when due)
  running → active (recurring success)
  running → completed (one-time success)
  running → failed
  active → paused
  paused → active (resume)
  any → deleted (cancel)
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Optional, Callable

# ---------------------------------------------------------------------------
# Recurrence parsing
# ---------------------------------------------------------------------------

_INTERVAL_RE = re.compile(
    r'every\s+(\d+)\s*(second|minute|hour|day|week)s?',
    re.IGNORECASE,
)

_RELATIVE_RE = re.compile(
    r'in\s+(\d+)\s*(second|minute|hour|day|week)s?',
    re.IGNORECASE,
)

_UNIT_SECONDS = {
    'second': 1, 'minute': 60, 'hour': 3600,
    'day': 86400, 'week': 604800,
}

_DAY_NAMES = {
    'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
    'friday': 4, 'saturday': 5, 'sunday': 6,
    'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3,
    'fri': 4, 'sat': 5, 'sun': 6,
    'weekday': -1, 'weekdays': -1,
}

_TIME_RE = re.compile(r'(\d{1,2})(?::(\d{2}))?\s*(am|pm)?', re.IGNORECASE)


def parse_schedule(text: str) -> dict:
    """Parse natural language schedule into structured fields.

    Returns dict with:
      schedule_type: "one_time" | "interval" | "calendar"
      recurrence_rule: dict | None
      next_run_at: float (unix timestamp)
      recurrence_description: str
    """
    text_lower = text.lower().strip()

    # --- Interval: "every N units" ---
    m = _INTERVAL_RE.search(text_lower)
    if m:
        value = int(m.group(1))
        unit = m.group(2).rstrip('s')
        interval_s = value * _UNIT_SECONDS[unit]
        return {
            'schedule_type': 'interval',
            'recurrence_rule': {'unit': unit, 'value': value, 'interval_seconds': interval_s},
            'next_run_at': time.time() + interval_s,
            'recurrence_description': f'every {value} {unit}{"s" if value != 1 else ""}',
        }

    # --- Relative: "in N units" ---
    m = _RELATIVE_RE.search(text_lower)
    if m:
        value = int(m.group(1))
        unit = m.group(2).rstrip('s')
        delay_s = value * _UNIT_SECONDS[unit]
        return {
            'schedule_type': 'one_time',
            'recurrence_rule': None,
            'next_run_at': time.time() + delay_s,
            'recurrence_description': f'in {value} {unit}{"s" if value != 1 else ""}',
        }

    # --- Calendar: "every <day> at <time>" or "daily at <time>" ---
    days = []
    for day_name, day_num in _DAY_NAMES.items():
        if day_name in text_lower:
            if day_num == -1:  # weekday/weekdays
                days = [0, 1, 2, 3, 4]
            else:
                if day_num not in days:
                    days.append(day_num)

    if 'daily' in text_lower or 'every day' in text_lower:
        days = [0, 1, 2, 3, 4, 5, 6]

    time_match = _TIME_RE.search(text)
    hour, minute = 9, 0  # default
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        ampm = (time_match.group(3) or '').lower()
        if ampm == 'pm' and hour < 12:
            hour += 12
        if ampm == 'am' and hour == 12:
            hour = 0

    if days:
        next_run = _next_calendar_run(days, hour, minute)
        if len(days) == 7:
            desc = f'daily at {_fmt_time(hour, minute)}'
        elif days == [0, 1, 2, 3, 4]:
            desc = f'weekdays at {_fmt_time(hour, minute)}'
        else:
            day_strs = [['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][d] for d in sorted(days)]
            desc = f'every {", ".join(day_strs)} at {_fmt_time(hour, minute)}'
        return {
            'schedule_type': 'calendar',
            'recurrence_rule': {'days_of_week': sorted(days), 'hour': hour, 'minute': minute},
            'next_run_at': next_run,
            'recurrence_description': desc,
        }

    # --- Absolute time: "at <time>" or "tomorrow at <time>" ---
    if time_match:
        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if 'tomorrow' in text_lower:
            target += timedelta(days=1)
        elif target <= now:
            target += timedelta(days=1)
        return {
            'schedule_type': 'one_time',
            'recurrence_rule': None,
            'next_run_at': target.timestamp(),
            'recurrence_description': f'at {_fmt_time(hour, minute)}',
        }

    # Fallback: treat as 1-minute delay
    return {
        'schedule_type': 'one_time',
        'recurrence_rule': None,
        'next_run_at': time.time() + 60,
        'recurrence_description': 'in 1 minute',
    }


def _next_calendar_run(days: list[int], hour: int, minute: int) -> float:
    now = datetime.now()
    for offset in range(8):  # check next 7 days + today
        candidate = now + timedelta(days=offset)
        if candidate.weekday() in days:
            target = candidate.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target > now:
                return target.timestamp()
    # Fallback
    return (now + timedelta(days=1)).replace(hour=hour, minute=minute, second=0).timestamp()


def compute_next_run(hook: dict) -> Optional[float]:
    """Compute the next run time for a recurring hook from now."""
    rule = hook.get('recurrence_rule')
    if not rule:
        return None

    stype = hook['schedule_type']
    now = time.time()

    if stype == 'interval':
        return now + rule['interval_seconds']

    if stype == 'calendar':
        return _next_calendar_run(rule['days_of_week'], rule['hour'], rule['minute'])

    return None


def _fmt_time(h: int, m: int) -> str:
    period = 'AM' if h < 12 else 'PM'
    dh = h % 12 or 12
    return f'{dh}:{m:02d} {period}'


# ---------------------------------------------------------------------------
# TimeHook (the schedule record)
# ---------------------------------------------------------------------------

VALID_STATES = {'active', 'running', 'paused', 'completed', 'failed'}
VALID_TYPES = {'one_time', 'interval', 'calendar'}


def new_hook(
    title: str,
    action_task: str,
    schedule_type: str,
    recurrence_rule: Optional[dict],
    next_run_at: float,
    recurrence_description: str,
    original_prompt: str = '',
) -> dict:
    """Create a new TimeHook dict."""
    now = time.time()
    return {
        'id': str(uuid.uuid4()),
        'title': title,
        'action_task': action_task,  # NL command sent to agent on fire
        'original_prompt': original_prompt,
        'schedule_type': schedule_type,
        'recurrence_rule': recurrence_rule,
        'recurrence_description': recurrence_description,
        'next_run_at': next_run_at,
        'last_run_at': None,
        'last_result': None,
        'last_error': None,
        'state': 'active',
        'allow_overlap': False,
        'fire_count': 0,
        'created_at': now,
        'updated_at': now,
    }


def hook_to_client(hook: dict) -> dict:
    """Convert a TimeHook dict to the shape sent over WebSocket."""
    return {
        'id': hook['id'],
        'title': hook['title'],
        'action_task': hook['action_task'],
        'state': hook['state'],
        'schedule_type': hook['schedule_type'],
        'recurrence_description': hook.get('recurrence_description', ''),
        'next_run_at': hook.get('next_run_at'),
        'last_run_at': hook.get('last_run_at'),
        'last_result': hook.get('last_result'),
        'last_error': hook.get('last_error'),
        'fire_count': hook.get('fire_count', 0),
        'created_at': hook['created_at'],
    }


# ---------------------------------------------------------------------------
# Scheduler engine
# ---------------------------------------------------------------------------

_PERSIST_PATH = os.path.expanduser('~/.spectra/hooks.json')


class Scheduler:
    """Non-blocking scheduler engine. Ticks every 1 second."""

    def __init__(self):
        self._hooks: dict[str, dict] = {}  # id -> hook
        self._lock = threading.Lock()
        self._run_agent_fn: Optional[Callable] = None  # set by ws_server
        self._state = None  # ConnectionState for WS events
        self._push_fn: Optional[Callable] = None  # _send_sim_push
        self._running_hook_id: Optional[str] = None
        self._load()

    # --- Persistence ---

    def _load(self):
        try:
            if os.path.exists(_PERSIST_PATH):
                with open(_PERSIST_PATH, 'r') as f:
                    hooks_list = json.load(f)
                for h in hooks_list:
                    self._hooks[h['id']] = h
                print(f'[Scheduler] Loaded {len(self._hooks)} hooks', flush=True)
        except Exception as e:
            print(f'[Scheduler] Load error: {e}', flush=True)

    def _save(self):
        try:
            os.makedirs(os.path.dirname(_PERSIST_PATH), exist_ok=True)
            with open(_PERSIST_PATH, 'w') as f:
                json.dump(list(self._hooks.values()), f, indent=2)
        except Exception as e:
            print(f'[Scheduler] Save error: {e}', flush=True)

    # --- CRUD ---

    def create(self, title: str, action_task: str, schedule_text: str,
               original_prompt: str = '') -> dict:
        parsed = parse_schedule(schedule_text)
        hook = new_hook(
            title=title,
            action_task=action_task,
            schedule_type=parsed['schedule_type'],
            recurrence_rule=parsed['recurrence_rule'],
            next_run_at=parsed['next_run_at'],
            recurrence_description=parsed['recurrence_description'],
            original_prompt=original_prompt,
        )
        with self._lock:
            self._hooks[hook['id']] = hook
            self._save()
        self._emit_update(hook)
        print(f'[Scheduler] Created: {title} ({parsed["recurrence_description"]})', flush=True)
        return hook

    def list_hooks(self) -> list[dict]:
        with self._lock:
            return [hook_to_client(h) for h in self._hooks.values()]

    def get_hook(self, hook_id: str) -> Optional[dict]:
        with self._lock:
            return self._hooks.get(hook_id)

    def pause(self, hook_id: str) -> bool:
        with self._lock:
            h = self._hooks.get(hook_id)
            if not h or h['state'] not in ('active', 'failed'):
                return False
            h['state'] = 'paused'
            h['updated_at'] = time.time()
            self._save()
        self._emit_update(h)
        print(f'[Scheduler] Paused: {h["title"]}', flush=True)
        return True

    def resume(self, hook_id: str) -> bool:
        with self._lock:
            h = self._hooks.get(hook_id)
            if not h or h['state'] != 'paused':
                return False
            h['state'] = 'active'
            # Recompute next run from NOW — don't replay stale backlog
            if h['schedule_type'] != 'one_time':
                h['next_run_at'] = compute_next_run(h)
            elif h.get('next_run_at') and h['next_run_at'] < time.time():
                # One-time in the past — set to 30s from now
                h['next_run_at'] = time.time() + 30
            h['updated_at'] = time.time()
            self._save()
        self._emit_update(h)
        print(f'[Scheduler] Resumed: {h["title"]}', flush=True)
        return True

    def cancel(self, hook_id: str) -> bool:
        with self._lock:
            h = self._hooks.pop(hook_id, None)
            if not h:
                return False
            self._save()
        self._emit_deleted(hook_id)
        print(f'[Scheduler] Cancelled: {h["title"]}', flush=True)
        return True

    def run_now(self, hook_id: str) -> bool:
        """Trigger an immediate execution without modifying the recurrence."""
        with self._lock:
            h = self._hooks.get(hook_id)
            if not h:
                return False
        # Dispatch fire async
        threading.Thread(target=self._fire, args=(h,), daemon=True).start()
        return True

    # --- Scheduler loop ---

    def start(self):
        """Start the scheduler loop in a daemon thread."""
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()
        print('[Scheduler] Started (1s tick)', flush=True)

    def _loop(self):
        while True:
            try:
                self._tick()
            except Exception as e:
                print(f'[Scheduler] Tick error: {e}', flush=True)
            time.sleep(1)

    def _tick(self):
        now = time.time()
        due = []
        with self._lock:
            for h in self._hooks.values():
                if (h['state'] == 'active'
                        and h.get('next_run_at')
                        and h['next_run_at'] <= now):
                    due.append(h)

        for h in due:
            # Overlap check
            if not h.get('allow_overlap', False) and self._running_hook_id == h['id']:
                print(f'[Scheduler] Skipping overlap: {h["title"]}', flush=True)
                # Advance next run so we don't re-check every tick
                with self._lock:
                    if h['schedule_type'] != 'one_time':
                        h['next_run_at'] = compute_next_run(h)
                        self._save()
                continue

            # Dispatch async — never block the loop
            threading.Thread(target=self._fire, args=(h,), daemon=True).start()

    def _fire(self, hook: dict):
        hook_id = hook['id']

        # Transition to running
        with self._lock:
            h = self._hooks.get(hook_id)
            if not h:
                return
            h['state'] = 'running'
            h['updated_at'] = time.time()
            self._save()
        self._running_hook_id = hook_id
        self._emit_update(h)
        self._emit_fired(h)

        # Execute
        success = False
        result_summary = None
        error_summary = None
        try:
            if self._run_agent_fn:
                self._run_agent_fn(h['action_task'])
                success = True
                result_summary = f'Completed: {h["action_task"]}'
            else:
                error_summary = 'No agent function available'
        except Exception as e:
            error_summary = str(e)[:200]
            print(f'[Scheduler] Execution error for {h["title"]}: {e}', flush=True)

        # Update state
        with self._lock:
            h = self._hooks.get(hook_id)
            if not h:
                return
            h['last_run_at'] = time.time()
            h['fire_count'] = h.get('fire_count', 0) + 1
            h['updated_at'] = time.time()

            if success:
                h['last_result'] = result_summary
                h['last_error'] = None
                if h['schedule_type'] == 'one_time':
                    h['state'] = 'completed'
                    h['next_run_at'] = None
                else:
                    h['state'] = 'active'
                    h['next_run_at'] = compute_next_run(h)
            else:
                h['last_error'] = error_summary
                h['state'] = 'failed'

            self._save()

        self._running_hook_id = None
        self._emit_update(h)
        self._emit_result(h, success, result_summary, error_summary)

    # --- Event emission ---

    def _emit_update(self, hook: dict):
        if self._state:
            try:
                self._state.send({'type': 'schedule_update', 'hook': hook_to_client(hook)})
            except Exception:
                pass

    def _emit_deleted(self, hook_id: str):
        if self._state:
            try:
                self._state.send({'type': 'schedule_deleted', 'hook_id': hook_id})
            except Exception:
                pass

    def _emit_fired(self, hook: dict):
        if self._state:
            try:
                self._state.send({
                    'type': 'schedule_fired',
                    'hook_id': hook['id'],
                    'title': hook['title'],
                    'schedule_type': hook['schedule_type'],
                })
            except Exception:
                pass
        # Also push notification
        if self._push_fn:
            self._push_fn('Running', hook['title'])

    def _emit_result(self, hook: dict, success: bool, result: str, error: str):
        if self._state:
            try:
                self._state.send({
                    'type': 'schedule_result',
                    'hook_id': hook['id'],
                    'success': success,
                    'result_summary': result,
                    'error_summary': error,
                })
            except Exception:
                pass
        # Push notification for completion/failure
        if self._push_fn:
            if success:
                self._push_fn('Task Complete', hook['title'])
            else:
                self._push_fn('Task Failed', f'{hook["title"]}: {error}')

"""Tests for core/scheduler.py.

Ported from the test suite on my time-triggers branch (de1c03c), rewritten
against the Scheduler that landed in main in the final hackathon commit.
"""
import time

import pytest

import core.scheduler as sched
from core.scheduler import Scheduler, compute_next_run, parse_schedule


@pytest.fixture
def scheduler(tmp_path, monkeypatch):
    monkeypatch.setattr(sched, '_PERSIST_PATH', str(tmp_path / 'hooks.json'))
    return Scheduler()


class TestParseSchedule:
    def test_every_n_minutes(self):
        r = parse_schedule('every 5 minutes')
        assert r['schedule_type'] == 'interval'
        assert r['recurrence_rule']['interval_seconds'] == 300
        assert r['next_run_at'] == pytest.approx(time.time() + 300, abs=2)

    def test_every_n_seconds_and_hours(self):
        assert parse_schedule('every 10 seconds')['recurrence_rule']['interval_seconds'] == 10
        assert parse_schedule('every 2 hours')['recurrence_rule']['interval_seconds'] == 7200

    def test_daily_at_time(self):
        r = parse_schedule('daily at 8am')
        assert r['schedule_type'] == 'calendar'
        assert r['recurrence_rule'] == {'days_of_week': [0, 1, 2, 3, 4, 5, 6], 'hour': 8, 'minute': 0}
        assert r['next_run_at'] > time.time()

    def test_weekdays_at_time(self):
        r = parse_schedule('weekdays at 9:30am')
        assert r['recurrence_rule']['days_of_week'] == [0, 1, 2, 3, 4]
        assert (r['recurrence_rule']['hour'], r['recurrence_rule']['minute']) == (9, 30)

    def test_in_n_minutes_is_one_time(self):
        r = parse_schedule('in 10 minutes')
        assert r['schedule_type'] == 'one_time'
        assert r['next_run_at'] == pytest.approx(time.time() + 600, abs=2)

    def test_tomorrow_at_time(self):
        r = parse_schedule('tomorrow at 3pm')
        assert r['schedule_type'] == 'one_time'
        assert time.time() < r['next_run_at'] <= time.time() + 2 * 86400

    def test_pm_conversion(self):
        assert parse_schedule('every friday at 7pm')['recurrence_rule']['hour'] == 19


class TestLifecycle:
    def test_create_and_list(self, scheduler):
        hook = scheduler.create('check mail', 'check mail', 'in 10 seconds')
        assert hook['state'] == 'active'
        assert [h['id'] for h in scheduler.list_hooks()] == [hook['id']]

    def test_cancel(self, scheduler):
        hook = scheduler.create('t', 't', 'every 5 minutes')
        assert scheduler.cancel(hook['id']) is True
        assert scheduler.list_hooks() == []
        assert scheduler.cancel('nope') is False

    def test_pause_and_resume_recomputes_next_run(self, scheduler):
        hook = scheduler.create('t', 't', 'every 5 minutes')
        scheduler.get_hook(hook['id'])['next_run_at'] = time.time() - 3600  # stale
        assert scheduler.pause(hook['id'])
        assert scheduler.get_hook(hook['id'])['state'] == 'paused'
        assert scheduler.resume(hook['id'])
        assert scheduler.get_hook(hook['id'])['next_run_at'] > time.time()


class TestFiring:
    def test_due_one_time_hook_runs_once_and_completes(self, scheduler):
        ran = []
        scheduler._run_agent_fn = ran.append
        hook = scheduler.create('say hi', 'say hi', 'in 1 second')
        scheduler.get_hook(hook['id'])['next_run_at'] = time.time() - 1
        scheduler._fire(scheduler.get_hook(hook['id']))
        h = scheduler.get_hook(hook['id'])
        assert ran == ['say hi']
        assert h['state'] == 'completed' and h['next_run_at'] is None and h['fire_count'] == 1

    def test_recurring_hook_stays_active(self, scheduler):
        scheduler._run_agent_fn = lambda t: None
        hook = scheduler.create('t', 't', 'every 30 seconds')
        scheduler._fire(scheduler.get_hook(hook['id']))
        h = scheduler.get_hook(hook['id'])
        assert h['state'] == 'active' and h['next_run_at'] > time.time()

    def test_failure_is_recorded(self, scheduler):
        def boom(task):
            raise RuntimeError('WDA down')
        scheduler._run_agent_fn = boom
        hook = scheduler.create('t', 't', 'every 30 seconds')
        scheduler._fire(scheduler.get_hook(hook['id']))
        h = scheduler.get_hook(hook['id'])
        assert h['state'] == 'failed' and 'WDA down' in h['last_error']

    def test_events_go_to_the_connected_client(self, scheduler):
        sent = []
        scheduler._state = type('S', (), {'send': lambda self, m: sent.append(m['type'])})()
        scheduler._run_agent_fn = lambda t: None
        hook = scheduler.create('t', 't', 'in 5 seconds')
        scheduler._fire(scheduler.get_hook(hook['id']))
        assert {'schedule_update', 'schedule_fired', 'schedule_result'} <= set(sent)

    def test_compute_next_run_interval(self):
        hook = {'schedule_type': 'interval', 'recurrence_rule': {'interval_seconds': 60}}
        assert compute_next_run(hook) == pytest.approx(time.time() + 60, abs=1)


def test_hooks_persist_across_instances(scheduler):
    hook = scheduler.create('t', 't', 'every 5 minutes')
    again = Scheduler()
    assert again.get_hook(hook['id'])['title'] == 't'

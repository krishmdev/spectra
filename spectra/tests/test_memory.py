"""Tests for episodic memory — cross-session lesson storage and retrieval."""

import json
import os
import pytest
from core.memory import EpisodicMemory, _extract_keywords


class TestKeywordExtraction:
    def test_removes_stop_words(self):
        kw = _extract_keywords('Turn on Bold Text in the Accessibility settings')
        assert 'the' not in kw
        assert 'in' not in kw
        assert 'turn' not in kw
        assert 'bold' in kw
        assert 'text' in kw
        assert 'accessibility' in kw
        assert 'settings' in kw

    def test_lowercase(self):
        kw = _extract_keywords('Open GENERAL Settings')
        assert 'general' in kw
        assert 'GENERAL' not in kw

    def test_empty_string(self):
        kw = _extract_keywords('')
        assert kw == set()


class TestAddAndRetrieve:
    def test_add_and_retrieve_similar_task(self, tmp_path):
        path = str(tmp_path / 'lessons.json')
        mem = EpisodicMemory(path)
        mem.add_lesson(
            task='Turn on Bold Text in Accessibility',
            app='Settings',
            lesson='In Display & Text Size, Bold Text is below the fold — scroll down.',
            failure_type='timeout',
            history_summary='scrolled up 3x; never found toggle',
        )
        result = mem.retrieve('Enable Bold Text in Accessibility settings', app='Settings')
        assert result is not None
        assert 'Bold Text' in result
        assert 'PAST LESSONS' in result

    def test_no_match_returns_none(self, tmp_path):
        path = str(tmp_path / 'lessons.json')
        mem = EpisodicMemory(path)
        mem.add_lesson(
            task='Turn on Bold Text in Accessibility',
            app='Settings',
            lesson='Scroll down in Display & Text Size.',
            failure_type='timeout',
            history_summary='test',
        )
        result = mem.retrieve('Order pizza from DoorDash', app='DoorDash')
        assert result is None

    def test_app_match_boosts_score(self, tmp_path):
        path = str(tmp_path / 'lessons.json')
        mem = EpisodicMemory(path)
        # Add a lesson with minimal keyword overlap but matching app
        mem.add_lesson(
            task='Change display brightness',
            app='Settings',
            lesson='Brightness slider is in Display & Brightness.',
            failure_type='stuck',
            history_summary='test',
        )
        # 'display' overlaps (+1), app matches (+2) = 3 >= threshold
        result = mem.retrieve('Adjust display settings', app='Settings')
        assert result is not None


class TestPersistence:
    def test_survives_across_instances(self, tmp_path):
        path = str(tmp_path / 'lessons.json')
        mem1 = EpisodicMemory(path)
        mem1.add_lesson(
            task='Test task',
            app='TestApp',
            lesson='A persistent lesson.',
            failure_type='stuck',
            history_summary='test',
        )
        # New instance, same path
        mem2 = EpisodicMemory(path)
        assert len(mem2.lessons) == 1
        assert mem2.lessons[0]['lesson'] == 'A persistent lesson.'

    def test_corrupted_file_loads_empty(self, tmp_path):
        path = str(tmp_path / 'lessons.json')
        with open(path, 'w') as f:
            f.write('not valid json{{{')
        mem = EpisodicMemory(path)
        assert mem.lessons == []


class TestPrune:
    def test_keeps_max_lessons(self, tmp_path):
        path = str(tmp_path / 'lessons.json')
        mem = EpisodicMemory(path)
        for i in range(60):
            mem.add_lesson(
                task=f'Task number {i}',
                app='Settings',
                lesson=f'Lesson {i}',
                failure_type='timeout',
                history_summary='test',
            )
        assert len(mem.lessons) <= 50


class TestHitCount:
    def test_retrieve_increments_hit_count(self, tmp_path):
        path = str(tmp_path / 'lessons.json')
        mem = EpisodicMemory(path)
        mem.add_lesson(
            task='Turn on Bold Text in Accessibility',
            app='Settings',
            lesson='Scroll down to find Bold Text.',
            failure_type='timeout',
            history_summary='test',
        )
        assert mem.lessons[0]['hit_count'] == 0
        mem.retrieve('Enable Bold Text Accessibility', app='Settings')
        assert mem.lessons[0]['hit_count'] == 1
        mem.retrieve('Bold Text Accessibility toggle', app='Settings')
        assert mem.lessons[0]['hit_count'] == 2


class TestReflectIntegration:
    """Requires GEMINI_API_KEY — skipped if not set."""

    @pytest.mark.skipif(
        not os.environ.get('GEMINI_API_KEY'),
        reason='GEMINI_API_KEY not set',
    )
    def test_planner_reflect(self):
        from core.planner import Planner
        planner = Planner()
        lesson = planner.reflect(
            task='Turn on Bold Text in Accessibility',
            history=[
                'Step 1: tap → Tapped [9] Accessibility',
                'Step 2: tap → Tapped [9] Display & Text Size',
                'Step 3: scroll up → Scrolled up',
                'Step 4: scroll up → Scrolled up',
                'Step 5: scroll up → Scrolled up',
                'Step 6: stuck — Cannot find Bold Text toggle',
            ],
            failure_type='stuck',
        )
        assert isinstance(lesson, str)
        assert len(lesson) > 10  # non-trivial response

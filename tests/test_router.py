"""Tests for TaskRouter — unit tests + optional live Gemini test."""

import os

import pytest

from core.router import TaskRouter


class TestParseRoute:
    """Unit tests for _parse_route — no API needed."""

    def _make_router(self):
        """Create a router with a mock planner (no API client needed for parsing)."""
        class FakePlanner:
            client = None
            model = None
        return TaskRouter(FakePlanner())

    def test_parse_settings_route(self):
        router = self._make_router()
        text = '{"category": "settings", "apps": ["Settings"], "multi_app": false, "comparison": false, "refined_task": "Turn on Dark Mode"}'
        route = router._parse_route(text, 'turn on dark mode')
        assert route['category'] == 'settings'
        assert len(route['apps']) == 1
        assert route['apps'][0]['name'] == 'Settings'
        assert route['multi_app'] is False

    def test_parse_comparison_route(self):
        router = self._make_router()
        text = '{"category": "rideshare", "apps": ["Uber", "Lyft"], "multi_app": true, "comparison": true, "refined_task": "Compare prices"}'
        route = router._parse_route(text, 'compare uber and lyft')
        assert route['comparison'] is True
        assert route['multi_app'] is True
        assert len(route['apps']) == 2

    def test_parse_malformed_falls_back(self):
        router = self._make_router()
        route = router._parse_route('not json at all', 'original task')
        assert route['category'] == 'general'
        assert route['apps'] == []
        assert route['refined_task'] == 'original task'

    def test_parse_unknown_app_skipped(self):
        router = self._make_router()
        text = '{"category": "general", "apps": ["NonExistentApp"], "multi_app": false, "comparison": false, "refined_task": "do something"}'
        route = router._parse_route(text, 'do something')
        assert route['apps'] == []

    def test_parse_json_in_markdown(self):
        router = self._make_router()
        text = '```json\n{"category": "settings", "apps": ["Settings"], "multi_app": false, "comparison": false, "refined_task": "Open General"}\n```'
        route = router._parse_route(text, 'open general')
        assert route['category'] == 'settings'


class TestConfigLoading:
    """Test that router loads registry from config."""

    def test_registry_loaded(self):
        class FakePlanner:
            client = None
            model = None
        router = TaskRouter(FakePlanner())
        assert 'settings' in router.registry
        assert any(a['name'] == 'Settings' for a in router.registry['settings'])


@pytest.mark.skipif(not os.environ.get('GEMINI_API_KEY'), reason='GEMINI_API_KEY not set')
class TestLiveRoute:
    """Live test — requires GEMINI_API_KEY."""

    def test_route_settings_task(self):
        from core.planner import Planner
        planner = Planner()
        router = TaskRouter(planner)
        route = router.route('Turn on Dark Mode in Settings')
        assert route['category'] in ('settings', 'general')
        assert isinstance(route['refined_task'], str)
        assert isinstance(route['apps'], list)

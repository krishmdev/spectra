"""Tests for PlanPreview — unit tests + optional live Gemini test."""

import os
from unittest.mock import patch

import pytest

from core.plan_preview import PlanPreview


class TestParseSteps:
    """Unit tests for _parse_steps — no API needed."""

    def test_numbered_list(self):
        text = '1. Open Settings\n2. Tap General\n3. Tap About'
        steps = PlanPreview._parse_steps(text)
        assert steps == ['Open Settings', 'Tap General', 'Tap About']

    def test_numbered_with_parens(self):
        text = '1) Open Uber\n2) Enter destination\n3) Check price'
        steps = PlanPreview._parse_steps(text)
        assert len(steps) == 3
        assert steps[0] == 'Open Uber'

    def test_no_numbers_fallback(self):
        text = 'Just open the app and check the price.'
        steps = PlanPreview._parse_steps(text)
        assert len(steps) == 1
        assert 'open the app' in steps[0]

    def test_mixed_content(self):
        text = 'Here is the plan:\n1. Open Settings\n2. Turn on Dark Mode\nDone!'
        steps = PlanPreview._parse_steps(text)
        assert len(steps) == 2


class TestPresentAndConfirm:
    """Mock input for interactive confirmation."""

    @patch('builtins.input', return_value='')
    def test_approve_with_enter(self, _mock):
        # PlanPreview needs a planner-like object — mock it
        class FakePlanner:
            client = None
            model = None
        pp = PlanPreview(FakePlanner())
        approved, plan = pp.present_and_confirm(['Step 1', 'Step 2'])
        assert approved is True
        assert plan == ['Step 1', 'Step 2']

    @patch('builtins.input', return_value='n')
    def test_reject(self, _mock):
        class FakePlanner:
            client = None
            model = None
        pp = PlanPreview(FakePlanner())
        approved, _ = pp.present_and_confirm(['Step 1'])
        assert approved is False


@pytest.mark.skipif(not os.environ.get('GEMINI_API_KEY'), reason='GEMINI_API_KEY not set')
class TestLiveGeneratePlan:
    """Live test — requires GEMINI_API_KEY."""

    def test_generate_plan_returns_steps(self):
        from core.planner import Planner
        planner = Planner()
        pp = PlanPreview(planner)
        steps = pp.generate_plan('Open Settings and turn on Dark Mode')
        assert isinstance(steps, list)
        assert len(steps) >= 1
        assert all(isinstance(s, str) for s in steps)

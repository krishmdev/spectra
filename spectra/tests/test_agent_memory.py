"""Unit tests for AgentMemory — no external dependencies."""

from core.memory import AgentMemory


class TestAgentMemory:

    def test_store_and_recall(self):
        m = AgentMemory()
        m.store('price', '$12.50')
        assert m.recall('price') == '$12.50'

    def test_recall_missing_key(self):
        m = AgentMemory()
        assert m.recall('nonexistent') is None

    def test_recall_all(self):
        m = AgentMemory()
        m.store('a', '1')
        m.store('b', '2')
        assert m.recall_all() == {'a': '1', 'b': '2'}

    def test_clear(self):
        m = AgentMemory()
        m.store('x', 'y')
        m.clear()
        assert m.recall('x') is None
        assert m.recall_all() == {}

    def test_format_empty(self):
        m = AgentMemory()
        assert m.format_for_prompt() == ''

    def test_format_populated(self):
        m = AgentMemory()
        m.store('uber_price', '$18.50')
        text = m.format_for_prompt()
        assert 'AGENT MEMORY:' in text
        assert 'uber_price' in text
        assert '$18.50' in text

    def test_overwrite(self):
        m = AgentMemory()
        m.store('price', '$10')
        m.store('price', '$15')
        assert m.recall('price') == '$15'

    def test_store_returns_confirmation(self):
        m = AgentMemory()
        result = m.store('key', 'val')
        assert 'Stored' in result
        assert 'key' in result

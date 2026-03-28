"""Live integration tests for core.tree_reader.TreeReader.

Requires a booted iOS simulator with WDA running on localhost:8100.
Run:  python -m pytest tests/test_tree_reader.py -v -s
"""

import pytest
from core.tree_reader import TreeReader


@pytest.fixture(scope='module')
def reader():
    return TreeReader('http://localhost:8100')


class TestSnapshotLive:
    """Tests that hit the real WDA server."""

    def test_returns_three_tuple(self, reader):
        result = reader.snapshot()
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_metadata_keys(self, reader):
        _, _, metadata = reader.snapshot()
        assert 'app_name' in metadata
        assert 'keyboard_visible' in metadata
        assert 'alert_present' in metadata
        assert 'perception_mode' in metadata
        assert 'screenshot_b64' in metadata

    def test_metadata_types(self, reader):
        _, _, metadata = reader.snapshot()
        assert isinstance(metadata['app_name'], str)
        assert isinstance(metadata['keyboard_visible'], bool)
        assert isinstance(metadata['alert_present'], bool)
        assert metadata['perception_mode'] in ('tree', 'screenshot')

    def test_tree_mode_has_refs(self, reader):
        """When in tree mode, ref_map should have >= 3 elements (by definition)."""
        compact, ref_map, metadata = reader.snapshot()
        if metadata['perception_mode'] == 'tree':
            assert len(ref_map) >= 3
            assert compact  # non-empty string
            assert metadata['screenshot_b64'] is None

    def test_screenshot_mode_has_b64(self, reader):
        """When in screenshot mode, screenshot_b64 should be a non-empty base64 string."""
        _, _, metadata = reader.snapshot()
        if metadata['perception_mode'] == 'screenshot':
            assert metadata['screenshot_b64']
            assert isinstance(metadata['screenshot_b64'], str)
            assert len(metadata['screenshot_b64']) > 100  # real PNG is large

    def test_print_snapshot(self, reader):
        """Print the full snapshot output for manual inspection."""
        compact, ref_map, metadata = reader.snapshot()
        print('\n=== Compact Tree ===')
        print(compact)
        print(f'\n=== Ref Map ({len(ref_map)} entries) ===')
        for ref, info in ref_map.items():
            print(f'  [{ref}] {info["label"][:40]} @ ({info["x"]},{info["y"]} {info["width"]}x{info["height"]})')
        print(f'\n=== Metadata ===')
        print(f'  app_name:         {metadata["app_name"]}')
        print(f'  keyboard_visible: {metadata["keyboard_visible"]}')
        print(f'  alert_present:    {metadata["alert_present"]}')
        print(f'  perception_mode:  {metadata["perception_mode"]}')
        has_screenshot = metadata["screenshot_b64"] is not None
        print(f'  screenshot_b64:   {"<" + str(len(metadata["screenshot_b64"])) + " chars>" if has_screenshot else "None"}')


class TestFallbackOnBadUrl:
    """TreeReader pointed at a dead URL should fall back to screenshot mode gracefully."""

    def test_bad_url_returns_screenshot_mode(self):
        bad_reader = TreeReader('http://localhost:19999')
        compact, ref_map, metadata = bad_reader.snapshot()
        assert metadata['perception_mode'] == 'screenshot'
        assert ref_map == {}
        assert 'screenshot mode' in compact.lower() or metadata.get('screenshot_b64') is not None

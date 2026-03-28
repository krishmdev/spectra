"""Tests for core.tree_parser.parse_tree()."""

import pytest
from core.tree_parser import parse_tree


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wrap(inner_xml: str) -> str:
    """Wrap XML fragments in an Application root element."""
    return (
        '<XCUIElementTypeApplication name="TestApp" '
        'visible="true" x="0" y="0" width="390" height="844">'
        f'{inner_xml}'
        '</XCUIElementTypeApplication>'
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBasicSettingsScreen:
    """Mirrors the PRD example output for a Settings-like screen."""

    XML = _wrap('''
        <XCUIElementTypeNavigationBar name="Settings" visible="true"
            x="0" y="44" width="390" height="44">
        </XCUIElementTypeNavigationBar>
        <XCUIElementTypeTable visible="true" x="0" y="88" width="390" height="700">
            <XCUIElementTypeCell name="Wi-Fi" value="Connected" visible="true"
                x="0" y="100" width="390" height="44">
            </XCUIElementTypeCell>
            <XCUIElementTypeCell name="Bluetooth" value="On" visible="true"
                x="0" y="144" width="390" height="44">
            </XCUIElementTypeCell>
            <XCUIElementTypeCell name="General" visible="true"
                x="0" y="188" width="390" height="44">
            </XCUIElementTypeCell>
            <XCUIElementTypeSwitch name="Airplane Mode" value="0" enabled="false"
                visible="true" x="320" y="232" width="51" height="31">
            </XCUIElementTypeSwitch>
        </XCUIElementTypeTable>
    ''')

    def test_output_format(self):
        text, ref_map = parse_tree(self.XML)
        lines = text.strip().split('\n')
        assert lines[0] == '[1] NavBar "Settings"'
        assert lines[1] == '[2] Cell "Wi-Fi" \u2192 "Connected"'
        assert lines[2] == '[3] Cell "Bluetooth" \u2192 "On"'
        assert lines[3] == '[4] Cell "General"'
        assert lines[4] == '[5] Switch "Airplane Mode" \u2192 "0" [disabled]'

    def test_sequential_refs(self):
        _, ref_map = parse_tree(self.XML)
        assert list(ref_map.keys()) == [1, 2, 3, 4, 5]

    def test_ref_map_count(self):
        _, ref_map = parse_tree(self.XML)
        assert len(ref_map) == 5


class TestSkipStatusBar:
    """StatusBar and its children should be completely absent."""

    XML = _wrap('''
        <XCUIElementTypeStatusBar visible="true" x="0" y="0" width="390" height="44">
            <XCUIElementTypeButton name="Signal" visible="true"
                x="10" y="5" width="30" height="20">
            </XCUIElementTypeButton>
        </XCUIElementTypeStatusBar>
        <XCUIElementTypeButton name="RealButton" visible="true"
            x="100" y="100" width="80" height="40">
        </XCUIElementTypeButton>
    ''')

    def test_statusbar_skipped(self):
        text, ref_map = parse_tree(self.XML)
        assert 'Signal' not in text
        assert 'StatusBar' not in text
        assert len(ref_map) == 1
        assert ref_map[1]['label'] == 'RealButton'


class TestSkipInvisible:
    """Invisible KEPT elements (Button, Cell, etc.) should be excluded.
    Invisible transparent containers still recurse — their visible children surface.
    """

    XML = _wrap('''
        <XCUIElementTypeButton name="Visible" visible="true"
            x="0" y="0" width="80" height="40">
        </XCUIElementTypeButton>
        <XCUIElementTypeOther visible="false" x="0" y="50" width="390" height="100">
            <XCUIElementTypeButton name="Hidden" visible="false"
                x="10" y="60" width="80" height="40">
            </XCUIElementTypeButton>
        </XCUIElementTypeOther>
    ''')

    def test_invisible_kept_elements_skipped(self):
        text, ref_map = parse_tree(self.XML)
        assert 'Hidden' not in text
        assert len(ref_map) == 1
        assert ref_map[1]['label'] == 'Visible'


class TestInvisibleContainerWithVisibleChildren:
    """Mirrors the real WDA pattern: invisible container, visible interactive children.

    WDA marks layout wrappers (CollectionView, Window, Other) as visible="false"
    even when their children are fully visible. We must always recurse through them.
    """

    XML = _wrap('''
        <XCUIElementTypeOther visible="false" x="0" y="0" width="390" height="844">
            <XCUIElementTypeButton name="DeepVisible" visible="true"
                x="10" y="100" width="80" height="40">
            </XCUIElementTypeButton>
        </XCUIElementTypeOther>
    ''')

    def test_visible_child_surfaces(self):
        text, ref_map = parse_tree(self.XML)
        assert 'DeepVisible' in text
        assert len(ref_map) == 1
        assert ref_map[1]['label'] == 'DeepVisible'


class TestTransparentContainers:
    """Unlabeled Other/Group containers don't emit but their children do."""

    XML = _wrap('''
        <XCUIElementTypeOther visible="true" x="0" y="0" width="390" height="844">
            <XCUIElementTypeGroup visible="true" x="0" y="0" width="390" height="200">
                <XCUIElementTypeButton name="DeepButton" visible="true"
                    x="20" y="20" width="100" height="40">
                </XCUIElementTypeButton>
            </XCUIElementTypeGroup>
        </XCUIElementTypeOther>
    ''')

    def test_containers_transparent(self):
        text, ref_map = parse_tree(self.XML)
        assert 'Other' not in text
        assert 'Group' not in text
        assert 'DeepButton' in text
        assert len(ref_map) == 1


class TestValueDiffersFromLabel:
    """Value is only shown when it differs from the label/name."""

    XML = _wrap('''
        <XCUIElementTypeCell name="Volume" value="Volume" visible="true"
            x="0" y="0" width="390" height="44">
        </XCUIElementTypeCell>
        <XCUIElementTypeCell name="Brightness" value="75%" visible="true"
            x="0" y="44" width="390" height="44">
        </XCUIElementTypeCell>
    ''')

    def test_same_value_hidden(self):
        text, _ = parse_tree(self.XML)
        lines = text.strip().split('\n')
        # Volume == Volume, so no arrow
        assert '\u2192' not in lines[0]
        # Brightness != 75%, so arrow shown
        assert '\u2192 "75%"' in lines[1]


class TestDisabledAndSelectedFlags:

    XML = _wrap('''
        <XCUIElementTypeButton name="DisabledBtn" enabled="false" visible="true"
            x="0" y="0" width="80" height="40">
        </XCUIElementTypeButton>
        <XCUIElementTypeTab name="Home" selected="true" visible="true"
            x="0" y="800" width="97" height="44">
        </XCUIElementTypeTab>
        <XCUIElementTypeButton name="Normal" visible="true"
            x="100" y="0" width="80" height="40">
        </XCUIElementTypeButton>
    ''')

    def test_flags(self):
        text, _ = parse_tree(self.XML)
        lines = text.strip().split('\n')
        assert '[disabled]' in lines[0]
        assert '[selected]' in lines[1]
        # Normal button has no flags
        assert '[' not in lines[2] or lines[2].index('[') == lines[2].index('[3]')


class TestRefMapStructure:
    """ref_map entries have all required keys with correct types."""

    XML = _wrap('''
        <XCUIElementTypeButton name="OK" value="" visible="true"
            x="150" y="400" width="90" height="44">
        </XCUIElementTypeButton>
    ''')

    def test_keys_and_types(self):
        _, ref_map = parse_tree(self.XML)
        entry = ref_map[1]
        assert entry['type'] == 'XCUIElementTypeButton'
        assert entry['label'] == 'OK'
        assert isinstance(entry['x'], int)
        assert isinstance(entry['y'], int)
        assert isinstance(entry['width'], int)
        assert isinstance(entry['height'], int)
        assert entry['x'] == 150
        assert entry['y'] == 400
        assert entry['width'] == 90
        assert entry['height'] == 44


class TestEmptyXml:
    """Graceful handling of an app with no interesting children."""

    XML = _wrap('')

    def test_empty(self):
        text, ref_map = parse_tree(self.XML)
        assert text == ''
        assert ref_map == {}


class TestIndentationInsideStructural:
    """Children of structural elements (NavBar, Alert) are indented."""

    XML = _wrap('''
        <XCUIElementTypeAlert name="Delete?" visible="true"
            x="50" y="300" width="290" height="200">
            <XCUIElementTypeButton name="Cancel" visible="true"
                x="60" y="450" width="120" height="44">
            </XCUIElementTypeButton>
            <XCUIElementTypeButton name="Delete" visible="true"
                x="190" y="450" width="120" height="44">
            </XCUIElementTypeButton>
        </XCUIElementTypeAlert>
    ''')

    def test_children_indented(self):
        text, _ = parse_tree(self.XML)
        lines = text.strip().split('\n')
        assert lines[0] == '[1] Alert "Delete?"'
        assert lines[1] == '  [2] Button "Cancel"'
        assert lines[2] == '  [3] Button "Delete"'


class TestKeyboardSkipped:
    """Keyboard and Key elements are entirely skipped."""

    XML = _wrap('''
        <XCUIElementTypeTextField name="Search" visible="true"
            x="20" y="100" width="350" height="40">
        </XCUIElementTypeTextField>
        <XCUIElementTypeKeyboard visible="true" x="0" y="500" width="390" height="300">
            <XCUIElementTypeKey name="A" visible="true"
                x="10" y="520" width="35" height="42">
            </XCUIElementTypeKey>
        </XCUIElementTypeKeyboard>
    ''')

    def test_keyboard_absent(self):
        text, ref_map = parse_tree(self.XML)
        assert 'Keyboard' not in text
        assert 'Key' not in text.split('"')  # avoid matching inside quoted labels
        assert len(ref_map) == 1
        assert ref_map[1]['label'] == 'Search'

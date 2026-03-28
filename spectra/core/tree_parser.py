"""Convert raw WDA accessibility XML into compact ref-tagged text for LLM consumption."""

import xml.etree.ElementTree as ET

TYPE_SHORT_NAMES = {
    'XCUIElementTypeButton': 'Button',
    'XCUIElementTypeStaticText': 'Text',
    'XCUIElementTypeTextField': 'TextField',
    'XCUIElementTypeSecureTextField': 'SecureField',
    'XCUIElementTypeTable': 'Table',
    'XCUIElementTypeCell': 'Cell',
    'XCUIElementTypeNavigationBar': 'NavBar',
    'XCUIElementTypeTabBar': 'TabBar',
    'XCUIElementTypeSwitch': 'Switch',
    'XCUIElementTypeSlider': 'Slider',
    'XCUIElementTypeAlert': 'Alert',
    'XCUIElementTypeSheet': 'Sheet',
    'XCUIElementTypeSearchField': 'SearchField',
    'XCUIElementTypeImage': 'Image',
    'XCUIElementTypeLink': 'Link',
    'XCUIElementTypeScrollView': 'ScrollView',
    'XCUIElementTypeTextView': 'TextArea',
    'XCUIElementTypeTab': 'Tab',
    'XCUIElementTypeSegmentedControl': 'SegmentedControl',
    'XCUIElementTypeIcon': 'Icon',
}

# Skip entire subtree — no recursion into children
_SKIP_TYPES = {'StatusBar', 'ScrollBar', 'Key', 'Keyboard', 'PageIndicator'}

# Emit and assign a ref number
_INTERACTIVE_TYPES = {
    'Button', 'TextField', 'SecureTextField', 'SearchField', 'TextArea',
    'Switch', 'Slider', 'Link', 'Cell', 'Tab', 'SegmentedControl', 'Icon',
}
_STRUCTURAL_TYPES = {'NavigationBar', 'TabBar', 'Alert', 'Sheet'}

_KEEP_TYPES = _INTERACTIVE_TYPES | _STRUCTURAL_TYPES


def _short_type(tag: str) -> str:
    """Strip XCUIElementType prefix to get the bare type name."""
    prefix = 'XCUIElementType'
    if tag.startswith(prefix):
        return tag[len(prefix):]
    return tag


def _display_name(tag: str) -> str:
    """Get the human-readable short name for display."""
    return TYPE_SHORT_NAMES.get(tag, _short_type(tag))


def _walk(element, depth, counter, lines, ref_map):
    tag = element.tag
    short = _short_type(tag)

    # Skip entire subtree for noise types (no recursion into children)
    if short in _SKIP_TYPES:
        return

    keep = short in _KEEP_TYPES

    # Only suppress invisible KEPT elements. Transparent containers (Other, Window,
    # CollectionView, etc.) may be marked visible="false" by WDA even when their
    # children are visible, so we always recurse through them.
    if element.get('visible') == 'false' and keep:
        return

    if keep:
        counter[0] += 1
        ref = counter[0]

        # Label: prefer human-readable 'label' attr, fall back to programmatic 'name'
        label = element.get('label') or element.get('name') or ''
        value = element.get('value') or ''
        enabled = element.get('enabled', 'true')
        selected = element.get('selected', 'false')

        # Build display line
        indent = '  ' * depth
        display = _display_name(tag)
        line = f'{indent}[{ref}] {display}'
        if label:
            line += f' "{label}"'
        if value and value != label:
            line += f' \u2192 "{value}"'

        flags = []
        if enabled == 'false':
            flags.append('disabled')
        if selected == 'true':
            flags.append('selected')
        if flags:
            line += ' [' + ', '.join(flags) + ']'

        lines.append(line)

        # Build ref_map entry
        ref_map[ref] = {
            'type': tag,
            'label': label,
            'value': value,
            'x': int(element.get('x', 0)),
            'y': int(element.get('y', 0)),
            'width': int(element.get('width', 0)),
            'height': int(element.get('height', 0)),
        }

        # Recurse children with increased depth
        child_depth = depth + 1
    else:
        # Transparent: recurse children at same depth
        child_depth = depth

    for child in element:
        _walk(child, child_depth, counter, lines, ref_map)


def parse_tree(xml_string: str) -> tuple[str, dict]:
    """Parse WDA XML into compact ref-tagged text and a ref map.

    Args:
        xml_string: Raw XML from WDA source()

    Returns:
        compact_text: Human-readable ref-tagged text
        ref_map: Dict mapping ref number -> {type, label, value, x, y, width, height}
    """
    root = ET.fromstring(xml_string)
    lines = []
    ref_map = {}
    counter = [0]

    # The root element is typically XCUIElementTypeApplication — treat it as transparent
    for child in root:
        _walk(child, 0, counter, lines, ref_map)

    return '\n'.join(lines), ref_map

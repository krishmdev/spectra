"""Element tree for the mock device, rendered as WDA-style accessibility XML.

The XML mimics what WebDriverAgent's /source returns for a native app: an
XCUIElementTypeApplication root, nested Window/Other containers, a separate
status bar window, and a keyboard subtree when a text field has focus. It is
generated, not captured from a real simulator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable
from xml.sax.saxutils import quoteattr

SCREEN_W = 402
SCREEN_H = 874

# Keys on the default English keyboard, in WDA order. The agent types through
# /wda/keys, so these only exist to make the tree as noisy as the real thing.
KEYBOARD_KEYS = (
    list('qwertyuiop') + list('asdfghjkl') + ['shift'] + list('zxcvbnm')
    + ['delete', 'more', 'Emoji', 'space', 'Return']
)


@dataclass
class El:
    type: str
    label: str = ''
    name: str = ''
    value: str | None = None
    frame: tuple[int, int, int, int] = (0, 0, 0, 0)
    enabled: bool = True
    visible: bool = True
    selected: bool = False
    accessible: bool | None = None
    children: list[El] = field(default_factory=list)
    on_tap: Callable[[], None] | None = None

    def add(self, *kids: El) -> El:
        self.children.extend(kids)
        return self

    def contains(self, x: float, y: float) -> bool:
        fx, fy, fw, fh = self.frame
        return fx <= x <= fx + fw and fy <= y <= fy + fh

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


def _attrs(el: El, index: int) -> str:
    x, y, w, h = el.frame
    tag = 'XCUIElementType' + el.type
    parts = [f'type="{tag}"']
    if el.name or el.label:
        parts.append(f'name={quoteattr(el.name or el.label)}')
    if el.label:
        parts.append(f'label={quoteattr(el.label)}')
    if el.value is not None:
        parts.append(f'value={quoteattr(el.value)}')
    accessible = el.accessible if el.accessible is not None else el.type not in _CONTAINERS
    parts += [
        f'enabled="{str(el.enabled).lower()}"',
        f'visible="{str(el.visible).lower()}"',
        f'accessible="{str(accessible).lower()}"',
    ]
    if el.selected:
        parts.append('selected="true"')
    parts += [f'x="{x}"', f'y="{y}"', f'width="{w}"', f'height="{h}"', f'index="{index}"']
    return ' '.join(parts)


_CONTAINERS = {'Other', 'Window', 'Table', 'CollectionView', 'ScrollView', 'StatusBar', 'Keyboard'}


def to_xml(el: El, depth: int = 0, index: int = 0) -> str:
    pad = '  ' * depth
    tag = 'XCUIElementType' + el.type
    if not el.children:
        return f'{pad}<{tag} {_attrs(el, index)}/>'
    inner = '\n'.join(to_xml(c, depth + 1, i) for i, c in enumerate(el.children))
    return f'{pad}<{tag} {_attrs(el, index)}>\n{inner}\n{pad}</{tag}>'


def status_bar_window() -> El:
    bar = El('StatusBar', frame=(0, 0, SCREEN_W, 54))
    left = El('Other', frame=(0, 0, 150, 54)).add(
        El('Other', frame=(30, 14, 70, 26)).add(
            El('StaticText', label='9:41', value='9:41', frame=(44, 18, 42, 20))))
    right = El('Other', frame=(250, 0, 152, 54)).add(
        El('Other', label='3 of 3 bars, Cellular', frame=(282, 20, 20, 12)),
        El('Other', label='Wi-Fi, 3 of 3 bars', frame=(306, 20, 18, 12)),
        El('Other', label='100% battery power', frame=(330, 18, 30, 14)),
    )
    bar.add(El('Other', frame=(0, 0, SCREEN_W, 54)).add(left, right))
    return El('Window', frame=(0, 0, SCREEN_W, SCREEN_H)).add(
        El('Other', frame=(0, 0, SCREEN_W, SCREEN_H)).add(bar))


def keyboard() -> El:
    kb = El('Keyboard', frame=(0, 540, SCREEN_W, 334))
    rows = El('Other', frame=(0, 540, SCREEN_W, 300))
    for i, k in enumerate(KEYBOARD_KEYS):
        col, row = i % 10, i // 10
        rows.add(El('Key', label=k, frame=(4 + col * 39, 552 + row * 56, 36, 46)))
    kb.add(rows)
    return El('Other', frame=(0, 540, SCREEN_W, 334)).add(kb)


def app_root(app_name: str, content: list[El], with_keyboard: bool = False,
             overlay: El | None = None) -> El:
    """Wrap screen content the way UIKit apps show up in WDA's tree."""
    main = El('Window', frame=(0, 0, SCREEN_W, SCREEN_H)).add(
        El('Other', frame=(0, 0, SCREEN_W, SCREEN_H)).add(
            El('Other', frame=(0, 0, SCREEN_W, SCREEN_H)).add(
                El('Other', frame=(0, 0, SCREEN_W, SCREEN_H)).add(*content))))
    windows = [main]
    if with_keyboard:
        windows.append(El('Window', frame=(0, 0, SCREEN_W, SCREEN_H)).add(keyboard()))
    if overlay is not None:
        windows.append(El('Window', frame=(0, 0, SCREEN_W, SCREEN_H)).add(
            El('Other', frame=(0, 0, SCREEN_W, SCREEN_H)).add(overlay)))
    windows.append(status_bar_window())
    return El('Application', label=app_name, name=app_name,
              frame=(0, 0, SCREEN_W, SCREEN_H), accessible=False).add(*windows)


def render(root: El) -> str:
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + to_xml(root)


def hit_test(root: El, x: float, y: float, modal: El | None = None) -> El | None:
    """Return the last-drawn tappable element under (x, y).

    When `modal` is set (an alert), only elements inside it can be hit.
    """
    scope = modal if modal is not None else root
    hit = None
    for el in scope.walk():
        if el.on_tap is not None and el.visible and el.enabled and el.contains(x, y):
            hit = el
    return hit

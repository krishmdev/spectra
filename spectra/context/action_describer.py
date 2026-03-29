"""Diff two consecutive accessibility tree snapshots and produce a
short natural-language description of what the user did.

Heuristics (no LLM call — must be fast):
- New screen / app switch  → "Opened <app>"
- Search field gained text  → "Searched for '<text>' in <app>"
- New prominent label appeared (navigation) → "Navigated to '<label>' in <app>"
- Button/link that was in old tree is gone + screen changed → "Tapped '<label>'"
- Text field value changed → "Typed '<text>'"
- Scroll position shifted significantly → "Scrolled in <app>"
"""
from typing import Optional, Tuple


def describe_transition(prev_frame: dict, curr_frame: dict) -> Optional[str]:
    """Return a one-line NL action, or None if nothing meaningful changed."""
    prev_app = _app_short(prev_frame.get('app', ''))
    curr_app = _app_short(curr_frame.get('app', ''))
    prev_labels = _label_set(prev_frame.get('ref_map', {}))
    curr_labels = _label_set(curr_frame.get('ref_map', {}))
    prev_texts = _text_values(prev_frame.get('ref_map', {}))
    curr_texts = _text_values(curr_frame.get('ref_map', {}))

    # App switch
    if prev_app != curr_app and curr_app:
        return f"Opened {curr_app}"

    # Text input: a text field/search field gained new value
    new_typed = _new_text_input(prev_frame.get('ref_map', {}), curr_frame.get('ref_map', {}))
    if new_typed:
        field_type, text = new_typed
        if 'search' in field_type.lower():
            return f"Searched for '{text}' in {curr_app}"
        return f"Typed '{text}' in {curr_app}"

    # Disappeared interactive element (button/link tap)
    disappeared = prev_labels - curr_labels
    appeared = curr_labels - prev_labels
    if disappeared and appeared:
        # The user likely tapped something from the old screen and landed on a new screen
        tapped = _best_tap_candidate(prev_frame.get('ref_map', {}), disappeared)
        destination = _best_destination(curr_frame.get('ref_map', {}), appeared)
        if tapped and destination:
            return f"Tapped '{tapped}' and navigated to '{destination}' in {curr_app}"
        if tapped:
            return f"Tapped '{tapped}' in {curr_app}"

    # Significant new labels only (scroll or navigation)
    if len(appeared) > 3 and len(disappeared) > 3:
        return f"Scrolled in {curr_app}"

    if appeared and not disappeared:
        dest = _best_destination(curr_frame.get('ref_map', {}), appeared)
        if dest:
            return f"Navigated to '{dest}' in {curr_app}"

    # Nothing meaningful
    return None


def _app_short(bundle_id: str) -> str:
    if not bundle_id:
        return ''
    return bundle_id.split('.')[-1]


def _label_set(ref_map: dict) -> set[str]:
    labels = set()
    for el in ref_map.values():
        if isinstance(el, dict):
            lbl = el.get('label', '').strip()
            if lbl:
                labels.add(lbl)
    return labels


def _text_values(ref_map: dict) -> dict[str, str]:
    """Map label -> value for text input fields."""
    result = {}
    for el in ref_map.values():
        if isinstance(el, dict):
            t = el.get('type', '')
            if 'TextField' in t or 'SearchField' in t or 'TextArea' in t:
                result[el.get('label', '')] = el.get('value', '') or ''
    return result


def _new_text_input(prev_map: dict, curr_map: dict) -> Optional[Tuple[str, str]]:
    """Detect if a text/search field gained new content."""
    for el in curr_map.values():
        if not isinstance(el, dict):
            continue
        t = el.get('type', '')
        if 'TextField' not in t and 'SearchField' not in t and 'TextArea' not in t:
            continue
        val = (el.get('value', '') or '').strip()
        if not val:
            continue
        label = el.get('label', '')
        # Check if same field existed before with different/empty value
        for prev_el in prev_map.values():
            if not isinstance(prev_el, dict):
                continue
            if prev_el.get('label') == label and prev_el.get('type') == t:
                prev_val = (prev_el.get('value', '') or '').strip()
                if prev_val != val and len(val) > len(prev_val):
                    return (t, val)
        # Field didn't exist before but has content now
        return (t, val)
    return None


def _best_tap_candidate(ref_map: dict, disappeared_labels: set) -> Optional[str]:
    """Pick the most likely tapped element from disappeared labels."""
    candidates = []
    for el in ref_map.values():
        if not isinstance(el, dict):
            continue
        lbl = el.get('label', '').strip()
        if lbl not in disappeared_labels:
            continue
        t = el.get('type', '')
        # Prefer buttons and links
        if 'Button' in t or 'Link' in t:
            candidates.insert(0, lbl)
        elif 'Cell' in t or 'Tab' in t:
            candidates.append(lbl)
    return candidates[0] if candidates else None


def _best_destination(ref_map: dict, appeared_labels: set) -> Optional[str]:
    """Pick the most descriptive new label as the navigation destination."""
    candidates = []
    for el in ref_map.values():
        if not isinstance(el, dict):
            continue
        lbl = el.get('label', '').strip()
        if lbl not in appeared_labels:
            continue
        t = el.get('type', '')
        # Prefer nav bar titles, static text headers
        if 'NavBar' in t or 'NavigationBar' in t:
            candidates.insert(0, lbl)
        elif 'StaticText' in t and len(lbl) > 3:
            candidates.append(lbl)
    return candidates[0] if candidates else None

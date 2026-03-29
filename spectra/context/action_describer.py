"""Diff two consecutive accessibility tree snapshots and produce a
short natural-language description of what the user did.

Actions are produced in a semi-canonical form:
  "Opened Maps"
  "Searched 'Brown University' in Safari"
  "Tapped 'Directions' in Maps"
  "Navigated to 'Brown University' in Maps"
  "Typed 'meeting tomorrow' in Calendar"
  "Scrolled in Safari"

The format is kept stable across runs so sequence matching works reliably.
"""
from typing import Optional, Tuple


def describe_transition(prev_frame: dict, curr_frame: dict) -> Optional[str]:
    """Return a one-line NL action, or None if nothing meaningful changed."""
    prev_app = _app_short(prev_frame.get('app', ''))
    curr_app = _app_short(curr_frame.get('app', ''))
    prev_map = prev_frame.get('ref_map', {})
    curr_map = curr_frame.get('ref_map', {})
    prev_labels = _label_set(prev_map)
    curr_labels = _label_set(curr_map)

    # App switch
    if prev_app != curr_app and curr_app:
        return f"Opened {curr_app}"

    # Text input: a text field/search field gained new value
    new_typed = _new_text_input(prev_map, curr_map)
    if new_typed:
        field_type, text = new_typed
        # Normalize: strip trailing whitespace, lowercase check for search
        text = text.strip()
        if not text:
            return None
        if 'search' in field_type.lower():
            return f"Searched '{text}' in {curr_app}"
        return f"Typed '{text}' in {curr_app}"

    disappeared = prev_labels - curr_labels
    appeared = curr_labels - prev_labels

    # URL bar change in Safari/browser — detect page navigation
    prev_url = _get_url_field(prev_map)
    curr_url = _get_url_field(curr_map)
    if curr_url and prev_url != curr_url:
        return f"Visited '{curr_url}' in {curr_app}"

    # Significant screen change — user tapped something
    if disappeared and appeared:
        tapped = _best_tap_candidate(prev_map, disappeared)
        destination = _best_destination(curr_map, appeared)
        if tapped and destination:
            return f"Tapped '{tapped}' in {curr_app}"
        if tapped:
            return f"Tapped '{tapped}' in {curr_app}"
        if destination:
            return f"Navigated to '{destination}' in {curr_app}"

    # Major screen change — almost everything replaced (page navigation)
    if len(appeared) > 5 and len(disappeared) > 5:
        # Check if there's a clear new title/heading
        dest = _best_destination(curr_map, appeared)
        if dest:
            return f"Navigated to '{dest}' in {curr_app}"
        return f"Scrolled in {curr_app}"

    # New content appeared without anything disappearing
    if appeared and not disappeared:
        dest = _best_destination(curr_map, appeared)
        if dest:
            return f"Navigated to '{dest}' in {curr_app}"

    return None


def normalize_action(action: str) -> str:
    """Reduce an action string to a canonical form for stable matching.

    Examples:
        "Searched 'Brown University' in Safari"  → "searched:safari:brown university"
        "Opened Maps"                             → "opened:maps:"
        "Tapped 'Directions' in Maps"             → "tapped:maps:directions"
        "Scrolled in Safari"                      → "scrolled:safari:"
    """
    a = action.strip()
    verb = ''
    app = ''
    entity = ''

    # Extract verb (first word)
    parts = a.split(' ', 1)
    verb = parts[0].lower().rstrip("'")

    rest = parts[1] if len(parts) > 1 else ''

    # Extract " in <App>" from the end
    in_idx = rest.rfind(' in ')
    if in_idx >= 0:
        app = rest[in_idx + 4:].strip().lower()
        rest = rest[:in_idx].strip()
    elif verb == 'opened':
        app = rest.strip().lower()
        rest = ''

    # Extract entity from quotes
    if "'" in rest:
        start = rest.find("'")
        end = rest.rfind("'")
        if start != end:
            entity = rest[start+1:end].strip().lower()
    elif rest:
        entity = rest.strip().lower()

    return f"{verb}:{app}:{entity}"


def abstract_action(action: str) -> str:
    """Replace the entity in a normalized action with {X} placeholder.

    Examples:
        "searched:safari:brown university"  → "searched:safari:{X}"
        "opened:maps:"                       → "opened:maps:"
        "tapped:maps:directions"             → "tapped:maps:directions"

    Only replaces entities that look like user-specific content (multi-word,
    or from search/type verbs). Single generic words like "directions" are kept.
    """
    norm = normalize_action(action) if ':' not in action else action
    parts = norm.split(':', 2)
    if len(parts) != 3:
        return norm

    verb, app, entity = parts

    # Verbs where the entity is always user-specific input
    if verb in ('searched', 'typed', 'visited') and entity:
        return f"{verb}:{app}:{{X}}"

    # Multi-word entities from navigation are likely user-specific
    if entity and len(entity.split()) >= 2:
        return f"{verb}:{app}:{{X}}"

    return norm


def extract_entity(action: str) -> str:
    """Pull the entity from a normalized action string.

    Example: "searched:safari:brown university" → "brown university"
    """
    norm = normalize_action(action) if ':' not in action else action
    parts = norm.split(':', 2)
    if len(parts) == 3:
        return parts[2]
    return ''


def _app_short(bundle_id: str) -> str:
    if not bundle_id:
        return ''
    return bundle_id.split('.')[-1]


def _label_set(ref_map: dict) -> set:
    labels = set()
    for el in ref_map.values():
        if isinstance(el, dict):
            lbl = el.get('label', '').strip()
            if lbl:
                labels.add(lbl)
    return labels


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
        for prev_el in prev_map.values():
            if not isinstance(prev_el, dict):
                continue
            if prev_el.get('label') == label and prev_el.get('type') == t:
                prev_val = (prev_el.get('value', '') or '').strip()
                if prev_val != val and len(val) > len(prev_val):
                    return (t, val)
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
        if 'Button' in t or 'Link' in t:
            candidates.insert(0, lbl)
        elif 'Cell' in t or 'Tab' in t:
            candidates.append(lbl)
    return candidates[0] if candidates else None


def _get_url_field(ref_map: dict) -> Optional[str]:
    """Extract URL/address bar content from a browser-like app."""
    for el in ref_map.values():
        if not isinstance(el, dict):
            continue
        t = el.get('type', '')
        lbl = (el.get('label', '') or '').lower()
        val = (el.get('value', '') or '').strip()
        # Safari/browser URL bar detection
        if ('TextField' in t or 'SearchField' in t) and val:
            if 'url' in lbl or 'address' in lbl or 'search or enter' in lbl or '.com' in val or '.org' in val or 'http' in val:
                return val
    return None


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
        if 'NavBar' in t or 'NavigationBar' in t:
            candidates.insert(0, lbl)
        elif 'StaticText' in t and len(lbl) > 3:
            candidates.append(lbl)
    return candidates[0] if candidates else None

"""Confidence-scored element matching for replay (the "self-healing locator").

Refs are regenerated on every snapshot, so replay has to find the recorded
target again in the live ref_map. Each candidate gets a score in [0, 1]:

    exact     same type and label (or same accessibility identifier)  0.97-1.0
    fuzzy     same type, similar label                                0.55-0.95
    position  same type, centre within 50px, label unrelated          0.30-0.50

Label similarity handles what actually changes between runs: case and
punctuation ("Display & Brightness" vs "Display and Brightness"), list cells
whose trailing parts change ("Mom, Call me when you land, Yesterday" vs
"Mom, You: On my way, 9:41 AM"), and small wording edits. Position only
breaks ties. If the two best candidates score within AMBIGUITY_MARGIN of each
other the match is marked ambiguous and its score is cut, so the replayer
asks the planner instead of guessing.

The exact -> fuzzy -> position tiers, MatchResult and the Confidence enum are
Akshay's design from the hackathon (57b3624). v0.2 extends it with a numeric
score, label normalisation, identifier matching and the ambiguity check; the
replayer uses the score to hand weak steps to the planner.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import Enum


class Confidence(Enum):
    HIGH = 'high'
    MEDIUM = 'medium'
    LOW = 'low'
    NONE = 'none'


@dataclass
class MatchResult:
    """Result of attempting to match a recorded target to a live ref_map entry."""
    ref: int | None
    confidence: Confidence
    match_type: str            # 'exact', 'fuzzy', 'position', 'none'
    detail: str
    score: float = 0.0
    ambiguous: bool = False


_POSITION_THRESHOLD = 50
AMBIGUITY_MARGIN = 0.05
_FUZZY_FLOOR = 0.6


def _norm(label: str) -> str:
    s = label.lower().replace('&', ' and ')
    s = re.sub(r'[‘’“”"\'`]', '', s)
    s = re.sub(r'[^a-z0-9$%.,:+-]+', ' ', s)
    return re.sub(r'\s+', ' ', s).strip()


def label_similarity(a: str, b: str) -> float:
    """1.0 for identical, ~0.9 for the same thing reworded, lower as they drift apart."""
    a, b = (a or '').strip(), (b or '').strip()
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    na, nb = _norm(a), _norm(b)
    if na == nb:
        return 0.95
    # List cells: "Name, preview, time". The first segment is the identity.
    ha, hb = na.split(',')[0].strip(), nb.split(',')[0].strip()
    if ',' in na and ',' in nb and ha and ha == hb:
        return 0.9
    ta, tb = set(na.replace(',', ' ').split()), set(nb.replace(',', ' ').split())
    jaccard = len(ta & tb) / len(ta | tb) if ta | tb else 0.0
    seq = SequenceMatcher(None, na, nb).ratio()
    contains = 0.85 if (na in nb or nb in na) and min(len(na), len(nb)) >= 3 else 0.0
    return max(jaccard, seq, contains) * 0.94


def _center(el: dict) -> tuple[float, float]:
    return el.get('x', 0) + el.get('width', 0) / 2, el.get('y', 0) + el.get('height', 0) / 2


def score_candidate(target: dict, el: dict) -> tuple[float, str]:
    if el.get('type') != target.get('type'):
        return 0.0, 'none'
    tx, ty = _center(target)
    ex, ey = _center(el)
    dist = math.hypot(ex - tx, ey - ty)
    near = max(0.0, 1.0 - dist / 400)   # tie-breaker only
    rec_id, el_id = target.get('identifier'), el.get('identifier')
    if rec_id and el_id and rec_id == el_id:
        return 0.97 + 0.03 * near, 'exact'
    sim = label_similarity(target.get('label', ''), el.get('label', ''))
    if sim == 1.0:
        return 0.97 + 0.03 * near, 'exact'
    if sim >= _FUZZY_FLOOR:
        return 0.5 + 0.43 * sim + 0.02 * near, 'fuzzy'
    if dist < _POSITION_THRESHOLD:
        return 0.3 + 0.2 * (1 - dist / _POSITION_THRESHOLD), 'position'
    return 0.0, 'none'


def _confidence(score: float) -> Confidence:
    if score >= 0.9:
        return Confidence.HIGH
    if score >= 0.55:
        return Confidence.MEDIUM
    if score > 0:
        return Confidence.LOW
    return Confidence.NONE


def match(target: dict, ref_map: dict) -> MatchResult:
    """Find the best matching element in *ref_map* for the recorded *target*."""
    if not target or not ref_map:
        return MatchResult(None, Confidence.NONE, 'none', 'No target or empty ref_map')

    scored = []
    for ref, el in ref_map.items():
        s, kind = score_candidate(target, el)
        if s > 0:
            scored.append((s, kind, ref, el))
    rec_label = (target.get('label') or '').strip()
    if not scored:
        cx, cy = _center(target)
        return MatchResult(None, Confidence.NONE, 'none',
                           f'No match for {target.get("type")} "{rec_label}" at ({cx:.0f},{cy:.0f})')

    scored.sort(key=lambda t: t[0], reverse=True)
    best_score, kind, ref, el = scored[0]
    ambiguous = (len(scored) > 1 and kind != 'exact'
                 and best_score - scored[1][0] < AMBIGUITY_MARGIN)
    if ambiguous:
        best_score -= 0.15
    detail = f'{kind} match ({best_score:.2f}): [{ref}] "{el.get("label", "")}" for "{rec_label}"'
    if ambiguous:
        detail += f' (ambiguous with [{scored[1][2]}] "{scored[1][3].get("label", "")}")'
    return MatchResult(ref, _confidence(best_score), kind, detail, round(best_score, 3), ambiguous)

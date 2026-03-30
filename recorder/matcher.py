"""Three-tier element matching for deterministic replay.

During replay, ref numbers are regenerated each snapshot so we cannot reuse
the original ref.  The matcher re-identifies the target element from the
current ref_map using the recorded target metadata.

Priority:
    1. Exact  — same label AND same type      → confidence HIGH
    2. Fuzzy  — substring label AND same type  → confidence MEDIUM
    3. Position — same type within 50px        → confidence LOW

If no tier matches, the step is marked as FAILED.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class Confidence(Enum):
    HIGH = 'high'
    MEDIUM = 'medium'
    LOW = 'low'
    NONE = 'none'


@dataclass
class MatchResult:
    """Result of attempting to match a recorded target to a live ref_map entry."""
    ref: int | None            # Matched ref number (None if no match)
    confidence: Confidence
    match_type: str            # 'exact', 'fuzzy', 'position', 'none'
    detail: str                # Human-readable explanation


# Maximum pixel distance for position-based matching
_POSITION_THRESHOLD = 50


def match(target: dict, ref_map: dict) -> MatchResult:
    """Find the best matching element in *ref_map* for the recorded *target*.

    Args:
        target: Recorded element metadata with keys:
            label, type, value, x, y, width, height
        ref_map: Current ref_map from TreeReader (ref → element dict).

    Returns:
        MatchResult with the best match (or confidence=NONE if unmatched).
    """
    if not target or not ref_map:
        return MatchResult(None, Confidence.NONE, 'none', 'No target or empty ref_map')

    rec_label = (target.get('label') or '').strip()
    rec_type = target.get('type', '')
    rec_cx = target.get('x', 0) + target.get('width', 0) / 2
    rec_cy = target.get('y', 0) + target.get('height', 0) / 2

    # ── Tier 1: Exact match (label AND type) ──
    for ref, el in ref_map.items():
        el_label = (el.get('label') or '').strip()
        if el.get('type') == rec_type and el_label == rec_label and rec_label:
            return MatchResult(
                ref, Confidence.HIGH, 'exact',
                f'Exact match: [{ref}] {rec_type} "{rec_label}"',
            )

    # ── Tier 2: Fuzzy match (substring label AND type) ──
    if rec_label:
        rec_lower = rec_label.lower()
        best_fuzzy: tuple[int | None, int] = (None, 0)  # (ref, match_length)
        for ref, el in ref_map.items():
            if el.get('type') != rec_type:
                continue
            el_label = (el.get('label') or '').strip().lower()
            if not el_label:
                continue
            # Check both directions: recorded ⊆ element OR element ⊆ recorded
            if rec_lower in el_label or el_label in rec_lower:
                match_len = min(len(rec_lower), len(el_label))
                if match_len > best_fuzzy[1]:
                    best_fuzzy = (ref, match_len)

        if best_fuzzy[0] is not None:
            ref = best_fuzzy[0]
            el = ref_map[ref]
            return MatchResult(
                ref, Confidence.MEDIUM, 'fuzzy',
                f'Fuzzy match: [{ref}] "{el.get("label")}" ≈ "{rec_label}"',
            )

    # ── Tier 3: Position match (same type within 50px of center) ──
    best_pos: tuple[int | None, float] = (None, float('inf'))
    for ref, el in ref_map.items():
        if el.get('type') != rec_type:
            continue
        cx = el.get('x', 0) + el.get('width', 0) / 2
        cy = el.get('y', 0) + el.get('height', 0) / 2
        dist = math.hypot(cx - rec_cx, cy - rec_cy)
        if dist < _POSITION_THRESHOLD and dist < best_pos[1]:
            best_pos = (ref, dist)

    if best_pos[0] is not None:
        ref = best_pos[0]
        el = ref_map[ref]
        return MatchResult(
            ref, Confidence.LOW, 'position',
            f'Position match: [{ref}] "{el.get("label", "")}" within {best_pos[1]:.0f}px',
        )

    # ── No match ──
    return MatchResult(
        None, Confidence.NONE, 'none',
        f'No match for {rec_type} "{rec_label}" at ({rec_cx:.0f},{rec_cy:.0f})',
    )

from __future__ import annotations
"""Detect action patterns as [initial_state → goal_state] pairs.

Workflows are derived directly from recorded actions — no LLM needed for
state extraction. The first half of a session's actions become the
initial_state, the second half become the goal_state.

When the observer detects the user doing something matching initial_state,
it suggests performing goal_state via the agent.
"""
import json
from context.action_log import ActionLog
from context.action_describer import normalize_action, abstract_action

MIN_SEQ_LEN = 2
MAX_SEQ_LEN = 10
SUGGESTION_COOLDOWN_S = 300
SESSION_GAP_S = 120
_NOISE_VERBS = frozenset(['scrolled'])


def _actions_to_state(actions: list[str]) -> str:
    """Convert a list of raw action strings into a readable state description.
    Groups consecutive actions in the same app and produces natural language.

    Example input:  ["Opened mobilesafari", "Typed 'fandango.com' in mobilesafari"]
    Example output: "Visited fandango.com in Safari"
    """
    if not actions:
        return ''

    # Collapse into (app, details) groups
    groups = []
    for a in actions:
        norm = normalize_action(a)
        parts = norm.split(':', 2)
        if len(parts) != 3:
            groups.append(a)
            continue
        verb, app, entity = parts
        app_display = app.replace('mobilesafari', 'Safari').replace('agent', 'Spectra').replace('springboard', 'Home')
        app_display = app_display.capitalize() if app_display else ''

        if verb == 'opened' and app_display:
            # Don't just say "Opened X" — skip if the next action provides more detail
            groups.append(f"Opened {app_display}")
        elif verb == 'searched' and entity:
            groups.append(f"Searched '{entity}' in {app_display}")
        elif verb == 'typed' and entity:
            groups.append(f"Typed '{entity}' in {app_display}")
        elif verb == 'tapped' and entity:
            groups.append(f"Tapped '{entity}' in {app_display}")
        elif verb == 'visited' and entity:
            groups.append(f"Visited {entity} in {app_display}")
        elif verb == 'navigated' and entity:
            groups.append(f"Navigated to '{entity}' in {app_display}")
        else:
            groups.append(a)

    # Deduplicate consecutive "Opened X" if followed by a more specific action in same app
    cleaned = []
    for i, g in enumerate(groups):
        if g.startswith('Opened ') and i + 1 < len(groups):
            next_g = groups[i + 1]
            app_name = g[len('Opened '):]
            if app_name.lower() in next_g.lower():
                continue  # skip the bare "Opened X" since the next action is more specific
        cleaned.append(g)

    if not cleaned:
        cleaned = groups

    return '; '.join(cleaned)


class SequenceDetector:
    def __init__(self, action_log: ActionLog):
        self.log = action_log

    def learn_sequences(self) -> int:
        """Scan action log for sessions. Split each session into
        initial_state (first half) and goal_state (second half),
        derived directly from the recorded actions."""
        actions = self.log.get_all()
        if len(actions) < MIN_SEQ_LEN:
            return 0

        actions = list(reversed(actions))  # chronological
        sessions = self._split_sessions(actions)

        existing = self.log.get_all_sequences()
        existing_abstract_keys = set()
        for seq in existing:
            abs_key = json.dumps([abstract_action(a) for a in seq['actions']])
            existing_abstract_keys.add(abs_key)

        new_count = 0

        for session in sessions:
            meaningful = [a for a in session
                         if normalize_action(a.action_nl).split(':')[0] not in _NOISE_VERBS]
            if len(meaningful) < MIN_SEQ_LEN:
                continue

            meaningful = meaningful[:MAX_SEQ_LEN]
            raw_actions = [a.action_nl for a in meaningful]
            abstract_actions = [abstract_action(a) for a in raw_actions]
            abs_key = json.dumps(abstract_actions)

            if abs_key in existing_abstract_keys:
                continue

            # Check backoff
            required = self.log.get_required_occurrences(raw_actions)
            if required > 1:
                occ = self._count_pattern_occurrences(sessions, abstract_actions)
                if occ < required:
                    continue

            # Split session: first half = initial_state, second half = goal_state
            split = len(raw_actions) // 2
            if split == 0:
                split = 1
            initial_actions = raw_actions[:split]
            goal_actions = raw_actions[split:]

            initial_state = _actions_to_state(initial_actions)
            goal_state = _actions_to_state(goal_actions)

            self.log.save_sequence(raw_actions, occurrence_count=1,
                                   initial_state=initial_state, goal_state=goal_state)
            existing_abstract_keys.add(abs_key)
            new_count += 1
            print(f"[SequenceDetector] Learned: [{initial_state}] → [{goal_state}]", flush=True)

        return new_count

    def check_for_suggestion(self):
        """Check if current actions match a known workflow's initial actions."""
        import time
        now = time.time()
        sequences = self.log.get_all_sequences()
        if not sequences:
            return None

        tail = self.log.get_tail(MAX_SEQ_LEN)
        if not tail:
            return None
        tail_abstract = [abstract_action(a.action_nl) for a in tail]

        best_match = None
        best_prefix_len = 0

        for seq in sequences:
            if seq.get('last_triggered_at'):
                if now - seq['last_triggered_at'] < SUGGESTION_COOLDOWN_S:
                    continue

            actions = seq['actions']
            if len(actions) < MIN_SEQ_LEN:
                continue

            actions_abstract = [abstract_action(a) for a in actions]

            # Match the initial half (prefix) of the raw actions
            split = len(actions) // 2
            if split == 0:
                split = 1

            for prefix_len in range(1, split + 1):
                prefix_abstract = actions_abstract[:prefix_len]
                if len(tail_abstract) < len(prefix_abstract):
                    continue

                recent_segment = tail_abstract[-len(prefix_abstract):]
                if self._pattern_match(recent_segment, prefix_abstract):
                    if prefix_len > best_prefix_len:
                        best_prefix_len = prefix_len
                        best_match = {
                            'sequence_id': seq['id'],
                            'prefix': actions[:prefix_len],
                            'next_action': seq.get('goal_state') or actions[-1],
                            'full_sequence': actions,
                            'occurrence_count': seq['occurrence_count'],
                            'initial_state': seq.get('initial_state'),
                            'goal_state': seq.get('goal_state'),
                        }

        return best_match

    def _split_sessions(self, actions) -> list:
        if not actions:
            return []
        sessions = [[actions[0]]]
        for i in range(1, len(actions)):
            gap = actions[i].timestamp - actions[i-1].timestamp
            if gap > SESSION_GAP_S:
                sessions.append([])
            sessions[-1].append(actions[i])
        return sessions

    def _count_pattern_occurrences(self, sessions, abstract_pattern) -> int:
        count = 0
        pat_len = len(abstract_pattern)
        for session in sessions:
            session_abs = [abstract_action(a.action_nl) for a in session]
            for i in range(len(session_abs) - pat_len + 1):
                if self._pattern_match(session_abs[i:i + pat_len], abstract_pattern):
                    count += 1
                    break
        return count

    def _pattern_match(self, actions, pattern) -> bool:
        if len(actions) != len(pattern):
            return False
        return all(self._abstract_matches(a, p) for a, p in zip(actions, pattern))

    @staticmethod
    def _abstract_matches(a: str, b: str) -> bool:
        pa = a.split(':', 2)
        pb = b.split(':', 2)
        if len(pa) != 3 or len(pb) != 3:
            return a == b
        v_a, app_a, ent_a = pa
        v_b, app_b, ent_b = pb
        if v_a != v_b:
            return False
        if app_a and app_b and app_a != app_b:
            return False
        if ent_a == '{X}' or ent_b == '{X}':
            return True
        if ent_a and ent_b:
            words_a = set(ent_a.split())
            words_b = set(ent_b.split())
            if words_a and words_b:
                overlap = len(words_a & words_b)
                if overlap / max(len(words_a), len(words_b)) < 0.5:
                    return False
        return True

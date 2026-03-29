from __future__ import annotations
"""Detect repeated action sequences and suggest the next action.

The detector maintains a table of known sequences. Each time a new action is
logged, it checks whether the recent tail of the action log matches any known
sequence prefix.  If so — and the sequence has been seen >= TRIGGER_THRESHOLD
times — it suggests the next action in that sequence.

Sequences are learned by scanning the full action log for repeated subsequences
of length >= MIN_SEQ_LEN.
"""
import json
from context.action_log import ActionLog

# How many times a sequence must be observed before triggering a suggestion
TRIGGER_THRESHOLD = 1

# Minimum number of actions in a meaningful sequence
MIN_SEQ_LEN = 2

# Maximum sequence length to look for
MAX_SEQ_LEN = 8

# Cooldown: don't re-suggest the same sequence within this many seconds
SUGGESTION_COOLDOWN_S = 300


class SequenceDetector:
    def __init__(self, action_log: ActionLog):
        self.log = action_log

    def learn_sequences(self) -> int:
        """Scan the full action log and discover repeated subsequences.
        Returns number of new sequences found."""
        actions = self.log.get_all()
        if len(actions) < MIN_SEQ_LEN:
            return 0

        nl_list = [a.action_nl for a in actions]
        # Reverse so newest first in the original, but we want chronological
        nl_list = list(reversed(nl_list))

        existing = self.log.get_all_sequences()
        existing_keys = set()
        existing_map = {}
        for seq in existing:
            key = json.dumps(seq['actions'])
            existing_keys.add(key)
            existing_map[key] = seq

        new_count = 0

        # Slide a window across the action list for each sequence length
        for seq_len in range(MIN_SEQ_LEN, min(MAX_SEQ_LEN + 1, len(nl_list))):
            # Count occurrences of each subsequence
            subseq_counts: dict[str, int] = {}
            for i in range(len(nl_list) - seq_len + 1):
                subseq = nl_list[i:i + seq_len]
                key = json.dumps(subseq)
                subseq_counts[key] = subseq_counts.get(key, 0) + 1

            for key, count in subseq_counts.items():
                if count < 2:
                    continue  # Need at least 2 occurrences to consider it a pattern
                if key in existing_keys:
                    # Update occurrence count
                    seq_info = existing_map[key]
                    if count > seq_info['occurrence_count']:
                        self.log.increment_sequence(seq_info['id'])
                else:
                    self.log.save_sequence(json.loads(key), occurrence_count=count)
                    existing_keys.add(key)
                    new_count += 1

        return new_count

    def check_for_suggestion(self) -> dict | None:
        """Check if the recent action tail matches a known sequence prefix.

        Returns dict with:
            - sequence_id: str
            - prefix: list[str]  (the matched prefix)
            - next_action: str   (the suggested next action)
            - full_sequence: list[str]
            - occurrence_count: int
        Or None if no suggestion.
        """
        import time
        now = time.time()
        sequences = self.log.get_all_sequences()
        if not sequences:
            return None

        # Get the recent tail of actions
        tail = self.log.get_tail(MAX_SEQ_LEN)
        if not tail:
            return None
        tail_nl = [a.action_nl for a in tail]

        best_match = None
        best_prefix_len = 0

        for seq in sequences:
            if seq['occurrence_count'] < TRIGGER_THRESHOLD:
                continue

            # Cooldown check
            if seq.get('last_triggered_at'):
                if now - seq['last_triggered_at'] < SUGGESTION_COOLDOWN_S:
                    continue

            actions = seq['actions']
            if len(actions) < MIN_SEQ_LEN:
                continue

            # Check if tail ends with a prefix of this sequence
            # Try progressively longer prefixes
            for prefix_len in range(MIN_SEQ_LEN - 1, len(actions)):
                prefix = actions[:prefix_len]
                if len(prefix) == 0:
                    continue
                # Does the tail end with this prefix?
                if len(tail_nl) >= len(prefix):
                    recent_segment = tail_nl[-len(prefix):]
                    if self._fuzzy_match(recent_segment, prefix):
                        if prefix_len > best_prefix_len:
                            best_prefix_len = prefix_len
                            best_match = {
                                'sequence_id': seq['id'],
                                'prefix': prefix,
                                'next_action': actions[prefix_len],
                                'full_sequence': actions,
                                'occurrence_count': seq['occurrence_count'],
                            }

        return best_match

    def _fuzzy_match(self, recent: list[str], prefix: list[str]) -> bool:
        """Check if two action lists match (exact string match for now)."""
        if len(recent) != len(prefix):
            return False
        return all(r == p for r, p in zip(recent, prefix))

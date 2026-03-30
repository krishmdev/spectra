from core.stuck_detector import StuckDetector


def test_same_label_with_different_refs_is_flagged():
    d = StuckDetector()
    # Refs shift every snapshot, so ref-based checks can't see this loop.
    for i, tree in enumerate(['a', 'b', 'c']):
        d.record(tree, 'tap', ref=10 + i, label='Time')
    warning = d.check()
    assert warning is not None
    assert '"time" 3 times' in warning


def test_different_labels_are_not_flagged():
    d = StuckDetector()
    for i, label in enumerate(['General', 'About', 'Name']):
        d.record(f'tree{i}', 'tap', ref=i, label=label)
    assert d.check() is None


def test_reset_clears_label_history():
    d = StuckDetector()
    for i in range(3):
        d.record(f't{i}', 'tap', ref=i, label='Time')
    d.reset()
    assert d.label_history == []
    assert d.check() is None

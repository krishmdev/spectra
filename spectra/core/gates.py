"""Confirmation gate — intercepts sensitive actions for user approval before execution."""

from core.router import load_config

# Only truly dangerous actions — money, bookings, purchases.
# Common actions like delete/remove/send are handled by task-intent matching.
_DEFAULT_SENSITIVE_LABELS = [
    'place order', 'confirm order', 'pay', 'purchase', 'buy now',
    'book ride', 'confirm booking', 'checkout',
]


def _load_sensitive_labels() -> list[str]:
    """Load sensitive labels from config/apps.json, falling back to defaults."""
    try:
        config = load_config()
        return config.get('gates', {}).get('sensitive_labels', _DEFAULT_SENSITIVE_LABELS)
    except Exception:
        return _DEFAULT_SENSITIVE_LABELS


class ConfirmationGate:
    """Check whether an action targets a sensitive UI element and request user confirmation."""

    def __init__(self):
        self.sensitive_labels = _load_sensitive_labels()
        self._task_lower: str = ''

    def set_task(self, task: str) -> None:
        """Set the current task so intent-matching can skip redundant confirmations."""
        self._task_lower = task.lower()

    def check(self, action: dict, ref_map: dict) -> bool:
        """Return True if this action requires user confirmation.

        Triggers on:
        1. Tap/type directly targeting a SecureTextField (password field).
        2. Tap/type on an element whose label contains a sensitive keyword,
           UNLESS the user's task already expresses that same intent.
        """
        action_name = action.get('name', '')
        if action_name not in ('tap', 'type_text'):
            return False

        ref = action.get('input', {}).get('ref')
        if ref is None:
            return False

        el = ref_map.get(ref) or ref_map.get(int(ref)) if ref is not None else None
        if not el:
            return False

        # Always gate SecureTextFields (passwords)
        if el.get('type') == 'XCUIElementTypeSecureTextField':
            return True

        label = (el.get('label') or '').lower()
        for keyword in self.sensitive_labels:
            if keyword in label:
                # If the user's task already contains this keyword, skip gate
                if keyword in self._task_lower:
                    return False
                return True
        return False

    def request_confirmation(self, action: dict, ref_map: dict) -> bool:
        """Display the pending action and wait for user approval.

        Returns True if user approves, False if rejected.
        """
        action_name = action.get('name', '')
        action_input = action.get('input', {})
        ref = action_input.get('ref')
        el = ref_map.get(ref) or ref_map.get(int(ref)) if ref is not None else None
        label = el.get('label', '') if el else ''

        print(f'\n  Confirmation required:')
        print(f'   Action: {action_name}')
        if label:
            print(f'   Target: "{label}"')
        reasoning = action_input.get('reasoning', '')
        if reasoning:
            print(f'   Reason: {reasoning}')

        response = input('   Allow? [y/n]: ').strip().lower()
        return response in ('y', 'yes', '')

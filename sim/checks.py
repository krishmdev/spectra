"""Ground-truth success checks: does the device state match what the scenario asked for?"""
from __future__ import annotations


def stock_price(state: dict, symbol: str) -> str | None:
    return next((s['price'] for s in state['stocks'] if s['symbol'] == symbol), None)


def check(scenario: dict, state: dict) -> tuple[bool, str]:
    """Return (passed, reason). Stricter than 'the agent said done': duplicates fail too."""
    ok = scenario['success']
    kind = ok['type']
    if kind == 'appearance':
        return state['appearance'] == ok['value'], f"appearance={state['appearance']}"
    if kind == 'reminder':
        n = state['reminders'].count(ok['title'])
        return n == ok['count'], f"{n} reminder(s) titled {ok['title']!r}"
    if kind == 'message':
        mine = [m['text'] for m in state['threads'].get(ok['contact'], []) if m['from'] == 'me']
        needle = ok.get('contains') or stock_price(state, ok['contains_stock'])
        if len(mine) != ok['count']:
            return False, f"{len(mine)} message(s) sent to {ok['contact']}"
        return needle.lower() in mine[-1].lower(), f"sent {mine[-1]!r}, expected it to contain {needle!r}"
    raise ValueError(f'unknown success type {kind!r}')

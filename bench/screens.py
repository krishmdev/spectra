"""A fixed set of mock-device screens (raw WDA-style XML) for serializer benchmarks.

Generated from sim/device.py, so the XML is synthetic: shaped like WDA output
(nested containers, status bar, keyboard) but not captured from a simulator.
"""
from __future__ import annotations

from sim.device import MESSAGES, REMINDERS, SETTINGS, STOCKS, Device


def _screens_for(seed: int):
    d = Device()

    def fresh():
        d.reset(seed)
        d.pending_alerts.clear()
        return d

    fresh()
    yield 'home', d.source()
    fresh().launch(SETTINGS)
    yield 'settings_root', d.source()
    d.scroll['Settings/root'] = 436
    yield 'settings_root_scrolled', d.source()
    d.stack[SETTINGS].append('Display & Brightness')
    yield 'display_brightness', d.source()
    fresh().launch(SETTINGS)
    d.stack[SETTINGS].append('General')
    yield 'general', d.source()
    fresh().launch(MESSAGES)
    yield 'messages_list', d.source()
    d.stack[MESSAGES].append('Mom')
    yield 'thread', d.source()
    d.focus = 'messages.Mom'
    d.drafts['messages.Mom'] = 'On my way'
    yield 'thread_typing', d.source()
    fresh().launch(REMINDERS)
    yield 'reminders_lists', d.source()
    d.stack[REMINDERS].append('Reminders')
    yield 'reminders_list', d.source()
    d.editing_reminder = True
    d.focus = 'reminders.new'
    d.drafts['reminders.new'] = 'Buy milk'
    yield 'reminders_editing', d.source()
    fresh()
    d.pending_alerts[REMINDERS] = {'title': '“Reminders” Would Like to Send You Notifications',
                                   'body': 'Notifications may include alerts, sounds, and icon badges.',
                                   'buttons': ['Don’t Allow', 'Allow']}
    d.launch(REMINDERS)
    yield 'reminders_alert', d.source()
    fresh().launch(STOCKS)
    yield 'stocks', d.source()


def screens(seeds=(0, 1, 2, 3)) -> list[tuple[str, str]]:
    out = []
    for seed in seeds:
        for name, xml in _screens_for(seed):
            out.append((f'{name}@{seed}', xml))
    return out

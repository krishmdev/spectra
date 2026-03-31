"""State machine for the mock iPhone: a home screen and four apps.

Every screen is rebuilt from `Device` state on each /source call, and taps are
resolved by hit-testing the same tree, so what the agent reads is exactly what
it can press. `reset(seed)` puts the device into a reproducible starting state;
the seed changes list order, stock prices, pre-existing reminders, and whether
a couple of layout perturbations (an update banner, a permission alert) appear.
"""
from __future__ import annotations

import hashlib
import json
import random
import threading
from dataclasses import dataclass, field

from sim.ui import SCREEN_H, SCREEN_W, El, app_root, hit_test, render

SPRINGBOARD = 'com.apple.springboard'
SETTINGS = 'com.apple.Preferences'
MESSAGES = 'com.apple.MobileSMS'
REMINDERS = 'com.apple.reminders'
STOCKS = 'com.apple.stocks'

APP_NAMES = {
    SPRINGBOARD: 'SpringBoard',
    SETTINGS: 'Settings',
    MESSAGES: 'Messages',
    REMINDERS: 'Reminders',
    STOCKS: 'Stocks',
}
INSTALLED = set(APP_NAMES)

CONTENT_TOP = 160
CONTENT_BOTTOM = 840
ROW_H = 52
SECTION_GAP = 36

SETTINGS_SECTIONS = [
    ['Airplane Mode', 'Wi-Fi', 'Bluetooth', 'Cellular', 'Battery'],
    ['General', 'Accessibility', 'Action Button', 'Camera', 'Control Center',
     'Display & Brightness', 'Home Screen & App Library', 'Search', 'Siri', 'StandBy', 'Wallpaper'],
    ['Notifications', 'Sounds & Haptics', 'Focus', 'Screen Time'],
    ['Face ID & Passcode', 'Emergency SOS', 'Privacy & Security'],
    ['App Store', 'Wallet & Apple Pay', 'Apps'],
]
SETTINGS_VALUES = {'Wi-Fi': 'Home-5G', 'Bluetooth': 'On', 'Airplane Mode': None}
GENERAL_CELLS = ['About', 'Software Update', 'AirDrop', 'AirPlay & Continuity', 'Picture in Picture',
                 'iPhone Storage', 'Background App Refresh', 'Date & Time', 'Keyboard', 'Fonts',
                 'Language & Region', 'Dictionary', 'VPN & Device Management', 'Transfer or Reset iPhone']

CONTACTS = ['Mom', 'Alex Chen', 'Priya Patel', 'Dad', '+1 (888) 555-1212', 'Jordan Lee']
PREVIEWS = {
    'Mom': 'Call me when you land', 'Alex Chen': 'Are we still on for Friday?',
    'Priya Patel': 'Sent the slides', 'Dad': 'Game starts at 7', '+1 (888) 555-1212': 'Your code is 481223',
    'Jordan Lee': 'lol yes',
}
STOCKS_BASE = [('AAPL', 'Apple Inc.', 229.87), ('NVDA', 'NVIDIA Corporation', 167.52),
               ('MSFT', 'Microsoft Corporation', 505.12), ('GOOGL', 'Alphabet Inc.', 201.33),
               ('TSLA', 'Tesla, Inc.', 331.05)]
# variant='relabel' simulates an OS update that renames a few things.
RELABEL = {
    'Display & Brightness': 'Display and Brightness',
    'Send': 'Send Message',
    'Message': 'iMessage',
    'Yesterday': 'Tuesday',
    'Call me when you land': 'Did you land yet?',
    'Are we still on for Friday?': 'Friday still good?',
}
REMINDER_POOL = ['Call the dentist', 'Pay rent', 'Return library books', 'Pick up dry cleaning',
                 'Renew passport', 'Water the plants']

HOME_ICONS = ['Settings', 'Messages', 'Reminders', 'Stocks', 'Calendar', 'Photos', 'Camera', 'Clock',
              'Weather', 'Notes', 'Maps', 'App Store']
DOCK = ['Phone', 'Safari', 'Messages', 'Music']
ICON_BUNDLES = {'Settings': SETTINGS, 'Messages': MESSAGES, 'Reminders': REMINDERS, 'Stocks': STOCKS}


@dataclass
class Device:
    seed: int = 0
    foreground: str = SPRINGBOARD
    appearance: str = 'light'
    auto_appearance: bool = False
    bold_text: bool = False
    update_banner: bool = False
    stack: dict[str, list[str]] = field(default_factory=dict)
    scroll: dict[str, int] = field(default_factory=dict)
    focus: str | None = None
    drafts: dict[str, str] = field(default_factory=dict)
    reminders: list[str] = field(default_factory=list)
    editing_reminder: bool = False
    threads: dict[str, list[dict]] = field(default_factory=dict)
    thread_order: list[str] = field(default_factory=list)
    stocks: list[dict] = field(default_factory=list)
    pending_alerts: dict[str, dict] = field(default_factory=dict)
    alert: dict | None = None
    events: list[dict] = field(default_factory=list)
    variant: str = ''
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)

    # ------------------------------------------------------------------
    # reset / ground truth
    # ------------------------------------------------------------------

    def reset(self, seed: int = 0, variant: str = '') -> None:
        with self.lock:
            rng = random.Random(seed)
            self.seed = seed
            self.variant = variant
            self.foreground = SPRINGBOARD
            self.appearance = 'light'
            self.auto_appearance = False
            self.bold_text = False
            self.update_banner = rng.random() < 0.5
            self.stack = {SETTINGS: ['root'], MESSAGES: ['list'], REMINDERS: ['lists'], STOCKS: ['list']}
            self.scroll = {}
            self.focus = None
            self.drafts = {}
            self.reminders = rng.sample(REMINDER_POOL, 2)
            self.editing_reminder = False
            order = CONTACTS[:]
            rng.shuffle(order)
            self.thread_order = order
            self.threads = {c: [{'from': 'them', 'text': PREVIEWS[c]}] for c in order}
            self.stocks = []
            for sym, name, base in STOCKS_BASE:
                price = round(base * (1 + rng.uniform(-0.04, 0.04)), 2)
                change = round(rng.uniform(-3, 3), 2)
                self.stocks.append({'symbol': sym, 'name': name, 'price': f'{price:.2f}',
                                    'change': f'{change:+.2f}%'})
            self.pending_alerts = {}
            if rng.random() < 0.5:
                self.pending_alerts[REMINDERS] = {
                    'title': '“Reminders” Would Like to Send You Notifications',
                    'body': 'Notifications may include alerts, sounds, and icon badges.',
                    'buttons': ['Don’t Allow', 'Allow'],
                }
            self.alert = None
            self.events = []

    def state(self) -> dict:
        with self.lock:
            data = {
                'seed': self.seed,
                'variant': self.variant,
                'foreground': self.foreground,
                'screen': self.screen_id(),
                'appearance': self.appearance,
                'bold_text': self.bold_text,
                'reminders': list(self.reminders),
                'threads': {c: list(m) for c, m in self.threads.items()},
                'stocks': [dict(s) for s in self.stocks],
                'alert': self.alert['title'] if self.alert else None,
                'update_banner': self.update_banner,
            }
        data['hash'] = hashlib.sha256(json.dumps(
            {k: v for k, v in data.items() if k != 'hash'}, sort_keys=True).encode()).hexdigest()[:16]
        return data

    def stock_price(self, symbol: str) -> str | None:
        for s in self.stocks:
            if s['symbol'] == symbol:
                return s['price']
        return None

    def t(self, label: str) -> str:
        return RELABEL.get(label, label) if self.variant == 'relabel' else label

    def screen_id(self) -> str:
        if self.foreground == SPRINGBOARD:
            return 'home'
        return f'{APP_NAMES[self.foreground]}/{self.stack[self.foreground][-1]}'

    def _log(self, kind: str, **kw) -> None:
        self.events.append({'event': kind, 'screen': self.screen_id(), **kw})

    # ------------------------------------------------------------------
    # WDA-facing actions
    # ------------------------------------------------------------------

    def source(self) -> str:
        with self.lock:
            return render(self._build())

    def active_app(self) -> dict:
        with self.lock:
            return {'bundleId': self.foreground, 'name': APP_NAMES[self.foreground], 'pid': 100}

    def launch(self, bundle_id: str) -> bool:
        with self.lock:
            if bundle_id not in INSTALLED:
                return False
            if bundle_id != self.foreground:
                # Activating the app that is already in front keeps its keyboard focus.
                self.focus = None
            self.foreground = bundle_id
            if bundle_id in self.pending_alerts:
                self.alert = self.pending_alerts.pop(bundle_id)
            self._log('launch', bundle_id=bundle_id)
            return True

    def home(self) -> None:
        with self.lock:
            self.foreground = SPRINGBOARD
            self.focus = None
            self.alert = None
            self._log('home')

    def tap(self, x: float, y: float) -> str | None:
        with self.lock:
            root = self._build()
            modal = None
            if self.alert is not None:
                modal = next((e for e in root.walk() if e.type == 'Alert'), None)
            el = hit_test(root, x, y, modal=modal)
            self._log('tap', x=x, y=y, target=el.label if el else None)
            if el is None:
                return None
            el.on_tap()
            return el.label

    def keys(self, text: str) -> bool:
        with self.lock:
            if self.focus is None:
                self._log('keys_dropped', text=text)
                return False
            self.drafts[self.focus] = self.drafts.get(self.focus, '') + text
            self._log('keys', text=text, field=self.focus)
            return True

    def drag(self, x1: float, y1: float, x2: float, y2: float) -> None:
        with self.lock:
            if self.alert is not None:
                return
            if x1 < 30 and x2 - x1 > 100 and abs(y2 - y1) < 80:
                self._back()
                self._log('edge_swipe')
                return
            dy = y1 - y2
            if abs(dy) < 20 or self.foreground == SPRINGBOARD:
                return
            key = self.screen_id()
            self.scroll[key] = max(0, min(self._max_scroll(key), self.scroll.get(key, 0) + int(dy)))
            self._log('scroll', dy=dy, offset=self.scroll[key])

    def open_url(self, url: str) -> bool:
        with self.lock:
            self._log('open_url', url=url)
            return False

    # ------------------------------------------------------------------
    # navigation helpers
    # ------------------------------------------------------------------

    def _push(self, screen: str) -> None:
        self.stack[self.foreground].append(screen)
        self.focus = None

    def _back(self) -> None:
        st = self.stack.get(self.foreground)
        if st and len(st) > 1:
            self._commit_reminder()
            st.pop()
            self.focus = None

    def _focus(self, field_id: str) -> None:
        self.focus = field_id

    def _max_scroll(self, key: str) -> int:
        if key == 'Settings/root':
            return max(0, self._settings_content_height() - (CONTENT_BOTTOM - CONTENT_TOP))
        if key == 'Settings/General':
            return max(0, len(GENERAL_CELLS) * ROW_H - (CONTENT_BOTTOM - CONTENT_TOP))
        return 0

    def _settings_content_height(self) -> int:
        h = 80 + SECTION_GAP + (ROW_H + SECTION_GAP if self.update_banner else 0)
        for sec in SETTINGS_SECTIONS:
            h += len(sec) * ROW_H + SECTION_GAP
        return h

    # ------------------------------------------------------------------
    # screen builders
    # ------------------------------------------------------------------

    def _build(self) -> El:
        fg = self.foreground
        if fg == SPRINGBOARD:
            return self._home_screen()
        screen = self.stack[fg][-1]
        builder = {SETTINGS: self._settings, MESSAGES: self._messages,
                   REMINDERS: self._reminders, STOCKS: self._stocks}[fg]
        content = builder(screen)
        overlay = self._alert_el() if self.alert else None
        return app_root(APP_NAMES[fg], content, with_keyboard=self.focus is not None, overlay=overlay)

    def _alert_el(self) -> El:
        a = self.alert
        box = El('Alert', label=a['title'], frame=(51, 330, 300, 214))
        body = El('Other', frame=(51, 330, 300, 150)).add(
            El('StaticText', label=a['title'], value=a['title'], frame=(67, 350, 268, 44)),
            El('StaticText', label=a['body'], value=a['body'], frame=(67, 400, 268, 60)))
        buttons = El('Other', frame=(51, 488, 300, 56))
        for i, b in enumerate(a['buttons']):
            buttons.add(El('Button', label=b, frame=(51 + i * 150, 488, 150, 56),
                           on_tap=lambda b=b: self._dismiss_alert(b)))
        return box.add(body, buttons)

    def _dismiss_alert(self, button: str) -> None:
        self._log('alert_dismissed', button=button)
        self.alert = None

    def _nav_bar(self, title: str, back: str | None = None, right: list[El] | None = None) -> El:
        bar = El('NavigationBar', label=title, name=title, frame=(0, 62, SCREEN_W, 44))
        if back:
            bar.add(El('Button', label=back, name='BackButton', frame=(8, 62, 100, 44),
                       on_tap=self._back))
        bar.add(El('StaticText', label=title, value=title, frame=(120, 72, 162, 24)))
        for r in right or []:
            bar.add(r)
        return bar

    def _scrolled_rows(self, key: str, rows: list[tuple[int, El]], table_label: str = '') -> El:
        """Place rows (natural_y, element) into a table, dropping recycled off-screen cells."""
        off = self.scroll.get(key, 0)
        table = El('Table', label=table_label, frame=(0, CONTENT_TOP, SCREEN_W, CONTENT_BOTTOM - CONTENT_TOP))
        for natural_y, el in rows:
            y = natural_y - off
            x, _, w, h = el.frame
            center = y + h / 2
            if center < CONTENT_TOP or center > CONTENT_BOTTOM:
                continue
            _shift(el, y - el.frame[1])
            table.add(el)
        return table

    # --- home screen ---

    def _home_screen(self) -> El:
        icons = []
        for i, name in enumerate(HOME_ICONS):
            col, row = i % 4, i // 4
            bundle = ICON_BUNDLES.get(name)
            icons.append(El('Icon', label=name, frame=(26 + col * 92, 90 + row * 104, 68, 86),
                            on_tap=(lambda b=bundle: self.launch(b)) if bundle else (lambda: None)))
        dock = El('Other', label='Dock', frame=(12, 770, 378, 92))
        for i, name in enumerate(DOCK):
            bundle = ICON_BUNDLES.get(name)
            dock.add(El('Icon', label=name, frame=(26 + i * 92, 782, 68, 68),
                        on_tap=(lambda b=bundle: self.launch(b)) if bundle else (lambda: None)))
        page = El('Other', label='Home screen icons', frame=(0, 60, SCREEN_W, 690)).add(
            El('Other', frame=(0, 60, SCREEN_W, 690)).add(*icons),
            El('PageIndicator', label='page 1 of 2', value='page 1 of 2', frame=(150, 730, 102, 26)))
        return app_root('SpringBoard', [page, dock])

    # --- Settings ---

    def _settings(self, screen: str) -> list[El]:
        if screen == 'root':
            return self._settings_root()
        if screen == 'Display & Brightness':
            return self._display()
        if screen == 'General':
            return self._general()
        return self._detail(screen, 'Settings' if len(self.stack[SETTINGS]) == 2 else self.stack[SETTINGS][-2])

    def _settings_root(self) -> list[El]:
        rows: list[tuple[int, El]] = []
        y = CONTENT_TOP
        rows.append((y, El('Cell', label='Apple Account, Sign in to access your iCloud data, the App Store, '
                                'Apple services, and more.', frame=(16, y, 370, 80),
                           on_tap=lambda: self._push('Apple Account'))))
        y += 80 + SECTION_GAP
        if self.update_banner:
            rows.append((y, _cell('Software Update Available', 'iOS 26.0.1', y,
                                  lambda: self._push('Software Update'))))
            y += ROW_H + SECTION_GAP
        for sec in SETTINGS_SECTIONS:
            for label in sec:
                if label == 'Airplane Mode':
                    cell = _cell(label, None, y, lambda: None)
                    cell.add(El('Switch', label='Airplane Mode', value='0', frame=(320, y + 10, 51, 31),
                                on_tap=lambda: None))
                else:
                    cell = _cell(self.t(label), SETTINGS_VALUES.get(label), y, lambda s=label: self._push(s))
                rows.append((y, cell))
                y += ROW_H
            y += SECTION_GAP
        return [
            self._nav_bar('Settings'),
            El('SearchField', label='Search', value='Search', frame=(16, 110, 370, 36),
               on_tap=lambda: self._focus('settings.search')),
            self._scrolled_rows('Settings/root', rows),
        ]

    def _display(self) -> list[El]:
        dark = self.appearance == 'dark'
        els = [
            self._nav_bar(self.t('Display & Brightness'), back='Settings'),
            El('StaticText', label='APPEARANCE', value='APPEARANCE', frame=(32, 166, 200, 18)),
            El('Button', label='Light', frame=(60, 196, 100, 170), selected=not dark,
               value='1' if not dark else '0', on_tap=lambda: self._set_appearance('light')),
            El('Button', label='Dark', frame=(242, 196, 100, 170), selected=dark,
               value='1' if dark else '0', on_tap=lambda: self._set_appearance('dark')),
        ]
        table = El('Table', frame=(0, 380, SCREEN_W, 460))
        y = 384
        auto = _cell('Automatic', None, y, lambda: None)
        auto.add(El('Switch', label='Automatic', value='1' if self.auto_appearance else '0',
                    frame=(320, y + 10, 51, 31), on_tap=self._toggle_auto))
        table.add(auto)
        y += ROW_H + SECTION_GAP
        table.add(El('StaticText', label='TEXT', value='TEXT', frame=(32, y - 22, 200, 18)))
        table.add(_cell('Text Size', None, y, lambda: self._push('Text Size')))
        y += ROW_H
        bold = _cell('Bold Text', None, y, lambda: None)
        bold.add(El('Switch', label='Bold Text', value='1' if self.bold_text else '0',
                    frame=(320, y + 10, 51, 31), on_tap=self._toggle_bold))
        table.add(bold)
        y += ROW_H + SECTION_GAP
        table.add(El('StaticText', label='BRIGHTNESS', value='BRIGHTNESS', frame=(32, y - 22, 200, 18)))
        table.add(El('Cell', frame=(16, y, 370, ROW_H)).add(
            El('Slider', label='Brightness', value='50%', frame=(60, y + 12, 280, 28), on_tap=lambda: None)))
        y += ROW_H
        tt = _cell('True Tone', None, y, lambda: None)
        tt.add(El('Switch', label='True Tone', value='1', frame=(320, y + 10, 51, 31), on_tap=lambda: None))
        table.add(tt)
        y += ROW_H + SECTION_GAP
        table.add(_cell('Night Shift', 'Off', y, lambda: self._push('Night Shift')))
        y += ROW_H
        table.add(_cell('Auto-Lock', '30 seconds', y, lambda: self._push('Auto-Lock')))
        return els + [table]

    def _set_appearance(self, mode: str) -> None:
        self.appearance = mode
        self._log('appearance', mode=mode)

    def _toggle_auto(self) -> None:
        self.auto_appearance = not self.auto_appearance

    def _toggle_bold(self) -> None:
        self.bold_text = not self.bold_text
        self._log('bold_text', on=self.bold_text)

    def _general(self) -> list[El]:
        rows = [(CONTENT_TOP + i * ROW_H, _cell(label, None, CONTENT_TOP + i * ROW_H,
                                                lambda s=label: self._push(s)))
                for i, label in enumerate(GENERAL_CELLS)]
        return [self._nav_bar('General', back='Settings'), self._scrolled_rows('Settings/General', rows)]

    def _detail(self, title: str, back: str) -> list[El]:
        table = El('Table', frame=(0, CONTENT_TOP, SCREEN_W, 300))
        for i, label in enumerate(['Learn More', 'Options']):
            table.add(_cell(label, None, CONTENT_TOP + i * ROW_H, lambda: None))
        return [self._nav_bar(title, back=back), table]

    # --- Messages ---

    def _messages(self, screen: str) -> list[El]:
        if screen == 'list':
            rows = []
            for i, contact in enumerate(self.thread_order):
                last = self.threads[contact][-1]
                preview = self.t(last['text']) if last['from'] == 'them' else f'You: {last["text"]}'
                y = CONTENT_TOP + i * 76
                rows.append(El('Cell', label=f'{contact}, {preview}, {self.t("Yesterday")}', frame=(0, y, SCREEN_W, 76),
                               on_tap=lambda c=contact: self._push(c)).add(
                    El('Image', label=contact, frame=(16, y + 14, 48, 48)),
                    El('StaticText', label=contact, value=contact, frame=(76, y + 12, 220, 22)),
                    El('StaticText', label=preview, value=preview, frame=(76, y + 38, 290, 20)),
                ))
            table = El('Table', label='Conversations', frame=(0, CONTENT_TOP, SCREEN_W, 680)).add(*rows)
            return [
                self._nav_bar('Messages', right=[
                    El('Button', label='Edit', frame=(8, 62, 60, 44), on_tap=lambda: None),
                    El('Button', label='Compose', frame=(346, 62, 44, 44), on_tap=lambda: None)]),
                El('SearchField', label='Search', value='Search', frame=(16, 110, 370, 36),
                   on_tap=lambda: self._focus('messages.search')),
                table,
            ]
        contact = screen
        field_id = f'messages.{contact}'
        draft = self.drafts.get(field_id, '')
        bubbles = El('CollectionView', frame=(0, 106, SCREEN_W, 600))
        msgs = self.threads[contact][-8:]
        for i, m in enumerate(msgs):
            who = 'Your iMessage' if m['from'] == 'me' else contact
            y = 120 + i * 58
            x = 150 if m['from'] == 'me' else 16
            bubbles.add(El('Cell', label=f'{who}, {m["text"]}', frame=(x, y, 236, 48)).add(
                El('TextView', value=m['text'], frame=(x + 8, y + 6, 220, 36), accessible=False)))
        bar_y = 480 if self.focus == field_id else 790
        compose = El('Other', frame=(0, bar_y, SCREEN_W, 50)).add(
            El('Button', label='Apps', frame=(12, bar_y + 8, 34, 34), on_tap=lambda: None),
            El('TextField', label=self.t('Message'), value=draft or 'iMessage', frame=(56, bar_y + 6, 290, 38),
               on_tap=lambda: self._focus(field_id)),
            El('Button', label=self.t('Send'), frame=(352, bar_y + 8, 34, 34), enabled=bool(draft),
               on_tap=lambda: self._send(contact)),
        )
        return [self._nav_bar(contact, back='Messages'), bubbles, compose]

    def _send(self, contact: str) -> None:
        field_id = f'messages.{contact}'
        text = self.drafts.pop(field_id, '').strip()
        if not text:
            return
        self.threads[contact].append({'from': 'me', 'text': text})
        self.thread_order.remove(contact)
        self.thread_order.insert(0, contact)
        self._log('sent', contact=contact, text=text)

    # --- Reminders ---

    def _reminders(self, screen: str) -> list[El]:
        if screen == 'lists':
            smart = El('CollectionView', frame=(0, CONTENT_TOP, SCREEN_W, 200))
            for i, name in enumerate(['Today', 'Scheduled', 'All', 'Flagged', 'Completed']):
                col, row = i % 2, i // 2
                smart.add(El('Cell', label=f'{name}, {len(self.reminders) if name == "All" else 0}',
                             frame=(16 + col * 188, CONTENT_TOP + row * 72, 180, 64),
                             on_tap=lambda: None))
            table = El('Table', frame=(0, 400, SCREEN_W, 200)).add(
                El('StaticText', label='My Lists', value='My Lists', frame=(20, 404, 200, 28)),
                El('Cell', label=f'Reminders, {len(self.reminders)}', frame=(16, 440, 370, ROW_H),
                   on_tap=lambda: self._push('Reminders')))
            return [
                El('SearchField', label='Search', value='Search', frame=(16, 110, 370, 36),
                   on_tap=lambda: None),
                smart, table,
                El('Button', label='Add List', frame=(290, 800, 100, 30), on_tap=lambda: None),
            ]
        right = []
        if self.editing_reminder:
            right.append(El('Button', label='Done', frame=(330, 62, 60, 44), on_tap=self._finish_reminder))
        table = El('Table', frame=(0, CONTENT_TOP, SCREEN_W, 600))
        y = CONTENT_TOP
        for title in self.reminders:
            table.add(El('Cell', label=title, frame=(0, y, SCREEN_W, ROW_H), on_tap=lambda: None).add(
                El('Button', label='Completed', value='0', frame=(16, y + 12, 28, 28), on_tap=lambda: None),
                El('TextField', label=title, value=title, frame=(56, y + 10, 320, 32), on_tap=lambda: None)))
            y += ROW_H
        if self.editing_reminder:
            draft = self.drafts.get('reminders.new', '')
            table.add(El('Cell', frame=(0, y, SCREEN_W, ROW_H)).add(
                El('Button', label='Completed', value='0', frame=(16, y + 12, 28, 28), on_tap=lambda: None),
                El('TextField', label='Title', value=draft, frame=(56, y + 10, 320, 32),
                   on_tap=lambda: self._focus('reminders.new'))))
        return [
            self._nav_bar('Reminders', back='Lists', right=right),
            table,
            El('Button', label='New Reminder', frame=(16, 790, 160, 36), on_tap=self._new_reminder),
        ]

    def _new_reminder(self) -> None:
        self._commit_reminder()
        self.editing_reminder = True
        self.drafts['reminders.new'] = ''
        self._focus('reminders.new')

    def _finish_reminder(self) -> None:
        self._commit_reminder()
        self.focus = None

    def _commit_reminder(self) -> None:
        if not self.editing_reminder:
            return
        text = self.drafts.pop('reminders.new', '').strip()
        self.editing_reminder = False
        if self.focus == 'reminders.new':
            self.focus = None
        if text:
            self.reminders.append(text)
            self._log('reminder_added', title=text)

    # --- Stocks ---

    def _stocks(self, screen: str) -> list[El]:
        table = El('Table', label='My Symbols', frame=(0, CONTENT_TOP, SCREEN_W, 600))
        for i, s in enumerate(self.stocks):
            y = CONTENT_TOP + i * 68
            table.add(El('Cell', label=f'{s["symbol"]}, {s["name"]}, {s["price"]}, {s["change"]}',
                         frame=(0, y, SCREEN_W, 68), on_tap=lambda: None).add(
                El('StaticText', label=s['symbol'], value=s['symbol'], frame=(16, y + 10, 100, 24)),
                El('StaticText', label=s['name'], value=s['name'], frame=(16, y + 36, 200, 20)),
                El('StaticText', label=s['price'], value=s['price'], frame=(270, y + 10, 110, 24)),
                El('Button', label=s['change'], frame=(300, y + 36, 80, 24), on_tap=lambda: None)))
        return [
            El('StaticText', label='Stocks', value='Stocks', frame=(16, 64, 200, 40)),
            El('Button', label='More', frame=(346, 64, 44, 40), on_tap=lambda: None),
            El('SearchField', label='Search', value='Search', frame=(16, 110, 370, 36), on_tap=lambda: None),
            table,
        ]


def _cell(label: str, value: str | None, y: int, on_tap) -> El:
    cell = El('Cell', label=label, frame=(16, y, 370, ROW_H), on_tap=on_tap)
    cell.add(El('Image', label=label, frame=(32, y + 12, 28, 28)),
             El('StaticText', label=label, value=label, frame=(72, y + 15, 220, 22)))
    if value:
        cell.value = value
        cell.add(El('StaticText', label=value, value=value, frame=(270, y + 15, 80, 22)))
    cell.add(El('Image', label='chevron', frame=(360, y + 18, 10, 16)))
    return cell


def _shift(el: El, dy: int) -> None:
    for e in el.walk():
        x, y, w, h = e.frame
        e.frame = (x, y + dy, w, h)


assert SCREEN_H > CONTENT_BOTTOM

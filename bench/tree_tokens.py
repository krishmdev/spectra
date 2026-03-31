"""Serializer benchmark: raw WDA XML vs the v0.1 compact tree vs the current one.

    python -m bench.tree_tokens --out bench/results/tree-tokens

For each mock screen (bench/screens.py) it records the size of what the planner
would receive and how much of the screen survives:

- chars, and estimated tokens (chars / 4). If GEMINI_API_KEY is set, also the
  model's own count from the countTokens endpoint.
- interactive retention: visible, on-screen, non-zero-size interactive
  elements in the raw XML (keyboard keys and status bar excluded) that got a
  ref in the output.
- text retention: visible static text that isn't already part of an
  interactive element's label (section headers, titles), found anywhere in
  the output.

The v0.1 parser is loaded straight from the v0.1-yhack tag.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import types
import xml.etree.ElementTree as ET

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from bench.screens import screens  # noqa: E402

INTERACTIVE = {'Button', 'Cell', 'TextField', 'SecureTextField', 'SearchField', 'Switch', 'Slider', 'Icon',
               'Link', 'Tab', 'SegmentedControl'}
NOISE = {'Keyboard', 'StatusBar'}
SCREEN_W, SCREEN_H = 402, 874


def load_parser_from_git(ref: str, path: str):
    src = subprocess.run(['git', 'show', f'{ref}:{path}'], cwd=REPO, capture_output=True, text=True,
                         check=True).stdout
    mod = types.ModuleType(f'tree_parser_{ref}')
    exec(compile(src, f'{ref}:{path}', 'exec'), mod.__dict__)
    return mod.parse_tree


def _frame(el):
    return tuple(int(float(el.get(k, 0))) for k in ('x', 'y', 'width', 'height'))


def ground_truth(xml: str) -> tuple[set, list[str]]:
    """(interactive element keys, informative static texts) for one raw screen."""
    root = ET.fromstring(xml)
    interactive, texts = set(), []

    def walk(el, labels_above, in_noise):
        short = el.tag.replace('XCUIElementType', '')
        noise = in_noise or short in NOISE
        x, y, w, h = _frame(el)
        on_screen = w > 0 and h > 0 and 0 <= x + w / 2 <= SCREEN_W and 0 <= y + h / 2 <= SCREEN_H
        visible = el.get('visible') != 'false' and on_screen
        label = el.get('label') or el.get('name') or ''
        if not noise and visible and short in INTERACTIVE:
            interactive.add((el.tag, x, y, w, h))
        if not noise and visible and short == 'StaticText':
            text = (el.get('value') or label).strip()
            if text and not any(text in above for above in labels_above):
                texts.append(text)
        above = labels_above + ([label] if short in INTERACTIVE and label else [])
        for c in el:
            walk(c, above, noise)

    for child in root:
        walk(child, [], False)
    return interactive, texts


def measure(name: str, xml: str, parse) -> dict:
    truth, texts = ground_truth(xml)
    if parse is None:
        out, kept = xml, truth
    else:
        out, ref_map, _app = parse(xml)
        kept = {(e['type'], e['x'], e['y'], e['width'], e['height']) for e in ref_map.values()}
    retained = len(truth & kept)
    text_hits = sum(1 for t in texts if t in out)
    return {
        'screen': name,
        'chars': len(out),
        'est_tokens': round(len(out) / 4),
        'interactive_total': len(truth),
        'interactive_retained': retained,
        'texts_total': len(texts),
        'texts_retained': text_hits,
        'output_sha256': hashlib.sha256(out.encode()).hexdigest()[:16],
        '_text': out,
    }


def gemini_counts(texts: list[str]) -> list[int] | None:
    if not os.environ.get('GEMINI_API_KEY'):
        return None
    from google import genai
    client = genai.Client(api_key=os.environ['GEMINI_API_KEY'])
    return [client.models.count_tokens(model='gemini-3-flash-preview', contents=t).total_tokens for t in texts]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--out', required=True)
    ap.add_argument('--baseline-ref', default='v0.1-yhack')
    args = ap.parse_args(argv)

    from core.tree_parser import parse_tree as current
    variants = {
        'raw_xml': None,
        'v0.1': load_parser_from_git(args.baseline_ref, 'spectra/core/tree_parser.py'),
        'v0.2': current,
    }
    fixtures = screens()
    rows = []
    for vname, parse in variants.items():
        for sname, xml in fixtures:
            r = measure(sname, xml, parse)
            r['variant'] = vname
            rows.append(r)
    counts = gemini_counts([r['_text'] for r in rows])
    for r, c in zip(rows, counts or [None] * len(rows)):
        r['gemini_tokens'] = c

    summary = {}
    for vname in variants:
        rs = [r for r in rows if r['variant'] == vname]
        tot = lambda k: sum(r[k] for r in rs)  # noqa: E731
        summary[vname] = {
            'screens': len(rs),
            'mean_chars': round(tot('chars') / len(rs), 1),
            'mean_est_tokens': round(tot('est_tokens') / len(rs), 1),
            'mean_gemini_tokens': round(tot('gemini_tokens') / len(rs), 1) if counts else None,
            'interactive_retention': round(tot('interactive_retained') / tot('interactive_total'), 3),
            'text_retention': round(tot('texts_retained') / tot('texts_total'), 3),
        }
    raw = summary['raw_xml']['mean_chars']
    for vname, s in summary.items():
        s['compression_vs_raw'] = round(raw / s['mean_chars'], 1)

    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, 'screens.jsonl'), 'w') as f:
        for r in rows:
            f.write(json.dumps({k: v for k, v in r.items() if k != '_text'}) + '\n')
    examples = os.path.join(args.out, 'examples')
    os.makedirs(examples, exist_ok=True)
    for r in rows:
        if r['screen'] in ('display_brightness@0', 'stocks@0', 'reminders_editing@0'):
            ext = 'xml' if r['variant'] == 'raw_xml' else 'txt'
            with open(os.path.join(examples, f"{r['screen'].replace('@', '_seed')}.{r['variant']}.{ext}"), 'w') as f:
                f.write(r['_text'] + '\n')
    meta = {
        'baseline_ref': args.baseline_ref,
        'baseline_commit': subprocess.run(['git', 'rev-parse', args.baseline_ref], cwd=REPO, capture_output=True,
                                          text=True).stdout.strip(),
        'head_commit': subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=REPO, capture_output=True,
                                      text=True).stdout.strip(),
        'fixtures': 'bench/screens.py (synthetic WDA-style XML from the mock device), seeds 0-3',
        'token_note': 'est_tokens = chars/4, an estimate; gemini_tokens only when a key was available',
    }
    with open(os.path.join(args.out, 'summary.json'), 'w') as f:
        json.dump({'meta': meta, 'summary': summary}, f, indent=2)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""See your local front-end change on the real site, with live data.

Opens a browser on findacrib.com but answers every page, script, stylesheet
and image that exists in your checkout from your checkout. Everything else
(the building data, listings, config.js, the API) still comes from the live
site, so you need no keys and no data build. Same trick the journey suite
uses, for human eyes.

    python3 scripts/preview.py                        # desktop, opens a window
    python3 scripts/preview.py --device phone         # iPhone (WebKit)
    python3 scripts/preview.py --device ipad --path /sf/
    python3 scripts/preview.py --shots shots/after    # phone + desktop + iPad
                                                      # screenshots, no window

With a window open, press Enter in the terminal to reload after you save a
file (files are read fresh on every request); Ctrl-C to quit. Use --shots
before and after a change for the screenshots a UI pull request needs.
"""
from __future__ import annotations

import argparse
import mimetypes
import sys
from pathlib import Path
from urllib.parse import urlsplit, unquote

ROOT = Path(__file__).resolve().parent.parent
LIVE = 'https://findacrib.com'
DEVICES = ('phone', 'desktop', 'ipad')

# Always from the live site, even when a local copy exists: config.js holds
# the live public keys (a local one is usually the unfilled example), and data
# files in a contributor's clone are missing or stale.
ALWAYS_LIVE = {'config.js', 'sw.js'}
DATA_SUFFIXES = {'.json', '.gz', '.geojson'}


def local_file(url: str, root: Path = ROOT, local_data: bool = False) -> Path | None:
    """The file in the checkout that should answer `url`, or None for live."""
    parts = urlsplit(url)
    if f'{parts.scheme}://{parts.netloc}' != LIVE:
        return None
    rel = unquote(parts.path).lstrip('/')
    if rel == '' or rel.endswith('/'):
        rel += 'index.html'
    if rel in ALWAYS_LIVE or '..' in Path(rel).parts:
        return None
    if Path(rel).suffix in DATA_SUFFIXES and not local_data:
        return None
    # Tracked data files live in data/ (2026-11-13) but are served at the site
    # root (findacrib.com/fmr.json), so a data URL also looks there.
    bases = (root, root / 'data') if Path(rel).suffix in DATA_SUFFIXES else (root,)
    for base in bases:
        f = (base / rel).resolve()
        try:
            f.relative_to(root.resolve())
        except ValueError:
            return None
        if f.is_file():
            return f
    return None


def context(p, device, headless):
    if device == 'phone':
        b = p.webkit.launch(headless=headless)
        return b, b.new_context(**p.devices['iPhone 14 Pro'], service_workers='block')
    if device == 'ipad':
        # iPadOS Safari presents a Mac user agent with touch (see journeys.py).
        b = p.webkit.launch(headless=headless)
        d = dict(p.devices['iPad Pro 11 landscape'])
        d['user_agent'] = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 '
                           '(KHTML, like Gecko) Version/26.0 Safari/605.1.15')
        return b, b.new_context(**d, service_workers='block')
    b = p.chromium.launch(headless=headless)
    return b, b.new_context(viewport={'width': 1300, 'height': 900}, service_workers='block')


def open_page(ctx, path, local_data):
    page = ctx.new_page()
    served = []

    def route(r):
        f = local_file(r.request.url, local_data=local_data)
        if f is None:
            return r.continue_()
        served.append(f.relative_to(ROOT).as_posix())
        kind = mimetypes.guess_type(f.name)[0] or 'application/octet-stream'
        if kind.startswith('text/') or kind == 'application/javascript':
            kind += '; charset=utf-8'
        r.fulfill(status=200, content_type=kind, body=f.read_bytes(),
                  headers={'Cache-Control': 'no-store'})

    page.route(LIVE + '/**', route)
    page.goto(LIVE + path, wait_until='load', timeout=90_000)
    return page, served


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--device', choices=DEVICES, default='desktop')
    ap.add_argument('--path', default='/', help='page to open, e.g. /sf/ or /alerts/')
    ap.add_argument('--shots', metavar='DIR', help='save phone/desktop/iPad screenshots here and exit')
    ap.add_argument('--wait', type=float, default=6, help='seconds to let the map settle before a screenshot')
    ap.add_argument('--local-data', action='store_true', help='also serve .json/.gz data files from the checkout')
    a = ap.parse_args()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit('playwright is missing: see Quick start in README.md')

    with sync_playwright() as p:
        if a.shots:
            out = Path(a.shots)
            out.mkdir(parents=True, exist_ok=True)
            for device in DEVICES:
                b, ctx = context(p, device, headless=True)
                page, served = open_page(ctx, a.path, a.local_data)
                page.wait_for_timeout(a.wait * 1000)
                name = (a.path.strip('/').replace('/', '-') or 'home') + f'-{device}.png'
                page.screenshot(path=str(out / name))
                print(f'{out / name}  (local: {len(set(served))} files)')
                b.close()
            return 0
        b, ctx = context(p, a.device, headless=False)
        page, served = open_page(ctx, a.path, a.local_data)
        print(f'{a.device}: {LIVE}{a.path} with {len(set(served))} local files '
              f'({", ".join(sorted(set(served))[:4])}{", ..." if len(set(served)) > 4 else ""})')
        print('Enter = reload from disk, Ctrl-C = quit')
        try:
            while True:
                input()
                served.clear()
                page.reload(wait_until='load', timeout=90_000)
                print(f'reloaded ({len(set(served))} local files)')
        except (KeyboardInterrupt, EOFError):
            pass
        b.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())

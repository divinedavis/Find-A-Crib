#!/usr/bin/env python3
"""User-journey tests for the Find A Crib web app, phone and desktop.

Drives the real page in a real browser engine through everything a visitor
does: land, search each way, pick a suggestion, tap pills and pins, open a
building, press every button on it, open and scroll the list, filter, save,
follow a deep link, come back to the view they left, and load the other
city maps. Every journey also asserts the page threw nothing and did not
crash, and the desktop pass checks the JS heap against a budget — the two
failure classes that took the phone down on 2026-09-06.

    python3 tests/journeys.py                 # local index.html, over live data
    python3 tests/journeys.py --target live   # https://findacrib.com as deployed
    python3 tests/journeys.py --only search   # one journey, by name substring

Exit status is the number of failed journeys. scripts/deploy_app.sh runs
this before and after every deploy of the app shell.

What it cannot see: a real iPhone's software keyboard, memory limits and
GPU. Playwright's WebKit is the same engine without the device. The crash
of 2026-09-06 (results sheet + keyboard closing) never reproduced here, so
a change on that path also wants the device lane — see DEVICE.md.
"""
import argparse
import json
import sys
import time
import traceback
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
LIVE = 'https://findacrib.com'
# What the inline QR in the Get-the-app modal must decode to (scripts/make_app_qr.py).
APP_STORE_URL = 'https://apps.apple.com/us/app/find-a-crib/id6807549249'
CITY_PAGES = ('la', 'sf', 'dc', 'westchester')
# One building per city known to carry a full record blob, for j_city_records.
# Picked by "richest h" from each city's buildings.hpd.json; if a rebuild ever
# drops one the journey says which city and which id, not just "no panel".
CITY_RECORD_CASES = {
    'la': ('LA-5511008010', ['Housing code violations', 'Complaints to LAHD', 'Eviction notices filed']),
    'sf': ('SF-1237-200BLOCKOFDIVISA', ['Eviction notices', 'Rent Board petitions', 'Buyout agreements']),
    'dc': ('DC-69000755_1', ['Owner of record']),
}
BBL = '2023190002'          # 2401 3RD AVE, Bronx — has violations, listings nearby
ADDR = '2401 3RD AVE'
PINS = "document.querySelectorAll('#map .leaflet-marker-icon').length"
BPINS = "document.querySelectorAll('#map .building-dot-hit').length"
LABEL = "document.getElementById('map-count').textContent"
CARDS = "document.querySelectorAll('#grid .card[data-bbl]').length"
HEAP_BUDGET_MB = 120        # desktop Chromium, after GC, after an area pick (was 114 MB before the fix at rest)
DOM_BUDGET = 40000



# Which analytics event each journey exercises. tests/journey_coverage.py reads
# this, asks the events table what real visitors actually did, and names the
# events no journey covers — so the suite grows from real behaviour instead of
# from guesses. Add the event here when you add a journey that drives it.
#
# Note the suite itself never writes these rows: the page's track() bails on
# navigator.webdriver, which Playwright always sets. Journeys therefore assert
# the DOM contract the event depends on (the data- attributes it reads), which
# is what actually breaks.
JOURNEY_EVENTS = {
    'land':                 ['geo_start'],
    'search_address':       ['search', 'building_view', 'section_view', 'violations_open', 'complaints_open',
                             'evictions_open', 'litigations_open', 'bedbugs_open', 'rodents_open'],
    'search_area':          ['search'],
    'search_zip_and_miss':  ['search'],
    'pin_and_list':         ['building_view'],
    'filters_and_save':     ['save', 'unsave', 'saved_view'],
    'deep_links_and_view':  ['building_view'],
    'city_pages':           [],
    'city_records':         ['building_view'],
    'no_signed_out_flash':  [],
    'no_chip_row_flash':    [],
    'memory':               [],
    'alerts_page':          [],
    'signin_modal':         ['signin'],
    'app_chip':             [],
    'app_qr_menu':          ['app_qr_open'],
    'boot_is_usable':       [],
    'city_chip':            [],
    'ad_tiles':             ['tile_served', 'tile_impression', 'featured_click', 'hc_click'],
    'outbound_links':       ['outbound'],
    'status_chips':         ['status_open'],
    'referral_gate':        ['referral_open', 'referral_share'],
    # home_set / home_open / home_clear are pre-2026-09-06 history: the
    # my-apartment pin was retired from the UI that day (no sheet button, no
    # profile row, no pill) and the code left dormant. Nothing to cover.
}
# Diagnostics and server-side rows, not things a visitor does.
NON_JOURNEY_EVENTS = {
    'render_storm', 'crash_trace', 'js_error', 'portfolio_open',   # diagnostics, not visitor actions
    # The my-apartment pin was retired from the UI on 2026-09-06 (no sheet
    # button, no profile row, no pill; the code left dormant). Rows older than
    # that still show in a 30-day window — there is nothing left to drive.
    'home_set', 'home_open', 'home_clear',
}

class Journey:
    def __init__(self, name, device):
        self.name, self.device = name, device
        self.errors = []
        self.notes = []

    def label(self):
        return f'{self.device}:{self.name}'


class Runner:
    def __init__(self, target, only, headed):
        self.target, self.only, self.headed = target, only, headed
        self.html = None if target == 'live' else (ROOT / 'index.html').read_text()
        # The city pages are generated FROM index.html by build_city_pages.py, so
        # a local run has to serve the generated copies too — otherwise a journey
        # that opens /la/ silently tests the deployed site and passes on a change
        # that was never built.
        self.city_html = {} if target == 'live' else {
            c: (ROOT / c / 'index.html').read_text()
            for c in CITY_PAGES if (ROOT / c / 'index.html').exists()
        }
        # …and the buildings files with them. Serving a local page against the
        # DEPLOYED data is the worst of both: the page is the new one, the blob
        # is last week's, and the panel the change added renders empty. Read
        # lazily — LA's slim file is 14 MB and most journeys never ask for it.
        self.sc = (ROOT / 'static' / 'supercluster' / 'supercluster.min.js').read_text()
        self.results = []

    # ---- browser plumbing -------------------------------------------------
    def context(self, p, device):
        if device == 'phone':
            b = p.webkit.launch(headless=not self.headed)
            ctx = b.new_context(**p.devices['iPhone 14 Pro'])
        else:
            b = p.chromium.launch(headless=not self.headed)
            ctx = b.new_context(viewport={'width': 1300, 'height': 900})
        return b, ctx

    def page(self, ctx, j):
        page = ctx.new_page()
        page.on('pageerror', lambda e: j.errors.append('pageerror: ' + str(e)[:200]))
        page.on('crash', lambda: j.errors.append('CRASH: renderer died'))
        page.on('console', lambda m: j.errors.append('console.error: ' + m.text[:200])
                if m.type == 'error' and 'Failed to load resource' not in m.text and 'Content Security Policy' not in m.text and 'Report Only' not in m.text and 'doubleclick.net' not in m.text else None)  # WebKit words Google's own conversion-ping refusal as 'Refused to execute'
        if self.html is not None:
            def route(r):
                u = r.request.url.split('#')[0]
                city = next((c for c in self.city_html
                             if u == f'{LIVE}/{c}/' or u == f'{LIVE}/{c}/index.html'
                             or u.startswith(f'{LIVE}/{c}/?')), None)
                if u == LIVE + '/' or u.startswith(LIVE + '/?'):
                    r.fulfill(status=200, content_type='text/html; charset=utf-8', body=self.html)
                elif city:
                    r.fulfill(status=200, content_type='text/html; charset=utf-8', body=self.city_html[city])
                elif self.local_data_path(u):
                    r.fulfill(status=200, content_type='application/json',
                              body=self.local_data_path(u).read_text())
                elif any(u.split('?')[0] == LIVE + '/static/' + name for name in
                         ('apple-street-preview.js', 'apple-street-frame.html', 'mapillary-preview.js')):
                    asset = ROOT / 'static' / u.split('?')[0].rsplit('/', 1)[-1]
                    r.fulfill(status=200, content_type='text/html' if asset.suffix == '.html'
                              else 'application/javascript', body=asset.read_text())
                elif u.startswith(LIVE + '/static/supercluster/'):
                    r.fulfill(status=200, content_type='application/javascript', body=self.sc)
                else:
                    r.continue_()
            page.route(LIVE + '/**', route)
        return page

    def local_data_path(self, url):
        """The on-disk buildings file a city-page request is asking for, or None.
        Only the two the app fetches, and only for a city page — everything else
        (listings, s8, fmr, seo pages) still comes from the live site."""
        if not self.city_html:
            return None
        for c in self.city_html:
            for name in ('buildings.slim.json', 'buildings.hpd.json', 'buildings.min.json'):
                if url == f'{LIVE}/{c}/{name}':
                    p = ROOT / c / name
                    return p if p.exists() else None
        return None

    def boot(self, page, path='/', wait_pins=True):
        # A hash-only change to a loaded page is not a navigation; a deep link
        # has to boot the page, so always leave first.
        if page.url.startswith(LIVE):
            page.goto('about:blank')
        # NOT networkidle (removed 2026-09-16). Every result card mounts an
        # Apple Look Around preview, and those stream MapKit tiles for as long
        # as they are on screen — ~11-20 MB across a long tail of requests,
        # measured that day. The 500 ms quiet window networkidle waits for
        # frequently never opens inside 90 s, so boot() threw
        # `Page.goto: Timeout 90000ms exceeded` on a random handful of desktop
        # journeys every run: 35/40, then 32/40, and 37/40 on an UNCHANGED
        # index.html, with a different set failing each time. Desktop only,
        # because desktop shows more cards at once than a phone and so runs
        # more previews.
        #
        # domcontentloaded plus the pin wait below is a stronger contract
        # anyway: networkidle only ever meant "the network went quiet", while
        # PINS > 0 means the app actually parsed its data and drew the map.
        page.goto(LIVE + path, wait_until='domcontentloaded', timeout=90000)
        if wait_pins:
            Runner.wait_until(page, PINS + ' > 0', timeout=60000)
        time.sleep(1.5)

    # ---- helpers ----------------------------------------------------------
    @staticmethod
    def click(page, sel):
        page.evaluate(f"(()=>{{const el=document.querySelector({json.dumps(sel)}); if(!el) throw new Error('missing '+{json.dumps(sel)}); el.dispatchEvent(new MouseEvent('click',{{bubbles:true}}));}})()")

    @staticmethod
    def typeq(page, q, settle=1.6):
        page.click('#q')
        page.fill('#q', q)
        time.sleep(settle)

    @staticmethod
    def pick_first(page):
        page.evaluate("document.querySelector('.ac-item').click()")
        time.sleep(2)

    @staticmethod
    def detail_open(page):
        return page.evaluate("!document.getElementById('detail-sheet').hidden")

    @staticmethod
    def close_detail(page):
        page.evaluate("const b=document.querySelector('#detail-sheet [data-detail=\"close\"]'); b && b.click()")
        time.sleep(0.5)

    @staticmethod
    def wait_until(page, js, timeout=20000, step=0.25):
        """Poll `js` (an expression) from here until it is truthy.

        NOT page.wait_for_function: that polls by building a Function inside
        the page, which the live site's CSP (no 'unsafe-eval') refuses — on
        WebKit it throws EvalError immediately, the wait returns at once, and
        every assertion after it reads a half-drawn page. page.evaluate is
        injected over the debugging protocol and is unaffected, so polling it
        from Python tests the real production policy. (2026-09-09)
        """
        end = time.time() + timeout / 1000.0
        while time.time() < end:
            try:
                if page.evaluate('() => !!(' + js + ')'):
                    return True
            except Exception:
                pass
            time.sleep(step)
        return False

    @staticmethod
    def sheet_loaded(page, timeout=20000):
        """The open-data sheet has answered: its body no longer says Loading."""
        Runner.wait_until(page, "!document.getElementById('viol-sheet').hidden && !/Loading /.test(document.getElementById('viol-body').innerText)", timeout)

    @staticmethod
    def ok(cond, msg, j):
        if not cond:
            j.errors.append(msg)

    # ---- journeys ---------------------------------------------------------
    def j_land(self, page, j, device):
        self.boot(page)
        n = page.evaluate(PINS)
        self.ok(20 <= n <= 400, f'city view should show a readable number of pills, got {n}', j)
        self.ok('of' in page.evaluate(LABEL), 'count pill missing', j)
        self.ok(page.evaluate("document.getElementById('search-helper').hidden"), 'helper card shown with no search', j)
        # The boot payload's fetch() is started from <head>, so it goes out once
        # — the boot script awaits that same response — and it starts before the
        # blocking scripts rather than ~1 s into the page. Pinned at 1 request
        # because a <link rel=preload> looked identical here and made WebKit
        # download the whole 1.1 MB file TWICE (2026-09-15).
        boot = page.evaluate(r"()=>{const e=performance.getEntriesByType('resource').filter(r=>/buildings\.(slim|min)\.json/.test(r.name));"
                             r"const l=performance.getEntriesByType('resource').filter(r=>/leaflet\.js/.test(r.name))[0];"
                             "return {n:e.length, start:e.length?Math.round(e[0].startTime):null, leaflet:l?Math.round(l.startTime):null}}")
        self.ok(boot['n'] == 1, f'the boot payload should be fetched once, not {boot["n"]} times: {boot}', j)
        self.ok(boot['start'] is not None and boot['leaflet'] is not None and boot['start'] <= boot['leaflet'] + 50,
                f'the boot payload should start with the head, not after the scripts: {boot}', j)
        j.notes.append(f'{n} pills, data at {boot["start"]}ms')
        if device == 'desktop':
            # Airbnb placement: brand, search and the right-hand buttons on one line, chips centred below —
            # at the normal width and at a zoomed-in one (a 1000px layout width is 130% zoom on a 1300px window)
            for w in (1300, 1000):
                page.set_viewport_size({'width': w, 'height': 900}); time.sleep(0.5)
                row = page.evaluate("(()=>{const r=s=>document.querySelector(s).getBoundingClientRect(); const b=r('.brand'), q=r('#q'), a=r('#auth-btn'), m=r('#menu-btn'), c=r('.chip-row'); return {b:b.top+b.height/2, q:q.top+q.height/2, a:a.top+a.height/2, m:m.top+m.height/2, chipsTop:c.top, rowBottom:Math.max(b.bottom,q.bottom,a.bottom), qCenter:(q.left+q.right)/2, W:innerWidth}})()")
                same = max(row['b'], row['q'], row['a'], row['m']) - min(row['b'], row['q'], row['a'], row['m']) < 14
                self.ok(same, f'header row not on one line at {w}px: {row}', j)
                self.ok(row['chipsTop'] >= row['rowBottom'] - 2, f'chips should sit below the top row at {w}px: {row}', j)
                self.ok(abs(row['qCenter'] - row['W'] / 2) < 0.2 * row['W'], f'search box should be roughly centred at {w}px: {row}', j)
            page.evaluate("document.getElementById('menu-btn').click()"); time.sleep(0.3)
            self.ok(not page.evaluate("document.getElementById('menu-pop').hidden"), 'menu button should open the menu', j)
            self.ok(page.evaluate("[...document.querySelectorAll('#menu-pop a, #menu-pop button')].length") >= 8, 'menu should list the header actions', j)
            self.ok(page.evaluate("!!document.querySelector('#menu-pop a[href^=\"/alerts/\"]')") and 'Alerts' in page.evaluate("document.getElementById('menu-pop').innerText"), 'menu should offer Alerts', j)
            chips = page.evaluate("[...document.querySelectorAll('.chip-row .filter-pill:not([hidden])')].filter(e=>getComputedStyle(e).display!=='none').map(e=>e.textContent.trim())")
            self.ok(any('Alerts' in c for c in chips) and not any('Lottery agents' in c for c in chips), f'top-bar chips should show Alerts, not Lottery agents: {chips}', j)
            page.keyboard.press('Escape'); time.sleep(0.2)
            self.ok(page.evaluate("document.getElementById('menu-pop').hidden"), 'Escape should close the menu', j)
            # Signed out, the menu's Alerts link opens the sign-up modal instead of leaving the page.
            self.click(page, '#menu-btn'); time.sleep(0.3)
            page.evaluate("document.querySelector('#menu-pop a[href^=\"/alerts/\"]').click()"); time.sleep(0.5)
            self.ok(not page.evaluate("document.getElementById('auth-modal').hidden") and page.evaluate("document.getElementById('auth-title').textContent") == 'Create account'
                    and page.evaluate("location.pathname") == '/', 'menu Alerts should open the sign-up modal when signed out', j)
            page.evaluate("document.querySelector('[data-auth=\"close\"]')?.click()"); time.sleep(0.2)
        else:
            # Phones: the Alerts chip sits immediately to the right of Saved (asked 2026-09-08).
            pos = page.evaluate("(()=>{const r=s=>document.querySelector(s).getBoundingClientRect(); const f=r('#pill-fav'), a=r('#pill-alerts-m'); return {fr:f.right, al:a.left, fy:f.top+f.height/2, ay:a.top+a.height/2, aw:a.width, href:document.getElementById('pill-alerts-m').getAttribute('href')}})()")
            self.ok(pos['aw'] > 0 and pos['al'] >= pos['fr'] and pos['al'] - pos['fr'] < 24 and abs(pos['ay'] - pos['fy']) < 4,
                    f'Alerts chip should sit right of Saved on phones: {pos}', j)
            self.ok(pos['href'].startswith('/alerts/'), f'Alerts chip should link to /alerts/: {pos}', j)
            page.evaluate("document.getElementById('pill-alerts-m').click()"); time.sleep(0.5)
            self.ok(not page.evaluate("document.getElementById('auth-modal').hidden") and page.evaluate("document.getElementById('auth-title').textContent") == 'Create account'
                    and page.evaluate("location.pathname") == '/', 'Alerts chip should open the sign-up modal when signed out', j)
            page.evaluate("document.querySelector('[data-auth=\"close\"]')?.click()"); time.sleep(0.2)

    def j_search_address(self, page, j, device):
        self.boot(page)
        self.typeq(page, ADDR)
        items = page.evaluate("[...document.querySelectorAll('.ac-item')].map(e=>e.innerText.split('\\n')[0])")
        self.ok(items and ADDR in items[0], f'address suggestion missing, got {items[:2]}', j)
        self.pick_first(page)
        self.ok(self.detail_open(page), 'picking an address should open the building sheet', j)
        btns = page.evaluate("[...document.querySelectorAll('#detail-sheet .d-actions a, #detail-sheet .d-actions button')].map(b=>b.textContent.trim())")
        for want in ('Violations', 'View on StreetEasy', 'View on map', 'Building (HPD) Complaints'):
            self.ok(any(want in b for b in btns), f'building sheet lacks "{want}" button: {btns}', j)
        self.ok(not any('my apartment' in b.lower() for b in btns), f'my-apartment button should be gone, got {btns}', j)
        # every button does something
        self.click(page, '#detail-sheet [data-detail="violations"]'); time.sleep(0.8)
        self.ok(not page.evaluate("document.getElementById('viol-sheet').hidden"), 'Violations button did not open the sheet', j)
        page.evaluate("document.querySelector('#viol-sheet .sheet-close')?.click()"); time.sleep(0.3)
        self.click(page, '#detail-sheet [data-detail="complaints"]'); self.sheet_loaded(page)
        self.ok(page.evaluate("!!document.querySelector('.viol-backdrop:not([hidden])')"), 'Complaints button did not open a sheet', j)
        page.evaluate("document.querySelectorAll('.viol-backdrop .sheet-close').forEach(b=>b.click())"); time.sleep(0.3)
        # NYC Open Data buttons: present, counted, and the sheets list real rows
        labels = page.evaluate("[...document.querySelectorAll('#detail-sheet .d-actions button')].map(b=>b.textContent.trim())")
        for want in ('Evictions', 'Housing court', 'Bedbug inspections', 'Rodent inspections'):
            self.ok(any(want in b for b in labels), f'building sheet lacks "{want}" button', j)
        vi = next((i for i, b in enumerate(labels) if b.startswith('Violations')), -1)
        self.ok(vi >= 0 and labels[vi + 1].startswith('Bedbug inspections') and labels[vi + 2].startswith('Rodent'), f'Bedbugs and Rodents should sit right under Violations, got {labels[:5]}', j)
        # Six Socrata queries; the slow one has taken 3s+, so wait for the
        # counts rather than a fixed pause (flaked on 2026-09-09).
        # every count, and the bedbug/rodent "this year" verdicts, which arrive from their own queries
        self.wait_until(page, "[...document.querySelectorAll('#detail-sheet [data-oc]')].every(e=>e.textContent.trim().startsWith('\u00b7') && (!/bedbugs|rodents/.test(e.dataset.oc) || /this year/.test(e.textContent)))")
        counts = page.evaluate("Object.fromEntries([...document.querySelectorAll('#detail-sheet [data-oc]')].map(e=>[e.dataset.oc, e.textContent.trim()]))")
        self.ok(all(v.startswith('·') for v in counts.values()), f'open-data counts should fill in on the buttons within 20s, got {counts}', j)
        tones = page.evaluate("Object.fromEntries(['bedbugs','rodents'].map(k=>[k, document.querySelector('#detail-sheet [data-detail=\"'+k+'\"]').className]))")
        self.ok(all('d-viol' in v for v in tones.values()), f'bedbug and rodent buttons should carry the violations styling, got {tones}', j)
        for k in ('bedbugs', 'rodents'):
            red, green = 'red' in tones[k], 'green' in tones[k]
            self.ok(red or green, f'{k} button should be red or green once the year is known: {counts} {tones}', j)
            self.ok((red and 'this year' in counts[k] and 'none' not in counts[k]) or (green and 'none' in counts[k] and 'this year' in counts[k]), f'{k} button must say why it is {"red" if red else "green"}: {counts[k]!r}', j)
        self.click(page, '#detail-sheet [data-detail="litigations"]'); self.sheet_loaded(page)
        body = page.evaluate("document.getElementById('viol-body').innerText")
        self.ok('Tenant Action' in body or 'case' in body.lower(), f'litigations sheet should list the case, got {body[:120]!r}', j)
        page.evaluate("document.querySelectorAll('.viol-backdrop .sheet-close').forEach(b=>b.click())"); time.sleep(0.3)
        # signed out, bedbug and rodent records ask for a free account (sign-up mode); the sheet must not open
        self.click(page, '#detail-sheet [data-detail="rodents"]'); time.sleep(1)
        self.ok(not page.evaluate("document.getElementById('auth-modal').hidden"), 'rodent record should ask for an account when signed out', j)
        self.ok(page.evaluate("document.getElementById('viol-sheet').hidden"), 'rodent sheet must stay closed when signed out', j)
        sub = page.evaluate("document.getElementById('auth-submit').textContent").lower()
        self.ok('create' in sub or 'sign up' in sub, f'gate should open in sign-up mode, got {sub!r}', j)
        page.evaluate("document.querySelector('[data-auth=\"close\"]')?.click()"); time.sleep(0.3)
        self.click(page, '#detail-sheet [data-detail="bedbugs"]'); time.sleep(1)
        self.ok(not page.evaluate("document.getElementById('auth-modal').hidden") and page.evaluate("document.getElementById('viol-sheet').hidden"), 'bedbug record should be gated when signed out', j)
        page.evaluate("document.querySelector('[data-auth=\"close\"]')?.click()"); time.sleep(0.3)
        self.click(page, '#detail-sheet [data-detail="evictions"]'); self.sheet_loaded(page)
        body = page.evaluate("document.getElementById('viol-body').innerText")
        self.ok('No marshal-executed evictions' in body or 'Marshal' in body, f'evictions sheet should answer, got {body[:120]!r}', j)
        page.evaluate("document.querySelectorAll('.viol-backdrop .sheet-close').forEach(b=>b.click())"); time.sleep(0.3)
        self.click(page, '#detail-sheet [data-detail="map"]'); time.sleep(1.5)
        self.ok(not self.detail_open(page), 'View on map should close the sheet', j)
        if device == 'phone':
            self.ok(page.evaluate("document.body.classList.contains('card-open')"), 'View on map should open the pin card on a phone', j)
            self.ok(ADDR in (page.evaluate("(document.querySelector('#building-card .card-addr')||{}).textContent") or ''), 'pin card shows the wrong building', j)
            self.ok('open violation' in (page.evaluate("(document.querySelector('#building-card .hpd-mini')||{}).textContent") or ''), 'pin card lacks the open-violations line', j)

    def j_search_area(self, page, j, device):
        self.boot(page)
        self.typeq(page, 'Bronx')
        first = page.evaluate("(document.querySelector('.ac-item')||{}).innerText||''")
        self.ok('Bronx' in first and 'Borough' in first, f'first suggestion should be the Bronx borough, got {first[:60]!r}', j)
        self.pick_first(page)
        self.ok(page.evaluate(LABEL).endswith('7,491'), f'Bronx should filter to 7,491, got {page.evaluate(LABEL)}', j)
        self.ok(page.evaluate("document.getElementById('search-helper').hidden"), 'no helper card after a clean area pick', j)
        self.ok(page.evaluate("document.getElementById('q').value") == '', 'search box should clear after an area pick', j)
        n0 = page.evaluate(PINS)
        self.click(page, '#map .leaflet-marker-icon'); time.sleep(1.5)
        self.ok(page.evaluate(PINS) != n0 or page.evaluate(BPINS) > 0, 'tapping a pill should zoom in and change the pins', j)

    def j_search_zip_and_miss(self, page, j, device):
        self.boot(page)
        self.typeq(page, '10001')
        first = page.evaluate("(document.querySelector('.ac-item')||{}).innerText||''")
        self.ok('10001' in first or int(page.evaluate(LABEL).split(' of ')[1].replace(',', '')) < 47165, 'a NYC ZIP should narrow the results', j)
        self.typeq(page, '10701')
        h = page.evaluate("document.getElementById('search-helper').innerText")
        self.ok('Yonkers' in h or 'Westchester' in h, f'uncovered ZIP should hand off to Westchester, got {h[:80]!r}', j)
        self.typeq(page, 'zzqx nowhere')
        h = page.evaluate("document.getElementById('search-helper').innerText")
        self.ok('outside New York City' in h and 'rent-stabilized' in h, f'no-match card should explain, got {h[:100]!r}', j)
        note = page.evaluate("(()=>{const n=document.getElementById('q-note'); return n.hidden ? '' : n.textContent})()")
        self.ok("isn’t rent-stabilized" in note and 'outside New York City' in note, f'no-match note under the search box missing, got {note!r}', j)
        self.ok(page.evaluate("document.getElementById('q').classList.contains('q-nomatch')"), 'search box should turn red on a miss', j)
        page.fill('#q', 'Bronx'); time.sleep(1.2)
        self.ok(page.evaluate("document.getElementById('q-note').hidden"), 'the note should clear once the search matches', j)
        self.typeq(page, 'rent stabilized')
        h = page.evaluate("document.getElementById('search-helper').innerText")
        self.ok('Every building on this map is rent-stabilized' in h, f'"rent stabilized" should get its own answer, got {h[:80]!r}', j)
        # landlord names are answered only for a signed-in visitor; signed out, the card must say so
        self.typeq(page, 'Clinton Management', settle=2.5)
        h = page.evaluate("document.getElementById('search-helper').innerText")
        self.ok('landlord' in h.lower() and 'account' in h.lower(), f'signed-out landlord search should point at sign-in, got {h[:120]!r}', j)

    def j_pin_and_list(self, page, j, device):
        self.boot(page, f'/#b={BBL}')
        if device == 'phone':
            self.ok(page.evaluate("document.body.classList.contains('card-open')"), '#b= should open the pin card', j)
            self.click(page, '#building-card [data-card="details"]'); time.sleep(1)
            self.ok(self.detail_open(page), 'Details on the pin card should open the sheet', j)
            self.close_detail(page)
            page.evaluate("document.querySelector('.card-close')?.click()"); time.sleep(0.5)
            # list sheet: pages of 40
            page.evaluate("document.getElementById('btn-toggle-view').click()"); time.sleep(1.2)
            self.ok(page.evaluate("document.body.classList.contains('list-open')"), 'List button should open the sheet', j)
            n0 = page.evaluate(CARDS)
            self.ok(0 < n0 <= 45, f'phone list should start with one page of cards, got {n0}', j)
            page.evaluate("document.querySelector('.grid-more')?.scrollIntoView()"); time.sleep(1.5)
            n1 = page.evaluate(CARDS)
            self.ok(n1 > n0 or not page.evaluate("!!document.querySelector('.grid-more')"), f'scrolling should append a page, {n0} -> {n1}', j)
            self.click(page, '#grid .card[data-bbl] [data-action="map"]'); time.sleep(1.5)
            self.ok(not page.evaluate("document.body.classList.contains('list-open')") and page.evaluate("document.body.classList.contains('card-open')"), 'View on map from the list should close the list and open the card', j)
        else:
            self.ok(page.evaluate(BPINS) > 0, '#b= should zoom to the building', j)
            self.click(page, '#map .building-dot-hit'); time.sleep(1.2)
            self.ok(page.evaluate("!!document.querySelector('.leaflet-popup')"), 'desktop pin click should open a popup', j)
            self.ok(page.evaluate("!!document.querySelector('#grid .card.is-selected')"), 'desktop pin click should highlight its card', j)
            n = page.evaluate(CARDS)
            self.ok(n > 0, 'desktop list empty', j)
            self.click(page, '#grid .card[data-bbl]'); time.sleep(1)
            self.ok(self.detail_open(page), 'clicking a list card should open the sheet', j)
            self.close_detail(page)

    def j_filters_and_save(self, page, j, device):
        self.boot(page)
        total = int(page.evaluate(LABEL).split(' of ')[1].replace(',', ''))
        page.evaluate("document.querySelectorAll('#borough-list input').forEach(c=>{c.checked=(c.dataset.b==='SI')}); document.querySelector('#borough-list input').dispatchEvent(new Event('change',{bubbles:true}))"); time.sleep(1)
        lab = page.evaluate(LABEL); in_view, si = [int(x.replace(',', '')) for x in lab.split(' of ')]
        self.ok(0 < si < total, f'Staten Island filter should shrink the match count, {total} -> {si}', j)
        self.ok(in_view >= 0.9 * si, f'the map should frame the filtered borough, but only {lab} are in view', j)
        page.evaluate("document.querySelectorAll('#borough-list input').forEach(c=>{c.checked=true}); document.querySelector('#borough-list input').dispatchEvent(new Event('change',{bubbles:true}))"); time.sleep(1)
        page.evaluate("const r=document.querySelector('input[name=\"listed\"][value=\"yes\"]'); r.checked=true; r.dispatchEvent(new Event('change',{bubbles:true}))"); time.sleep(1)
        listed = int(page.evaluate(LABEL).split(' of ')[1].replace(',', ''))
        self.ok(0 < listed < 2000, f'"recently advertised" filter should leave a few hundred, got {listed}', j)
        page.evaluate("const r=document.querySelector('input[name=\"listed\"][value=\"any\"]'); r.checked=true; r.dispatchEvent(new Event('change',{bubbles:true}))"); time.sleep(0.8)
        if device == 'desktop':
            # filters modal: footer visible without scrolling, Save present, five-row neighborhood box, wording
            page.evaluate("document.getElementById('pill-filters').click()"); time.sleep(0.8)
            self.ok(not page.evaluate("document.getElementById('filters-modal').hidden"), 'Filters should open the modal', j)
            vis = page.evaluate("(()=>{const b=document.getElementById('filters-done').getBoundingClientRect(); return b.bottom <= innerHeight && b.top >= 0 && b.height > 0})()")
            self.ok(vis, 'Show results should be visible at the bottom of the filters modal without scrolling', j)
            self.ok(page.evaluate("!!document.getElementById('filters-save')"), 'filters modal lacks Save this search', j)
            self.ok(page.evaluate("document.getElementById('nb-list').getBoundingClientRect().height") <= 170, 'neighborhood list should show about five rows', j)
            body = page.evaluate("document.getElementById('filters-modal').innerText")
            self.ok('Recently available' in body and 'Recently advertised' not in body and 'HPD · HUD' not in body, 'filters wording not updated', j)
            page.evaluate("document.querySelector('[data-filters=\"close\"]').click()"); time.sleep(0.3)
            first = page.evaluate("document.querySelector('#grid .card[data-bbl]').dataset.bbl")
            centre = page.evaluate("(()=>{const c=__facMap.getCenter(); return [c.lat, c.lng]})()")
            page.hover('#grid .card[data-bbl] >> nth=0'); time.sleep(1.0)
            self.ok(page.evaluate("!!document.querySelector('#map .pin-hover')"), 'hovering a tile should paint its pin blue', j)
            self.ok(page.evaluate("document.querySelector('#grid .card[data-bbl]').dataset.bbl") == first, 'the list must hold still while a tile is hovered', j)
            self.ok(page.evaluate("(()=>{const c=__facMap.getCenter(); return [c.lat, c.lng]})()") == centre, 'hovering a tile must not move the map (2026-09-08)', j)
            # Where that pin is, so the street-zoom checks land on real buildings rather than the city centre.
            here = page.evaluate("(()=>{const e=document.querySelector('#map .pin-hover'); if(!e) return null; const r=e.getBoundingClientRect(), m=document.getElementById('map').getBoundingClientRect(); const ll=__facMap.containerPointToLatLng([r.left+r.width/2-m.left, r.top+r.height/2-m.top]); return [ll.lat, ll.lng]})()")
            page.mouse.move(5, 5); time.sleep(0.5)
            self.ok(not page.evaluate("!!document.querySelector('#map .pin-hover')"), 'leaving the tile should clear the highlight', j)
            # Close enough (zoom 16+), the white pills read as rent, not unit counts.
            page.evaluate("ll => __facMap.setView(ll || __facMap.getCenter(), 17, {animate:false})", here); time.sleep(1.5)
            pills = page.evaluate("(()=>{const u=[...document.querySelectorAll('#map .unit-pill')]; return {n:u.length, rent:u.filter(e=>e.classList.contains('rent-pill')).length, sample:u.slice(0,3).map(e=>e.textContent)}})()")
            self.ok(pills['n'] == 0 or pills['rent'] > 0, f'at street zoom white pills should show rent: {pills}', j)
            self.ok(pills['n'] == 0 or all('$' in t for t in pills['sample']), f'rent pills should carry a dollar figure: {pills}', j)
            # Resting on a pin floats a hover card above it after a moment; leaving clears it.
            # Pins are drawn a margin past the viewport, so pick one actually on screen and not under the results pane.
            pt = page.evaluate("(()=>{const g=document.getElementById('grid')?.closest('aside')?.getBoundingClientRect(); for (const e of document.querySelectorAll('#map .building-dot-hit')) { const r=e.getBoundingClientRect(); if (r.width && r.top>120 && r.bottom<innerHeight-20 && r.left>20 && r.right<innerWidth-20 && !(g && r.left<g.right && r.right>g.left && r.top<g.bottom && r.bottom>g.top)) return [r.left+r.width/2, r.top+r.height/2]; } return null})()")
            if pt:
                page.mouse.move(pt[0], pt[1]); time.sleep(0.9)
                hov = page.evaluate("(()=>{const h=document.getElementById('map-hover'); return {hidden:h.hidden, text:h.innerText, price:!!h.querySelector('.mh-price'), addr:!!h.querySelector('.mh-addr')}})()")
                self.ok(not hov['hidden'] and hov['price'] and hov['addr'] and len(hov['text']) > 10, f'hovering a pin should show the hover card: {hov}', j)
                page.mouse.move(5, 5); time.sleep(0.4)
                self.ok(page.evaluate("document.getElementById('map-hover').hidden"), 'leaving the pin should hide the hover card', j)
            else:
                j.notes.append('no building pins at zoom 17 here — hover card unchecked')
            page.evaluate("__facMap.setView(__facMap.getCenter(), 14, {animate:false})"); time.sleep(1.5)
            pills = page.evaluate("(()=>{const u=[...document.querySelectorAll('#map .unit-pill')]; return {n:u.length, rent:u.filter(e=>e.classList.contains('rent-pill')).length}})()")
            self.ok(pills['rent'] == 0, f'zoomed out, white pills should go back to unit counts: {pills}', j)
        # save a building anonymously (localStorage), then the Saved filter shows it
        self.boot(page, f'/#d={BBL}')
        self.ok(self.detail_open(page), '#d= should open the sheet', j)
        favs_js = "(()=>{try{return JSON.parse(localStorage.getItem('jhf_favs')||'[]')}catch(e){return []}})()"
        before = page.evaluate(favs_js)
        self.click(page, '#detail-sheet [data-detail="fav"]'); time.sleep(0.8)
        after = page.evaluate(favs_js)
        gated = not page.evaluate("document.getElementById('auth-modal').hidden")
        self.ok(after != before or gated, 'heart should toggle the local save or ask to sign in', j)
        if gated:
            self.ok('sign up' in page.evaluate("document.getElementById('auth-submit').textContent").lower() or 'create' in page.evaluate("document.getElementById('auth-submit').textContent").lower(), 'heart should open the modal in sign-UP mode', j)
            page.evaluate("document.querySelector('[data-auth=\"close\"]')?.click()"); time.sleep(0.3)
        if BBL not in after and not gated:               # it was already saved (the my-apartment step saves too); toggle back on
            self.click(page, '#detail-sheet [data-detail="fav"]'); time.sleep(0.8)
            after = page.evaluate(favs_js)
        j.notes.append('save asks for sign-in' if gated else f'{len(after)} saved locally')
        if BBL in after:
            self.close_detail(page)
            self.click(page, '#pill-fav'); time.sleep(1)
            self.ok(page.evaluate(LABEL).endswith(f' of {len(after)}'), f'Saved filter should show the saved buildings, got {page.evaluate(LABEL)}', j)

    def j_deep_links_and_view(self, page, j, device):
        self.boot(page, '/?q=Bronx')
        self.ok(page.evaluate(LABEL).endswith('7,491'), f'?q=Bronx should filter, got {page.evaluate(LABEL)}', j)
        # zoom to a block, refresh: the whole city comes back, no geo chip, no remembered view
        self.boot(page, f'/#b={BBL}')
        self.ok(page.evaluate(BPINS) > 0, '#b= should zoom to the building', j)
        self.boot(page, '/')
        in_view, total = [int(x.replace(',', '')) for x in page.evaluate(LABEL).split(' of ')]
        self.ok(in_view >= 0.4 * total, f'a refresh should show the whole city, but only {in_view:,} of {total:,} are in view', j)
        self.ok(not page.evaluate("!!document.querySelector('.geo-chip')"), 'no network-location chip on landing', j)
        self.boot(page, f'/#d={BBL}')
        self.ok(self.detail_open(page), 'deep link must still open the building', j)

    def j_city_pages(self, page, j, device):
        for city, low in (('la', 1000), ('sf', 1000), ('dc', 100), ('westchester', 100)):
            page.goto(f'{LIVE}/{city}/', wait_until='domcontentloaded', timeout=90000)
            try:
                self.wait_until(page, PINS + ' > 0', timeout=120000)   # LA is 67k parcels
            except Exception:
                j.errors.append(f'/{city}/ never drew pins'); continue
            time.sleep(1)
            lab = page.evaluate(LABEL)
            self.ok(int(lab.split(' of ')[1].replace(',', '')) >= low, f'/{city}/ count looks wrong: {lab}', j)
            j.notes.append(f'{city} {lab}')

    def j_no_signed_out_flash(self, page, j, device):
        """A signed-in visitor must not be shown a Sign in button on reload.

        Reported 2026-09-12 with a screen recording: refreshing on a phone
        flashed "Sign in" and a wider header before the avatar appeared. The
        session is restored asynchronously by Supabase, so the markup's
        signed-out state painted first. The head script now decides from
        storage, before the first frame.
        """
        # Each state is set on a FULLY LOADED page and read back on the next
        # load. Setting storage on a 'commit'-state page, or seeding it with
        # add_init_script, both raced the document-start head script and made
        # this pass on one device and fail on the other.
        # data-auth is stamped by the head script and then CORRECTED by the app
        # once Supabase reports the real session — and since the boot got faster
        # (2026-09-15) that correction can land before the assertions read it.
        # Record the value the first frame actually had.
        page.add_init_script("""
            window.__firstAuth = undefined; window.__firstBtn = undefined;
            const rec = () => {
                if (window.__firstAuth === undefined && document.documentElement)
                    window.__firstAuth = document.documentElement.getAttribute('data-auth');
            };
            // Snapshot the button on the first frame it exists — reading it at
            // the end of the test measures the settled header, not the paint.
            const snap = () => {
                const b = document.getElementById('auth-btn');
                if (!b) { requestAnimationFrame(snap); return; }
                rec();
                if (window.__firstBtn === undefined) {
                    const cs = getComputedStyle(b);
                    window.__firstBtn = { text: b.textContent.trim(), fontSize: parseFloat(cs.fontSize),
                                          width: b.getBoundingClientRect().width };
                }
            };
            // documentElement does not exist yet at document-start, so watch the
            // document itself and let the attribute change bubble up to it.
            new MutationObserver(rec).observe(document, { attributes: true, subtree: true, attributeFilter: ['data-auth'] });
            document.addEventListener('DOMContentLoaded', rec);
            requestAnimationFrame(snap);
        """)

        def paint_after(setup):
            # Let whatever the previous load started finish first. Leaving while
            # the app's feed fetches are in flight aborts them, and WebKit
            # reports those aborts as page errors — which got common once the
            # boot payload started earlier and the feeds followed it sooner.
            try:
                page.wait_for_load_state('networkidle', timeout=30000)
            except Exception:
                pass
            # Seed on a page that does NOT run the app. The app writes fac.auth
            # itself the moment Supabase reports no session, and once the boot
            # got faster (buildings.slim.json is preloaded since 2026-09-15)
            # that write started beating the seed on the landing page, so the
            # state under test never survived to the next load.
            page.goto(LIVE + '/privacy.html', wait_until='domcontentloaded', timeout=90000)
            page.evaluate(setup)
            page.goto('about:blank')
            # 'commit' returns as the document starts — the earliest the first
            # paint could happen, which is the moment being tested.
            page.goto(LIVE + '/', wait_until='commit', timeout=90000)
            page.wait_for_selector('#auth-btn', state='attached', timeout=30000)
            return page.evaluate("""() => {
                const b = document.getElementById('auth-btn');
                const cs = getComputedStyle(b);
                const first = window.__firstAuth, fb = window.__firstBtn;
                // What the stamp BUYS: with data-auth set, the button has to be
                // the small avatar circle. Measured with the attribute applied
                // rather than off the first frame, because WebKit sometimes
                // runs that frame before it has applied the stylesheet and then
                // reports the unstyled width for any build, good or bad.
                const had = document.documentElement.getAttribute('data-auth');
                document.documentElement.setAttribute('data-auth', 'in');
                const stamped = { fontSize: parseFloat(getComputedStyle(b).fontSize),
                                  width: b.getBoundingClientRect().width };
                if (had === null) document.documentElement.removeAttribute('data-auth');
                else document.documentElement.setAttribute('data-auth', had);
                return { auth: first === undefined ? document.documentElement.getAttribute('data-auth') : first,
                         text: fb ? fb.text : b.textContent.trim(),
                         fontSize: stamped.fontSize,
                         width: stamped.width,
                         firstWidth: fb ? Math.round(fb.width) : null,
                         liveFontSize: parseFloat(cs.fontSize) };
            }""")

        CLEAR = ("localStorage.removeItem('fac.auth');"
                 "Object.keys(localStorage).filter(k=>k.startsWith('sb-')).forEach(k=>localStorage.removeItem(k));")
        # A session the client accepts at rest and only rejects after a round
        # trip. A bare {access_token} is thrown out synchronously, so the header
        # reverted before the frame under test could be measured.
        SESSION = ("localStorage.setItem('sb-test-auth-token', JSON.stringify({"
                   "access_token:'x', refresh_token:'y', token_type:'bearer', expires_in:3600,"
                   "expires_at: Math.floor(Date.now()/1000) + 3600,"
                   "user:{id:'00000000-0000-0000-0000-000000000000', aud:'authenticated', role:'authenticated'}}));")

        # A device that has signed in here before — which means it carries a
        # Supabase session too. Seeding only our own hint made the app revert the
        # header the moment Supabase reported no session, and once the boot got
        # faster (2026-09-15) that revert beat the frame being measured.
        r = paint_after(CLEAR + "localStorage.setItem('fac.auth','in');" + SESSION)
        self.ok(r['auth'] == 'in', f"head script should stamp data-auth=in, got {r['auth']}", j)
        self.ok(r['fontSize'] == 0,
                f"'Sign in' is legible on a signed-in device's first paint (font-size {r['fontSize']})", j)
        self.ok(r['width'] <= 40,
                f"the header paints the wide Sign in pill before the avatar ({r['width']:.0f}px)", j)
        j.notes.append(f"stamped {r['width']:.0f}px circle, first frame {r['firstWidth']}px")

        # Supabase's own session key is enough on its own, so the header is
        # right on the FIRST load after signing in — including straight after
        # clearing site data, which wipes any hint of ours.
        r = paint_after(CLEAR + SESSION)
        self.ok(r['auth'] == 'in', f"a live Supabase session key should be enough, got {r['auth']}", j)

        # …and a device that has never signed in still gets a real Sign in button.
        r = paint_after(CLEAR)
        self.ok(r['auth'] is None, f"a signed-out device must not be stamped, got {r['auth']}", j)
        self.ok(r['text'] == 'Sign in' and r['liveFontSize'] > 0,
                f"signed out, the button has to say Sign in, got {r!r}", j)

    def j_no_chip_row_flash(self, page, j, device):
        """The filter pills must not paint in the chip row and then vanish.

        Eight of them are written into .chip-row in the markup and moved into
        the filters modal by the boot script, so until that ran they rendered in
        the row and disappeared — a line of buttons flashing on every load
        (reported 2026-09-12; on a phone #pill-agent was 140x36 at first paint
        and gone by the time the page settled).
        """
        page.goto('about:blank')
        page.goto(LIVE + '/', wait_until='commit', timeout=90000)
        page.wait_for_selector('.chip-row', state='attached', timeout=30000)
        early = page.evaluate("""() => [...document.querySelectorAll('.chip-row > [id^=pill-]')]
            .filter(e => e.getBoundingClientRect().width > 0)
            .map(e => e.id + ' ' + Math.round(e.getBoundingClientRect().width) + 'px')""")
        moved = ['pill-borough', 'pill-nb', 'pill-listed', 'pill-s8',
                 'pill-beds', 'pill-price', 'pill-viol', 'pill-agent']
        leaked = [e for e in early if e.split()[0] in moved]
        self.ok(not leaked, f"filter pills painted in the chip row before being moved: {leaked}", j)
        # and they must still be reachable once the boot script has run.
        # Wait for that script's own output, not for the network to go quiet:
        # the Look Around previews keep it busy indefinitely (see boot()).
        self.wait_until(page, "document.querySelectorAll('#filters-body > [id^=pill-]').length > 0", 90000)
        time.sleep(1.5)
        inside = page.evaluate("""() => [...document.querySelectorAll('#filters-body > [id^=pill-]')].map(e => e.id)""")
        for m in moved:
            self.ok(m in inside, f"{m} never reached the filters modal", j)
        j.notes.append(f"{len(inside)} pills in the filters sheet, none leaked")

    def j_city_records(self, page, j, device):
        """Every city's building page must show the record ITS city publishes.

        Until 2026-09-12 only New York had one: LA, SF and DC buildings showed
        an address, a unit count and a year, and the whole owner/violation panel
        was gated on IS_NYC. Each of those cities does publish a per-property
        record — LAHD enforcement, the SF Rent Board's case history, the DC
        assessor's roll — and this asserts each one arrives and is named in that
        city's own words, not New York's.
        """
        if device != 'desktop':
            return                       # same markup either way; once is enough
        for city, (bid, want) in CITY_RECORD_CASES.items():
            page.goto('about:blank')
            page.goto(f'{LIVE}/{city}/#d={bid}', wait_until='domcontentloaded', timeout=90000)
            try:
                self.wait_until(page, "!document.getElementById('detail-sheet').hidden", timeout=60000)
            except Exception:
                j.errors.append(f'/{city}/#d={bid} never opened the building'); continue
            # the blob is lazy — buildings.hpd.json arrives after the first paint
            try:
                self.wait_until(page, "!!document.querySelector('[data-sec=\"hpd\"] .hpd-section h4')", timeout=30000)
            except Exception:
                j.errors.append(f'{city}: no record panel on {bid}'); continue
            heads = page.evaluate("[...document.querySelectorAll('[data-sec=\"hpd\"] h4')].map(e=>e.textContent.trim())")
            for w in want:
                self.ok(w in heads, f'{city}: record panel should show "{w}", got {heads}', j)
            # New York's wording must not leak into another city's panel.
            txt = page.evaluate("document.querySelector('[data-sec=\"hpd\"]').innerText")
            self.ok('HPD' not in txt, f'{city}: panel mentions HPD, which is a New York agency', j)
            j.notes.append(f'{city} {len(heads)} sections')

    def j_memory(self, page, j, device):
        if device != 'desktop':
            return
        cdp = page.context.new_cdp_session(page)
        cdp.send('Performance.enable'); cdp.send('HeapProfiler.enable')
        self.boot(page)
        self.typeq(page, 'Bronx'); self.pick_first(page)
        page.evaluate("document.querySelectorAll('#borough-list input').forEach(c=>{c.checked=true}); document.querySelector('#borough-list input').dispatchEvent(new Event('change',{bubbles:true}))"); time.sleep(2)
        cdp.send('HeapProfiler.collectGarbage'); time.sleep(0.5)
        m = {x['name']: x['value'] for x in cdp.send('Performance.getMetrics')['metrics']}
        heap, nodes = m['JSHeapUsedSize'] / 1e6, m['Nodes']
        j.notes.append(f'heap {heap:.0f} MB, {nodes:.0f} DOM nodes')
        self.ok(heap < HEAP_BUDGET_MB, f'JS heap {heap:.0f} MB over the {HEAP_BUDGET_MB} MB budget', j)
        self.ok(nodes < DOM_BUDGET, f'{nodes:.0f} DOM nodes over budget', j)

    def j_alerts_page(self, page, j, device):
        page.goto(LIVE + '/alerts/', wait_until='domcontentloaded', timeout=90000)
        self.wait_until(page, "!!document.getElementById('gate')", 30000); time.sleep(1)
        # Signed out (2026-09-08): the gate card, not the form; its button goes to the map's sign-up modal and back.
        self.ok(not page.evaluate("document.getElementById('gate').hidden") and page.evaluate("document.getElementById('form').hidden"), 'signed-out alerts page should show the account gate, not the form', j)
        href = page.evaluate("document.getElementById('gate-btn').getAttribute('href')")
        self.ok(href.startswith('/?auth=signup') and 'next=%2Falerts%2F' in href, f'gate button should open sign-up and come back: {href}', j)
        r = page.request.post(LIVE + '/api/alerts/subscribe', data=json.dumps({'email': 'x@example.com', 'boroughs': ['Bk']}), headers={'Content-Type': 'application/json'})
        # 429 counts as gated too: the endpoint is rate limited, and running
        # the suite several times in a row (as a deploy does) trips it. Both
        # codes mean the same thing here — an anonymous caller got nothing.
        self.ok(r.status in (401, 429), f'/api/alerts/subscribe without a session should be refused, got {r.status}', j)
        page.evaluate("document.getElementById('form').hidden = false")   # the form itself still works once revealed
        self.ok(page.evaluate("document.getElementById('submit').textContent.trim()") == 'Email me when something opens', 'alerts form should offer a fresh sign-up', j)
        page.click('text=Brooklyn'); time.sleep(0.3)
        self.ok(page.evaluate("document.querySelector('#boros input[value=Bk]').checked"), 'borough chip should toggle on', j)
        self.ok(page.evaluate("getComputedStyle(document.querySelector('#boros input[value=Bk] + span')).backgroundColor") != 'rgba(0, 0, 0, 0)', 'a chosen borough should be filled', j)
        page.click('text=Brooklyn'); time.sleep(0.3)
        self.ok(not page.evaluate("document.querySelector('#boros input[value=Bk]').checked"), 'borough chip should toggle off', j)
        r = page.request.get(LIVE + '/api/alerts/prefs')
        # 429 counts as gated too: the endpoint is rate limited, and running
        # the suite several times in a row (as a deploy does) trips it. Both
        # codes mean the same thing here — an anonymous caller got nothing.
        self.ok(r.status in (401, 429), f'/api/alerts/prefs without a session should be refused, got {r.status}', j)
        j.notes.append('prefs endpoint gated')

    def j_app_chip(self, page, j, device):
        # iPhone app chip right of Alerts (asked 2026-09-09): iPhones see it, desktop never does.
        self.boot(page)
        info = page.evaluate("(()=>{const a=document.getElementById('pill-app-m'), al=document.getElementById('pill-alerts-m'); const r=a.getBoundingClientRect(), ar=al.getBoundingClientRect(); return {shown:r.width>0&&getComputedStyle(a).display!=='none', href:a.getAttribute('href'), left:r.left, alertsRight:ar.right, sameRow:Math.abs(r.top-ar.top)<4, overflow:document.documentElement.scrollWidth>innerWidth, ios:document.documentElement.classList.contains('ios')}})()")
        self.ok(info['href'].startswith('https://apps.apple.com/us/app/find-a-crib/id6807549249'), f"chip should link to the App Store listing: {info['href']}", j)
        self.ok(not info['overflow'], 'page must not scroll sideways with the chip in the row', j)
        if device == 'phone':
            self.ok(info['ios'], 'an iPhone should be detected as iOS', j)
            self.ok(info['shown'], 'iPhone app chip should be visible on an iPhone', j)
            self.ok(info['sameRow'] and info['left'] >= info['alertsRight'] - 1, f"chip should sit right of Alerts: {info}", j)
            j.notes.append('chip right of Alerts')
        else:
            self.ok(not info['shown'], 'iPhone app chip must not show on desktop', j)
            self.app_qr(page, j)

    def app_qr(self, page, j):
        """Desktop's Get-the-app chip, and the QR behind it, actually decoded.

        A laptop cannot follow an App Store link to the device the app installs
        on, so desktop gets a QR instead of #pill-app-m (asked 2026-09-16).

        Asserting the <path> is non-empty would prove nothing — a QR fails in
        ways that still look like a QR. The generator can mask wrongly, CSS can
        scale it below the point where modules survive rasterising, dark mode
        can invert it, and a quiet zone one module too thin stops a camera
        finding the symbol at all even though the code itself is perfect. All
        four render as "a square of noise nobody can scan". So this screenshots
        the panel as painted and hands the pixels to OpenCV: if the detector can
        read it, a phone can. The 24px of panel padding IS the quiet zone and
        nothing is added on this side — at 14px the detector found nothing,
        which is how that bug was caught before it shipped.

        Both themes, because the panel's fixed white background is the only
        thing keeping the modules dark-on-light when the page goes dark.
        """
        import cv2, numpy as np
        chip = page.evaluate("(()=>{const a=document.getElementById('pill-app-d'),l=document.querySelector('.chip-row a[href=\\'/directory/\\']');"
                             "const r=a.getBoundingClientRect(),lr=l.getBoundingClientRect();"
                             "return {shown:r.width>0&&getComputedStyle(a).display!=='none',left:r.left,landlordsRight:lr.right,"
                             "sameRow:Math.abs(r.top-lr.top)<4,overflow:document.documentElement.scrollWidth>innerWidth}})()")
        self.ok(chip['shown'], 'desktop should offer a Get-the-app chip', j)
        self.ok(chip['sameRow'] and chip['left'] >= chip['landlordsRight'] - 1,
                f'the chip should sit right of Landlords: {chip}', j)
        self.ok(not chip['overflow'], 'the chip must not push the row sideways', j)
        for theme in ('light', 'dark'):
            page.evaluate("document.documentElement.setAttribute('data-theme', %r)" % theme)
            self.click(page, '#pill-app-d')
            self.wait_until(page, "!document.getElementById('app-modal').hidden", 5000)
            panel = page.query_selector('#app-modal .qr-panel')
            img = cv2.imdecode(np.frombuffer(panel.screenshot(), np.uint8), cv2.IMREAD_COLOR)
            txt, _pts, _rect = cv2.QRCodeDetector().detectAndDecode(img)
            self.ok(txt == APP_STORE_URL, f'{theme}: the QR should decode to the App Store listing, got {txt!r}', j)
            box = page.evaluate("(()=>{const r=document.querySelector('#app-modal .qr-code').getBoundingClientRect();"
                                "return {w:r.width, onscreen:r.top>=0&&r.bottom<=innerHeight}})()")
            self.ok(box['w'] >= 140, f'{theme}: the QR paints {box["w"]:.0f}px wide, too small to scan off a screen', j)
            self.ok(box['onscreen'], f'{theme}: the QR is cut off in a {page.viewport_size["height"]}px window', j)
            page.keyboard.press('Escape')
            self.wait_until(page, "document.getElementById('app-modal').hidden", 5000)
        page.evaluate("document.documentElement.removeAttribute('data-theme')")
        j.notes.append('QR decodes in both themes')

    def j_app_qr_menu(self, page, j, device):
        """The other way into the Get-the-app modal: the desktop ☰ menu.

        The chip and the menu row are separate entry points — the menu row
        works by clicking the chip it mirrors, so a rename of #pill-app-d would
        break the menu silently while the chip kept working. Desktop only; the
        phone has no ☰ and reaches the App Store through #pill-app-m.
        """
        self.boot(page)
        if device == 'phone':
            self.ok(not page.evaluate("!!document.getElementById('menu-btn')?.offsetParent"),
                    'phones should not show the desktop menu button', j)
            j.notes.append('n/a on phone')
            return
        self.click(page, '#menu-btn')
        self.wait_until(page, "!document.getElementById('menu-pop').hidden", 5000)
        row = page.evaluate("[...document.querySelectorAll('#menu-pop [data-menu]')].map(b=>b.dataset.menu)")
        self.ok('app' in row, f'the menu should offer Get the app, got {row}', j)
        self.click(page, '#menu-pop [data-menu="app"]')
        self.wait_until(page, "!document.getElementById('app-modal').hidden", 5000)
        self.ok(page.evaluate("document.getElementById('menu-pop').hidden"),
                'opening the modal should close the menu behind it', j)
        store = page.evaluate("document.getElementById('app-store-link').getAttribute('href')")
        self.ok(store == APP_STORE_URL, f'the modal should link to the App Store, got {store}', j)
        self.ok(page.evaluate("document.getElementById('app-store-link').getAttribute('target')") == '_blank'
                and 'noopener' in (page.evaluate("document.getElementById('app-store-link').getAttribute('rel')") or ''),
                'the App Store link is off-site: it needs target=_blank and rel=noopener', j)
        page.keyboard.press('Escape')
        self.wait_until(page, "document.getElementById('app-modal').hidden", 5000)
        j.notes.append('menu -> modal -> Escape')

    def j_boot_is_usable(self, page, j, device):
        """The page must become usable without waiting for the network to stop.

        It never stops: the Look Around previews stream MapKit tiles for as
        long as they are on screen. boot() used to wait for networkidle and a
        random handful of desktop journeys therefore died on
        `Page.goto: Timeout 90000ms` every run — including on an unchanged
        index.html (2026-09-16). This pins the property that replaced it: pins
        on the map, a usable search box and a results list, all well inside the
        old 90 s timeout, while requests are still in flight.
        """
        import time as _t
        start = _t.time()
        self.boot(page)
        ready_ms = int((_t.time() - start) * 1000)
        self.ok(ready_ms < 45000, f'the map should be usable in well under 45 s, took {ready_ms} ms', j)
        self.ok(page.evaluate(PINS) > 0, 'the map should have drawn pins', j)
        self.ok(page.evaluate("!document.getElementById('q').disabled"), 'the search box should accept input', j)
        self.ok(page.evaluate("document.querySelectorAll('#grid .card').length") > 0,
                'the results list should have cards', j)
        j.notes.append(f'usable in {ready_ms} ms')

    def j_city_chip(self, page, j, device):
        """The header must not flash four city chips before JS collapses them.

        The links ship in the HTML and JS moves the three you are not in under
        the current one; until CSS did that from <html data-city>, a phone
        painted all four, the row overflowed and the whole header reflowed on
        every load. (2026-09-09)
        """
        vis = "[...document.querySelectorAll('#city-nav a')].filter(a=>a.getBoundingClientRect().width>0).map(a=>a.textContent.trim())"
        self.boot(page)
        after = page.evaluate(vis)
        headerH = page.evaluate("Math.round(document.querySelector('header.topbar').getBoundingClientRect().height)")
        self.ok(page.evaluate("[...document.querySelectorAll('#profile-cities a')].map(a=>a.textContent.trim())") == ['NYC', 'SF', 'LA', 'DC'],
                'the profile sheet lists every city', j)
        self.ok(not page.evaluate("document.documentElement.scrollWidth > innerWidth"), 'the header must not overflow sideways', j)
        if device == 'phone':
            self.ok(after == ['NYC'], f'a phone should rest on one city chip, got {after}', j)
            self.ok(page.evaluate("[...document.querySelectorAll('#city-more a')].map(a=>a.textContent.trim())") == ['SF', 'LA', 'DC'],
                    'the other cities should be under the chip', j)
            # Tapping the chip opens them. Wait for the popover rather than
            # sleeping — half a second was enough locally and not on live
            # (2026-09-09). A synthetic click can also navigate, which tears the
            # context down, so both outcomes are read defensively.
            self.click(page, '#city-nav a.cur')
            self.wait_until(page, "!document.getElementById('city-more').hidden", 5000)
            try:
                opened = page.evaluate(vis)
            except Exception:
                opened = None
            self.ok(opened is None or opened == ['NYC', 'SF', 'LA', 'DC'], f'tapping the chip should show every city, got {opened}', j)
            j.notes.append(f'1 chip at rest, header {headerH}px')
        else:
            self.ok(after == ['NYC', 'SF', 'LA', 'DC'], f'desktop shows every city, got {after}', j)
            j.notes.append(f'4 chips, header {headerH}px')

    def j_ad_tiles(self, page, j, device):
        """The re-rental and lottery tiles — the only inventory anyone would buy.

        1,491 people saw a tile in the last 30 days and no journey covered them.
        The advertiser numbers are built from data- attributes on these cards
        (tile_served / tile_impression read the agent and address off the node),
        so an attribute quietly disappearing would empty the dashboard while the
        page still looked fine. Added 2026-09-09 from the events table.
        """
        self.boot(page)
        if device == 'phone':
            page.evaluate("document.getElementById('btn-toggle-view').click()"); time.sleep(1.5)
        self.wait_until(page, "document.querySelectorAll('#grid .card').length > 0", 20000)
        feat = page.evaluate("""(() => {
            const c = document.querySelector('#grid .card.feat-card');
            if (!c) return null;
            return {agent: c.dataset.featAgent || '', addr: c.dataset.featAddr || '', flag: !!c.querySelector('.feat-flag')};
        })()""")
        hc = page.evaluate("""(() => {
            const c = document.querySelector('#grid .card.hc-card');
            if (!c) return null;
            return {name: c.dataset.hcName || '', boro: c.dataset.hcBoro || '', flag: !!c.querySelector('.hc-flag')};
        })()""")
        self.ok(feat is not None or hc is not None, 'no sponsored or lottery tile rendered in the list at all', j)
        if feat:
            self.ok(feat['agent'] and feat['addr'],
                    f"a re-rental tile must carry the agent and address the advertiser report counts, got {feat}", j)
            self.ok(feat['flag'], 'a sponsored tile must be flagged as one', j)
        if hc:
            self.ok(hc['name'], f'a lottery tile must carry its name, got {hc}', j)
            self.ok(hc['flag'], 'a lottery tile must be flagged as one', j)
        j.notes.append('re-rental ' + ('ok' if feat else 'none') + ', lottery ' + ('ok' if hc else 'none'))

    def j_outbound_links(self, page, j, device):
        """Every hand-off off the site: 695 people did one last month.

        A link that loses target or rel, or an agent phone number that stops
        being a tel:, is a dead end for the visitor and an uncounted click for
        the dashboard. Added 2026-09-09 from the events table.
        """
        self.boot(page)
        self.typeq(page, ADDR)
        self.pick_first(page)
        self.ok(self.detail_open(page), 'the building sheet should be open', j)
        links = page.evaluate("""(() => {
            const out = [];
            document.querySelectorAll('#detail-sheet a[href^="http"], #detail-sheet a[href^="tel:"]').forEach(a => {
                const ext = /^https?:/.test(a.getAttribute('href')) && !a.href.startsWith(location.origin);
                out.push({href: a.getAttribute('href').slice(0, 60), ext,
                          target: a.getAttribute('target') || '', rel: a.getAttribute('rel') || ''});
            });
            return out;
        })()""")
        ext = [l for l in links if l['ext']]
        self.ok(bool(links), 'the building sheet should offer somewhere to go', j)
        bad = [l for l in ext if l['target'] != '_blank' or 'noopener' not in l['rel']]
        self.ok(not bad, f'every off-site link needs target=_blank and rel=noopener, got {bad[:3]}', j)
        j.notes.append(f'{len(ext)} off-site link(s)')

    def j_status_chips(self, page, j, device):
        """The chips that explain what the register actually says.

        30 people opened one last month and nothing covered them. The chip also
        re-renders part of the sheet, which is the same place the open-data
        counts were being wiped, so this checks those survive too.
        Added 2026-09-09 from the events table.
        """
        self.boot(page, f'/#d={BBL}')
        if not self.detail_open(page):
            page.evaluate(f"location.hash = '#d={BBL}'"); time.sleep(1.5)
        self.ok(self.detail_open(page), 'the building sheet should open from a #d= link', j)
        chips = page.evaluate("document.querySelectorAll('#detail-sheet [data-status]').length")
        self.ok(chips > 0, 'a stabilized building should show at least one status chip', j)
        self.click(page, '#detail-sheet [data-status]'); time.sleep(0.6)
        shown = page.evaluate("(()=>{const d=document.querySelector('#detail-sheet .d-status-def'); return d && !d.hidden && d.textContent.trim().length > 20})()")
        self.ok(shown, 'tapping a status chip should explain what it means', j)
        self.ok(page.evaluate("document.querySelector('#detail-sheet [data-status]').getAttribute('aria-expanded') === 'true'"),
                'the chip should report its expanded state to a screen reader', j)
        self.ok(page.evaluate("document.querySelectorAll('#detail-sheet [data-oc]').length") == 4,
                'the open-data buttons must survive the status re-render', j)
        j.notes.append(f'{chips} status chip(s)')

    def j_referral_gate(self, page, j, device):
        """Invite a friend, both get Plus — 39 people opened it last month.

        Signed out it must become the sign-up modal rather than a broken empty
        sheet, because the link can only be minted for an account. That gate is
        the whole journey: it is the difference between an invite flow and a
        dead button. Added 2026-09-09 from the events table.
        """
        self.boot(page)
        # The button only shows once auth has resolved; signed out it is hidden,
        # so drive the same entry point the header button uses.
        hidden = page.evaluate("(()=>{const b=document.getElementById('ref-btn'); return !b || b.hidden})()")
        self.ok(hidden, 'the Free Plus button should stay hidden until someone is signed in', j)
        page.evaluate("document.getElementById('ref-btn').hidden = false")
        self.click(page, '#ref-btn'); time.sleep(0.8)
        self.ok(page.evaluate("document.getElementById('referral-modal').hidden"),
                'signed out, the referral modal must not open with an empty link', j)
        self.ok(not page.evaluate("document.getElementById('auth-modal').hidden"),
                'signed out, inviting should ask for an account first', j)
        sub = (page.evaluate("document.getElementById('auth-submit').textContent") or '').lower()
        self.ok('create' in sub or 'sign up' in sub, f'the gate should open in sign-up mode, got {sub!r}', j)
        # and the modal it would have opened is wired: close button and a copy CTA
        page.evaluate("document.querySelector('[data-auth=\"close\"]')?.click()"); time.sleep(0.3)
        self.ok(page.evaluate("!!document.getElementById('ref-copy') && !!document.getElementById('ref-link')"),
                'the referral modal needs its link field and copy button', j)
        j.notes.append('gated to sign-up')

    def j_signin_modal(self, page, j, device):
        self.boot(page)
        self.click(page, '#auth-btn'); time.sleep(0.6)
        self.ok(not page.evaluate("document.getElementById('auth-modal').hidden"), 'Sign in should open the modal', j)
        self.ok(page.evaluate("!!document.querySelector('#auth-google')"), 'sign-in modal lacks Google', j)
        page.evaluate("document.querySelector('[data-auth=\"close\"]')?.click()"); time.sleep(0.3)
        self.ok(page.evaluate("document.getElementById('auth-modal').hidden"), 'modal should close', j)

    JOURNEYS = ['land', 'search_address', 'search_area', 'search_zip_and_miss', 'pin_and_list',
                'filters_and_save', 'deep_links_and_view', 'city_pages', 'city_records', 'no_signed_out_flash', 'no_chip_row_flash', 'memory', 'alerts_page', 'signin_modal', 'app_chip', 'app_qr_menu', 'boot_is_usable', 'city_chip',
                'ad_tiles', 'outbound_links', 'status_chips', 'referral_gate']

    # ---- run --------------------------------------------------------------
    def run(self):
        t0 = time.time()
        with sync_playwright() as p:
            for device in ('phone', 'desktop'):
                b, ctx = self.context(p, device)
                for name in self.JOURNEYS:
                    if self.only and self.only not in name:
                        continue
                    j = Journey(name, device)
                    page = self.page(ctx, j)
                    try:
                        getattr(self, 'j_' + name)(page, j, device)
                    except Exception as e:
                        j.errors.append('exception: ' + str(e).splitlines()[0][:200])
                    finally:
                        try: page.close()
                        except Exception: pass
                    self.results.append(j)
                    status = 'ok  ' if not j.errors else 'FAIL'
                    print(f'{status} {j.label():<32} {"; ".join(j.notes)}')
                    for e in j.errors:
                        print(f'       - {e}')
                b.close()
        failed = [j for j in self.results if j.errors]
        print(f'\n{len(self.results) - len(failed)}/{len(self.results)} journeys passed on {self.target} in {time.time() - t0:.0f}s')
        return len(failed)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--target', choices=['local', 'live'], default='local')
    ap.add_argument('--only', default='')
    ap.add_argument('--headed', action='store_true')
    a = ap.parse_args()
    sys.exit(Runner(a.target, a.only, a.headed).run())

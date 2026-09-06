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
BBL = '2023190002'          # 2401 3RD AVE, Bronx — has violations, listings nearby
ADDR = '2401 3RD AVE'
PINS = "document.querySelectorAll('#map .leaflet-marker-icon').length"
BPINS = "document.querySelectorAll('#map .building-dot-hit').length"
LABEL = "document.getElementById('map-count').textContent"
CARDS = "document.querySelectorAll('#grid .card[data-bbl]').length"
HEAP_BUDGET_MB = 120        # desktop Chromium, after GC, after an area pick (was 114 MB before the fix at rest)
DOM_BUDGET = 40000


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
                if m.type == 'error' and 'Failed to load resource' not in m.text and 'Content Security Policy' not in m.text and 'Report Only' not in m.text else None)
        if self.html is not None:
            def route(r):
                u = r.request.url.split('#')[0]
                if u == LIVE + '/' or u.startswith(LIVE + '/?'):
                    r.fulfill(status=200, content_type='text/html; charset=utf-8', body=self.html)
                elif u.startswith(LIVE + '/static/supercluster/'):
                    r.fulfill(status=200, content_type='application/javascript', body=self.sc)
                else:
                    r.continue_()
            page.route(LIVE + '/**', route)
        return page

    def boot(self, page, path='/', wait_pins=True):
        # A hash-only change to a loaded page is not a navigation; a deep link
        # has to boot the page, so always leave first.
        if page.url.startswith(LIVE):
            page.goto('about:blank')
        page.goto(LIVE + path, wait_until='networkidle', timeout=90000)
        if wait_pins:
            page.wait_for_function('() => ' + PINS + ' > 0', timeout=60000)
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
        j.notes.append(f'{n} pills')

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
        self.click(page, '#detail-sheet [data-detail="complaints"]'); time.sleep(0.8)
        self.ok(page.evaluate("!!document.querySelector('.viol-backdrop:not([hidden])')"), 'Complaints button did not open a sheet', j)
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
            page.hover('#grid .card[data-bbl] >> nth=0'); time.sleep(0.6)
            self.ok(page.evaluate("!!document.querySelector('#map .pin-hover')"), 'hovering a tile should paint its pin green', j)
            page.mouse.move(5, 5); time.sleep(0.3)
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
            page.goto(f'{LIVE}/{city}/', wait_until='networkidle', timeout=90000)
            try:
                page.wait_for_function('() => ' + PINS + ' > 0', timeout=120000)   # LA is 67k parcels
            except Exception:
                j.errors.append(f'/{city}/ never drew pins'); continue
            time.sleep(1)
            lab = page.evaluate(LABEL)
            self.ok(int(lab.split(' of ')[1].replace(',', '')) >= low, f'/{city}/ count looks wrong: {lab}', j)
            j.notes.append(f'{city} {lab}')

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

    def j_signin_modal(self, page, j, device):
        self.boot(page)
        self.click(page, '#auth-btn'); time.sleep(0.6)
        self.ok(not page.evaluate("document.getElementById('auth-modal').hidden"), 'Sign in should open the modal', j)
        self.ok(page.evaluate("!!document.querySelector('#auth-google')"), 'sign-in modal lacks Google', j)
        page.evaluate("document.querySelector('[data-auth=\"close\"]')?.click()"); time.sleep(0.3)
        self.ok(page.evaluate("document.getElementById('auth-modal').hidden"), 'modal should close', j)

    JOURNEYS = ['land', 'search_address', 'search_area', 'search_zip_and_miss', 'pin_and_list',
                'filters_and_save', 'deep_links_and_view', 'city_pages', 'memory', 'signin_modal']

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

#!/usr/bin/env python3
"""Mapillary preview checks; mocks API responses so tests consume no API quota.
Run with the Playwright Python environment. No local server required.
"""
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
MODULE = (ROOT / 'static/mapillary-preview.js').read_text()
HTML = '''<style>.tile{position:relative;width:300px;height:150px;margin:10px}
.mly-visual{position:absolute;inset:0}img{width:100%;height:100%}[hidden]{display:none!important}</style>
<div id="tiles"></div><script>window.MAPILLARY_PREVIEW_TOKEN='test-token';</script>
<script src="/preview.js"></script>'''


def main():
    with sync_playwright() as p:
        for kind in ('chromium', 'webkit'):
            browser = getattr(p, kind).launch()
            page = browser.new_page(viewport={'width':390,'height':844})
            calls, errors = [], []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.route('http://localhost/**', lambda r: r.fulfill(
                content_type='application/javascript' if r.request.url.endswith('/preview.js') else 'text/html',
                body=MODULE if r.request.url.endswith('/preview.js') else HTML))
            def api(route):
                query = parse_qs(urlparse(route.request.url).query)
                bounds = list(map(float, query['bbox'][0].split(',')))
                lng, lat = (bounds[0]+bounds[2])/2, (bounds[1]+bounds[3])/2
                calls.append((lat,lng))
                if lat > 41:
                    route.fulfill(status=429, content_type='application/json', body='{}')
                    return
                import json
                rows = [] if lat < 39 else [{
                    'id':'sample-1', 'computed_geometry':{'coordinates':[lng,lat]},
                    'compass_angle':0, 'is_pano':False, 'captured_at':1704067200000,
                    'thumb_1024_url':'https://images.example/test.png',
                    'creator':{'username':'Test photographer'},
                }]
                route.fulfill(content_type='application/json', body=json.dumps({'data':rows}))
            page.route('https://graph.mapillary.com/**', api)
            page.route('https://images.example/**', lambda r: r.fulfill(
                content_type='image/png', body=(ROOT / 'icon-192.png').read_bytes()))
            page.goto('http://localhost/?photos=mapillary')
            def render(lat=40.8, count=1):
                page.evaluate('''([lat,count]) => {
                    document.getElementById('tiles').innerHTML=Array.from({length:count},(_,i)=>
                        '<div class="tile">'+MapillaryPreview.html({lat,lng:-73.9,a:'Test property'})+'</div>').join('');
                    MapillaryPreview.watch(document);
                }''', [lat,count])
            render(count=2)
            page.locator('.mly-credit:not([hidden])').first.wait_for()
            page.wait_for_timeout(100)
            assert len(calls)==1, 'Duplicate coordinates should share the request'
            assert page.locator('.mly-visual img:not([hidden])').count()==2
            assert '2024' in page.locator('.mly-label').first.text_content()
            assert 'CC BY-SA' in page.locator('.mly-credit').first.text_content()
            assert '/app/user/' in page.locator('.mly-author').first.get_attribute('href')
            page.evaluate("window.parentClicks=0; document.getElementById('tiles').addEventListener('click',()=>window.parentClicks++)")
            page.locator('.mly-source').first.dispatch_event('click')
            assert page.evaluate('window.parentClicks')==0, 'Attribution opened the building'
            render()
            page.locator('.mly-credit:not([hidden])').wait_for()
            assert len(calls)==1, 'Redrawing the same tile should use the cached result'
            render(38)
            page.get_by_text('No nearby street photo found',exact=True).wait_for()
            render(42)
            page.get_by_text('Photos temporarily busy',exact=True).wait_for()
            # Offscreen tiles do not query until scrolled into view.
            page.evaluate("document.getElementById('tiles').style.marginTop='2000px'")
            render(40.5)
            before=len(calls)
            page.wait_for_timeout(200)
            assert len(calls)==before
            page.locator('.tile').scroll_into_view_if_needed()
            page.locator('.mly-credit:not([hidden])').wait_for()
            assert len(calls)==before+1
            page.goto('http://localhost/')
            assert not page.evaluate('MapillaryPreview.enabled')
            assert page.evaluate('MapillaryPreview.html({lat:40,lng:-73})')==''
            # Even an explicitly selected preview is inert on the production hostname.
            page.route('https://findacrib.com/**', lambda r: r.fulfill(
                content_type='application/javascript' if r.request.url.endswith('/preview.js') else 'text/html',
                body=MODULE if r.request.url.endswith('/preview.js') else HTML))
            page.goto('https://findacrib.com/?photos=mapillary')
            assert not page.evaluate('MapillaryPreview.enabled')
            assert not errors, errors
            print(f'PASS {kind}: photos, attribution, request reuse, lazy loading, missing coverage, API errors, preview gating',flush=True)
            browser.close()


if __name__=='__main__':
    main()

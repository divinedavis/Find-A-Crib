#!/usr/bin/env python3
"""Apple photo integration and Google cost regression on phone and desktop.

Uses local app code and a stub Apple SDK; consumes no imagery quota.
"""
from playwright.sync_api import sync_playwright
from journeys import Runner, Journey, ROOT, LIVE, BBL, CITY_PAGES, PINS, ADDR
from apple_street_preview import SDK


def main():
    for city in ('', *CITY_PAGES):
        html = (ROOT / city / 'index.html').read_text()
        assert 'maps/api/streetview' not in html, f'Paid imagery remains in {city or "NYC"}'
        assert 'maps/embed/v1/streetview' not in html
        assert 'GMAPS_KEY' not in html

    runner = Runner('local', '', False)
    with sync_playwright() as p:
        for device in ('phone', 'desktop'):
            browser, ctx = runner.context(p, device)
            j = Journey('apple_photos', device)
            page = runner.page(ctx, j)
            google, pending_hpd = [], []
            def block_google(route):
                google.append(True)
                route.abort()
            page.route('**/maps/api/streetview*', block_google)
            page.route('**/maps/embed/v1/streetview?*', block_google)
            page.route('https://cdn.apple-mapkit.com/**', lambda r: r.fulfill(
                content_type='application/javascript', body=SDK))
            page.route('**/config.js*', lambda r: r.fulfill(
                content_type='application/javascript', body="window.APPLE_MAPS_TOKEN='test.web.token';"))
            page.add_init_script('window.testCreated=0;window.testLoading=0;window.testMaxLoading=0;window.testDestroyed=0;')
            page.route(LIVE + '/buildings.hpd.json', lambda r: pending_hpd.append(r))
            page.goto(LIVE + '/#b=' + BBL, wait_until='domcontentloaded')
            assert runner.wait_until(page, PINS + ' > 0', timeout=60000)
            if device == 'phone':
                assert runner.wait_until(page, "!document.getElementById('building-card').hidden")
                page.locator('#building-card .apple-street-status[hidden]').wait_for(state='attached')
                page.locator('#building-card [data-card="details"]').click()
            else:
                runner.typeq(page, ADDR)
                runner.pick_first(page)
            page.locator('#detail-sheet .apple-street-status[hidden]').wait_for(state='attached')
            frame = page.locator('#detail-sheet .apple-street-canvas iframe')
            assert frame.count() == 1
            frame.evaluate('(f)=>f.dataset.testIdentity="retained"')
            for route in pending_hpd:
                route.fulfill(content_type='application/json', body=(ROOT / 'buildings.hpd.json').read_text())
            page.wait_for_timeout(1200)
            assert frame.get_attribute('data-test-identity') == 'retained', 'Records refresh reset photo'
            assert page.locator('.street-view-controls a').get_attribute('href').startswith('https://maps.apple.com/look-around?coordinate=')
            page.evaluate('''()=>{
              window.testReleaseTimes=[];
              const release=AppleStreetPreview.release;
              AppleStreetPreview.release=root=>{testReleaseTimes.push(performance.now());return release(root);};
            }''')
            immediate = page.evaluate('''()=>{
              document.querySelector('#detail-sheet [data-detail="close"]').click();
              return {hidden:document.getElementById('detail-sheet').hidden,releases:testReleaseTimes.length};
            }''')
            assert immediate['hidden'], 'Back should hide detail immediately'
            assert immediate['releases'] == 0, 'Viewer teardown blocked the first paint'
            page.locator('#detail-sheet iframe').wait_for(state='detached', timeout=3000)
            assert page.evaluate('testReleaseTimes.length') == 1, 'Deferred cleanup did not release viewer'
            assert not google, 'Browsing requested Google imagery'
            assert not j.errors, j.errors
            print(f'PASS {device}: Apple photos, no Google imagery, records refresh, detail cleanup', flush=True)
            page.close()

            j = Journey('apple_no_token', device)
            page = runner.page(ctx, j)
            page.route('**/config.js*', lambda r: r.fulfill(content_type='application/javascript', body=''))
            runner.boot(page, '/#b=' + BBL)
            if device == 'phone':
                page.locator('#building-card [data-card="details"]').click()
            else:
                runner.typeq(page, ADDR)
                runner.pick_first(page)
            page.locator('#detail-sheet').get_by_text('Street photo temporarily unavailable', exact=True).wait_for()
            assert page.locator('.street-view-controls a').is_visible()
            assert not page.locator('#detail-sheet iframe').count()
            assert not j.errors, j.errors
            print(f'PASS {device}: missing token leaves Apple Maps link', flush=True)
            browser.close()


if __name__ == '__main__':
    main()

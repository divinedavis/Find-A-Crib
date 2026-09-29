#!/usr/bin/env python3
"""Check visible dashboard rates and badges with synthetic API data.

Run with ~/.venvs/dhcr-map/bin/python tests/dashboard_benchmarks.py [--live].
"""
import argparse
import re

from playwright.sync_api import expect, sync_playwright

from dashboard_auth import BASE, ROOT, USER, callback


def run(browser, live):
    context = browser.new_context()
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    if not live:
        page.route(BASE + '/dashboard/', lambda route: route.fulfill(
            path=str(ROOT / 'dashboard/index.html'), content_type='text/html'))
        for path in ('config.js', 'static/supabase/supabase.js'):
            page.route(BASE + '/' + path, lambda route, request, path=path: route.fulfill(
                path=str(ROOT / path), content_type='application/javascript'))
    page.route('**/auth/v1/user', lambda route: route.fulfill(json=USER))
    payload = {}
    page.route('**/api/dashboard-*', lambda route: route.fulfill(json=payload))

    # The screenshot's rates must win over a contradictory hidden cohort and
    # per-visit rate. Also exercise band boundaries, rounding and small samples.
    cases = [
        ('reported mismatch', 1981, 308, 68, 13,
         ('16%', 'above benchmark'), ('3.4%', 'above benchmark'), ('0.7%', 'below benchmark')),
        ('lower boundary', 1000, 130, 20, 20,
         ('13%', 'in line'), ('2.0%', 'in line'), ('2.0%', 'in line')),
        ('upper boundary', 1000, 120, 30, 30,
         ('12%', 'below benchmark'), ('3.0%', 'in line'), ('3.0%', 'in line')),
        ('alert above band', 1000, 140, 10, 40,
         ('14%', 'above benchmark'), ('1.0%', 'below benchmark'), ('4.0%', 'above benchmark')),
        ('rounded boundaries', 10000, 1349, 304, 196,
         ('13%', 'in line'), ('3.0%', 'in line'), ('2.0%', 'in line')),
        ('small sample', 50, 20, 10, 10,
         ('40%', None), ('20.0%', None), ('20.0%', None)),
    ]
    for name, visitors, returning, accounts, alerts, ret, signup, alert in cases:
        payload.clear()
        payload.update({
            'totals': {'visitors': visitors, 'returning': returning,
                       'accounts': accounts, 'visits': visitors * 10},
            'alerts': {'signups': alerts},
            'retention': {'d30': {'within_rate': 0.01, 'within_cohort': 5000}},
        })
        if name == 'reported mismatch':
            page.goto(BASE + '/dashboard/' + callback(), wait_until='networkidle')
        else:
            page.reload(wait_until='networkidle')
        expect(page.locator('#app')).to_be_visible()
        for label, (rate, verdict) in [
            ('Returning visitors · this range', ret),
            ('Sign-up conversion', signup),
            ('Alert sign-up conversion', alert),
        ]:
            tile = page.locator('#tiles .tile').filter(
                has=page.get_by_text(label, exact=True))
            expect(tile.locator('.t-val')).to_contain_text(rate)
            if verdict is None:
                expect(tile.locator('.bn')).to_have_count(0)
                expect(tile).to_contain_text('too few visitors to compare')
            else:
                expect(tile.locator('.bn')).to_have_text(verdict)
                expected_class = {'above benchmark': 'bn-hi', 'below benchmark': 'bn-low',
                                  'in line': 'bn-mid'}[verdict]
                assert expected_class in tile.locator('.bn').get_attribute('class').split()
        expect(page.locator('#tiles')).to_contain_text('Selected range vs. a 30-day window')
        assert not errors, errors
        print(f'PASS {browser.browser_type.name}: {name}', flush=True)

    # Page views (replaced the time-on-site tile, 2026-09-28).
    payload['page_views'] = {'total': 10735, 'map': 10232, 'other': 503}
    page.reload(wait_until='networkidle')
    tile = page.locator('#tiles .tile').filter(
        has=page.get_by_text('Page views · website', exact=True))
    expect(tile.locator('.t-val')).to_have_text('10,735')
    expect(tile).to_contain_text('10,232 on the map · 503 on building, landlord & guide pages')
    expect(page.locator('#tiles')).not_to_contain_text('Median time on site')
    payload['page_views_30d'] = {'total': 10344, 'map': 9961, 'other': 383}
    page.reload(wait_until='networkidle')
    expect(page.locator('#page-goal2')).to_contain_text('Page view goal: 25k/month to register for Raptive')
    expect(page.locator('#page-goal2')).to_contain_text('10,344 in the last 30 days · 41%')
    assert not errors, errors
    print(f'PASS {browser.browser_type.name}: page views tile', flush=True)

    # The ads-served tile (replaced MRR): total of the three live surfaces;
    # TestFlight test ads are named but never added in.
    payload['ads_served'] = {'web_tiles': 146455, 'app_tiles': 884, 'admob': 12,
                             'admob_test': 40, 'total': 147351}
    page.reload(wait_until='networkidle')
    tile = page.locator('#tiles .tile').filter(
        has=page.get_by_text('Ads served · all platforms', exact=True))
    expect(tile.locator('.t-val')).to_have_text('147,351')
    expect(tile).to_contain_text('146,455 web tiles · 884 app tiles · 12 Google ads')
    expect(tile).to_contain_text('40 TestFlight test ads not counted')
    expect(page.locator('#tiles')).not_to_contain_text('· MRR')
    # A site still in AdSense review: Google's ads are named, never added in.
    payload['ads_served'] = {'web_tiles': 10, 'app_tiles': 2, 'admob': 0, 'adsense': 0,
                             'adsense_review': 6, 'total': 12}
    page.reload(wait_until='networkidle')
    expect(tile.locator('.t-val')).to_have_text('12')
    expect(tile).to_contain_text('6 AdSense ads from review never counted')
    # Mediavine (2026-09-29): the page's own count, paid vs filler, per page view.
    payload['mediavine'] = {'paid': 40, 'house': 60, 'total': 100, 'rows': 12}
    payload['page_views'] = {'total': 50, 'map': 45, 'other': 5}
    page.reload(wait_until='networkidle')
    mv = page.locator('#tiles .tile').filter(has=page.get_by_text('Mediavine ads · website', exact=True))
    expect(mv.locator('.t-val')).to_have_text('100')
    expect(mv).to_contain_text('40 paid · 60 Mediavine filler · 2.0 per page view')
    expect(mv).to_contain_text('Add your Page RPM from Mediavine')
    payload['mediavine']['page_rpm'] = 12
    page.reload(wait_until='networkidle')
    expect(mv).to_contain_text('$0.60 at your $12.00 page RPM')
    payload.pop('ads_served')
    page.reload(wait_until='networkidle')
    expect(tile.locator('.t-val')).to_have_text('—')
    assert not errors, errors
    print(f'PASS {browser.browser_type.name}: ads served tile', flush=True)

    # A range with nothing cached dims the old numbers and says "Loading…"
    # until its payload lands, instead of sitting there looking frozen.
    # Delay in the page, not the route handler: a sleeping sync handler
    # stalls Playwright itself and the click lands after every fetch is done.
    page.add_init_script("""(() => {
      const f = window.fetch;
      window.fetch = (u, o) => String(u).includes('/api/dashboard-')
        ? new Promise(r => setTimeout(() => r(f(u, o)), 1500)) : f(u, o);
    })()""")
    page.reload(wait_until='domcontentloaded')
    expect(page.locator('#tiles .tile').first).to_be_visible(timeout=15000)
    content = page.locator('#top')
    page.locator('#range-switch button[data-range="today"]').click()
    expect(content).to_have_class(re.compile(r'\bloading\b'))
    expect(page.locator('#range-note')).to_contain_text('today')
    expect(content).not_to_have_class(re.compile(r'\bloading\b'), timeout=15000)
    assert not errors, errors
    print(f'PASS {browser.browser_type.name}: range loading state clears', flush=True)
    context.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    with sync_playwright() as playwright:
        for engine in (playwright.chromium, playwright.webkit):
            browser = engine.launch()
            run(browser, args.live)
            browser.close()

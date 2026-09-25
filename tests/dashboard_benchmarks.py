#!/usr/bin/env python3
"""Check visible dashboard rates and badges with synthetic API data.

Run with ~/.venvs/dhcr-map/bin/python tests/dashboard_benchmarks.py [--live].
"""
import argparse

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

    # The time tile: website headline, iPhone app median on its own line.
    for app, want in [
        ({'sessions': 104, 'engaged': 99, 'median_secs': 151}, 'iPhone app 2m 31s median · 99 sessions'),
        ({'sessions': 13, 'engaged': 11, 'median_secs': 36}, 'iPhone app 36s median · 11 sessions · small sample'),
        ({'sessions': 2, 'engaged': 0, 'median_secs': None}, 'iPhone app — no engaged sessions in this range'),
    ]:
        payload['dwell'] = {'sessions': 260, 'engaged': 211, 'median_secs': 84, 'mean_all_secs': 235}
        payload['dwell_app'] = app
        page.reload(wait_until='networkidle')
        tile = page.locator('#tiles .tile').filter(
            has=page.get_by_text('Median time on site · website', exact=True))
        expect(tile.locator('.t-val')).to_contain_text('1m 24s')
        expect(tile).to_contain_text(want)
        assert not errors, errors
        print(f'PASS {browser.browser_type.name}: app time {want}', flush=True)

    # The ads-served tile (replaced MRR): total of the three live surfaces;
    # TestFlight test ads are named but never added in.
    payload['ads_served'] = {'web_tiles': 146455, 'app_tiles': 884, 'admob': 12,
                             'admob_test': 40, 'total': 147351}
    page.reload(wait_until='networkidle')
    tile = page.locator('#tiles .tile').filter(
        has=page.get_by_text('Ads served · all platforms', exact=True))
    expect(tile.locator('.t-val')).to_have_text('147,351')
    expect(tile).to_contain_text('146,455 web tiles · 884 app tiles · 12 AdMob banner')
    expect(tile).to_contain_text('40 TestFlight test ads not counted')
    expect(page.locator('#tiles')).not_to_contain_text('· MRR')
    payload.pop('ads_served')
    page.reload(wait_until='networkidle')
    expect(tile.locator('.t-val')).to_have_text('—')
    assert not errors, errors
    print(f'PASS {browser.browser_type.name}: ads served tile', flush=True)
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

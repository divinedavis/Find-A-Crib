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
    expect(page.locator('#page-goal2')).to_contain_text('Raptive: 25k Google Analytics page views in 30 days')
    expect(page.locator('#page-goal2')).to_contain_text('≈10,344 (our count; Raptive reads GA) · 41%')
    expect(page.locator('#page-goal2-gates')).to_contain_text('≥50% of traffic from US/UK/CA/AU/NZ')
    expect(page.locator('#page-goal2-gates')).to_contain_text('domain 6+ months old')
    expect(page.locator('#page-goal2-gates')).to_contain_text('long-form content on most pages')
    assert not errors, errors
    print(f'PASS {browser.browser_type.name}: page views tile', flush=True)

    # Visitors and sign-ups over time (2026-09-30): two linked panels with a
    # 7/30/90/all picker replace the shared bar card on this tab.
    payload['daily_series'] = {
        'days': [{'date': '2026-09-%02d' % d, 'visitors': 100 + d, 'signups': d % 4} for d in range(1, 31)],
        'periods': {'7': {'visitors': 700, 'prev_visitors': 600, 'signups': 14, 'prev_signups': 10},
                    '30': {'visitors': 2500, 'prev_visitors': 900, 'signups': 45, 'prev_signups': 5},
                    '90': {'visitors': 2600, 'prev_visitors': 0, 'signups': 46, 'prev_signups': 0},
                    'all': {'visitors': 2650, 'signups': 47}}}
    page.reload(wait_until='networkidle')
    expect(page.locator('#sec-visitor-trend #vt-svg')).to_be_visible()
    expect(page.locator('#sec-visitor-trend #vs-svg')).to_be_visible()
    expect(page.locator('#spark-card')).to_be_hidden()
    page.select_option('#vt-range', '7')
    expect(page.locator('#vt-sum')).to_contain_text('700')
    expect(page.locator('#vt-sum')).to_contain_text('+17%')
    page.select_option('#vt-range', '0')
    expect(page.locator('#vt-sum')).to_contain_text('since 24 Jun')
    page.select_option('#vt-range', '30')
    expect(page.locator('#fac-investor-callout')).to_have_count(0)
    assert not errors, errors
    print(f'PASS {browser.browser_type.name}: visitors chart', flush=True)

    # "Ads served · all platforms" was removed (owner, 2026-09-30): it was
    # mostly our own listing tiles. It must not come back by accident.
    page.reload(wait_until='networkidle')
    expect(page.locator('#tiles')).not_to_contain_text('Ads served · all platforms')
    expect(page.locator('#tiles')).not_to_contain_text('Pay conversion · visitors who paid')
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
    # Free-to-paid (2026-09-30): the industry's one pay-conversion number —
    # paying Plus ÷ all accounts against the 2–5% freemium band.
    payload.setdefault('totals', {})['accounts_all'] = 250
    payload['subscriptions'] = dict(payload.get('subscriptions') or {}, paying=5, mrr=24.95)
    page.reload(wait_until='networkidle')
    ftp = page.locator('#tiles .tile').filter(has=page.get_by_text('Free-to-paid conversion', exact=True))
    expect(ftp.locator('.t-val')).to_have_text('2.0%')
    expect(ftp).to_contain_text('5 paying of 250 accounts')
    expect(ftp).to_contain_text('inside the band')
    expect(page.locator('#tiles .tile')).to_have_count(9)
    assert not errors, errors
    print(f'PASS {browser.browser_type.name}: ad and pay tiles', flush=True)

    # Product health card removed (owner, 2026-09-30); the iPhone section is
    # one downloads trend chart now, no tiles (same owner, same day).
    expect(page.locator('#sec-fac-health')).to_have_count(0)
    payload['appstore'] = {
        'as_of': '2026-09-12', 'updated': '2026-09-13T09:00:00Z',
        'summary': {'d28': {'conv_page_view': 50.0}},
        'days': {'2026-09-09': {'downloads_first': 4, 'page_views': 10},
                 '2026-09-10': {'downloads_first': 2, 'page_views': 6, 'redownloads': 1},
                 '2026-09-12': {'downloads_first': 6, 'page_views': 9}}}
    page.reload(wait_until='networkidle')
    card = page.locator('#sec-appstore')
    expect(card).to_be_visible()
    expect(card.locator('#dl-svg')).to_have_count(1)
    expect(card.locator('.ads-tile')).to_have_count(0)
    expect(card.locator('#dl-sum')).to_contain_text('12')          # 4+2+0+6 first-time downloads
    expect(card.locator('#dl-sum')).to_contain_text('50%')
    expect(card.locator('#dl-table tr')).to_have_count(5)           # header + 4 days (9/11 reads as 0)
    card.locator('#dl-range').select_option('7')
    page.wait_for_timeout(500)
    expect(card.locator('#dl-svg')).to_have_count(1)
    assert not errors, errors
    print(f'PASS {browser.browser_type.name}: downloads chart, no health card', flush=True)

    # Alert sign-ups before / after the paywall (owner, 2026-09-30): three
    # lines — before (to 30 Sep), after-tried (dashed) and after-paid (from
    # 30 Sep) — and a before/after summary.
    def day(d, **kw):
        base = {'date': d, 'visitors': 1000, 'signups': 20, 'on': 20, 'gf_signups': 20,
                'visitors_day': 150, 'signups_day': 3, 'on_day': 3,
                'post_visitors': None, 'post_signups': None, 'post_on': None}
        base.update(kw); return base
    payload['alert_trend'] = [day('2026-09-28'), day('2026-09-29'),
                              day('2026-09-30', gf_signups=19, post_visitors=200, post_signups=2, post_on=0),
                              day('2026-10-01', post_visitors=400, post_signups=6, post_on=2)]
    page.reload(wait_until='networkidle')
    at = page.locator('#sec-alert-trend')
    expect(at.locator('#at-legend')).to_contain_text('Before paywall — set up an alert')
    expect(at.locator('#at-legend')).to_contain_text('After paywall — tried (saved an alert)')
    expect(at.locator('#at-legend')).to_contain_text('After paywall — paid (alerts on)')
    expect(at.locator('#at-svg path[stroke-dasharray]')).to_have_count(1)
    expect(at.locator('#at-sum')).to_contain_text('6 tried · 2 paid')
    expect(at.locator('#at-sum')).to_contain_text('of 400 visitors since 30 Sep (0.50% paid')
    # The before line stops at 30 Sep: its path has 3 points, not 4.
    pre_d = at.locator('#at-svg path').first.get_attribute('d')
    assert pre_d.count('L') == 2, pre_d
    assert not errors, errors
    print(f'PASS {browser.browser_type.name}: alert chart before/after paywall', flush=True)

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

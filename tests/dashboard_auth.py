#!/usr/bin/env python3
"""Exercise dashboard auth with the real SDK and synthetic auth/API responses.

Run with ~/.venvs/dhcr-map/bin/python tests/dashboard_auth.py [--live].
No real account credentials are used or sent to an authentication service.
"""
import argparse
import base64
import json
from pathlib import Path
import time
from urllib.parse import urlencode

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://divinedavis.com'   # the dashboard's home since 2026-09-18
USER = {'id': 'dashboard-test-owner', 'email': 'owner@example.com', 'user_metadata': {}}


def callback():
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip('=')
    now = int(time.time())
    token = '.'.join([encode({'alg': 'ES256', 'typ': 'JWT'}),
                      encode({'sub': USER['id'], 'aud': 'authenticated',
                              'iat': now, 'exp': now + 3600}), 'test-signature'])
    return '#' + urlencode({'access_token': token, 'refresh_token': 'test-refresh',
                            'expires_in': 3600, 'expires_at': now + 3600,
                            'provider_token': 'test-provider', 'sb': '',
                            'token_type': 'bearer'})


def run(browser, live, scenario):
    context = browser.new_context()
    page = context.new_page()
    errors, authorizations = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    if not live:
        page.route(BASE + '/dashboard/', lambda route: route.fulfill(
            path=str(ROOT / 'dashboard/index.html'), content_type='text/html'))
        for served, path in (('dashboard/supabase-config.js', 'dashboard/supabase-config.js'),
                             ('dashboard/supabase.js', 'static/supabase/supabase.js')):
            page.route(BASE + '/' + served + '*', lambda route, request, path=path: route.fulfill(
                path=str(ROOT / path), content_type='application/javascript'))

    def auth(route):
        url = route.request.url
        if '/authorize?' in url:
            authorizations.append(url)
            route.fulfill(content_type='text/html', body='Google sign-in redirect')
        elif '/logout' in url:
            route.fulfill(status=204)
        elif '/user' in url:
            if scenario == 'rejected_callback':
                route.fulfill(status=401, json={'code': 'bad_jwt', 'message': 'Invalid session'})
            else:
                route.fulfill(json=USER)
        else:
            raise AssertionError('Unexpected auth request: ' + url.split('?')[0])

    page.route('**/auth/v1/**', auth)
    slowed = []

    def feed(route):
        # slow_feed: a signed-in owner whose metrics take longer than the 8 s
        # sign-in failsafe (cold all-time loads ran 8-9 s on 2026-09-26).
        # Only the first call: the page then prefetches every range, and each
        # blocked handler would stack another 10 s onto the wait.
        if scenario == 'slow_feed' and not slowed:
            slowed.append(1)
            time.sleep(10)
        route.fulfill(status=403 if scenario == 'forbidden_signout' else 200, json={})
    page.route('**/api/dashboard-*', feed)
    suffix = '' if scenario == 'signed_out' else callback()
    if scenario == 'provider_error':
        suffix = '#error=access_denied&error_description=Test+denial'
    page.goto(BASE + '/dashboard/' + suffix, wait_until='networkidle')

    if scenario == 'slow_feed':
        expect(page.locator('#app')).to_be_visible()
        # The failsafe used to fire at 8 s and write this under the sign-in
        # button, blaming sign-in for a slow data load.
        assert 'taking too long' not in (page.locator('#gate-err').text_content() or '')
        assert not errors, errors
        context.close()
        return
    elif scenario == 'success':
        expect(page.locator('#app')).to_be_visible()
        assert not page.evaluate('location.hash')
        page.reload(wait_until='networkidle')
        expect(page.locator('#app')).to_be_visible()
        page.locator('#signout').click()
        expect(page.locator('#gate')).to_be_visible()
        expect(page.locator('#google-btn')).to_contain_text('Sign in with Google')
    elif scenario == 'forbidden_signout':
        expect(page.locator('#gate-title')).to_have_text('Not your dashboard')
        page.locator('#google-btn').click()
        expect(page.locator('#google-btn')).to_contain_text('Sign in with Google')
    elif scenario in ('rejected_callback', 'provider_error'):
        expect(page.locator('#gate-err')).to_be_visible()
        expect(page.locator('#gate-err')).to_contain_text('Couldn’t finish signing you in')
        assert not page.evaluate('location.hash')
        expect(page.locator('#app')).not_to_be_visible()
    else:
        expect(page.locator('#gate')).to_be_visible()
        expect(page.locator('#gate-err')).not_to_be_visible()

    page.locator('#google-btn').click()
    page.wait_for_url('**/auth/v1/authorize?**')
    assert authorizations and 'provider=google' in authorizations[0]
    assert 'redirect_to=https%3A%2F%2Fdivinedavis.com%2Fdashboard%2F' in authorizations[0]
    assert not errors, errors
    context.close()


# The Users table renders from /api/dashboard-users. This drives it with three
# synthetic accounts — one on the app, one on a phone browser, one on a
# computer — and checks the column the owner reads to know which front end
# people are on (2026-09-23), plus that the Sign-in column is gone.
USERS_ROWS = [
    {'name': 'App user', 'email': 'a@example.com', 'provider': 'google',
     'created_at': '2026-09-01T00:00:00Z', 'last_seen': '2026-09-23T00:00:00Z',
     'device': 'app', 'phone': 'iphone', 'saves': 1, 'alerts': True,
     'ios_app': True, 'ios_build': '79'},
    {'name': 'Phone browser', 'email': 'b@example.com', 'provider': 'email',
     'created_at': '2026-09-02T00:00:00Z', 'last_seen': '2026-09-22T00:00:00Z',
     'device': 'mobile_web', 'phone': 'android', 'saves': 0, 'alerts': False},
    {'name': 'Computer', 'email': 'c@example.com', 'provider': 'apple',
     'created_at': '2026-09-03T00:00:00Z', 'last_seen': '2026-09-21T00:00:00Z',
     'device': 'desktop', 'phone': None, 'saves': 0, 'alerts': False},
]


def run_users_table(browser, live):
    context = browser.new_context()
    page = context.new_page()
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    if not live:
        page.route(BASE + '/dashboard/users/', lambda route: route.fulfill(
            path=str(ROOT / 'dashboard/users/index.html'), content_type='text/html'))
        for served, path in (('dashboard/supabase-config.js', 'dashboard/supabase-config.js'),
                             ('dashboard/supabase.js', 'static/supabase/supabase.js')):
            page.route(BASE + '/' + served + '*', lambda route, request, path=path: route.fulfill(
                path=str(ROOT / path), content_type='application/javascript'))
    page.route('**/auth/v1/**', lambda route: route.fulfill(json=USER)
               if '/user' in route.request.url else route.fulfill(status=204))
    page.route('**/api/dashboard-users', lambda route: route.fulfill(json={'users': USERS_ROWS}))
    page.goto(BASE + '/dashboard/users/' + callback(), wait_until='networkidle')

    expect(page.locator('#urows tr')).to_have_count(3)
    # The header text is upper-cased by CSS, so compare in one case.
    headers = [h.strip().lower() for h in page.locator('#uhead th').all_inner_texts()]
    assert not any('sign-in' in h for h in headers), f'the Sign-in column is gone: {headers}'
    assert any('last device' in h for h in headers), headers
    # One badge per front end, in the row for that account.
    for name, badge in (('App user', 'Mobile app'), ('Phone browser', 'Mobile web'),
                        ('Computer', 'Desktop')):
        row = page.locator('#urows tr', has_text=name)
        expect(row.locator('td').last).to_contain_text(badge)
    assert not errors, errors
    context.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true')
    args = parser.parse_args()
    with sync_playwright() as playwright:
        for engine in (playwright.chromium, playwright.webkit):
            browser = engine.launch()
            for scenario in ('signed_out', 'success', 'slow_feed', 'rejected_callback',
                             'provider_error', 'forbidden_signout'):
                run(browser, args.live, scenario)
                print(f'PASS {engine.name}: {scenario}', flush=True)
            run_users_table(browser, args.live)
            print(f'PASS {engine.name}: users_table', flush=True)
            browser.close()

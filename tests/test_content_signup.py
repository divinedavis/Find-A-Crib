"""The Sign up button in the header of every content page (owner, 2026-11-21).

Why it exists: in November 2026 a quarter of the site's web visitors landed on
a landlord, building, voucher or ZIP page, and 2 of 1,059 such visitors in
three months made an account. Those pages had no way to sign up; the only
"Sign in" was on the map.

What these tests hold in place:
  1. the button is on the pages both builders write (build_seo.page and the
     growth engine's _page), and it is the same button;
  2. it sits inside <header class="site">, which build_seo removes before it
     hashes a page, so shipping it restamps no lastmod (the 2026-08-18 and
     2026-10-06 corpus-wide restamps were both one shared string in page());
  3. it opens the map's sign-up modal through ?auth=signup, names the section
     it was clicked on, and the map files that under its own wall, `page`;
  4. it never says "free".
"""
import os
import re
import unittest

import build_seo as B
from growth import techniques as T

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "https://findacrib.com/test-signup/"


def seo_page():
    return B.page(title="T", desc="D", canonical=URL, body="<p>body</p>")


def growth_page():
    return T._page("T", "D", URL, "<p>body</p>")


def header(html):
    return re.search(r'<header class="site">.*?</header>', html, re.S).group(0)


def index_html(city=""):
    with open(os.path.join(ROOT, "web", city, "index.html"), encoding="utf-8") as f:
        return f.read()


class TheButtonIsOnEveryContentPage(unittest.TestCase):
    def test_both_builders_carry_the_same_button(self):
        self.assertEqual(B.SIGNUP_BUTTON, T.SIGNUP_BUTTON)

    def test_it_is_in_the_header_of_a_build_seo_page(self):
        self.assertIn(B.SIGNUP_BUTTON, header(seo_page()))

    def test_it_is_in_the_header_of_a_growth_page(self):
        self.assertIn(T.SIGNUP_BUTTON, header(growth_page()))

    def test_each_page_has_exactly_one(self):
        for html in (seo_page(), growth_page()):
            self.assertEqual(html.count('id="fac-signup"'), 1)

    def test_both_stylesheets_style_it_and_can_hide_it(self):
        for css in (B.CSS, T.CSS):
            self.assertIn("header.site a.signup{", css)
            self.assertIn("header.site a.signup[hidden]{display:none}", css)


class ShippingItRestampsNothing(unittest.TestCase):
    def test_the_button_is_outside_what_build_seo_hashes(self):
        with_button = seo_page()
        without = with_button.replace(B.SIGNUP_BUTTON, "")
        self.assertNotEqual(with_button, without)
        self.assertEqual(B._lastmod_body(with_button), B._lastmod_body(without))

    def test_the_button_cannot_end_the_header_early(self):
        """_lastmod_body cuts the header at the first </header>."""
        self.assertNotIn("</header>", B.SIGNUP_BUTTON)
        self.assertNotIn("fac-signup", B._lastmod_body(seo_page()))


class WhatTheButtonDoes(unittest.TestCase):
    def test_without_javascript_it_still_opens_sign_up(self):
        m = re.search(r'<a class="signup" id="fac-signup" href="([^"]+)">([^<]+)</a>', B.SIGNUP_BUTTON)
        self.assertIsNotNone(m)
        self.assertEqual(m.group(1), "/?auth=signup&amp;from=page")
        self.assertEqual(m.group(2), "Sign up")

    def test_the_section_name_is_cut_down_to_what_the_map_accepts(self):
        """The script builds `from` from the first path segment; the map keeps
        it only if it matches [a-z0-9-]{1,24}. Both ends must agree."""
        self.assertIn("replace(/[^a-z0-9-]/g,'').slice(0,24)", B.SIGNUP_BUTTON)
        self.assertIn("/^[a-z0-9-]{1,24}$/.test(f)", index_html())

    def test_a_signed_in_visitor_is_not_asked_to_sign_up(self):
        self.assertIn("/^sb-.+-auth-token$/", B.SIGNUP_BUTTON)
        self.assertIn("a.hidden=true", B.SIGNUP_BUTTON)

    def test_it_never_says_free(self):
        self.assertNotRegex(B.SIGNUP_BUTTON.lower(), r"\bfree\b")


class TheMapOpensItsOwnWall(unittest.TestCase):
    def test_the_map_reads_from_and_strips_it_from_the_address(self):
        html = index_html()
        self.assertIn("p.get('from')", html)
        self.assertIn("p.delete('from')", html)

    def test_the_click_is_logged_as_its_own_wall_with_the_section(self):
        html = index_html()
        self.assertIn("openAuthModal(PAGE_GATE_MSG, 'page', { from: authGateFrom })", html)
        self.assertIn("Object.assign({ for: wall || 'other' }, extra || {})", html)

    def test_the_wall_says_what_an_account_gets(self):
        self.assertRegex(index_html(), r"\n\s*page: PROMISE_ACCOUNT,")

    def test_the_wall_message_never_says_free(self):
        m = re.search(r"const PAGE_GATE_MSG = '([^']+)'", index_html())
        self.assertIsNotNone(m)
        self.assertNotRegex(m.group(1).lower(), r"\bfree\b")

    def test_the_city_maps_carry_the_same_handling(self):
        for city in ("sf", "la", "dc", "westchester"):
            self.assertIn("openAuthModal(PAGE_GATE_MSG, 'page', { from: authGateFrom })", index_html(city))


if __name__ == "__main__":
    unittest.main()

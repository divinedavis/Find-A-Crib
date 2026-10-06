#!/usr/bin/env python3
"""Site-wide chrome must never be able to restamp every <lastmod> on the site.

This file exists because the rule it guards has been broken twice, each time by
a correct one-line product change, and each time the damage was invisible for
days:

  2026-08-18  CITY_NAV gained three links. All 47,596 lastmods moved to that
              date and 10,000 URLs went to IndexNow in one payload.
  2026-10-06  <meta name="apple-itunes-app"> was added to page()'s <head> for
              Safari's Smart App Banner. 4,082 of the 4,105 submitted URLs were
              restamped and announced, against 318 and 327 the two nights
              before.

build_seo._lastmod_body's docstring stated the rule after the first one ("a
chrome edit must never again be able to claim 47,596 pages changed") and the
second one happened anyway, because a docstring cannot fail a build. These
assertions can.

If you added a site-wide tag to page() and this file is now red: the tag belongs
in build_seo.PAGE_CHROME (usually HEAD_CHROME), not loose in the template. That
is the whole fix — the tag still reaches every page, it just stops claiming the
page changed.
"""
import hashlib
import unittest

import build_seo as B

URL = "https://findacrib.com/test-lastmod/"


def a_page(**kw):
    kw.setdefault("title", "T")
    kw.setdefault("desc", "D")
    kw.setdefault("canonical", URL)
    kw.setdefault("body", "<p>body</p>")
    return B.page(**kw)


class ChromeIsNotContent(unittest.TestCase):
    def test_no_chrome_fragment_reaches_the_hash(self):
        body = B._lastmod_body(a_page())
        for frag in B.PAGE_CHROME:
            if frag:
                self.assertNotIn(frag, body)

    def test_every_chrome_fragment_is_actually_in_the_page(self):
        """A fragment that has drifted from the template silently stops working.

        PAGE_CHROME strips by exact match, so a constant that no longer appears
        in the rendered page removes nothing and the tag it names is back inside
        the hash with no sign that anything is wrong.
        """
        rendered = a_page()
        for frag in B.PAGE_CHROME:
            if frag:
                self.assertIn(frag, rendered)

    def test_a_new_site_wide_head_tag_changes_the_bytes_and_no_lastmod(self):
        before = a_page()
        hashed = B._lastmod_body(before)
        head, chrome = B.HEAD_CHROME, B.PAGE_CHROME
        try:
            B.HEAD_CHROME = head + '<meta name="example-site-verification" content="x">'
            B.PAGE_CHROME = (B.HEAD_CHROME,) + chrome[1:]
            after = a_page()
            self.assertNotEqual(after, before, "the tag must reach the served page")
            self.assertEqual(B._lastmod_body(after), hashed, "and must not reach the hash")
        finally:
            B.HEAD_CHROME, B.PAGE_CHROME = head, chrome

    def test_page_specific_fields_are_still_hashed(self):
        """The guard must not become 'nothing counts as a change'."""
        base = B._lastmod_body(a_page())
        for kw in ({"title": "T2"}, {"desc": "D2"}, {"body": "<p>other</p>"},
                   {"canonical": URL + "2/"}, {"og_title": "OG"},
                   {"jsonld": {"@type": "Thing"}},
                   {"robots": "noindex,follow", "robots_name": "googlebot"}):
            self.assertNotEqual(B._lastmod_body(a_page(**kw)), base, kw)


class HashRuleMigration(unittest.TestCase):
    """Narrowing the hash must not itself restamp the corpus.

    The one-time migration in _track_lastmod is the only thing standing between
    a hashing-rule change and the exact event the rule change exists to prevent.
    """

    def setUp(self):
        self._state = dict(B.LM_STATE)
        B.LM_STATE.clear()
        B.LM_NEW.clear()
        del B.LM_CHANGED[:]

    def tearDown(self):
        B.LM_STATE.clear()
        B.LM_STATE.update(self._state)
        B.LM_NEW.clear()
        del B.LM_CHANGED[:]

    def _entry(self, rule, contents, when):
        return {"h": hashlib.sha1(rule(contents).encode("utf-8")).hexdigest(), "m": when}

    def test_an_entry_from_every_superseded_rule_keeps_its_date(self):
        contents = a_page()
        for v, rule in B._LM_RULES.items():
            B.LM_STATE.clear()
            B.LM_NEW.clear()
            del B.LM_CHANGED[:]
            prev = self._entry(rule, contents, "2026-01-01")
            if v > 1:
                prev["v"] = v        # v1 entries predate stamping and carry no "v"
            B.LM_STATE[URL] = prev
            self.assertEqual(B._track_lastmod(URL, contents), "2026-01-01", f"v{v}")
            self.assertEqual(B.LM_CHANGED, [], f"v{v} must not ping IndexNow")
            self.assertEqual(B.LM_NEW[URL]["v"], B.LM_VERSION)

    def test_a_genuine_change_still_bumps_and_still_pings(self):
        contents = a_page()
        B.LM_STATE[URL] = self._entry(B._lastmod_body, a_page(desc="D2"), "2026-01-01")
        B.LM_STATE[URL]["v"] = B.LM_VERSION
        self.assertEqual(B._track_lastmod(URL, contents), B.BUILD_DATE)
        self.assertEqual(B.LM_CHANGED, [URL])


if __name__ == "__main__":
    unittest.main()

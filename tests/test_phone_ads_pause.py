"""A phone's ad tag waits for a real stop, not a look at the map (2026-11-25).

The digest of 2026-11-25 had an iPhone that died 2.3 s after "ads:load idle":
the visitor was pinch-zooming, stopped for 3.2 s, the tag went in, and they
zoomed again with the ad stack booting on top of it. It was the second death
within seconds of the tag in six days (11/20: 0.9 s), and by then the page's
own code was idle while the map moved. The loader in <head> now wants hands
off the screen 3 s and the page quiet 5 s; from 30 s the old shorter pause is
enough, and the tag no longer goes in at 30 s whatever the visitor is doing.

These tests pin the numbers and the order of the three rules; the phone
`ads_later_on_phones` journey drives the real thing.
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CITIES = ("", "dc", "la", "sf", "westchester")


def loader(city=""):
    with open(os.path.join(ROOT, "web", city, "index.html"), encoding="utf-8") as f:
        h = f.read()
    m = re.search(r"\(function \(\) \{\n  try \{ if \(localStorage\.getItem\('fac\.noads'\).*?\n\}\)\(\);\n", h, re.S)
    assert m, f"web/{city}: the ad loader is gone"
    return m.group(0)


def numbers(js):
    m = re.search(r"var MIN_MS = [^;]*;", js)
    return {k: int(v) for k, v in re.findall(r"(\w+) = (\d+)", m.group(0))}


class PhoneAdsWaitForAStop(unittest.TestCase):
    def setUp(self):
        self.js = loader()
        self.n = numbers(self.js)

    def test_a_stop_is_longer_than_a_look_at_the_map(self):
        """3.2 s between two zooms was the pause that let the tag in."""
        self.assertGreaterEqual(self.n["IDLE_MS"], 3000)
        self.assertGreaterEqual(self.n["QUIET_MS"], 5000)

    def test_the_first_seconds_are_still_ad_free(self):
        self.assertEqual(self.n["MIN_MS"], 8000)

    def test_late_in_the_visit_a_shorter_pause_is_enough_but_still_a_pause(self):
        self.assertEqual(self.n["LATE_MS"], 30000)
        self.assertGreaterEqual(self.n["LATE_IDLE_MS"], 1500)
        self.assertGreaterEqual(self.n["LATE_QUIET_MS"], 3000)
        self.assertLess(self.n["LATE_IDLE_MS"], self.n["IDLE_MS"])
        self.assertLess(self.n["LATE_QUIET_MS"], self.n["QUIET_MS"])

    def test_the_hard_limit_comes_after_the_late_window(self):
        """At 30 s the tag used to go in mid-gesture; the limit that ignores
        the visitor is now well past it, and not unbounded."""
        self.assertGreater(self.n["MAX_MS"], self.n["LATE_MS"])
        self.assertLessEqual(self.n["MAX_MS"], 60000)

    def test_each_rule_checks_hands_and_page(self):
        self.assertIn("var hands = now - last, page = now - (window.__facBusyAt || 0);", self.js)
        self.assertIn("if (now - start >= LATE_MS && hands >= LATE_IDLE_MS && page >= LATE_QUIET_MS) return load('late');", self.js)
        self.assertIn("if (now - start >= MIN_MS && hands >= IDLE_MS && page >= QUIET_MS) return load('idle');", self.js)

    def test_no_rule_fires_while_typing_or_hidden(self):
        guard = self.js.index("if (document.visibilityState === 'visible' && !typing()) {")
        for rule in ("load('max')", "load('late')", "load('idle')"):
            self.assertGreater(self.js.index(rule), guard)

    def test_other_devices_load_at_once(self):
        self.assertIn("if (!phone) return load('now');", self.js)

    def test_every_city_page_has_the_same_loader(self):
        for c in CITIES[1:]:
            self.assertEqual(loader(c), self.js, f"web/{c}/index.html drifted")


if __name__ == "__main__":
    unittest.main()

"""A phone's hidden list does not rebuild while the map is moving (2026-11-22).

The digest of 2026-11-22 had one page death: an iPhone on its first visit,
dead 22 s after boot in the middle of a pinch-zoom, with four full list
rebuilds in its last six seconds. On a phone the list is a sheet parked just
under the screen while the map shows, so every one of those rebuilds (40
cards, their photos and street previews) was for a list nobody could see.

index.html now makes a rebuild wait while the sheet is shut and run when it
opens. These tests pin the pieces; the phone `boot_is_usable` journey drives
the real thing (move the map: no rebuild; open the list: one rebuild).
"""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def html(city=""):
    with open(os.path.join(ROOT, "web", city, "index.html"), encoding="utf-8") as f:
        return f.read()


class HiddenListWaits(unittest.TestCase):
    def setUp(self):
        self.h = html()
        m = re.search(r"function refreshGrid\(\) \{.*?\n  \}\n", self.h, re.S)
        self.assertIsNotNone(m)
        self.fn = m.group(0)

    def test_hidden_means_a_phone_layout_with_the_sheet_shut(self):
        self.assertIn("const PHONE_LIST = window.matchMedia('(max-width: 900px)');", self.h)
        self.assertIn("const listHidden = () => PHONE_LIST.matches && !document.body.classList.contains('list-open');", self.h)

    def test_a_rebuild_waits_only_when_the_list_already_has_cards(self):
        """The first build must run, or the sheet would open on nothing."""
        self.assertIn("if (listHidden() && grid.querySelector('.card')) { gridLater = true; tr('grid:later'); return; }", self.fn)

    def test_the_wait_comes_after_the_counts_and_the_same_list_check(self):
        """The "X of Y" pill over the map still updates on every move, and a
        move that changes nothing is still reported as grid:same."""
        count = self.fn.index("getElementById('map-count')")
        same = self.fn.index("tr('grid:same')")
        later = self.fn.index("tr('grid:later')")
        build = self.fn.index("tr('grid:build '")
        self.assertLess(count, later)
        self.assertLess(same, later)
        self.assertLess(later, build)

    def test_a_waiting_rebuild_does_not_claim_the_list_is_current(self):
        """lastGridSig is only set once the list is really rebuilt; setting it
        before the wait would make the catch-up read "same cards" and skip."""
        self.assertLess(self.fn.index("tr('grid:later')"), self.fn.index("lastGridSig = sig;"))

    def test_opening_the_sheet_catches_up(self):
        self.assertIn("if (open && gridLater) refreshGrid();", self.h)

    def test_leaving_the_phone_layout_catches_up(self):
        self.assertIn("PHONE_LIST.addEventListener?.('change', () => { if (gridLater && !listHidden()) refreshGrid(); });", self.h)

    def test_the_city_maps_carry_it_too(self):
        for city in ("sf", "la", "dc", "westchester"):
            self.assertIn("tr('grid:later')", html(city))


class TheErrorReportKnowsTheNewStep(unittest.TestCase):
    def test_grid_later_counts_as_part_of_the_boot_feeds_redraw(self):
        import error_report as er
        self.assertTrue(er._BOOT_FEED_STEP.search("grid:later"))
        self.assertFalse(er._BOOT_FEED_STEP.search("la:mount 1/1"))


if __name__ == "__main__":
    unittest.main()

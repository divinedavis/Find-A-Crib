#!/usr/bin/env python3
"""A capped sample must span its population, and an advertised noindex must be named.

2026-10-14, from T089 canonical_integrity's scheduled revisit. Four audits in
growth/techniques.py sampled a sorted population with

    step = max(1, len(seq) // cap)
    sample = seq[::step][:cap]

and three of them documented that sample as spanning the whole set. It does so
only when len(seq) is a large multiple of cap. For cap <= len(seq) < 2*cap the
integer division floors to step=1 and the expression is just seq[:cap] — the
first cap items in sorted order.

t_canonical_integrity had been living in that band since it was activated on
2026-09-14: 1,704 advertised sitemap URLs against CANON_SITEMAP_CAP=1500, so it
read the alphabetically-first 1,500 and never once looked at the last 204, while
reporting "1500 of 1,704 listed" — a line every review since read as an 88%
sample of the advertised set.

The second half of this file pins a separate defect in the same audit, found in
the same revisit: the "advertised in a sitemap but NOINDEXED" check sat inside
the self-canonical branch, so a page whose </head> ran past CANON_HEAD_BYTES was
counted UNDETERMINED and carried its advertised noindex away unreported. That
class is a property of the robots tag alone and is now judged before the
canonical is classified at all.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from growth import techniques as T  # noqa: E402


def old_stride(seq, cap):
    """The pre-2026-10-14 idiom, kept here as the thing being compared against."""
    step = max(1, len(seq) // cap)
    return list(seq)[::step][:cap]


class EvenSampleSpansThePopulation(unittest.TestCase):
    def test_small_population_is_read_in_full(self):
        for n in (0, 1, 5, 23, 39, 40):
            self.assertEqual(T._even_sample(list(range(n)), 40), list(range(n)),
                             f"a population of {n} is at or under the cap and must be read whole")

    def test_both_ends_are_always_included(self):
        for n, cap in ((1704, 1500), (47, 24), (2999, 1500), (47165, 400), (41, 40)):
            got = T._even_sample(list(range(n)), cap)
            self.assertEqual(got[0], 0, f"n={n} cap={cap} dropped the first item")
            self.assertEqual(got[-1], n - 1, f"n={n} cap={cap} dropped the last item")

    def test_sample_size_is_exactly_the_cap(self):
        for n, cap in ((1704, 1500), (47, 24), (2999, 1500), (47165, 400)):
            self.assertEqual(len(T._even_sample(list(range(n)), cap)), cap)

    def test_no_item_is_picked_twice(self):
        for n, cap in ((1704, 1500), (41, 40), (47, 24), (2999, 1500), (3001, 1500)):
            got = T._even_sample(list(range(n)), cap)
            self.assertEqual(len(set(got)), len(got), f"n={n} cap={cap} picked a duplicate")

    def test_deterministic(self):
        seq = list(range(1704))
        self.assertEqual(T._even_sample(seq, 1500), T._even_sample(seq, 1500))

    def test_degenerate_cap(self):
        self.assertEqual(T._even_sample([1, 2, 3], 0), [])
        self.assertEqual(T._even_sample([1, 2, 3], -1), [])
        self.assertEqual(T._even_sample([7, 8, 9], 1), [7])

    def test_accepts_an_iterator(self):
        self.assertEqual(T._even_sample(iter(range(5)), 40), [0, 1, 2, 3, 4])


class TheBandTheOldStrideLostOutright(unittest.TestCase):
    """The regression itself, stated as the numbers this site actually had."""

    def test_this_sites_sitemap_population_lost_its_tail(self):
        n, cap = 1704, T.CANON_SITEMAP_CAP
        self.assertEqual(cap, 1500, "the band in these tests is stated for cap=1500")
        was = old_stride(list(range(n)), cap)
        self.assertEqual(was[-1], 1499,
                         "the old stride is expected to stop at index 1499 for 1,704 URLs")
        self.assertEqual(n - 1 - was[-1], 204, "204 advertised URLs went unread")
        now = T._even_sample(list(range(n)), cap)
        self.assertEqual(now[-1], n - 1)

    def test_worst_case_in_the_band_is_half_the_population(self):
        # Just under 2*cap the old stride read the first half and skipped the rest.
        was = old_stride(list(range(2999)), 1500)
        self.assertEqual(was[-1], 1499)
        now = T._even_sample(list(range(2999)), 1500)
        self.assertEqual(now[-1], 2998)

    def test_outside_the_band_the_two_agree_on_reach(self):
        # The building tier at 47,165 against COMPARE_SAMPLE=400 was never in the
        # band, which is why t_derived_building_facts' reading was sound.
        was = old_stride(list(range(47165)), 400)
        self.assertGreater(was[-1], 45000, "the stride already spanned the tier here")

    def test_every_call_site_now_uses_the_helper(self):
        """No executable `step = max(1, ...)` sampler is left in the module.

        Matched on the assignment rather than on the slice, because the slice
        also appears in _even_sample's own block comment, which documents the
        idiom it replaced and must stay readable.
        """
        src = (HERE.parent / "growth" / "techniques.py").read_text()
        import re
        live = [ln for ln in src.splitlines()
                if re.match(r"\s+step = max\(1, len\(", ln)]
        self.assertEqual(live, [], f"a degenerate stride sampler survives: {live}")
        for cap in ("DUP_SAMPLE", "COMPARE_SAMPLE",
                    "CANON_SECTION_SAMPLE", "CANON_SITEMAP_CAP"):
            self.assertIn(f"_even_sample(paths, {cap})" if cap != "CANON_SITEMAP_CAP"
                          else f"_even_sample(listed, {cap})", src,
                          f"{cap}'s call site does not go through _even_sample")


class Ctx:
    def __init__(self, docroot):
        self.docroot = docroot


def write(root, relpath, head, body="<p>hi</p>"):
    p = root / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"<!doctype html><html><head>{head}</head><body>{body}</body></html>")
    return p


class AdvertisedNoindexIsNamedWhateverTheCanonicalSays(unittest.TestCase):
    """The hoisted check, exercised through the real audit against a real docroot."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        # CANON_FLOOR pages of ordinary, correct filler so the audit runs at all.
        self.locs = []
        for i in range(T.CANON_FLOOR + 5):
            url = f"/filler/{i:03d}/"
            write(self.root, f"filler/{i:03d}/index.html",
                  f'<link rel="canonical" href="https://findacrib.com{url}">')
            self.locs.append(url)

    def sitemap(self, extra):
        locs = "".join(f"<url><loc>https://findacrib.com{u}</loc></url>"
                       for u in self.locs + extra)
        (self.root / "sitemap.xml").write_text(
            f'<?xml version="1.0"?><urlset>{locs}</urlset>')

    def run_audit(self):
        return T.t_canonical_integrity(Ctx(str(self.root)))

    def test_truncated_head_no_longer_hides_an_advertised_noindex(self):
        """The silent case: </head> past the read cap used to swallow the finding."""
        pad = "<!--" + ("x" * (T.CANON_HEAD_BYTES + 500)) + "-->"
        write(self.root, "trap/index.html",
              '<meta name="robots" content="noindex,follow">' + pad)
        self.sitemap(["/trap/"])
        got = self.run_audit()
        self.assertFalse(got["ok"], "a sitemap advertising a noindexed page must fail")
        self.assertIn("advertised in a sitemap but NOINDEXED", got["detail"])
        self.assertIn("/trap/", got["detail"])

    def test_self_canonical_noindex_still_reported(self):
        """The case that already worked must keep working."""
        write(self.root, "trap/index.html",
              '<meta name="robots" content="noindex"><link rel="canonical" '
              'href="https://findacrib.com/trap/">')
        self.sitemap(["/trap/"])
        got = self.run_audit()
        self.assertFalse(got["ok"])
        self.assertIn("advertised in a sitemap but NOINDEXED", got["detail"])

    def test_noindex_with_two_canonicals_names_both_faults(self):
        write(self.root, "trap/index.html",
              '<meta name="robots" content="noindex">'
              '<link rel="canonical" href="https://findacrib.com/trap/">'
              '<link rel="canonical" href="https://findacrib.com/other/">')
        self.sitemap(["/trap/"])
        got = self.run_audit()
        self.assertFalse(got["ok"])
        self.assertIn("MORE THAN ONE canonical", got["detail"])
        self.assertIn("advertised in a sitemap but NOINDEXED", got["detail"])

    def test_noindex_page_NOT_advertised_is_not_a_fault(self):
        """~46,000 building pages are deliberately noindex,follow and unlisted."""
        write(self.root, "quiet/index.html",
              '<meta name="robots" content="noindex,follow">'
              '<link rel="canonical" href="https://findacrib.com/quiet/">')
        self.sitemap([])
        got = self.run_audit()
        self.assertTrue(got["ok"], got["detail"])
        self.assertNotIn("NOINDEXED", got["detail"])

    def test_clean_docroot_reports_full_sitemap_coverage(self):
        self.sitemap([])
        got = self.run_audit()
        self.assertTrue(got["ok"], got["detail"])
        self.assertIn("no canonical defects found", got["detail"])
        self.assertIn("which is every one of the", got["detail"],
                      "under the cap the audit must say it read the whole listing")


if __name__ == "__main__":
    unittest.main(verbosity=2)

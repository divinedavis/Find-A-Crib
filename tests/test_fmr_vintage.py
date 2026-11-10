"""build_fmr.py records WHICH fiscal year it fetched, in fmr.meta.json.

2026-11-10. fmr.json is a bare {zip: [studio, 1BR, 2BR, 3BR]} map with no
vintage in it. build_fmr.py derives the federal fiscal year anyway — it is how
HUD's download URL is built — and until now threw it away, so five places on the
site hardcoded "HUD FY2026" as a guess that nothing downstream could check, and
the 2026-11-09 growth review could not establish which year's figures the live
/section8/ pages were publishing. These tests hold the fix:

  * THE META MUST DESCRIBE THE FILE BESIDE IT. A meta naming a year the data is
    not, or an effective date that is not that year's 1 October, is worse than
    no meta at all: growth.techniques._fmr_vintage would print a wrong year onto
    a rent figure a tenant is reading. The fallback path is the one that can
    produce a surprising year, so it is tested explicitly.
  * fmr.json's SHAPE MUST NOT CHANGE. Building.swift, the four city shells' EST
    table, renter_tools.py and growth.techniques.Context.fmr all read that map
    as it is; the vintage went into a sibling file precisely so none of them had
    to change, and test_fmr_json_shape_is_unchanged fails if that is undone.
  * WHAT build_fmr WRITES MUST BE WHAT THE RENDERER ACCEPTS. The two halves live
    in different files and are run on different machines (build_fmr on a
    workstation, because HUD's WAF answers the droplet with an empty 202), so
    the handshake between them is only real if something tests both ends.

SKIPPED WITHOUT openpyxl, which build_fmr imports at module scope and the
droplet's system python does not have. That is deliberate: a hard import here
would add a fifth collection error to a suite that already carries four, rather
than a skip a reader can see the reason for.
"""
import datetime as dt
import io
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import openpyxl
    import build_fmr
    HAVE = True
except ImportError:                                     # no openpyxl on this box
    HAVE = False

from growth import techniques as T  # noqa: E402

# Two ZIPs the sheet carries and one it does not, so missing_zips is non-zero.
ROWS = [("11111", [2000, 2200, 2500, 3000]), ("22222", [1000, 1100, 1200, 1500])]
WANTED = {"11111", "22222", "33333"}


def _sheet(rows):
    """A workbook shaped like HUD's SAFMR export: SAFMR at 3/6/9/12."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ZIP", "area", "name"] + [f"c{i}" for i in range(12)])
    for z, a in rows:
        r = [z, "METRO35620M", "New York"] + [None] * 12
        r[3], r[6], r[9], r[12] = a
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@unittest.skipUnless(HAVE, "openpyxl is not installed")
class MetaFile(unittest.TestCase):

    def _run(self, fetch, fy=None):
        out = tempfile.mkdtemp()
        argv, real_fetch, real_zips = sys.argv, build_fmr.fetch_safmr, build_fmr.load_zips
        build_fmr.fetch_safmr, build_fmr.load_zips = fetch, lambda: set(WANTED)
        sys.argv = ["build_fmr.py", "--out", out] + (["--fy", str(fy)] if fy else [])
        try:
            build_fmr.main()
        finally:
            sys.argv, build_fmr.fetch_safmr, build_fmr.load_zips = argv, real_fetch, real_zips
        with open(os.path.join(out, "fmr.json")) as f:
            data = json.load(f)
        with open(os.path.join(out, "fmr.meta.json")) as f:
            return data, json.load(f)

    def test_the_meta_names_the_year_that_was_fetched(self):
        _, m = self._run(lambda fy: _sheet(ROWS), fy=2027)
        self.assertEqual(m["fiscal_year"], 2027)
        self.assertEqual(m["requested_fiscal_year"], 2027)
        self.assertIs(m["fell_back"], False)
        self.assertIn("fy2027_safmrs.xlsx", m["source"])

    def test_effective_is_1_october_of_the_prior_calendar_year(self):
        """FY2027 began 2026-10-01. _fmr_vintage refuses a meta that disagrees."""
        _, m = self._run(lambda fy: _sheet(ROWS), fy=2027)
        self.assertEqual(m["effective"], "2026-10-01")

    def test_the_counts_describe_the_data_actually_written(self):
        data, m = self._run(lambda fy: _sheet(ROWS), fy=2027)
        self.assertEqual(m["zips"], len(data))
        self.assertEqual(m["zips"], 2)
        self.assertEqual(m["missing_zips"], 1)

    def test_built_is_an_iso_utc_stamp(self):
        _, m = self._run(lambda fy: _sheet(ROWS), fy=2027)
        dt.datetime.strptime(m["built"], "%Y-%m-%dT%H:%M:%SZ")

    def test_a_fallback_records_the_year_it_actually_got_not_the_one_it_wanted(self):
        """The case that would otherwise mislabel: HUD has not posted the new year.

        build_fmr asks for the derived year, 404s, and takes the year before. The
        meta must say so on every field, or the page would print the year HUD
        does not yet publish over figures from the year it does.
        """
        asked = []

        def flaky(fy):
            asked.append(fy)
            if fy == build_fmr.fiscal_year():
                raise urllib.error.HTTPError("u", 404, "not found", None, None)
            return _sheet(ROWS)

        cur = build_fmr.fiscal_year()
        _, m = self._run(flaky)
        self.assertEqual(asked, [cur, cur - 1])
        self.assertEqual(m["fiscal_year"], cur - 1)
        self.assertEqual(m["requested_fiscal_year"], cur)
        self.assertIs(m["fell_back"], True)
        self.assertEqual(m["effective"], f"{cur - 2}-10-01")

    def test_fmr_json_shape_is_unchanged(self):
        """The vintage went in a SIBLING file so no existing reader changes."""
        data, _ = self._run(lambda fy: _sheet(ROWS), fy=2027)
        self.assertEqual(data, {"11111": [2000, 2200, 2500, 3000],
                                "22222": [1000, 1100, 1200, 1500]})
        for a in data.values():
            self.assertEqual(len(a), 4)
            self.assertTrue(all(isinstance(x, int) for x in a))

    def test_what_build_fmr_writes_is_what_the_renderer_accepts(self):
        """The handshake across the two machines, tested from both ends."""
        _, m = self._run(lambda fy: _sheet(ROWS), fy=2027)
        self.assertEqual(
            T._fmr_vintage(m, dt.date(2026, 11, 10)),
            " These are HUD’s FY2027 figures, the table in effect since 1 October 2026.")

    def test_a_fallback_meta_is_also_accepted_and_reads_as_superseded(self):
        """A file one year behind must be announced as behind, not named quietly."""
        def flaky(fy):
            if fy == 2027:
                raise urllib.error.HTTPError("u", 404, "not found", None, None)
            return _sheet(ROWS)

        with unittest.mock.patch.object(build_fmr, "fiscal_year", lambda: 2027):
            _, m = self._run(flaky)
        said = T._fmr_vintage(m, dt.date(2026, 11, 10))
        self.assertIn("FY2026 figures.", said)
        self.assertIn("FY2027 table took effect on 1 October 2026", said)


@unittest.skipUnless(HAVE, "openpyxl is not installed")
class FiscalYear(unittest.TestCase):
    """build_fmr.fiscal_year and techniques._federal_fiscal_year must agree.

    They are the same two lines in two files on purpose — build_fmr imports
    openpyxl at module scope and growth.techniques is imported by the nightly
    /section8/ refresh on a box without it — so the duplication needs a test.
    """

    def test_the_two_implementations_agree_across_a_year(self):
        for month in range(1, 13):
            d = dt.date(2026, month, 15)
            self.assertEqual(build_fmr.fiscal_year(d), T._federal_fiscal_year(d),
                             f"disagree in month {month}")

    def test_both_turn_over_on_1_october(self):
        for impl in (build_fmr.fiscal_year, T._federal_fiscal_year):
            self.assertEqual(impl(dt.date(2026, 9, 30)), 2026)
            self.assertEqual(impl(dt.date(2026, 10, 1)), 2027)


if __name__ == "__main__":
    unittest.main()

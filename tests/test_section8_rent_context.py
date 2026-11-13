"""_rent_context: asking rent against the ZIP's HUD typical rent on /section8/.

2026-11-09. fmr.json has held HUD Small-Area Fair Market Rents for 178 NYC ZIPs
([studio, 1BR, 2BR, 3BR]) all along, and every one of the 253 matched voucher
rows has both a price and a ZIP in it, but nothing had ever put the two side by
side. This block does, on the hub and the borough pages.

The four things these tests exist to hold, because each is a way of being wrong
rather than merely ugly:

  * IT MUST NOT BECOME A VOUCHER-COVERAGE TEST. The cap on a voucher is the
    PHA's payment standard, not the published FMR, and the feed carries no
    bedroom count at all — so a "your voucher covers this" verdict would be a
    wrong answer to the highest-stakes question on the page. The note's
    disclaimers are pinned here, not left to review.

  * IT MUST NAME NO FISCAL YEAR IT CANNOT SUBSTANTIATE. The year hardcoded
    elsewhere on the site ("HUD FY2026" in index.html, the four city shells,
    renter_tools.py and the iOS metadata) is not safe to copy: HUD's FY2027
    figures took effect 2026-10-01. 2026-11-10 gave build_fmr.py a sibling
    fmr.meta.json recording the year it actually fetched, so the rule is now
    "name the year only when that file states it" rather than "never". NoVintage
    holds the no-meta case — byte-for-byte the 2026-11-09 wording — and Vintage
    holds every way a meta can fail to earn a label.

  * "A STUDIO" AND "A THREE-BEDROOM" MUST FIT THE ROW THEY DESCRIBE. The prose
    labels positions 0 and 3, which is only true of an ascending row, so a row
    that is not four positive ascending figures is skipped rather than described
    with a label that may not fit it.

  * A MISSING fmr.json MUST NOT TAKE /section8/ DOWN. Nothing on the droplet
    writes that file — refresh_fmr.sh scp's it from a workstation straight into
    the docroot, never into git — so a box without it is ordinary. The pages
    carry a nightly-refresh promise made by ~373 build_seo.py hub pages; losing
    them over a missing reference file would be far worse than losing one block.
"""
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from growth import ledger, techniques as T  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "data")  # the committed data files (2026-11-13)
FRESH = 2_000_000_000.0

HEAD = "How these asking rents compare with HUD’s typical rents"
BLOCK_RE = re.compile(
    r"<h2>" + HEAD + r"</h2>"
    r"<p class='sub'>(?P<lead>.*?)</p>"
    r"<div class='note'>(?P<note>.*?)</div>", re.S)

# [studio, 1BR, 2BR, 3BR] — ascending, as every real row in fmr.json is.
ZIPS = {"11111": [2000, 2200, 2500, 3000]}


def _row(i, price, zipcode="11111", boro="SI"):
    return {"addr": f"{i} Test St", "b8": False, "bbl": f"500000{i:04d}",
            "boro": boro, "boro_name": T.BORO_NAME[boro], "boro_slug": T.BORO_SLUG[boro],
            "n": 1, "nb": f"Nb{i % 3}", "price": price, "units": 10, "oc": 0,
            "url": "https://example.com/l", "zip": zipcode}


def _ctx(fmr=None, meta=None):
    """A Context whose only loaded feed is the FMR map under test.

    meta=None leaves .fmr_meta to load for real, which finds no fmr.meta.json in
    the repo and yields {} — the no-meta case the live droplet is in today.
    """
    c = T.Context(REPO, tempfile.mkdtemp())
    c.out = tempfile.mkdtemp()
    c._fmr = dict(ZIPS) if fmr is None else fmr
    if meta is not None:
        c._fmr_meta = meta
    return c


# A well-formed meta for the fiscal year that began 1 October 2026.
def _meta(fy=2027, **over):
    m = {"fiscal_year": fy, "effective": f"{fy - 1}-10-01", "zips": 178,
         "built": "2026-11-10T07:00:00Z", "fell_back": False,
         "source": "https://www.huduser.gov/x.xlsx"}
    m.update(over)
    return m


def _lead(html):
    m = BLOCK_RE.search(html)
    return m.group("lead") if m else None


class Buckets(unittest.TestCase):
    """Which side of the ZIP's span each rent lands on."""

    def _counts(self, prices):
        html = T._rent_context(_ctx(), [_row(i, p) for i, p in enumerate(prices)],
                               "right now")
        return _lead(html) or ""

    def test_at_or_below_the_studio_figure_is_below(self):
        """2000 is the studio figure — "at or below" includes it."""
        lead = self._counts([1000, 1500, 1800, 1999, 2000])
        self.assertIn("every one is at or below", lead)

    def test_at_the_three_bedroom_figure_is_inside_not_above(self):
        """3000 is the 3BR figure. Off by one here would call it unaffordable."""
        lead = self._counts([2001, 2500, 2999, 3000, 3000])
        self.assertIn("every one falls between", lead)

    def test_one_above_the_three_bedroom_figure_is_above(self):
        lead = self._counts([3001, 3500, 4000, 9000, 20000])
        self.assertIn("every one is above even the three-bedroom figure", lead)

    def test_a_mixed_page_counts_all_three(self):
        lead = self._counts([1500, 1800, 2500, 2600, 3500, 4000])
        self.assertIn("2 are at or below", lead)
        self.assertIn("2 fall between", lead)
        self.assertIn("2 are above even", lead)

    def test_the_three_buckets_partition_every_placed_row(self):
        """Any rent lands in exactly one bucket, so the counts must sum to n."""
        prices = [900, 2000, 2001, 2999, 3000, 3001, 50000]
        lead = self._counts(prices)
        self.assertEqual(sum(int(n) for n in re.findall(r"\b(\d+) (?:are|is|fall|falls)", lead)),
                         len(prices))


class Wording(unittest.TestCase):
    def test_sole_bucket_says_every_one_not_the_repeated_count(self):
        """"Of all 11 asking rents …, 11 fall between" is a tautology."""
        lead = _lead(T._rent_context(_ctx(), [_row(i, 2500) for i in range(11)],
                                    "right now"))
        self.assertIn("Of all 11 asking rents listed right now, every one falls", lead)
        self.assertNotIn("11 fall", lead)

    def test_full_coverage_says_all(self):
        lead = _lead(T._rent_context(_ctx(), [_row(i, 1500 + i * 400) for i in range(6)],
                                     "right now"))
        self.assertTrue(lead.startswith("Of all 6 asking rents listed right now,"), lead)

    def test_unplaceable_rents_are_counted_out_of_the_total_not_hidden(self):
        """Describing 8 rows under a total of 10 would overstate the sample."""
        rows = [_row(i, 1500) for i in range(8)]
        rows.append(_row(98, 1500, zipcode="99999"))   # no HUD entry
        rows.append(_row(99, 1500, zipcode=""))        # no ZIP at all
        lead = _lead(T._rent_context(_ctx(), rows, "right now"))
        self.assertTrue(lead.startswith("Of 8 of the 10 asking rents listed right now,"), lead)

    def test_rows_with_no_price_are_not_in_the_denominator(self):
        rows = [_row(i, 1500) for i in range(6)] + [_row(90, None), _row(91, 0)]
        lead = _lead(T._rent_context(_ctx(), rows, "right now"))
        self.assertTrue(lead.startswith("Of all 6 asking rents listed right now,"), lead)

    def test_a_zero_bucket_is_never_named(self):
        lead = _lead(T._rent_context(_ctx(), [_row(i, 2500) for i in range(6)],
                                     "right now"))
        self.assertNotIn("0 ", lead)
        self.assertNotIn("at or below", lead)
        self.assertNotIn("above even", lead)

    def test_singular_bucket_agrees_with_its_verb(self):
        lead = _lead(T._rent_context(_ctx(), [_row(0, 1500)] + [_row(i, 2500)
                                                               for i in range(1, 6)],
                                     "right now"))
        self.assertIn("1 is at or below", lead)
        self.assertIn("5 fall between", lead)

    def test_the_tense_degrades_with_the_feed(self):
        """Every present-tense claim on this tier derives from the feed's date."""
        lead = _lead(T._rent_context(_ctx(), [_row(i, 2500) for i in range(6)],
                                     "as of July 11, 2026"))
        self.assertIn("listed as of July 11, 2026", lead)
        self.assertNotIn("right now", lead)

    def test_the_phrase_is_escaped(self):
        html = T._rent_context(_ctx(), [_row(i, 2500) for i in range(6)],
                               'as of <script>"x"')
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_the_phrase_is_escaped_on_the_partial_coverage_branch_too(self):
        """Two branches build the subject, and each interpolates the phrase.

        The full-coverage branch above covered one of them; a mutation that
        dropped _esc() from the other survived the suite until this was added.
        """
        rows = [_row(i, 2500) for i in range(6)] + [_row(99, 2500, zipcode="99999")]
        html = T._rent_context(_ctx(), rows, 'as of <script>"x"')
        self.assertTrue(_lead(html).startswith("Of 6 of the 7 "), _lead(html))
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)


class Floor(unittest.TestCase):
    def test_below_the_floor_renders_nothing(self):
        """Staten Island's 3 rows: arithmetic the table directly above already shows."""
        rows = [_row(i, 1500 + i * 500) for i in range(T.FMR_MIN_ROWS - 1)]
        self.assertEqual(T._rent_context(_ctx(), rows, "right now"), "")

    def test_at_the_floor_renders(self):
        rows = [_row(i, 1500 + i * 500) for i in range(T.FMR_MIN_ROWS)]
        self.assertNotEqual(T._rent_context(_ctx(), rows, "right now"), "")

    def test_floor_is_above_one(self):
        """A tripwire, not a style rule.

        At a floor of 1 the sole-bucket branch would render "Of all 1 asking
        rents listed right now, every one falls …" — a span claim about a single
        listing, which is the overprecision the floor exists to prevent.
        """
        self.assertGreater(T.FMR_MIN_ROWS, 1)


class BadData(unittest.TestCase):
    """A row this cannot label honestly is skipped, never guessed at."""

    def _one_bad(self, entry):
        rows = [_row(i, 1500) for i in range(6)] + [_row(99, 1500, zipcode="22222")]
        lead = _lead(T._rent_context(_ctx({**ZIPS, "22222": entry}), rows, "right now"))
        self.assertTrue(lead.startswith("Of 6 of the 7 "), f"{entry!r} was not skipped: {lead}")

    def test_wrong_length_is_skipped(self):
        self._one_bad([2000, 2200, 2500])

    def test_non_numeric_is_skipped(self):
        self._one_bad([2000, 2200, "2500", 3000])

    def test_non_positive_is_skipped(self):
        self._one_bad([0, 2200, 2500, 3000])

    def test_booleans_are_skipped(self):
        """bool is an int in Python; True > 0 would sneak past a naive check."""
        self._one_bad([True, 2200, 2500, 3000])

    def test_descending_is_skipped(self):
        """Position 0 is only "a studio" if the row really ascends."""
        self._one_bad([3000, 2500, 2200, 2000])

    def test_not_a_list_is_skipped(self):
        self._one_bad({"studio": 2000})

    def test_an_empty_fmr_map_renders_nothing(self):
        rows = [_row(i, 1500) for i in range(6)]
        self.assertEqual(T._rent_context(_ctx({}), rows, "right now"), "")


class Loader(unittest.TestCase):
    """Context.fmr: docroot first, and never fatal."""

    def test_a_missing_file_gives_an_empty_map_rather_than_raising(self):
        c = T.Context(tempfile.mkdtemp(), tempfile.mkdtemp())
        self.assertEqual(c.fmr, {})

    def test_malformed_json_gives_an_empty_map(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "fmr.json"), "w") as f:
            f.write("{not json")
        self.assertEqual(T.Context(d, tempfile.mkdtemp()).fmr, {})

    def test_a_json_non_object_gives_an_empty_map(self):
        d = tempfile.mkdtemp()
        with open(os.path.join(d, "fmr.json"), "w") as f:
            f.write("[1, 2, 3]")
        self.assertEqual(T.Context(d, tempfile.mkdtemp()).fmr, {})

    def test_the_docroot_copy_wins_over_the_checkout(self):
        """refresh_fmr.sh updates the docroot; the committed copy is the fallback."""
        build, doc = tempfile.mkdtemp(), tempfile.mkdtemp()
        with open(os.path.join(build, "fmr.json"), "w") as f:
            f.write('{"11111": [1, 1, 1, 1]}')
        with open(os.path.join(doc, "fmr.json"), "w") as f:
            f.write('{"11111": [2, 2, 2, 2]}')
        self.assertEqual(T.Context(build, doc).fmr, {"11111": [2, 2, 2, 2]})

    def test_the_real_checkout_copy_loads_and_is_shaped_as_the_block_expects(self):
        """If fmr.json ever changes shape, fail here rather than silently render ""."""
        fmr = T.Context(DATA, tempfile.mkdtemp()).fmr
        self.assertGreater(len(fmr), 100)
        ok = [a for a in fmr.values()
              if isinstance(a, list) and len(a) == 4 and list(a) == sorted(a)
              and all(isinstance(x, (int, float)) and x > 0 for x in a)]
        self.assertEqual(len(ok), len(fmr), "some fmr.json rows are not 4 ascending figures")


class Note(unittest.TestCase):
    """The disclaimers are the feature, not decoration."""

    def setUp(self):
        html = T._rent_context(_ctx(), [_row(i, 1500 + i * 400) for i in range(6)],
                               "right now")
        self.note = BLOCK_RE.search(html).group("note")
        self.html = html

    def test_it_says_the_figure_is_not_building_specific(self):
        self.assertIn("not for this building", self.note)
        self.assertIn("whole ZIP code", self.note)

    def test_it_says_the_feed_has_no_bedroom_count(self):
        self.assertIn("does not say how many bedrooms", self.note)

    def test_it_refuses_the_voucher_coverage_reading_explicitly(self):
        self.assertIn("not a test of whether a voucher will cover the rent", self.note)

    def test_it_points_at_the_payment_standard_and_the_authority(self):
        self.assertIn("payment standard", self.note)
        self.assertIn("housing authority", self.note)
        self.assertIn("different number from the published Fair Market Rent", self.note)

    def test_it_never_claims_a_voucher_covers_anything(self):
        for bad in ("your voucher covers", "voucher will cover this",
                    "affordable to voucher", "within your voucher"):
            self.assertNotIn(bad, self.html.lower())

    def test_the_hud_link_is_external_and_untrusted(self):
        self.assertIn("huduser.gov/portal/datasets/fmr/smallarea/index.html", self.note)
        self.assertIn("rel='nofollow noopener'", self.note)


class NoVintage(unittest.TestCase):
    """With no fmr.meta.json beside it, fmr.json carries no year — claim none.

    This is the state of the live droplet as of 2026-11-10 and must stay
    byte-for-byte what 2026-11-09 shipped: refresh_fmr.sh has not run since
    build_fmr.py started writing the meta, so nothing can date these figures.
    """

    def _html(self):
        return T._rent_context(_ctx(), [_row(i, 1500 + i * 400) for i in range(6)],
                               "right now")

    def test_no_fiscal_year_is_named(self):
        self.assertIsNone(re.search(r"FY\s*\d{4}|fiscal year", self._html(), re.I))

    def test_no_bare_year_is_named(self):
        """Catches "HUD's 2026 Small-Area …" as well as the FY form."""
        html = self._html()
        self.assertIsNone(re.search(r"\b(19|20)\d\d\b", html),
                          "a year appeared in a block whose data has no vintage")

    def test_the_feed_date_still_reaches_the_lead(self):
        """The guard above must not be satisfied by dropping the feed's own date."""
        lead = _lead(T._rent_context(_ctx(), [_row(i, 2500) for i in range(6)],
                                     "as of July 11, 2026"))
        self.assertIn("July 11, 2026", lead)


class Vintage(unittest.TestCase):
    """The year is named only when fmr.meta.json earns it.

    Every refusal below is a way the label could be WRONG rather than merely
    absent, and a wrong year on a rent figure is the kind of error this site
    cannot afford: a reader who clicks through to HUD's current table and finds
    different numbers has no way to tell which of the two to trust.
    """

    # The current fiscal year is PINNED to FY2027 rather than taken from the
    # clock. Without this every assertion below flips on 2027-10-01 and a suite
    # that goes red on a date tells a future reader nothing about the code.
    def _html(self, meta, current=2027):
        rows = [_row(i, 1500 + i * 400) for i in range(6)]
        with mock.patch.object(T, "_federal_fiscal_year", lambda _d: current):
            return T._rent_context(_ctx(meta=meta), rows, "right now")

    # ---- the year is in effect: name it

    def test_current_year_is_named_with_its_effective_date(self):
        note = BLOCK_RE.search(self._html(_meta(2027))).group("note")
        self.assertIn("These are HUD\u2019s FY2027 figures, the table in effect since "
                      "1 October 2026.", note)

    def test_naming_the_year_does_not_disturb_the_disclaimers(self):
        """The vintage is additive — the voucher-coverage refusal must survive."""
        note = BLOCK_RE.search(self._html(_meta(2027))).group("note")
        self.assertIn("It is not a test of", note)
        self.assertIn("payment standard your housing authority sets", note)
        self.assertIn("does not say how many", note)
        self.assertIn("HUD publishes the current figures by ZIP", note)

    # ---- the year has been superseded: say so rather than name it quietly

    def test_a_superseded_year_says_a_newer_table_exists(self):
        note = BLOCK_RE.search(self._html(_meta(2026))).group("note")
        self.assertIn("These are HUD\u2019s FY2026 figures.", note)
        self.assertIn("FY2027 table took effect on 1 October 2026", note)
        self.assertIn("a newer set of figures exists", note)

    def test_a_superseded_year_is_not_presented_as_current(self):
        note = BLOCK_RE.search(self._html(_meta(2026))).group("note")
        self.assertNotIn("in effect since", note)

    # ---- refusals: a meta that has not earned a label

    def test_a_year_not_yet_in_effect_is_refused(self):
        """HUD posts a file before its year starts. Not-yet-current is not now."""
        import datetime as dt
        self.assertEqual(T._fmr_vintage(_meta(2030), dt.date(2026, 11, 10)), "")
        self.assertEqual(T._fmr_vintage(_meta(2028), dt.date(2026, 11, 10)), "")

    def test_a_meta_whose_two_fields_disagree_is_refused(self):
        """effective must be 1 October of fiscal_year - 1, or something else wrote it."""
        self.assertEqual(T._fmr_vintage(_meta(2027, effective="2026-01-01")), "")
        self.assertEqual(T._fmr_vintage(_meta(2027, effective=None)), "")

    def test_a_string_year_is_refused(self):
        """Also closes the injection path: only an int ever reaches the markup."""
        self.assertEqual(T._fmr_vintage(_meta(2027, fiscal_year="2027")), "")
        self.assertEqual(
            T._fmr_vintage({"fiscal_year": "2027<script>", "effective": "2026-10-01"}), "")

    def test_a_bool_year_is_refused(self):
        """True == 1 in Python, so isinstance(True, int) is not enough.

        HONEST ABOUT WHAT THIS PINS, because a mutation run on 2026-11-10 said
        so: deleting the explicit bool guard in _fmr_vintage does NOT make this
        test fail. Any bool is 0 or 1, so the 2000..2100 range check refuses it
        either way, and the bool guard is belt-and-braces that only becomes
        load-bearing if that range is ever widened. The guard is kept for that
        reason and because it states the intent at the point of the check; this
        test pins the BEHAVIOUR (a bool never reaches the markup) rather than
        the particular line that delivers it.
        """
        self.assertEqual(T._fmr_vintage(_meta(2027, fiscal_year=True)), "")
        self.assertEqual(T._fmr_vintage(_meta(2027, fiscal_year=False)), "")

    def test_an_absurd_year_is_refused(self):
        self.assertEqual(T._fmr_vintage({"fiscal_year": 12, "effective": "11-10-01"}), "")

    def test_a_missing_or_non_dict_meta_is_refused(self):
        for bad in ({}, None, [], "FY2027", 2027):
            self.assertEqual(T._fmr_vintage(bad), "", repr(bad))

    def test_a_refused_meta_leaves_the_2026_11_09_wording_exactly(self):
        """A bad meta must not merely drop the year — it must change nothing."""
        plain = self._html({})
        for bad in (_meta(2027, effective="nope"), _meta(2031),
                    _meta(2027, fiscal_year="2027"), {"zips": 178}):
            self.assertEqual(self._html(bad), plain)
        self.assertIsNone(re.search(r"\b(19|20)\d\d\b", plain))

    # ---- the boundary of the fiscal year itself

    def test_the_fiscal_year_boundary_is_1_october(self):
        self.assertEqual(T._federal_fiscal_year(__import__("datetime").date(2026, 9, 30)), 2026)
        self.assertEqual(T._federal_fiscal_year(__import__("datetime").date(2026, 10, 1)), 2027)
        self.assertEqual(T._federal_fiscal_year(__import__("datetime").date(2026, 12, 31)), 2027)
        self.assertEqual(T._federal_fiscal_year(__import__("datetime").date(2027, 1, 1)), 2027)

    def test_the_same_file_reads_current_before_1_october_and_stale_after(self):
        """One file, two verdicts, decided only by the date it is read on."""
        import datetime as dt
        m = _meta(2026)
        self.assertIn("in effect since", T._fmr_vintage(m, dt.date(2026, 9, 30)))
        self.assertIn("a newer set of figures exists", T._fmr_vintage(m, dt.date(2026, 10, 1)))


class MetaLoader(unittest.TestCase):
    """fmr.meta.json loads like every other feed: non-fatal, docroot first."""

    # Context(build_dir, docroot) — that order, which is easy to get backwards:
    # the first write of this test had them swapped and asserted the docroot lost.
    def _ctx_with(self, docroot_meta=None, build_meta=None):
        import json
        build, doc = tempfile.mkdtemp(), tempfile.mkdtemp()
        for base, m in ((doc, docroot_meta), (build, build_meta)):
            if m is not None:
                with open(os.path.join(base, "fmr.meta.json"), "w") as f:
                    json.dump(m, f)
        return T.Context(build, doc)

    def test_a_missing_meta_is_empty_and_does_not_raise(self):
        """Nothing on the droplet writes this file; absence must stay ordinary."""
        self.assertEqual(self._ctx_with().fmr_meta, {})

    def test_the_docroot_copy_wins_over_the_checkout(self):
        """refresh_fmr.sh ships the docroot pair; the committed copy is the fallback."""
        c = self._ctx_with(docroot_meta=_meta(2027), build_meta=_meta(2019))
        self.assertEqual(c.fmr_meta["fiscal_year"], 2027)

    def test_the_checkout_is_the_fallback(self):
        c = self._ctx_with(build_meta=_meta(2026))
        self.assertEqual(c.fmr_meta["fiscal_year"], 2026)

    def test_malformed_json_is_empty_and_does_not_raise(self):
        """A half-written scp must not take /section8/ down."""
        doc = tempfile.mkdtemp()
        with open(os.path.join(doc, "fmr.meta.json"), "w") as f:
            f.write("{not json")
        self.assertEqual(T.Context(tempfile.mkdtemp(), doc).fmr_meta, {})

    def test_a_non_dict_meta_is_empty(self):
        self.assertEqual(self._ctx_with(docroot_meta=[1, 2, 3]).fmr_meta, {})

    def test_it_is_read_once_and_cached(self):
        c = self._ctx_with(docroot_meta=_meta(2027))
        self.assertIs(c.fmr_meta, c.fmr_meta)

    def test_the_repo_has_no_meta_yet_so_the_live_pages_name_no_year(self):
        """The state this ships in: fmr.json is tracked, fmr.meta.json is not.

        build_fmr.py only started writing it on 2026-11-10 and it is produced on
        a workstation, so until refresh_fmr.sh next runs there is no vintage to
        read and the block must stay silent. When this test starts failing, a
        meta has arrived in the checkout and the block will name its year.
        """
        self.assertEqual(T.Context(REPO, tempfile.mkdtemp()).fmr_meta, {})


class Render(unittest.TestCase):
    """Through t_fresh_section8, on the real pages."""

    def _run(self, rows, fmr=None, no_fmr_file=False):
        docroot = tempfile.mkdtemp()
        out = tempfile.mkdtemp()
        build = REPO
        if no_fmr_file:
            # A build dir with no fmr.json and no docroot copy either — but the
            # other feeds still have to load, so point it at copies of the real
            # ones via the docroot and leave fmr.json out of both.
            build = tempfile.mkdtemp()
        ctx = T.Context(build, docroot)
        ctx.out = out
        ctx._s8 = {"avail_updated": FRESH}
        if not no_fmr_file:
            ctx._fmr = dict(ZIPS) if fmr is None else fmr
        with mock.patch.object(T, "_live_listings", lambda c: rows), \
             mock.patch.object(T, "_feed_freshness",
                               lambda c: (False, "November 9, 2026", None)), \
             mock.patch.object(ledger, "set_state"), \
             mock.patch.object(ledger, "get_state", lambda k, d=None: d):
            res = T.t_fresh_section8(ctx)
        pages = {}
        for rel in ("index.html", os.path.join("staten-island", "index.html")):
            p = os.path.join(out, "section8", rel)
            if os.path.exists(p):
                with open(p) as f:
                    pages[rel] = f.read()
        return res, pages

    def test_the_hub_and_the_borough_page_both_carry_it(self):
        rows = [_row(i, 1500 + (i % 7) * 400) for i in range(30)]
        res, pages = self._run(rows)
        self.assertTrue(res["ok"])
        self.assertIn(HEAD, pages["index.html"])
        self.assertIn(HEAD, pages[os.path.join("staten-island", "index.html")])

    def test_it_sits_after_the_source_of_income_note_and_before_the_table(self):
        """An answer block belongs above the 253-row table, not under it."""
        rows = [_row(i, 1500 + (i % 7) * 400) for i in range(30)]
        _, pages = self._run(rows)
        hub = pages["index.html"]
        self.assertLess(hub.index("Source-of-income discrimination"), hub.index(HEAD))
        self.assertLess(hub.index(HEAD), hub.index("All live listings, cheapest first"))

    def test_the_pages_still_publish_with_no_fmr_json_anywhere(self):
        rows = [_row(i, 1500 + (i % 7) * 400) for i in range(30)]
        res, pages = self._run(rows, no_fmr_file=True)
        self.assertTrue(res["ok"], res)
        self.assertIn("All live listings, cheapest first", pages["index.html"])
        self.assertNotIn(HEAD, pages["index.html"])

    def test_an_empty_borough_page_carries_no_block(self):
        """No rows, nothing to compare, and no stats block either."""
        rows = [_row(i, 1500 + (i % 7) * 400, boro="Bx") for i in range(30)]
        docroot = tempfile.mkdtemp()
        si = os.path.join(docroot, "section8", "staten-island")
        os.makedirs(si, exist_ok=True)
        with open(os.path.join(si, "index.html"), "w") as f:
            f.write("<p>live already</p>")   # keeps the page in boro_pages
        ctx = T.Context(REPO, docroot)
        ctx.out = tempfile.mkdtemp()
        ctx._s8 = {"avail_updated": FRESH}
        ctx._fmr = dict(ZIPS)
        with mock.patch.object(T, "_live_listings", lambda c: rows), \
             mock.patch.object(T, "_feed_freshness",
                               lambda c: (False, "November 9, 2026", None)), \
             mock.patch.object(ledger, "set_state"), \
             mock.patch.object(ledger, "get_state", lambda k, d=None: d):
            T.t_fresh_section8(ctx)
        with open(os.path.join(ctx.out, "section8", "staten-island", "index.html")) as f:
            page = f.read()
        self.assertIn("No rent-stabilized Staten Island buildings", page)
        self.assertNotIn(HEAD, page)


if __name__ == "__main__":
    unittest.main()

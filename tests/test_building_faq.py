"""The building-page FAQ: what it must say, and what it must never say.

Why these exist (2026-10-11). The building tier is 47,165 of ~49,300 published
pages and the only tier that has earned Search Console impressions at any
scale. Until today its FAQPage node was built by hand, inline, with one answer:

    "Yes. 164 Sherman Ave in Inwood, Manhattan is a DHCR-registered
     rent-stabilized building with about 48 apartments."

Two things were wrong with it, and both are the kind that read fine:

  * no part of the rendered page carried it, so the richest markup on the
    highest-value tier described content that was not there — the thing
    faq_html's own docstring exists to prevent;
  * "Yes." answers "Is <addr> rent stabilized?" without the caveat the rest of
    the site never omits. A retrieved passage is scored and handed to a model
    on its own, stripped of the footer that carried the limit, so the one
    string an answer engine lifts as THE answer told a tenant their apartment
    is stabilized. DHCR registers the building.

A docstring cannot fail a build, so each of those is a test below, along with
the degradations (no unit count, no year, no voucher) and the grammar — "1
apartments" is the tell that a template is filling itself in, which is the
impression the whole block exists to undo.
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import build_seo as B  # noqa: E402

ADDR, NB, BORO = "164 Sherman Ave", "Inwood", "Manhattan"


def faq(**kw):
    kw.setdefault("bbl", "1021930001")
    return B.building_faq(ADDR, NB, BORO, **kw)


def answers(pairs):
    return " ".join(a for _q, a in pairs)


class StatusAnswer(unittest.TestCase):
    """The first pair is the page's <h1> and the claim the page exists to make."""

    def test_always_present(self):
        self.assertTrue(faq())
        self.assertEqual(faq()[0][0], f"Is {ADDR} rent stabilized?")

    def test_never_answers_yes(self):
        # The regression this file was written for. "Yes." to "is my apartment
        # rent stabilized" is an answer this data cannot support.
        a = faq()[0][1]
        self.assertFalse(a.startswith("Yes"))
        self.assertNotIn("Yes.", a)

    def test_names_the_source_in_the_answer_not_the_footer(self):
        a = faq()[0][1]
        self.assertIn("DHCR", a)
        self.assertIn("2024", a)

    def test_carries_the_per_unit_caveat_in_the_same_passage(self):
        # The whole point: the limit travels with the claim, because the
        # passage travels without the page.
        a = faq()[0][1]
        self.assertIn("not for each apartment", a)
        self.assertIn("deregulated", a)

    def test_names_the_place(self):
        # Self-contained: an answer lifted alone still says which city.
        self.assertIn(NB, faq()[0][1])
        self.assertIn(BORO, faq()[0][1])


class ApartmentsAnswer(unittest.TestCase):
    def test_asked_only_when_the_record_answers_it(self):
        self.assertEqual(len(faq()), 1)
        self.assertEqual(len(faq(units=48)), 2)

    def test_keeps_the_body_hedge(self):
        # PLUTO counts, so the page says "about" and so must this.
        self.assertIn("about 48", faq(units=48)[1][1])

    def test_singular_grammar(self):
        a = faq(units=1)[1][1]
        self.assertIn("about 1 residential apartment,", a)
        self.assertNotIn("1 residential apartments", a)

    def test_does_not_let_a_unit_count_imply_stabilized_units(self):
        # 48 apartments is not 48 stabilized apartments, and a passage that
        # says the first without the second invites the inference.
        a = faq(units=48)[1][1]
        self.assertIn("does not say how many of them are rent stabilized", a)

    def test_year_rides_along_when_both_are_known(self):
        pairs = faq(units=48, yr=1920)
        self.assertEqual(len(pairs), 2)
        self.assertIn("built in 1920", pairs[1][1])

    def test_year_gets_its_own_pair_when_the_count_is_missing(self):
        # Without this the year would be dropped with the count it was
        # attached to, on a page that still displays it.
        pairs = faq(yr=1920)
        self.assertEqual(len(pairs), 2)
        self.assertEqual(pairs[1][0], f"When was {ADDR} built?")
        self.assertIn("1920", pairs[1][1])

    def test_a_build_year_is_never_offered_as_the_test_of_status(self):
        self.assertIn("is not what puts a New York building under rent "
                      "stabilization", faq(yr=1920)[1][1])

    def test_no_pair_when_neither_is_known(self):
        self.assertEqual([q for q, _ in faq()],
                         [f"Is {ADDR} rent stabilized?"])


class VoucherAnswer(unittest.TestCase):
    def test_absent_without_a_listing(self):
        self.assertNotIn("voucher", answers(faq(units=48)).lower())

    def test_dates_the_feed(self):
        a = faq(voucher={"n": 1}, voucher_asof="2026-10-11")[1][1]
        self.assertIn("2026-10-11", a)

    def test_silence_is_never_a_refusal(self):
        # voucher_html's wording, kept word-for-word in substance: the two
        # surfaces must not make different claims about one landlord.
        a = faq(voucher={"n": 2, "p": 1800}, voucher_asof="2026-10-11")[1][1]
        self.assertIn("refused nobody", a)
        self.assertIn("illegal in New York City", a)
        self.assertIn("landlord's own statement", a)

    def test_claims_the_listing_not_the_policy(self):
        a = faq(voucher={"n": 1}, voucher_asof="2026-10-11")[1][1]
        self.assertIn("AffordableHousing.com", a)
        self.assertNotIn("accepts vouchers", a)

    def test_plural_and_price(self):
        a = faq(voucher={"n": 3, "p": 2150}, voucher_asof="2026-10-11")[1][1]
        self.assertIn("3 apartments", a)
        self.assertIn("are listed", a)
        self.assertIn("$2,150 a month", a)

    def test_singular(self):
        a = faq(voucher={"n": 1}, voucher_asof="2026-10-11")[1][1]
        self.assertIn("An apartment", a)
        self.assertIn("is listed", a)

    def test_price_omitted_when_the_feed_has_none(self):
        self.assertNotIn("$", faq(voucher={"n": 1}, voucher_asof="2026-10-11")[1][1])


class MarkupMatchesTheRenderedPage(unittest.TestCase):
    """The defect that is not about wording: markup with nothing behind it."""

    def test_every_marked_up_answer_is_also_rendered(self):
        pairs = faq(units=48, yr=1920, voucher={"n": 1, "p": 1800},
                    voucher_asof="2026-10-11")
        self.assertEqual(len(pairs), 3)
        html = B.faq_html(pairs)
        ld = B.faq_jsonld(pairs)
        for q, a in pairs:
            self.assertIn(B.esc(q), html)
            self.assertIn(B.esc(a), html)
        self.assertEqual([e["name"] for e in ld["mainEntity"]],
                         [q for q, _ in pairs])
        self.assertEqual([e["acceptedAnswer"]["text"] for e in ld["mainEntity"]],
                         [a for _q, a in pairs])

    def test_pairs_are_plain_text_not_html(self):
        # faq_html escapes and faq_jsonld hands the string to json.dumps, so a
        # pre-escaped answer would be double-escaped into both.
        for q, a in faq(units=48, yr=1920, voucher={"n": 1},
                        voucher_asof="2026-10-11"):
            self.assertNotIn("&amp;", q + a)
            self.assertNotIn("<", q + a)

    def test_an_apostrophe_survives_both_renderers(self):
        pairs = faq(units=48)
        self.assertIn("landlord or DHCR", pairs[0][1])
        # "apartment's rent history" is in the answer; it must round-trip
        # through the HTML escaper and through json.dumps unchanged.
        self.assertIn("apartment's rent history", pairs[0][1])
        self.assertIn("apartment&#x27;s rent history", B.faq_html(pairs))
        self.assertEqual(
            json.loads(json.dumps(B.faq_jsonld(pairs)))
            ["mainEntity"][0]["acceptedAnswer"]["text"],
            pairs[0][1])


class ReadsAsWritten(unittest.TestCase):
    """Reader-facing text on 47,165 pages. No empty slots, no stray template."""

    def test_no_unfilled_slot_on_any_degradation(self):
        for kw in ({}, {"units": 48}, {"yr": 1920}, {"units": 1, "yr": 1920},
                   {"units": 48, "voucher": {"n": 1}, "voucher_asof": "2026-10-11"}):
            for q, a in faq(**kw):
                for bad in ("{", "}", "None", "  ", " ,", " .", "0 apartment"):
                    self.assertNotIn(bad, q + " " + a, f"{bad!r} in {kw}")
                self.assertTrue(a.endswith("."), a)
                self.assertTrue(q.endswith("?"), q)

    def test_bbl_omitted_rather_than_emitted_empty(self):
        pairs = B.building_faq(ADDR, NB, BORO, units=48, bbl=None)
        self.assertNotIn("BBL", pairs[1][1])
        self.assertIn("BBL 1021930001", faq(units=48)[1][1])


if __name__ == "__main__":
    unittest.main()


class TheRecordedStatusCodeRidesInTheAnswer(unittest.TestCase):
    """2026-10-21. The DHCR file's own STATUS columns were on the page as a
    bare facts-table cell and nowhere in the marked-up answer — the same gap
    the 2026-10-20 recency sentence closed for violations.last_12mo.

    Measured first: this block was 70.0% shared with its siblings at the
    median (worst 77.8%, above 60% in 185 of 185 neighborhoods) against 22.4%
    for the computed comparison block. The caveats are why, and they are not
    the thing to cut, so the code — which differs between neighbours on 27.8%
    of buildings that carry more than one — is what got added.
    """

    def test_singular_code_is_named(self):
        a = faq(codes=["J-51"])[0][1]
        self.assertIn("its stabilization code is J-51", a)

    def test_several_codes_read_as_a_list(self):
        a = faq(codes=["MULTIPLE DWELLING A", "421-A (1-15)"])[0][1]
        self.assertIn("its stabilization codes are MULTIPLE DWELLING A "
                      "and 421-A (1-15)", a)

    def test_three_codes_keep_their_commas(self):
        a = faq(codes=["MULTIPLE DWELLING A", "J-51", "GARDEN COMPLEX"])[0][1]
        self.assertIn("codes are MULTIPLE DWELLING A, J-51 and GARDEN COMPLEX", a)

    def test_the_label_is_the_one_the_facts_table_uses(self):
        # The table renders the same field for the same building as
        # "Stabilization code". Two labels for one cell is how a reader
        # concludes they are two different facts.
        self.assertIn("stabilization code", faq(codes=["HOTEL"])[0][1])

    def test_parse_noise_is_dropped_and_the_real_code_kept(self):
        # 88 distinct values appear in the corpus; the tail is a seven-character
        # truncation ("OWNER O") or a bad text layer ("GLASS A" for CLASS A).
        a = faq(codes=["MULTIPLE DWELLING A", "HPD"])[0][1]
        self.assertIn("its stabilization code is MULTIPLE DWELLING A", a)
        self.assertNotIn("HPD", a)

    def test_a_truncated_cell_is_never_named(self):
        for junk in ("OWNER O", "GLASS A", "STABLIL", "000", "N/A", "X", "2522.6"):
            self.assertIsNone(B.dhcr_status_phrase([junk]), junk)

    def test_no_recognised_code_leaves_the_clause_out_entirely(self):
        # Insurance, not a live path: every one of the 47,165 rows carries at
        # least one recognised code today. It must still read as written.
        a = faq(codes=["000"])[0][1]
        self.assertNotIn("where", a)
        self.assertNotIn("  ", a)
        self.assertIn("building files. Registration is recorded", a)

    def test_missing_and_empty_codes_behave_the_same(self):
        for c in (None, [], ["NONE"]):
            self.assertIsNone(B.dhcr_status_phrase(c), repr(c))
        self.assertIn("building files. Registration", faq()[0][1])

    def test_the_code_never_carries_a_legal_consequence(self):
        # 421-a/J-51 stabilization does NOT automatically end when the benefit
        # does: it turns on the 12-point lease notice, on whether the building
        # was stabilized beforehand, and on pre/post-1984 occupancy. A tenant
        # who read "your stabilization ended" and stopped asserting a right
        # they still hold would be harmed by this page.
        a = faq(codes=["421-A (1-15)"])[0][1]
        for claim in ("expire", "expires", "no longer rent stabilized",
                      "ends when", "tax benefit ends", "will end"):
            self.assertNotIn(claim, a.lower(), claim)

    def test_the_answer_stays_plain_text(self):
        # ARTICLES 14 & 15 is the one recognised code with an ampersand;
        # faq_html escapes and faq_jsonld json.dumps, so pre-escaping here
        # would double-escape into both.
        a = faq(codes=["ARTICLES 14 & 15"])[0][1]
        self.assertIn("ARTICLES 14 & 15", a)
        self.assertNotIn("&amp;", a)


class TheCaveatIsMadeOnceNotTwice(unittest.TestCase):
    """2026-10-21. The apartments answer used to end "...and the DHCR files
    this site is built on register the building rather than its individual
    apartments", which the FIRST answer already says in the same block and in
    stronger terms. ~20 identical words on 46,981 of 47,165 pages.
    """

    def test_the_apartments_answer_no_longer_restates_it(self):
        a = faq(units=48)[1][1]
        self.assertNotIn("register the building rather than", a)

    def test_but_the_block_still_makes_the_caveat(self):
        # Dropped from the conditional pair, kept in the unconditional one, so
        # no degradation can lose it.
        for kw in ({"units": 48}, {"yr": 1910}, {"units": 1, "yr": 1910}, {}):
            self.assertIn("not for each apartment", answers(faq(**kw)), kw)

    def test_the_pluto_specific_half_survives(self):
        # A different point from the one above, and the only place on the page
        # that makes it.
        a = faq(units=48)[1][1]
        self.assertIn("does not say how many of them are rent stabilized", a)

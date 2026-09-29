#!/usr/bin/env python3
"""Unit tests for the JSON re-rental sources (rerental_feeds.py) and the
rerental_daily / featured_rerentals changes that carry them. No network: HDC
responses come from tests/fixtures/hdc_re_rentals.json (trimmed real rows plus
two marked synthetic ones).

    python3 tests/test_rerental_feeds.py
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import featured_rerentals as fr  # noqa: E402
import rerental_daily as rd  # noqa: E402
import rerental_feeds as F  # noqa: E402

FIXTURE = json.loads((ROOT / "tests" / "fixtures" / "hdc_re_rentals.json").read_text())
AGENT = "NYC Housing Development Corporation (HDC)"


def fake_fetch(url):
    page = int(url.rsplit("=", 1)[1])
    return FIXTURE[f"page{page}"]


def records():
    return F.hdc_records(F.hdc_fetch(fetch=fake_fetch), AGENT)


class HdcFetch(unittest.TestCase):
    def test_follows_page_count(self):
        seen = []
        rows = F.hdc_fetch(fetch=lambda u: (seen.append(u), fake_fetch(u))[1])
        self.assertEqual(len(seen), 2)
        self.assertEqual(len(rows), 7)

    def test_page_count_is_bounded(self):
        runaway = {"json": [], "pagination": {"page-count": 500}}
        calls = []
        F.hdc_fetch(max_pages=3, fetch=lambda u: (calls.append(u), runaway)[1])
        self.assertEqual(len(calls), 3)

    def test_bad_shape_is_a_feed_error(self):
        with self.assertRaises(F.FeedError):
            F.hdc_fetch(fetch=lambda u: {"error": "maintenance"})


class HdcRecords(unittest.TestCase):
    def setUp(self):
        self.recs = records()
        self.by_key = {r["_key"]: r for r in self.recs}

    def test_rows_without_an_id_are_dropped(self):
        self.assertEqual(len(self.recs), 6)
        self.assertNotIn("SYNTHETIC NO ID", [r["title"] for r in self.recs])

    def test_rent_range_is_rent_with_cents_dropped(self):
        r = self.by_key["hdc 8767"]                       # "$1,614.52 - $2,085.19"
        self.assertEqual((r["money_kind"], r["money_low"], r["money_high"]), ("rent", 1614, 2085))
        single = self.by_key["hdc 8779"]                  # "$2,214.04"
        self.assertEqual((single["money_low"], single["money_high"]), (2214, 2214))

    def test_no_rent_is_no_price_not_a_guess(self):
        r = self.by_key["hdc 9001"]
        self.assertIsNone(r["money_kind"])
        self.assertIsNone(r["money_low"])

    def test_a_figure_that_cannot_be_a_rent_is_not_printed(self):
        row = dict(FIXTURE["page1"]["json"][0], nid="9100", rent_range="$154")
        (r,) = F.hdc_records([row], AGENT)
        self.assertIsNone(r["money_kind"])
        row = dict(row, rent_range="$98,366 - $176,410")  # an income band, never rent
        (r,) = F.hdc_records([row], AGENT)
        self.assertEqual(r["money_kind"], "income")

    def test_borough_names_match_the_rest_of_the_feed(self):
        self.assertEqual(self.by_key["hdc 8767"]["borough"], "Bronx")   # "The Bronx"
        self.assertEqual(self.by_key["hdc 9001"]["borough"], "Staten Island")

    def test_shouting_is_tidied_and_mixed_case_left_alone(self):
        r = self.by_key["hdc 8763"]
        self.assertEqual(r["title"], "Nehemiah Spring Creek 4B-2")
        self.assertTrue(r["address"].startswith("1115, 1117 & 1123 Ashford Street, 516 Schroeders Ave"))
        self.assertIn("NY 11239", r["address"])
        self.assertNotIn("*", r["address"])
        self.assertEqual(self.by_key["hdc 8779"]["title"], "Nehemiah Spring Creek 4B1")
        self.assertEqual(F.tidy_case("OCEANHILL II"), "Oceanhill II")
        self.assertEqual(F.tidy_case("126-43 39TH AVENUE"), "126-43 39th Avenue")

    def test_beds_only_when_there_is_one_size(self):
        self.assertEqual(self.by_key["hdc 8779"]["beds"], "2")
        self.assertIsNone(self.by_key["hdc 8777"]["beds"])       # 1-, 2-bed and studio
        self.assertEqual(self.by_key["hdc 9001"]["beds"], "studio")

    def test_link_is_the_board_and_says_so(self):
        for r in self.recs:
            self.assertEqual(r["href"], F.HDC_PAGE)
            self.assertEqual(r["href_kind"], "agent_page")
            self.assertEqual(r["agent_page"], F.HDC_PAGE)

    def test_photo_only_from_hdc(self):
        self.assertTrue(self.by_key["hdc 8779"]["image_src"].startswith("https://www.nychdc.com/"))
        self.assertIsNone(self.by_key["hdc 9001"]["image_src"])  # points off-site

    def test_zip_and_missing_zip(self):
        self.assertEqual(self.by_key["hdc 8779"]["zip"], "11239")
        self.assertIsNone(self.by_key["hdc 8619"]["zip"])        # "Hunter's Point South"

    def test_record_shape_matches_featured_json(self):
        published = {"agent", "agent_page", "title", "address", "borough", "zip", "money_kind",
                     "money_low", "money_high", "income_1p_max", "units", "beds", "href",
                     "href_kind", "image_src"}
        for r in self.recs:
            self.assertEqual({k for k in r if not k.startswith("_")}, published)
            for k in ("money_low", "money_high", "units"):
                self.assertTrue(r[k] is None or isinstance(r[k], int), k)
            self.assertTrue(r["beds"] is None or isinstance(r["beds"], str))

    def test_records_pass_the_featured_noise_filter(self):
        kept = [r for r in self.recs if fr.is_real_listing(r, fr.office_addresses())]
        self.assertEqual(len(kept), 6)

    def test_markup_is_flattened(self):
        self.assertEqual(F.text("<p>A &amp; B</p>\r\n<br />"), "A &amp; B")
        self.assertEqual(F.text("x" * 500, 10), "x" * 10)


class DailyItems(unittest.TestCase):
    def test_items_carry_borough_rent_and_a_geocodable_address(self):
        items = {i["key"]: i for i in F.daily_items(records())}
        it = items["hdc 8763"]
        self.assertEqual(it["label"], "Nehemiah Spring Creek 4B-2 — 1115, 1117 & 1123 Ashford Street")
        self.assertEqual(it["geo"], "1123 Ashford Street")
        self.assertEqual((it["boro"], it["rent_low"]), ("Brooklyn", 803))
        self.assertIsNone(items["hdc 9001"]["rent_low"])
        self.assertEqual(items["hdc 8779"]["url"], F.HDC_PAGE)

    def test_first_address(self):
        self.assertEqual(F.first_address("500 Vandalia Ave, East New York, NY 11239"),
                         ("500 Vandalia Ave", "500 Vandalia Ave"))

    def test_duplicates_collapse(self):
        recs = records()
        self.assertEqual(len(F.daily_items(recs + recs)), len(recs))


class FeedRecords(unittest.TestCase):
    META = {"url": F.HDC_PAGE, "feed": "hdc"}

    def test_a_dead_feed_is_an_error_not_an_exception(self):
        def down():
            raise F.FeedError("HTTP 503")
        with mock.patch.dict(F.FEEDS, {"hdc": {"fetch": down, "records": F.hdc_records}}):
            self.assertEqual(F.feed_records(AGENT, self.META), ([], "HTTP 503"))

    def test_a_parser_bug_is_contained(self):
        def boom(rows, agent, url):
            raise KeyError("x")
        with mock.patch.dict(F.FEEDS, {"hdc": {"fetch": lambda: [], "records": boom}}):
            recs, err = F.feed_records(AGENT, self.META)
        self.assertEqual(recs, [])
        self.assertIn("KeyError", err)

    def test_unknown_feed(self):
        self.assertEqual(F.feed_records("x", {"url": "u", "feed": "nope"})[0], [])

    def test_daily_sweep_reports_a_dead_feed_per_source(self):
        with mock.patch.object(F, "feed_records", return_value=([], "HTTP 503")):
            out = rd.sweep({AGENT: self.META})
        self.assertEqual(out[AGENT]["error"], "HTTP 503")
        self.assertEqual(out[AGENT]["items"], [])

    def test_fetch_json_rejects_non_json_and_oversize(self):
        class Resp:
            def __init__(self, body): self.body = body
            def read(self, n): return self.body[:n]
            def __enter__(self): return self
            def __exit__(self, *a): return False
        with mock.patch("urllib.request.urlopen", return_value=Resp(b"<html>")):
            with self.assertRaises(F.FeedError):
                F.fetch_json("https://www.nychdc.com/api/re-rentals")
        with mock.patch("urllib.request.urlopen", return_value=Resp(b"[" + b" " * (F.MAX_BYTES + 5))):
            with self.assertRaises(F.FeedError):
                F.fetch_json("https://www.nychdc.com/api/re-rentals")


class DailyChanges(unittest.TestCase):
    def test_neighbourhood_after_a_dash_is_the_same_building(self):
        self.assertEqual(rd.key_of("1182 Ogden Ave - Highbridge, Bronx"),
                         rd.key_of("1182 Ogden Ave, Bronx, NY 10452"))
        # a dash followed by a number is address, not neighbourhood
        self.assertNotEqual(rd.key_of("55 Water St – Unit 12B"), rd.key_of("55 Water St"))

    def test_named_building_lines_are_listings(self):
        text = ("MODERATE INCOME VACANCY TO BE FILLED\n"
                "The Westport at 500 W. 56th Street, New York, NY 10019\n"
                "Applications are accepted at 553 W. 30th Street on a first come basis for everyone\n")
        items, _ = rd.listings_from(text, False)
        self.assertEqual([i["key"] for i in items], ["500 west 56"])
        self.assertEqual(items[0]["geo"], "500 W. 56th Street, New York, NY 10019")
        self.assertTrue(items[0]["label"].startswith("The Westport at"))

    def test_extra_office_addresses_are_skipped(self):
        text = "1182 Ogden Ave, Bronx, NY 10452\n2817 23RD AVENUE, ASTORIA, NY 11105\n"
        items, _ = rd.listings_from(text, False, ["28-15 23rd Avenue", "2817 23rd Avenue"])
        self.assertEqual([i["label"][:4] for i in items], ["1182"])

    def test_diff_keeps_feed_fields_and_record_new_uses_them(self):
        items = F.daily_items(records())
        results = {AGENT: {"url": F.HDC_PAGE, "error": None, "items": items,
                           "stated": 0, "waitlist": False}}
        deltas = rd.diff({AGENT: ["hdc 8779"]}, results)
        new = {i["key"]: i for i in deltas[AGENT]["new"]}
        self.assertEqual(new["hdc 8767"]["boro"], "Bronx")
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(rd, "NEW_FEED", os.path.join(d, "new.json")), \
                mock.patch.object(rd, "PLACES", os.path.join(d, "places.json")), \
                mock.patch.object(rd, "place_of", return_value={"hood": "Concourse", "boro": "Bronx"}) as po, \
                mock.patch.object(rd, "featured_money", return_value={}):
            rd.record_new(deltas, results, "2026-09-29")
            with open(os.path.join(d, "new.json")) as f:
                feed = json.load(f)["items"]
        row = {i["key"]: i for i in feed}["hdc 8767"]
        self.assertEqual((row["boro"], row["hood"], row["rent_low"]), ("Bronx", "Concourse", 1614))
        self.assertEqual(row["url"], F.HDC_PAGE)
        # the geocoder was asked about the street, not "River Crest Apartments — ..."
        self.assertIn("1164 River Avenue", [c.args[0] for c in po.call_args_list])
        self.assertEqual(len(feed), 5)          # 8779 was already on the board


class FeaturedChanges(unittest.TestCase):
    def test_a_zip_on_the_line_above_unit_is_not_a_unit_count(self):
        self.assertIsNone(fr.UNITS.search("Bronx, NY 10452 \nUnit Photos - Apt 6D"))
        self.assertEqual(fr.UNITS.search("3 units available").group(1), "3")


if __name__ == "__main__":
    unittest.main()

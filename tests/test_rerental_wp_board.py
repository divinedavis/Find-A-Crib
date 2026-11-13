"""Reside New York's board read over WordPress REST, the batch guard, and the
posting date travelling into rerental_new.json (2026-11-13: 18 listings posted
Nov 5-11 were mailed as "18 new" the day the page finally rendered fully)."""
import json
import os
import sys
import tempfile
import pathlib
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import rerental_daily as rd   # noqa: E402
import rerental_feeds as rf   # noqa: E402

FIX = json.loads((ROOT / "tests" / "fixtures" / "reside_open_market.json").read_text())
RESIDE = "Reside New York LLC"
# The keys production held for Reside on 2026-11-13 (rerental_history.json),
# from the rendered board. The REST read must produce exactly these, or the
# switch itself would mail every listing again.
PROD_KEYS = {"park 6d", "barker 706", "sedgwick 62", "190 east 205", "hoe 5c", "250 west 49",
             "98 himrod 4f", "864 49 d12", "173 tompkins 2", "173 tompkins 1", "ogden 5e",
             "333 cypress 4g", "829 east 55", "350 rutland 3b", "hoe 4c", "637 east 176", "872 home 2b"}


def fake_fetch(terms=None, props=None):
    def fetch(url, timeout=None):
        if "/property-status?" in url:
            return FIX["terms"] if terms is None else terms
        if "/property?" in url:
            assert "orderby=modified" in url and "property-status=580" in url
            return FIX["properties"] if props is None else props
        raise AssertionError(url)
    return fetch


def board(**kw):
    return rf.wp_board(**rd.WP_BOARDS[RESIDE], fetch=fake_fetch(**kw))


def test_rest_rows_have_title_link_and_dates():
    rows = board()
    assert len(rows) == 20
    r = next(r for r in rows if "Barker" in r["title"])
    assert r["title"] == "2500 Barker Ave Apartment – Unit 706"      # &#8211; unescaped
    assert r["link"].startswith("https://residenewyork.com/property/")
    assert r["posted"] == "2026-11-13"


def test_keys_match_what_production_already_holds():
    with mock.patch.object(rf, "fetch_json", fake_fetch()):
        items, _ = rd.wp_items(RESIDE, {"url": "https://residenewyork.com/property-status/open-market/",
                                        "wp": rd.WP_BOARDS[RESIDE]}, {})
    assert {i["key"] for i in items} == PROD_KEYS
    assert all(i.get("posted") and i["url"].startswith("https://residenewyork.com/property/")
               for i in items)


def test_untrusted_rows_are_cleaned():
    props = [
        {"status": "publish", "date": "2026-11-10T10:00:00", "modified": "2026-11-10T10:00:00",
         "link": "http://residenewyork.com/property/x/", "title": {"rendered": "<b>12 Main St</b> &amp; Unit 2A"}},
        {"status": "publish", "date": "2026-11-10T10:00:00", "modified": "x",
         "link": "https://evil.example/property/y/", "title": {"rendered": "14 Main St – Unit 3B"}},
        {"status": "draft", "date": "2026-11-10T10:00:00", "link": "https://residenewyork.com/z/",
         "title": {"rendered": "16 Main St"}},
        {"status": "publish", "title": {"rendered": "   "}},
    ]
    rows = board(props=props)
    assert [r["title"] for r in rows] == ["12 Main St & Unit 2A", "14 Main St – Unit 3B"]
    assert rows[0]["link"] is None and rows[1]["link"] is None     # http and off-site links dropped
    assert rows[1]["modified"] is None


def test_feed_errors_fall_back_to_rendering():
    for kw in ({"terms": []}, {"props": []}, {"props": {"code": "rest_invalid_param"}}):
        try:
            board(**kw)
        except rf.FeedError:
            continue
        raise AssertionError(f"{kw} should raise")
    try:
        rf.wp_board("http://residenewyork.com", "property-status", "open-market", fetch=fake_fetch())
    except rf.FeedError:
        pass
    else:
        raise AssertionError("http site accepted")
    pages = {RESIDE: {"url": "https://residenewyork.com/property-status/open-market/"}}
    with mock.patch.object(rf, "wp_board", side_effect=rf.FeedError("down")):
        assert rd.sweep_wp(pages, {}) == {}            # left for the browser pass


def rec(keys, posted=None):
    return {"error": None, "items": [{"key": k, "label": k, "url": None,
                                      **({"posted": posted} if posted else {})} for k in keys]}


def test_batch_guard_flags_a_board_that_suddenly_grows():
    before = ["a1", "a2", "a3", "a4", "a5", "a6", "a7"]
    now = [f"b{i}" for i in range(17)]
    d = rd.diff({RESIDE: before}, {RESIDE: rec(now)})[RESIDE]
    assert d["board_change"] and len(d["new"]) == 17
    assert all(i["board_change"] for i in d["new"])


def test_no_guard_for_a_normal_day_or_dated_listings():
    d = rd.diff({RESIDE: ["a1", "a2"]}, {RESIDE: rec(["a1", "a2", "n1", "n2", "n3"])})[RESIDE]
    assert not d["board_change"] and not any(i.get("board_change") for i in d["new"])
    d = rd.diff({RESIDE: ["a1"]}, {RESIDE: rec([f"n{i}" for i in range(12)], posted="2026-11-12")})[RESIDE]
    assert not d["board_change"]                      # dates say which are new; no guess needed


def test_report_names_the_board_change():
    deltas = rd.diff({RESIDE: ["a1"] * 1}, {RESIDE: rec([f"n{i}" for i in range(9)])})
    results = {RESIDE: dict(rec([f"n{i}" for i in range(9)]), stated=0, waitlist=False, url="u")}
    text = rd.to_text(results, deltas, "2026-11-13", 9, [])
    assert "board change at: Reside New York LLC" in text and "board change, sent as still open" in text


def test_posted_and_board_change_reach_rerental_new_json():
    with tempfile.TemporaryDirectory() as tmp:
        new_feed, places = os.path.join(tmp, "new.json"), os.path.join(tmp, "places.json")
        deltas = {RESIDE: {"new": [{"key": "k1", "label": "1 A St", "url": "https://residenewyork.com/property/1/",
                                    "posted": "2026-11-05"},
                                   {"key": "k2", "label": "2 B St", "url": None, "board_change": True}]}}
        with mock.patch.object(rd, "NEW_FEED", new_feed), mock.patch.object(rd, "PLACES", places), \
                mock.patch.object(rd, "load_places", return_value={}), \
                mock.patch.object(rd, "place_of", return_value=None), \
                mock.patch.object(rd, "featured_money", return_value={}):
            rd.record_new(deltas, {RESIDE: {"url": "https://residenewyork.com/property-status/open-market/"}},
                          "2026-11-13")
        rows = {r["key"]: r for r in json.load(open(new_feed))["items"]}
    assert rows["k1"]["posted"] == "2026-11-05" and "board_change" not in rows["k1"]
    assert rows["k2"]["board_change"] is True and "posted" not in rows["k2"]

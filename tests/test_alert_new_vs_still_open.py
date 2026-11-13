"""Borough alerts call a re-rental "new" only when it is (2026-11-13: an email
said "18 new re-rentals" for listings the agent posted Nov 5-11)."""
import datetime
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "pipeline"))

from growth import emailkit    # noqa: E402
import lottery_alerts as la    # noqa: E402

NOW = datetime.datetime(2026, 11, 13, 0, 0, tzinfo=la.NY)
SUB = {"id": "s1", "email": "renter@example.com", "token": "tok", "boroughs": ["M", "Bk"],
       "kinds": ["lottery", "rerental"], "last_sent_at": "2026-11-12T13:05:00+00:00"}


def rr(i, posted=None, board_change=False, boro="Bk"):
    feed = {"items": [{"agent": "Reside New York LLC", "key": f"k{i}", "label": f"{100 + i} Example St – Unit {i}A",
                       "url": f"https://residenewyork.com/property/{i}/", "boro": {"Bk": "Brooklyn", "M": "Manhattan"}[boro],
                       **({"posted": posted} if posted else {}), **({"board_change": True} if board_change else {})}]}
    return la.rerental_items(feed)[0]


def test_new_means_posted_since_the_last_email():
    since = la.fresh_since(SUB, NOW)
    assert since == datetime.date(2026, 11, 12)
    assert la.is_new(rr(1, "2026-11-12"), since)
    assert not la.is_new(rr(2, "2026-11-05"), since)
    assert la.is_new(rr(3), since)                         # no date, normal sweep: new
    assert not la.is_new(rr(4, board_change=True), since)  # no date, batch guard: still open
    assert la.is_new(rr(5, "2026-11-12", board_change=True), since)


def test_unknown_history_uses_two_days():
    since = la.fresh_since({"last_sent_at": None}, NOW)
    assert since == datetime.date(2026, 11, 11)


def test_the_18_listing_case_says_still_open_not_new():
    items = [rr(i, f"2026-11-{5 + i % 7:02d}") for i in range(18)]    # posted Nov 5-11
    subject, html, text, _ = la.render_alert(items, SUB, emailkit, now=NOW)
    assert subject == "18 re-rentals still open in Manhattan and Brooklyn"
    assert "new re-rental" not in subject and "18 new" not in text
    assert "still open" in text and "posted Nov 5" in text
    assert "18 re-rentals still open" in text and "more re-rentals" not in text


def test_mixed_case_counts_only_the_new_ones():
    items = [rr(i, "2026-11-12") for i in range(3)] + [rr(10 + i, "2026-11-06") for i in range(15)]
    subject, html, text, _ = la.render_alert(items, SUB, emailkit, now=NOW)
    assert subject == "3 new re-rentals + 15 more still open in Manhattan and Brooklyn"
    assert text.index("3 new re-rentals") < text.index("15 more re-rentals still open")


def test_all_new_reads_as_before():
    items = [rr(i, "2026-11-12") for i in range(2)] + [rr(9)]
    subject, *_ = la.render_alert(items, SUB, emailkit, now=NOW)
    assert subject == "3 new re-rentals in Manhattan and Brooklyn"


def test_single_older_listing():
    subject, *_ = la.render_alert([rr(1, "2026-11-05")], SUB, emailkit, now=NOW)
    assert subject.startswith("Re-rental still open in Brooklyn: ")


def test_push_says_still_open_too():
    title, _ = la.push_text([rr(i, "2026-11-06") for i in range(18)], SUB, NOW)
    assert title == "18 re-rentals still open"
    title, _ = la.push_text([rr(1, "2026-11-12"), rr(2, "2026-11-06")], SUB, NOW)
    assert title == "New: 1 re-rental + 1 still open"
    title, _ = la.push_text([rr(2, "2026-11-06")], SUB, NOW)
    assert title == "Re-rental still open in Brooklyn"


def test_posted_date_is_shown_and_validated():
    assert "posted Nov 5" in rr(1, "2026-11-05")["meta"]
    bad = rr(2, "<script>")
    assert bad["posted"] is None and "posted" not in bad["meta"]

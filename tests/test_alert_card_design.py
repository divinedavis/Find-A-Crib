"""The alert card every user alert uses (owner, 2026-11-05: "i like it, lets
use it"). Saved-building changes show only numbers they carry."""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from growth import emailkit  # noqa: E402
import saved_alerts as sa    # noqa: E402

REC = {"bbl": "3011970001", "a": "245 EASTERN PARKWAY", "nb": "Prospect Heights", "b": "Bk"}
USER = {"token": "t0k", "home_bbl": None}


def one(change):
    return sa.render_changes(USER, [dict(change, bbl=REC["bbl"])], {REC["bbl"]: REC}, emailkit)


def test_rent_drop_shows_new_and_old_rent():
    _, html, text, _ = one({"kind": "price", "price": 2195, "was": 2450, "url": "https://x/l",
                            "text": "Voucher listing rent dropped: $2,450 → $2,195/mo."})
    assert "Rent dropped at a building you saved." in html
    assert "$2,195" in html and "line-through" in html and "$2,450" in html
    assert "↓ $255 / mo · 10%" in html
    assert "See the listing" in html and "<style" not in html
    assert "$2,195 (was $2,450)" in text


def test_violations_are_red_and_say_how_many_are_open():
    _, html, _, _ = one({"kind": "violations", "price": None, "n": 3, "open": 7, "url": None,
                         "text": "3 new open HPD violations (7 open now)."})
    assert ">Heads up</span>" in html and "7 open now" in html and "#b42318" in html


def test_no_number_no_big_block():
    # A status change without unit counts: no invented figure.
    _, html, _, _ = one({"kind": "status", "price": None, "units": None, "url": None,
                         "text": "DHCR registration changed: registration codes changed to none."})
    assert "font-size:42px" not in html


def test_reports_keep_the_plain_look():
    html, _ = emailkit.render(title="Report", blocks=[{"type": "note", "text": "x"}])
    assert "border-radius:22px" not in html

"""The In-App Events calendar: holiday dates and Apple's text limits, offline."""
import os
import sys
import types
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# No App Store Connect key in tests: stand in for the two API modules.
sys.modules["asc_creative_assets"] = types.SimpleNamespace(_cfg=lambda: {"ASC_APP_ID": "0"}, call=None)
sys.modules["asc_app_events"] = types.SimpleNamespace()
import asc_events_auto as ev  # noqa: E402


def test_thanksgiving_is_the_fourth_thursday():
    assert ev.thanksgiving(2026) == date(2026, 11, 26)
    assert ev.thanksgiving(2027) == date(2027, 11, 25)


def test_every_month_fits_apples_limits_and_runs_under_31_days():
    for m in range(1, 13):
        for s in ev.planned(date(2026, m, 1)):   # spec() asserts the text limits
            assert ev.parse(s["eventEnd"]) - ev.parse(s["eventStart"]) <= ev.timedelta(days=31), s["referenceName"]


def test_holiday_weeks_are_planned_and_exempt_from_the_14_day_skip():
    by = {s["referenceName"]: s for s in ev.planned(date(2026, 10, 24))}
    assert by["Halloween 2026"]["deepLink"] == "findacrib://search"
    assert by["Thanksgiving 2026"]["deepLink"] == "findacrib://tool/repair"
    assert by["Halloween 2026"]["min_left"] < 14
    assert by["Halloween 2026"]["card"] == "fac-events-icon/halloween/card-3840x2160.png"


def test_every_event_carries_the_logo_art():
    for m in range(1, 13):
        for s in ev.planned(date(2026, m, 1)):
            assert s["card"].startswith(("fac-events-logo/everyday/", "fac-events-icon/")), s["referenceName"]
    dec = {s["referenceName"]: s for s in ev.planned(date(2026, 12, 1))}
    assert dec["Bedbug reports 2026"]["card"] == "fac-events-logo/everyday/card-3840x2160.png"


def test_every_holiday_in_holidays_json_has_an_event():
    import json
    ids = [h["id"] for h in json.loads(ev.HOLIDAYS_JSON.read_text())["holidays"]]
    assert sorted(ids) == sorted(ev.HOLIDAY_EVENTS)
    seen = set()
    for m in range(1, 13):
        seen |= {s["referenceName"].rsplit(" ", 1)[0] for s in ev.planned(date(2026, m, 1)) if s.get("holiday")}
    names = {h["name"] for h in json.loads(ev.HOLIDAYS_JSON.read_text())["holidays"]}
    assert names <= seen, names - seen


def test_holiday_dates():
    hs = {h["id"]: h for h in __import__("json").loads(ev.HOLIDAYS_JSON.read_text())["holidays"]}
    assert ev.holiday_day(hs["black-friday"], 2026) == date(2026, 11, 27)
    assert ev.holiday_day(hs["memorial"], 2027) == date(2027, 5, 31)
    assert ev.holiday_day(hs["mlk"], 2027) == date(2027, 1, 18)

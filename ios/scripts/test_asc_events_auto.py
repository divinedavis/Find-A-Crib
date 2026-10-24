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

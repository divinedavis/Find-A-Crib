"""A Housing Connect lottery with no map pin gets coordinates from its
address, so its card shows the street instead of no photo (2026-11-07)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import housing_connect as hc  # noqa: E402


def _with_lookup(fn, body):
    real = hc.coords_for
    hc.coords_for = fn
    try:
        body()
    finally:
        hc.coords_for = real


def test_missing_pin_is_filled_from_the_address():
    rec = {"lotteryId": 7676, "lotteryName": "6-05 129th Street Apartments", "borough": "Queens",
           "markers": [{"address": "6-05 129TH ST", "zip": "11356"}]}

    def check():
        out = hc.one(rec)
        assert (out["lat"], out["lng"]) == (40.79162, -73.83837)
    _with_lookup(lambda address, borough: (40.79162, -73.83837), check)


def test_a_pin_from_housing_connect_is_kept():
    rec = {"lotteryId": 1, "borough": "Bronx", "markers": [{"address": "1 X ST", "lat": "40.8", "lng": "-73.9"}]}

    def never(*a):
        raise AssertionError("no lookup needed")

    def check():
        out = hc.one(rec)
        assert (out["lat"], out["lng"]) == (40.8, -73.9)
    _with_lookup(never, check)

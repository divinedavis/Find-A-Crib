"""Each Housing Connect lottery carries the one photo the city publishes for
it, so the card stops showing a street view of scaffolding (owner,
2026-11-17: "do these nyc lotteries not have more photos per building?")."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import housing_connect as hc  # noqa: E402

PIN = [{"address": "1 X ST", "lat": "40.8", "lng": "-73.9"}]


def test_city_photo_is_kept():
    url = "https://a806-housingconnectapi.nyc.gov/MailTemplates/photos/38316431.png"
    out = hc.one({"lotteryId": 1, "borough": "Brooklyn", "markers": PIN, "defaultPhotoStream": url})
    assert out["image"] == url


def test_no_photo_or_a_foreign_url_is_dropped():
    for bad in (None, "", "http://a806-housingconnectapi.nyc.gov/x.png",
                "https://evil.example/x.png", "javascript:alert(1)",
                "https://a806-housingconnectapi.nyc.gov.evil.example/x.png"):
        out = hc.one({"lotteryId": 1, "borough": "Brooklyn", "markers": PIN, "defaultPhotoStream": bad})
        assert out["image"] is None, bad

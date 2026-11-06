"""The live journeys' ad-noise filter (tests/journeys.py ad_noise): a failed
ad tracking image is the ad stack's, one of ours is not (2026-11-06)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import journeys  # noqa: E402


class Msg:
    def __init__(self, text, url="https://findacrib.com/"):
        self.text, self.location = text, {"url": url}


def test_a_failed_third_party_ad_image_is_noise():
    assert journeys.ad_noise(Msg("Cannot load image https://ila3.co/o/676718?p=2306&aff_clickid=x&sub1=emxdigital"))


def test_one_of_our_images_failing_is_not():
    assert not journeys.ad_noise(Msg("Cannot load image https://findacrib.com/static/icons/app.png"))
    assert not journeys.ad_noise(Msg("Cannot load image https://data.cityofnewyork.us/x.png"))

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


U = "https://a806-housingconnectapi.nyc.gov/MailTemplates/photos/"


def test_photo_set_keeps_the_city_order_lead_first_and_drops_foreign_urls():
    advert = {"photos": [{"item1": U + "3.png", "item3": 2}, {"item1": U + "1.png", "item3": 0},
                         {"item1": "https://evil.example/x.png", "item3": 1}, {"item1": U + "2.png", "item3": 1},
                         {"item1": U + "1.png", "item3": 5}, "junk"]}
    assert hc.photo_set(advert, U + "1.png") == [U + "1.png", U + "2.png", U + "3.png"]
    assert hc.photo_set(None, U + "1.png") == [U + "1.png"]
    assert len(hc.photo_set({"photos": [{"item1": U + f"{i}.png", "item3": i} for i in range(30)]})) == hc.MAX_PHOTOS


def test_add_photos_sets_images_only_when_there_is_more_than_one():
    out = [{"id": 1, "image": U + "a.png"}, {"id": 2, "image": U + "b.png"}, {"id": 3, "image": None}]
    adverts = {1: {"photos": [{"item1": U + "a.png", "item3": 0}, {"item1": U + "a2.png", "item3": 1}]},
               2: None, 3: {"photos": [{"item1": U + "c.png", "item3": 0}, {"item1": U + "c2.png", "item3": 1}]}}
    hc.add_photos(out, fetcher=adverts.get, pause=0, now=1000)
    assert out[0]["images"] == [U + "a.png", U + "a2.png"]
    assert "images" not in out[1] and out[1]["image"] == U + "b.png"   # a failed call keeps the one photo
    assert out[2]["image"] == U + "c.png" and out[2]["images"] == [U + "c.png", U + "c2.png"]


def test_photo_sets_are_cached_for_a_day_and_failures_retried_sooner():
    calls = []
    def fetch(i):
        calls.append(i)
        return None if i == 2 else {"photos": [{"item1": U + f"{i}a.png", "item3": 0}, {"item1": U + f"{i}b.png", "item3": 1}]}
    lots = lambda: [{"id": 1, "image": U + "1a.png"}, {"id": 2, "image": U + "2a.png"}]
    cache = hc.add_photos(lots(), fetcher=fetch, pause=0, now=0)
    assert calls == [1, 2]
    out = lots(); hc.add_photos(out, fetcher=fetch, pause=0, cache=cache, now=600)   # the next 10-minute run
    assert calls == [1, 2] and out[0]["images"] == [U + "1a.png", U + "1b.png"]      # served from the cache
    hc.add_photos(lots(), fetcher=fetch, pause=0, cache=cache, now=hc.PHOTO_RETRY + 1)
    assert calls == [1, 2, 2]                                                        # only the failure retried
    hc.add_photos(lots(), fetcher=fetch, pause=0, cache=cache, now=hc.PHOTO_TTL + 1)
    assert calls == [1, 2, 2, 1, 2]
    hc.add_photos([{"id": 1, "image": None}], fetcher=fetch, pause=0, cache=cache, now=hc.PHOTO_TTL + 2)
    assert "2" not in cache                                                          # closed lottery forgotten

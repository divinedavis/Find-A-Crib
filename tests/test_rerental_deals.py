"""rerental_deals — move-in deals only when the listing says so (2026-10-27)."""
import rerental_deals as D

HOUSE_55 = ("INCENTIVES : One month free on a 1 year lease, Two months free on a 2 year lease "
            "50% off amenities fees during 1st lease year $1,000 security deposit regardless of the unit size. "
            "Pet Policy – No fees or deposit required.")
LUMEN = ("INCENTIVES : 1 month free on a 1 or 2 year lease, 50% off amenities fees during 1st lease year, "
         "$1,000 off security deposit regardless of the unit size Pet Policy")
KG = "Verdant Fort Greene 240 Willoughby Street ►► TWO MONTHS FREE RENT WITH A 1- OR 2-YEAR LEASE ◄◄ New luxury"


def titles(d):
    return [p["title"] for p in d["perks"]]


def test_two_offers_become_up_to():
    d = D.find_deal(HOUSE_55)
    assert titles(d) == ["Up to 2 months free", "$1,000 security deposit", "50% off amenity fees"]
    assert d["perks"][0]["detail"] == "1 mo on 1-yr, 2 on 2-yr"
    assert d["perks"][1]["detail"] == "Any unit size" and d["perks"][2]["detail"] == "First lease year"
    assert d["free_on_12"] == 1


def test_deposit_off_and_either_lease():
    d = D.find_deal(LUMEN)
    assert titles(d)[:2] == ["1 month free", "$1,000 off the security deposit"]
    assert d["perks"][0]["detail"] == "On a 1- or 2-year lease" and d["free_on_12"] == 1


def test_shouting_banner():
    d = D.find_deal(KG)
    assert titles(d) == ["2 months free"] and d["free_on_12"] == 2


def test_no_deal_no_box():
    for t in ["No fee to apply • No broker’s fee • Smoke-free building",
              "Security deposit is one month's rent.", "Applicants are not eligible for 2 months free.",
              "Security deposit: $3,450", ""]:
        assert D.find_deal(t) is None, t


def test_months_free_without_a_lease_has_no_average():
    d = D.find_deal("Move-in special: 1 month free!")
    assert titles(d) == ["1 month free"] and d["free_on_12"] is None


def test_site_banner_on_every_listing_is_dropped():
    recs = [{"agent": "A", "deal_src": KG} for _ in range(3)] + [{"agent": "B", "deal_src": LUMEN}]
    assert D.attach(recs) == 1
    assert "deal" not in recs[0] and recs[3]["deal"]["free_on_12"] == 1
    assert all("deal_src" not in r for r in recs)


def test_board_card_is_the_fallback():
    r = {"agent": "K&G", "_card": ["240 Willoughby Street", "TWO MONTHS FREE RENT WITH A 1- OR 2-YEAR LEASE"]}
    D.attach([r])
    assert titles(r["deal"]) == ["2 months free"]

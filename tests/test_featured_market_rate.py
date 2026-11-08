"""featured_rerentals.market_rate: a market-rate unit on an agent's
affordable board is not a re-rental (54 Crown St, 2026-11-08)."""
import featured_rerentals as F


def rec(**kw):
    r = {"agent": "MNS", "address": "54 Crown ST", "money_kind": "rent",
         "money_low": 2653, "money_high": 2653, "beds": None, "_card": []}
    r.update(kw)
    return r


def test_net_rent_on_the_listing_page_is_market_rate():
    page = ("Brand New Luxury Two Bedroom Two Bathroom Now Available In Crown Heights! "
            "Now offering 2 months free on a 14 month lease. Net rent advertised")
    assert F.market_rate(rec(money_low=5292, deal_src=page)) == "net rent"


def test_net_effective_on_the_card_is_market_rate():
    assert F.market_rate(rec(_card=["$3,100 net effective"]))


def test_an_affordable_rent_with_a_free_month_stays():
    page = "Income restricted. 1 month free on a 13-month lease. Household income $64,000 - $98,000."
    assert F.market_rate(rec(money_low=2653, deal_src=page)) is None


def test_rent_over_the_165_ami_ceiling_for_its_size():
    assert F.market_rate(rec(money_low=5100, beds="1"))
    assert F.market_rate(rec(money_low=5100, beds="2")) is None


def test_unknown_size_uses_the_three_bed_ceiling():
    assert F.market_rate(rec(money_low=7000)) is not None
    assert F.market_rate(rec(money_low=6900)) is None


def test_income_figures_are_not_rents():
    assert F.market_rate(rec(money_kind="income", money_low=150000)) is None

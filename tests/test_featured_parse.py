"""featured_rerentals.parse_card — the card shapes the HPD re-rental list
turned up on 2026-10-28, when ~30 agents' listings were being missed."""
import featured_rerentals as F


def card(*lines, addr=None):
    return {"lines": list(lines), "addr": addr, "href": None, "img": None, "heading": ""}


def parse(*lines, addr=None):
    return F.parse_card(card(*lines, addr=addr), "Agent", "https://example.org/board")


def test_a_studio_with_no_bed_after_it():
    # St. Nicks: "2481 Crotona Avenue: Studio"
    r = parse("2481 Crotona Avenue: Studio")
    assert r["beds"] == "studio"
    assert r["address"] == "2481 Crotona Avenue"


def test_a_yoga_studio_is_not_an_apartment_size():
    r = parse("240 Willoughby Street, Brooklyn, NY 11201", "Fitness center, yoga studio")
    assert r["beds"] is None


def test_units_available_keeps_a_card_with_no_rent():
    # Spring Leasing prints "UNIT(S) AVAILABLE" and no price.
    r = parse("1488 New York Avenue, Brooklyn, NY 11210", "1488 NEW YORK AVENUE UNIT(S) AVAILABLE")
    assert F.is_real_listing(r, set())


def test_a_bare_address_with_nothing_else_is_still_dropped():
    r = parse("1488 New York Avenue, Brooklyn, NY 11210")
    assert not F.is_real_listing(r, set())


def test_homeownership_and_coops_are_not_rentals():
    assert parse("Belle Gardens (Homeownership)", "20 Suydam Place, Brooklyn, NY 11233") is None
    assert parse("ANCP Phase I", "518 W 161st St, New York, NY") is None


def test_a_rented_unit_and_a_coming_soon_building_are_closed():
    assert parse("RENTED", "1182 Ogden Ave - Highbridge, Bronx", "Rent $2,308") is None
    assert parse("COMING SOON", "9 Ft Washington Avenue, New York, NY") is None


def test_a_rent_stabilized_card_is_not_rented():
    assert parse("1182 Ogden Ave, Bronx", "Rent-stabilized, Rent $2,308") is not None


def test_paused_applications_count_as_on_hold():
    r = parse("Applications temporarily paused", "36-23 172nd Street, Queens, NY 11358", "Rent $1,670")
    assert r["on_hold"]
    assert r["title"] == ""


def test_a_household_range_is_not_a_street():
    assert F.NOT_A_STREET.match("1 - 3 people")


def test_the_name_before_an_embedded_address_is_the_title():
    r = parse("Greenpoint Central Apartments - 65 Dupont Street", "65 Dupont Street",
              "Rent: $3423.00 - $4376.00")
    assert r["title"] == "Greenpoint Central Apartments"


def jev_run(records, listing):
    """jev_review with a stand-in TypeSafe client that answers every card alike."""
    import os, sys, types
    from unittest import mock

    class A:
        def __init__(self, p):
            self.noul = p

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def system_one(self, state, questions):
            return types.SimpleNamespace(usage=types.SimpleNamespace(input_tokens=1),
                                         answers={"open": A(0.9), "listing": A(listing), "rent": A(0.5)})

    sdk = types.SimpleNamespace(TypeSafeClient=Client, Noul=lambda instructions: instructions)
    with mock.patch.dict(sys.modules, {"typesafe_sdk": sdk}), \
         mock.patch.dict(os.environ, {"TYPESAFE_API_KEY": "test"}):
        return F.jev_review(records)[0]


def jev_card(**extra):
    return dict({"_amounts": [], "money_kind": None, "money_low": None, "_card": ["302 East 2nd Street"],
                 "address": "302 East 2nd Street", "agent": "Stanton Norfolk"}, **extra)


def test_jev_still_drops_a_card_it_reads_as_no_apartment():
    assert jev_run([jev_card()], listing=0.14) == []


def test_a_page_checked_by_hand_survives_jevs_not_a_listing_veto():
    # East Village Homes' RentCafe homepage: kept 10-28, dropped at 0.14 on 10-29.
    assert len(jev_run([jev_card(_vouched=True)], listing=0.14)) == 1

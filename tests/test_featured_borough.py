"""featured_rerentals.borough_of — which borough a re-rental card is in."""
import featured_rerentals as F


def test_named_borough_beats_new_york():
    assert F.borough_of("2187 Ryer Avenue. Unit 6D", "Bronx, NY", None) == "Bronx"


def test_link_names_the_borough_when_the_card_says_new_york():
    # MNS, 2026-10-04: the card said "New York", the link ended in /bronx.
    blob = "New York, NY \n details 240428 rental morris heights bronx"
    assert F.borough_of("1730 Harrison AVE", blob, None) == "Bronx"


def test_bare_new_york_still_means_manhattan():
    assert F.borough_of("555 W 38th St", "New York, NY", None) == "Manhattan"


def test_zip_when_nothing_is_named():
    assert F.borough_of("1 Main St", "", "11201") == "Brooklyn"

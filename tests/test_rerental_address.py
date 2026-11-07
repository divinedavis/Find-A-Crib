"""rerental_address: every re-rental card in the 445 Grand Avenue format
(owner, 2026-10-22). Offline: the ZIP lookup is stubbed."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import rerental_address as ra  # noqa: E402

ra.ZIP_CACHE = "/dev/null"
CASES = [
    # agent's text, title, borough, zip  ->  title, address
    ("445 Grand Avenue, Brooklyn, NY 11238", "Arris Grand", "Brooklyn", "11238",
     "Arris Grand", "445 Grand Avenue, Brooklyn, NY 11238"),
    ("55 Willoughby St, Brooklyn, NY 11201", "House 55 Apartments", "Brooklyn", "11201",
     "House 55 Apartments", "55 Willoughby St, Brooklyn, NY 11201"),
    ("Greenpoint Central Apartments - 65 Dupont Street Units Still Available", "", "Brooklyn", None,
     "Greenpoint Central Apartments", "65 Dupont Street, Brooklyn, NY 11222"),
    ("183 Covert Street Unit 2F 1026", "", "Brooklyn", None, "Unit 2F", "183 Covert Street, Brooklyn, NY 11222"),
    ("1420 Stebbins avenue apartments - 0126 Multiple Units", "", "Bronx", None, "", "1420 Stebbins Avenue, Bronx, NY 11222"),
    ("44-15 Colden Street Apartment – Unit 1S", "Open Market", "Queens", None, "Unit 1S", "44-15 Colden Street, Queens, NY 11222"),
    ("1164 River Avenue, Concourse, Bronx, 10452", "River Crest Apartments", "Bronx", "10452",
     "River Crest Apartments", "1164 River Avenue, Bronx, NY 10452"),
    ("126-43 39th Avenue & 126-55 39th Avenue Flushing, NY 11368", "Willets Point Commons", "Queens", "11368",
     "Willets Point Commons", "126-43 39th Avenue & 126-55 39th Avenue, Queens, NY 11368"),
]


def test_every_card_reads_like_445_grand_avenue():
    for src, title, boro, z, want_title, want_addr in CASES:
        r = {"address": src, "title": title, "borough": boro, "zip": z}
        ra.tidy([r], lookup_zip=lambda street, b, cache: ("11222", None), lookup_xy=lambda *a: None)
        assert (r["title"], r["address"]) == (want_title, want_addr), (src, r)
        assert r["address_src"] == src


def test_the_citys_borough_beats_the_agents():
    r = {"address": "2710 Decatur Ave. Unit PH2", "title": "", "borough": "Brooklyn", "zip": None}
    ra.tidy([r], lookup_zip=lambda street, b, cache: ("10458", "Bronx"), lookup_xy=lambda *a: None)
    assert r["address"] == "2710 Decatur Ave, Bronx, NY 10458" and r["borough"] == "Bronx"


def test_an_address_it_cannot_place_is_left_as_written():
    r = {"address": "55 South Essex Avenue", "title": "", "borough": None, "zip": None}
    ra.tidy([r], lookup_zip=lambda street, b, cache: (None, None), lookup_xy=lambda *a: None)
    assert r["address"] == "55 South Essex Avenue"


def test_street_key_matches_abbreviations_and_ordinals():
    assert ra.street_key("2710 Decatur Ave.") == ra.street_key("2710 DECATUR AVENUE, Bronx, NY")
    assert ra.street_key("148-37 88th Ave") == ra.street_key("148-37 88 AVENUE")
    assert ra.street_key("55 South Essex Avenue") != ra.street_key("55 SOUTH STREET")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)


def test_a_placed_address_gets_coordinates_for_the_street_view():
    # 2026-11-07: 58 of 125 re-rentals had no photo; the app shows the street there.
    r = {"address": "1730 Harrison Ave, Bronx, NY 10453", "borough": "Bronx"}
    ra.tidy([r], lookup_zip=lambda street, b, cache: ("10453", "Bronx"),
            lookup_xy=lambda street, b, cache: (40.849718, -73.913916))
    assert (r["lat"], r["lng"]) == (40.849718, -73.913916)


def test_no_exact_hit_means_no_coordinates():
    r = {"address": "1730 Harrison Ave, Bronx, NY 10453", "borough": "Bronx"}
    ra.tidy([r], lookup_zip=lambda street, b, cache: ("10453", "Bronx"), lookup_xy=lambda *a: None)
    assert "lat" not in r, "a guess would show another building's street"


def test_a_range_or_pair_is_placed_at_its_first_building():
    assert ra.street_candidates("263-267 West 126th Street", "Manhattan")[-1] == "263 West 126th Street"
    assert ra.street_candidates("2317-21 Tiebout Avenue", "Bronx")[-1] == "2317 Tiebout Avenue"
    assert "19-38 Cornaga Ave" in ra.street_candidates("19-38 Cornaga Ave & 10-18 Beach 20th Street", "Queens")
    assert ra.street_candidates("17-11 Hancock Street", "Queens") == ["17-11 Hancock Street"], "a Queens house number is not a range"

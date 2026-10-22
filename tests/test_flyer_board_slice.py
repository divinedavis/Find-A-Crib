"""flyer_reader.board_slice: a re-rental linked to its spot on an agent's
board is read from its own block, not the whole board (2026-10-22)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import flyer_reader as fr  # noqa: E402

BOARD = ("Our listings | 2187 Ryer Avenue. Unit 6D | Bronx, NY | Rent: $2,660 | Min Income: $98,278 - $168,480 | "
         "103 Liberty Avenue. Unit 6C | Brooklyn, NY | Rent: $3,741.18 | Min Income: $128,270 - $238,160 | "
         "2187 Ryer Avenue. Unit 8A | Bronx, NY | Rent: $3,187 | Min Income: $109,269 - $227,500 | "
         "22 Milford Street. Unit 2G | Brooklyn, NY | Rent: $2,316.47")


def listing(addr, frag):
    return {"href_kind": "agent_page", "address": addr, "href": f"https://example.com/board#:~:text={frag}"}


def test_slice_starts_at_the_full_address_and_stops_at_the_next_listing(monkeypatch=None):
    fr.listing_page.text_of = lambda url, render=False: BOARD
    s = fr.board_slice(listing("103 Liberty Avenue. Unit 6C", "103%20Liberty"))
    assert s.startswith("103 Liberty Avenue. Unit 6C") and "$128,270" in s
    assert "2187 Ryer" not in s and "$109,269" not in s


def test_full_address_beats_the_fragment_when_a_building_has_several_units():
    fr.listing_page.text_of = lambda url, render=False: BOARD
    s = fr.board_slice(listing("2187 Ryer Avenue. Unit 8A", "2187%20Ryer"))
    assert s.startswith("2187 Ryer Avenue. Unit 8A") and "$109,269" in s and "Milford" not in s


def test_only_fragment_links_count_as_board_listings():
    assert fr.on_board(listing("x", "y"))
    assert not fr.on_board({"href_kind": "agent_page", "href": "https://example.com/board"})
    assert not fr.on_board({"href_kind": "listing", "href": "https://example.com/a#:~:text=b"})


def test_slice_stops_at_other_buildings_heading():
    import flyer_reader as fr
    page = ("240 Willoughby Street, Brooklyn, New York 11201\nIncome Limits\n1 people $107,383 - $154,440\n"
            " Additional Opportunities (BRONX) \n Diego Beekman\n Studio: $2,525.00\n")
    orig = fr.listing_page.text_of
    fr.listing_page.text_of = lambda url, render=False: page
    try:
        sl = fr.board_slice({"href": "https://x.test/v#:~:text=240%20Willoughby", "address": "240 Willoughby Street, Brooklyn, NY 11201",
                             "address_src": "240 Willoughby Street, Brooklyn, New York 11201"})
    finally:
        fr.listing_page.text_of = orig
    assert "$154,440" in sl and "Beekman" not in sl, sl


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn(); print("ok", name)

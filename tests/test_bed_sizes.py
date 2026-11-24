"""bed_sizes: what a card prints -> the sizes the alerts filter on.

The dangerous mistake is reading too FEW sizes: "Studio, 1 & 2 Bedrooms" read
as "2" would hide a home from everyone who asked for a studio or a 1-bedroom.
So lists and ranges are read whole, and anything unreadable is None ("the
source did not say"), which never hides a listing from anyone.
"""
import bed_sizes as B


def test_one_stated_size():
    for text, want in {"Unit Size: 0": [0], "Unit Size: studio": [0], "Unit Size: 3": [3],
                       "2 Bedroom apartment": [2], "2-Bedroom": [2], "1BR": [1], "1 bd": [1], "2 BRs": [2],
                       "Bedrooms: 2": [2], "Studio": [0], "Type: Studio": [0], "Studios from $1,900": [0],
                       "$1,200 2 bed": [2]}.items():
        assert B.sizes_in([text]) == want, text


def test_lists_and_ranges_are_read_whole():
    for text, want in {"Studio, 1 & 2 Bedrooms": [0, 1, 2], "1-3 beds": [1, 2, 3], "1 and 2 bedroom units": [1, 2],
                       "studio or 1 bedroom": [0, 1], "3 to 4 bedrooms": [3, 4], "Unit Size: 0 - 2": [0, 1, 2],
                       "Beds: Studio - 2": [0, 1, 2], "1 & 2 BR": [1, 2],
                       "1-Bedroom, 2-Bedroom, Studio": [0, 1, 2]}.items():
        assert B.sizes_in([text]) == want, text


def test_four_or_more_is_one_bucket():
    assert B.sizes_in(["4+ bedrooms"]) == [4]
    assert B.sizes_in(["5 bedrooms"]) == [4]
    assert B.sizes_of([6]) == [4]


def test_bathrooms_people_money_and_addresses_are_not_sizes():
    for text in ("Rent: $2,368.05", "1 PERSON $87,704.57 -$154,440.00", "Household size: 1-2",
                 "3 PEOPLE $82,393.71", "325 Gates Ave.", "110 2nd Ave", "Apt 2 Brooklyn",
                 "unit 4 bedford ave", "12 bedrooms", "Yoga studio and gym", "Gym, yoga studio",
                 "Studio space for artists", ""):
        assert B.sizes_in([text]) is None, text
    assert B.sizes_in(["2 bed / 1 bath"]) == [2]
    assert B.sizes_in(["1 bath, 2 bed"]) == [2]
    assert B.sizes_in(["Bathrooms: 1, Bedrooms: 2"]) == [2]
    assert B.sizes_in(["Studio / 1 Bath"]) == [0]


def test_a_whole_card_is_the_union_of_its_lines():
    card = ["325 Gates Ave.", "Brooklyn, NY", "Unit Size: 0", "Household size: 1-2", "Rent: $2,368.05",
            "1 PERSON $87,704.57 -$154,440.00", "2 PEOPLE $87,704.57 -$176,410.00"]
    assert B.sizes_in(card) == [0]
    assert B.sizes_in("2 Bedroom\nalso 1BR available") == [1, 2]


def test_a_feeds_own_field():
    assert B.sizes_of(["Studio", "1-bed", "3-bed"]) == [0, 1, 3]      # Housing Connect
    assert B.sizes_of("studio") == [0] and B.sizes_of("2") == [2]      # a featured tile
    assert B.sizes_of([1, 1, None, 2]) == [1, 2]                       # a flyer's unit table
    for nothing in (None, "", [], [None], "n/a", True):
        assert B.sizes_of(nothing) is None


def test_fits_only_rules_out_on_a_stated_size():
    assert not B.fits([1], [0])
    assert B.fits([1], [0, 1])
    assert B.fits([1], None) and B.fits([1], [])          # not stated: never hidden
    assert B.fits([], [0]) and B.fits(None, [0])          # no choice: every size
    assert B.fits([4], [5])
    assert B.fits("rubbish", [0])                         # an unreadable choice is no filter


def test_words_for_the_email_footer():
    assert B.words([1]) == "1-bedrooms"
    assert B.words([0, 1]) == "studios and 1-bedrooms"
    assert B.words([2, 3, 4]) == "2-bedrooms, 3-bedrooms and 4+ bedrooms"
    assert B.words([]) == "" and B.words(None) == ""

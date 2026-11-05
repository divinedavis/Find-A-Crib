"""The alert emails' list (owner, 2026-10-27; restyled as the alert card
2026-11-05): linked items render as rows with the price on the right, a list
of two or more opens with its count, and the page stays inline-styled."""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))


def _items():
    import lottery_alerts as la
    return la.rerental_items({"items": [
        {"agent": "A Co", "key": "g", "label": "445 Grand Avenue, Brooklyn, NY 11238", "url": "https://x/1",
         "boro": "Brooklyn", "hood": "Clinton Hill", "rent_low": None},
        {"agent": "B Co", "key": "f", "label": "2171 Frederick Douglass Blvd", "url": "https://x/2",
         "boro": "Manhattan", "hood": "Central Harlem", "rent_low": 4176}]})


def test_row_has_price_right_and_trims_the_city():
    import lottery_alerts as la
    a, b = (la.email_row(i) for i in _items())
    assert a["text"] == "445 Grand Avenue" and a["right"] is None
    assert b["right"] == "$4,176" and b["sub"] == "Central Harlem · Manhattan · listed by B Co"


def test_counts_tiles_need_two_items():
    import lottery_alerts as la
    items = _items()
    assert la.counts_block(items[:1], "new") is None
    assert la.counts_block(items, "new")["items"][0] == (2, "new")


def test_alert_renders_group_and_tiles_inline():
    import lottery_alerts as la
    from growth import emailkit
    sub = {"email": "d@x.com", "boroughs": ["M", "Bk"], "kinds": ["rerental"], "token": "0" * 8}
    _, html, text, _ = la.render_alert(_items(), sub, emailkit)
    # The alert card (owner, 2026-11-05): white card, label top right, the
    # count large, rows with a coloured square and the price on the right.
    assert "border-radius:22px" in html and ">Re-rental</span>" in html
    assert "$4,176" in html and ">new</span>" in html and ">2</span>" in html
    assert "<style" not in html                                      # Gmail strips <style>
    assert "2171 Frederick Douglass Blvd — $4,176" in text           # the text part keeps the price


def test_single_item_is_a_building_card():
    import lottery_alerts as la
    from growth import emailkit
    sub = {"email": "d@x.com", "boroughs": ["M"], "kinds": ["rerental"], "token": "0" * 8}
    _, html, text, _ = la.render_alert(_items()[1:], sub, emailkit)
    assert "No lottery needed" in html and "First come, first served" in html
    assert "$4,176" in html and "/ mo" in html
    assert "Open the listing" in html                                # the button goes to the listing
    assert "<style" not in html

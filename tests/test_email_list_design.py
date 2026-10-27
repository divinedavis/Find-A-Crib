"""The alert emails' iPhone-style list (owner, 2026-10-27, design #2 of three):
linked items render as one white group with the price on the right, a list of
two or more opens with count tiles, and the page stays inline-styled."""
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
    assert "border-radius:14px" in html and "&rsaquo;" in html      # the white group, the chevron
    assert "$4,176" in html and "new</div>" in html                  # price column, count tile
    assert "<style" not in html                                      # Gmail strips <style>
    assert "2171 Frederick Douglass Blvd — $4,176" in text           # the text part keeps the price

"""llms.txt names the re-rental feed and the two NYC guides (2026-10-29)."""
import json
import os
import tempfile
import types

from growth import techniques as T


def run(featured=None, live=()):
    with tempfile.TemporaryDirectory() as doc:
        if featured is not None:
            with open(os.path.join(doc, "featured.json"), "w") as f:
                json.dump(featured, f)
        out = {}
        ctx = types.SimpleNamespace(
            buildings=[{}] * 3, s8={}, by_bbl={}, docroot=doc,
            live_or_staged=lambda rel: rel in live,
            write_raw=lambda name, text: out.__setitem__(name, text))
        T.t_llms_txt(ctx)
        return out


GUIDES = ("guide/how-to-find-a-rent-stabilized-apartment/index.html",
          "guide/is-my-apartment-rent-stabilized/index.html")


def test_the_re_rental_feed_is_counted_from_the_file():
    feed = {"listings": [{"agent": "A"}, {"agent": "A"}, {"agent": "B"}]}
    txt = run(feed)["llms.txt"]
    assert "Affordable re-rentals, checked every morning: 3 open apartments from 2 marketing agents" in txt


def test_no_feed_means_no_re_rental_line_rather_than_a_guess():
    assert "re-rentals, checked" not in run(None)["llms.txt"]
    assert "re-rentals, checked" not in run({"listings": []})["llms.txt"]


def test_the_nyc_guides_are_listed_only_when_live():
    assert "/guide/how-to-find-a-rent-stabilized-apartment/" not in run()["llms.txt"]
    txt = run(live=GUIDES)["llms.txt"]
    assert "https://findacrib.com/guide/how-to-find-a-rent-stabilized-apartment/" in txt
    assert "https://findacrib.com/guide/is-my-apartment-rent-stabilized/" in txt


def test_robots_names_claudes_search_crawler():
    assert "User-agent: Claude-SearchBot\nAllow: /" in run()["robots.txt"]


def test_robots_blocks_the_seo_audit_crawlers():
    txt = run()["robots.txt"]
    group = txt.split("User-agent: QlyzeBot", 1)[1].split("\n\n", 1)[0]
    for b in ("SemrushBot", "SiteAuditBot", "AhrefsBot", "AhrefsSiteAudit"):
        assert f"User-agent: {b}" in group
    assert group.rstrip().endswith("Disallow: /")
    # the AI crawlers and everyone else stay allowed
    assert txt.startswith("User-agent: *\nAllow: /")
    assert "User-agent: GPTBot\nAllow: /" in txt


def test_refresh_seo_never_overwrites_robots_txt():
    with open(os.path.join(os.path.dirname(__file__), "..", "scripts", "refresh_seo.sh")) as f:
        sh = f.read()
    assert '--exclude robots.txt "$BUILD/seo/" "$DOC/"' in sh

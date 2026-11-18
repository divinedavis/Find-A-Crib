"""The building photo in a one-listing alert (owner, 2026-11-18)."""
import os
import sys
import pathlib
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import alert_photos as ap  # noqa: E402

# The MGNY page of 2026-11-18: a site-wide og:image card, a logo, the photo.
PAGE = """<html><head>
<meta property="og:image" content="https://agent.example/wp-content/uploads/2026/09/og-default-mgny-1200x630-1.jpg" />
</head><body>
<img width="150" height="135" src="https://agent.example/uploads/logo.svg">
<img width="120" src="/uploads/small-thumb.jpg">
<img width="777" height="519" src="/wp-content/uploads/2026/04/13418640-777x519-1.jpeg">
</body></html>"""


def test_page_photos_skip_the_default_card_logo_and_thumbnails():
    got = ap.page_photos(PAGE, "https://agent.example/listing/2633-ocean-avenue/")
    assert got == ["https://agent.example/wp-content/uploads/2026/04/13418640-777x519-1.jpeg"]


def test_a_real_og_image_comes_first():
    page = '<meta property="og:image" content="https://a.example/photos/front.jpg">' + PAGE
    assert ap.page_photos(page, "https://a.example/")[0] == "https://a.example/photos/front.jpg"


def test_featured_photo_is_used_without_fetching():
    feat = {"listings": [{"href": "https://a.example/l/1", "image": "/featured/img/aa.jpg",
                          "image_large": "/featured/img/aa_l.jpg"}]}
    r = ap.Resolver(tempfile.mkdtemp(), {}, featured=feat, fetch=False)
    assert r({"url": "https://a.example/l/1#:~:text=12%20Main"}) == "https://findacrib.com/featured/img/aa_l.jpg"
    assert r({"url": "https://a.example/l/2"}) is None


def test_one_picture_on_two_listings_is_stock(monkeypatch=None):
    d = tempfile.mkdtemp()
    r = ap.Resolver(d, {})
    r._host = lambda src: "https://findacrib.com/alert-img/x.jpg"
    assert r({"url": "https://a.example/1", "image_src": "https://a.example/same.jpg"})
    r.cache["by_item"].clear()
    assert r({"url": "https://a.example/2", "image_src": "https://a.example/same.jpg"}) is None


def test_answers_are_cached_and_misses_retry_later():
    r = ap.Resolver(tempfile.mkdtemp(), {}, fetch=False, now=1000)
    calls = []
    r._find = lambda it, key: calls.append(key)
    r({"url": "https://a.example/1"}); r({"url": "https://a.example/1"})
    assert len(calls) == 1
    r.now = 1000 + ap.MISS_TTL + 1
    r({"url": "https://a.example/1"})
    assert len(calls) == 2


def test_private_addresses_are_never_fetched():
    for u in ("http://127.0.0.1/x.jpg", "http://169.254.169.254/latest/", "http://10.0.0.5/", "file:///etc/passwd"):
        assert not ap._ok_url(u)
        assert ap._get(u, 100, "*/*") == (None, None)


def test_jpeg_is_shrunk_and_tiny_images_refused():
    from PIL import Image
    import io
    buf = io.BytesIO(); Image.new("RGB", (2000, 1000), "gray").save(buf, "PNG")
    jpg, w = ap._jpeg(buf.getvalue())
    assert w == ap.OUT_W and jpg[:2] == b"\xff\xd8"
    buf = io.BytesIO(); Image.new("RGB", (200, 200)).save(buf, "PNG")
    assert ap._jpeg(buf.getvalue()) == (None, 0)


def test_prune_bounds_the_cache():
    c = {"by_item": {str(i): {"at": i} for i in range(500)}, "by_src": {}}
    ap.prune(c, keep=400)
    assert len(c["by_item"]) == 400 and "0" not in c["by_item"] and "499" in c["by_item"]

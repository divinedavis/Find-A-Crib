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


def _resolver(answers):
    """A stand-in for socket.getaddrinfo: {(host, family): [address, ...]}."""
    import socket

    def fake(host, port, family=0, *a, **k):
        if (host, family) not in answers:
            raise socket.gaierror("no such name")
        return [(family, 1, 6, "", (ip, 0)) for ip in answers[(host, family)]]
    return fake


def test_a_numeric_address_is_judged_as_written_whatever_the_network_says():
    """On an IPv6-only network the resolver turned 10.0.0.5 into
    2607:7700:0:28:0:2:a00:5, which looks public, and the check passed it
    (2026-11-25). A numeric host must never reach the resolver."""
    import socket
    real, asked = socket.getaddrinfo, []
    socket.getaddrinfo = lambda *a, **k: asked.append(a) or [(30, 1, 6, "", ("2607:7700:0:28:0:2:a00:5", 0, 0, 0))]
    try:
        for host in ("10.0.0.5", "192.168.1.1", "127.0.0.1", "169.254.169.254", "::1", "[::1]", "fe80::1%en0",
                     "::ffff:10.0.0.5", "64:ff9b::a00:5", "64:ff9b::7f00:1"):
            assert not ap._public_host(host), host
        for host in ("8.8.8.8", "2606:4700:4700::1111", "64:ff9b::808:808"):
            assert ap._public_host(host), host
        assert not asked
    finally:
        socket.getaddrinfo = real


def test_a_name_pointing_at_a_private_address_cannot_hide_behind_ipv6_translation():
    import socket
    real = socket.getaddrinfo
    try:
        # The resolver prefers a translated, public-looking IPv6 form; the
        # plain IPv4 answer is the private address it stands for.
        socket.getaddrinfo = _resolver({("inside.example", 0): ["2607:7700:0:28:0:2:a00:5"],
                                        ("inside.example", socket.AF_INET): ["10.0.0.5"]})
        assert not ap._public_host("inside.example")
        socket.getaddrinfo = _resolver({("mixed.example", 0): ["93.184.216.34", "10.0.0.5"],
                                        ("mixed.example", socket.AF_INET): ["93.184.216.34", "10.0.0.5"]})
        assert not ap._public_host("mixed.example")
        socket.getaddrinfo = _resolver({("ok.example", 0): ["93.184.216.34"],
                                        ("ok.example", socket.AF_INET): ["93.184.216.34"]})
        assert ap._public_host("ok.example")
        # IPv6 only: no IPv4 answer is not a reason to refuse it.
        socket.getaddrinfo = _resolver({("six.example", 0): ["2606:4700:4700::1111"]})
        assert ap._public_host("six.example")
        socket.getaddrinfo = _resolver({})
        assert not ap._public_host("nowhere.example")
        assert not ap._public_host("")
    finally:
        socket.getaddrinfo = real


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

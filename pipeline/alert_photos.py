"""A photo of the building for a one-listing alert email (owner, 2026-11-18:
picked the "editorial" design, the building's photo under the address).

Where the photo comes from, first match wins:
  1. the feed's own photo (Housing Connect `image`, HCR `image`), re-hosted;
  2. featured.json, the re-rental tiles' photo by listing link, which is
     already on findacrib.com;
  3. the listing page itself: its og:image unless that is the site's default
     card, else the first large <img> in the page.

Every photo is downloaded and served from findacrib.com/alert-img/, never
hotlinked: an email client loads it on every open, the agent's site would
see each one, and the image would break the day they move a file. One photo
that turns up for two different listings is the site's stock picture, not
this building, and is dropped. No photo is fine: the email then has no
picture, never a placeholder.
"""
import hashlib
import html as htmlmod
import io
import ipaddress
import json
import os
import re
import socket
import time
import urllib.parse
import urllib.request

SITE = "https://findacrib.com"
UA = "Mozilla/5.0 (compatible; FindACribBot/1.0; +https://findacrib.com/)"
MAX_PAGE = 1_500_000
MAX_IMG = 4_000_000
MIN_W = 400
OUT_W = 1200
MISS_TTL = 6 * 3600          # a page without a photo is asked again after 6 h
# The agent's site-wide share card, logo or placeholder, not the building.
STOCK = re.compile(r"(^|[/_.-])(og-?default|default|logo|placeholder|no-?image|avatar|icon|favicon|sprite|banner)"
                   r"([/_.-]|$)", re.I)


_NAT64 = ipaddress.ip_network("64:ff9b::/96")


def _public_host(host):
    """Only public addresses: listing links come from scraped boards, and a
    link to a private address must not make this box fetch inside its own
    network.

    An address written as numbers is judged as written. A network that only
    speaks IPv6 hands back a made-up IPv6 form of an IPv4 address (NAT64), and
    that form looks public: on such a network "10.0.0.5" resolved to
    2607:7700:0:28:0:2:a00:5 and passed (2026-11-25). For a name, the plain
    IPv4 answers are checked as well as whatever the resolver prefers, so a
    name pointing at a private IPv4 address cannot hide behind the same
    translation."""
    host = (host or "").strip("[]")
    try:
        return _global(ipaddress.ip_address(host.split("%")[0]))
    except ValueError:
        pass
    seen = []
    for family in (0, socket.AF_INET):
        try:
            infos = socket.getaddrinfo(host, None, family)
        except (socket.gaierror, UnicodeError, OSError):
            if family == 0:
                return False
            continue                       # a name with no IPv4 address at all
        for info in infos:
            try:
                ip = ipaddress.ip_address(info[4][0].split("%")[0])
            except ValueError:
                return False
            if not _global(ip):
                return False
            seen.append(ip)
    return bool(seen)


def _global(ip):
    """A public address, looking inside the IPv6 forms that carry an IPv4 one
    (::ffff:a.b.c.d and the standard NAT64 prefix 64:ff9b::/96)."""
    if ip.version == 6:
        inner = ip.ipv4_mapped
        if inner is None and ip in _NAT64:
            inner = ipaddress.ip_address(int(ip) & 0xFFFFFFFF)
        if inner is not None:
            return inner.is_global
    return ip.is_global


def _ok_url(u):
    p = urllib.parse.urlsplit(u or "")
    return p.scheme in ("http", "https") and bool(p.hostname) and _public_host(p.hostname)


class _CheckRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _ok_url(newurl):
            raise urllib.error.URLError("redirect to a non-public address")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_OPENER = urllib.request.build_opener(_CheckRedirects)


def _get(url, limit, accept, timeout=12):
    """(bytes, content type) or (None, None)."""
    if not _ok_url(url):
        return None, None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": accept,
                                                   "Referer": SITE + "/"})
        with _OPENER.open(req, timeout=timeout) as r:
            ctype = (r.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            data = r.read(limit + 1)
    except Exception:
        return None, None
    if len(data) > limit:
        return None, None
    return data, ctype


def page_photos(page, base):
    """Candidate photo URLs in a listing page, best first."""
    out = []
    for m in re.finditer(r"<meta\b[^>]*>", page, re.I):
        tag = m.group(0)
        if re.search(r"""(property|name)\s*=\s*["'](og:image|twitter:image)(:secure_url)?["']""", tag, re.I):
            c = re.search(r"""content\s*=\s*["']([^"']+)""", tag, re.I)
            if c:
                out.append(c.group(1))
    for m in re.finditer(r"<img\b[^>]*>", page, re.I):
        tag = m.group(0)
        src = re.search(r"""\s(?:data-src|src)\s*=\s*["']([^"']+)""", tag, re.I)
        w = re.search(r"""\swidth\s*=\s*["']?(\d+)""", tag, re.I)
        if src and w and int(w.group(1)) >= MIN_W:
            out.append(src.group(1))
    seen, good = set(), []
    for u in out:
        u = urllib.parse.urljoin(base, htmlmod.unescape(u.strip()))
        path = urllib.parse.urlsplit(u).path
        if u in seen or path.lower().endswith(".svg") or STOCK.search(path.rsplit("/", 1)[-1]):
            continue
        seen.add(u)
        good.append(u)
    return good


def _jpeg(data):
    """Re-encode as a JPEG no wider than OUT_W, and its width; (None, 0) if
    it is not a photo at least MIN_W wide."""
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        return None, 0
    if im.width < MIN_W or im.height < MIN_W * 0.4:
        return None, 0
    if im.width > OUT_W:
        im = im.resize((OUT_W, round(im.height * OUT_W / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=82, optimize=True, progressive=True)
    return buf.getvalue(), im.width


class Resolver:
    """photo(item) -> absolute https URL or None. Remembers answers in
    `cache` (a dict kept in the alerts state) so a listing's page is read
    once, not on every 10-minute run."""

    def __init__(self, docroot, cache, featured=None, fetch=True, now=None):
        self.dir = os.path.join(docroot, "alert-img")
        self.cache = cache
        self.cache.setdefault("by_item", {})
        self.cache.setdefault("by_src", {})
        self.fetch = fetch
        self.now = now or time.time()
        self.featured = {}
        for f in (featured or {}).get("listings") or []:
            img = f.get("image_large") or f.get("image")
            if f.get("href") and img and str(img).startswith("/featured/img/"):
                self.featured[f["href"]] = SITE + img

    def __call__(self, item):
        key = item.get("url") or item.get("id")
        if not key:
            return None
        hit = self.cache["by_item"].get(key)
        if hit and (hit.get("url") or self.now - hit.get("at", 0) < MISS_TTL):
            return hit.get("url")
        url = self._find(item, key)
        self.cache["by_item"][key] = {"url": url, "at": self.now}
        return url

    def _find(self, item, key):
        bare = key.split("#", 1)[0]
        if self.featured.get(bare):
            return self.featured[bare]
        if not self.fetch:
            return None
        cands = [item["image_src"]] if item.get("image_src") else []
        if not cands and item.get("url"):
            page, ctype = _get(item["url"], MAX_PAGE, "text/html,*/*;q=0.5")
            if page and "html" in (ctype or "html"):
                cands = page_photos(page.decode("utf-8", "replace"), item["url"])
        for src in cands[:4]:
            owners = self.cache["by_src"].setdefault(src, [])
            if bare not in owners:
                owners.append(bare)
                del owners[:-5]
            if len(owners) > 1:
                continue                      # the same picture on two listings: stock
            url = self._host(src)
            if url:
                return url
        return None

    def _host(self, src):
        name = hashlib.sha1(src.encode()).hexdigest()[:16] + ".jpg"
        path = os.path.join(self.dir, name)
        if not os.path.exists(path):
            data, ctype = _get(src, MAX_IMG, "image/*")
            if not data or not (ctype or "image/").startswith("image/"):
                return None
            jpg, _ = _jpeg(data)
            if not jpg:
                return None
            os.makedirs(self.dir, exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(jpg)
            os.replace(tmp, path)
        return f"{SITE}/alert-img/{name}"


def prune(cache, keep=400):
    """Bound the cache: newest `keep` items, sources still owned by one."""
    items = cache.get("by_item") or {}
    if len(items) > keep:
        for k in sorted(items, key=lambda k: items[k].get("at", 0))[:len(items) - keep]:
            del items[k]
    srcs = cache.get("by_src") or {}
    if len(srcs) > keep * 2:
        for k in list(srcs)[:len(srcs) - keep * 2]:
            del srcs[k]


if __name__ == "__main__":
    import sys
    r = Resolver(sys.argv[2] if len(sys.argv) > 2 else "/tmp", {})
    print(r({"url": sys.argv[1]}))

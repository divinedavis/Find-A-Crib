"""Readable text of a re-rental's own page (2026-10-03), for Help me apply.
Only URLs that are in today's featured.json are ever fetched (the caller
checks), so this can't be pointed at an arbitrary site."""
import html, os, re, subprocess, urllib.parse, urllib.request

MAX_CHARS = 12000

# Agents whose listing pages are JavaScript apps: the HTML is an empty shell
# and the unit table (bedrooms, rent, income limits) only exists after the
# page runs (2026-10-04: iAfford NY and Affordable for NY, 10 listings, read
# as ~55 characters). render=True opens these in Chromium, using the
# re-rental scraper's venv, which has Playwright (the API's venv doesn't).
JS_SITES = ("afny.org", "iaffordny.com")
BROWSER_PY = os.environ.get("FAC_BROWSER_PY", "/opt/findacrib/venv/bin/python")
_RENDER = r"""
import sys
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(user_agent="Mozilla/5.0 (compatible; FindACrib/1.0; +https://findacrib.com)")
    pg.goto(sys.argv[1], wait_until="domcontentloaded", timeout=40000)
    try:
        # The unit table arrives after the page shell; wait for it.
        pg.wait_for_function("/Unit Size|Household Income/i.test(document.body.innerText)", timeout=20000)
    except Exception:
        pass
    sys.stdout.write(pg.evaluate("() => document.body.innerText"))
    b.close()
"""


def rendered_text(url, timeout=90):
    """The page's text after its JavaScript runs, or "" (no browser, timeout)."""
    try:
        cmd = [BROWSER_PY, "-c", _RENDER, url]
        # One browser at a time on the droplet (the re-rental sweep holds the
        # same lock); skipped where there's no lock dir (a laptop).
        if os.path.isdir("/run/lock"):
            cmd = ["flock", "-w", "600", "/run/lock/fac-browser.lock"] + cmd
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 600)
    except Exception:
        return ""
    t = re.sub(r"[ \t\r\f\v]+", " ", r.stdout or "")
    return re.sub(r"\n\s*\n+", "\n", t).strip()[:MAX_CHARS]


def text_of(url, timeout=12, render=False):
    t = _static_text(url, timeout)
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if render and len(t) < 300 and any(host == h or host.endswith("." + h) for h in JS_SITES):
        return rendered_text(url) or t
    return t


def _static_text(url, timeout):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; FindACrib/1.0; +https://findacrib.com)"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            if "html" not in (r.headers.get("Content-Type") or "html"):
                return ""
            raw = r.read(2_000_000).decode("utf-8", "replace")
    except Exception:
        return ""
    raw = re.sub(r"(?is)<(script|style|noscript|svg|header|footer|nav)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h\d)>", "\n", raw)
    t = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    t = re.sub(r"[ \t\r\f\v]+", " ", t)
    t = re.sub(r"\n\s*\n+", "\n", t).strip()
    return t[:MAX_CHARS]

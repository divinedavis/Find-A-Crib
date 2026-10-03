"""Readable text of a re-rental's own page (2026-10-03), for Help me apply.
Only URLs that are in today's featured.json are ever fetched (the caller
checks), so this can't be pointed at an arbitrary site."""
import html, re, urllib.request

MAX_CHARS = 12000


def text_of(url, timeout=12):
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

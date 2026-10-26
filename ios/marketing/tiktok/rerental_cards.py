"""Five TikTok cards of open NYC re-rentals, in the style of a ReRentalAlert
carousel the owner sent 2026-10-26: full-width building photo, red price
tag, handwritten note, the details underneath.

    ~/.venvs/dhcr-map/bin/python ios/marketing/tiktok/rerental_cards.py <photo_dir> [out_dir]

<photo_dir> holds the listing photos named by CARDS[i]["photo"] (downloaded
from findacrib.com/featured/img/ (Atlantic Chestnut: the 1065px photo
inside HDC's remarketing PDF, via pdfimages), which mirror each marketing agent's own
listing photo). Rents, incomes and how-to-apply were checked against each
agent's live listing on 2026-10-26 (featured_units.json had gone stale on
two); re-check before re-posting.
"""
import base64
import html
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

W, H = 1080, 1350
AS_OF = "Oct 26, 2026"

CARDS = [
    {"photo": "55_Willoughby_St.jpg", "agent": "MGNY Consulting", "where": "Downtown Brooklyn",
     "name": "House 55", "tag": "Studios from", "price": "$3,543", "tag_sub": "47 units open · 1-beds from $3,600",
     "note": "47 apartments open downtown",
     "rows": [("Income", "$126,412 – $198,510, by unit"), ("Household", "1 – 3 people"),
              ("Apply", "On MGNY Consulting's listing page")]},
    {"photo": "250_Euclid_Ave.jpg", "agent": "NYC HDC", "where": "East New York, Brooklyn",
     "name": "Atlantic Chestnut", "tag": "Studios from", "price": "$1,485", "tag_sub": "80% AMI · 2-beds $2,292",
     "note": "first come, first served",
     "rows": [("Income", "$54,206 – $146,560, by unit"), ("Household", "1 – 5 people"),
              ("Apply", "Email Rentals@phippsny.org or call 646-388-8227")]},
    {"photo": "465_West_163_Street.jpg", "agent": "iAfford NY", "where": "Washington Heights, Manhattan",
     "name": "465 West 163rd St", "tag": "Studio", "price": "$1,831", "tag_sub": "Unit 3B · 130% AMI",
     "note": "a Manhattan studio under $1,900",
     "rows": [("Income", "$69,294 – $176,410"), ("Household", "1 – 2 people"),
              ("Apply", "Mail a signed application to iAfford NY · first come, first served")]},
    {"photo": "875_4th_Avenue.jpg", "agent": "Reside New York", "where": "Sunset Park, Brooklyn",
     "name": "875 4th Avenue", "tag": "Studio", "price": "$2,157", "tag_sub": "Unit 302 · 130% AMI",
     "note": "one unit open",
     "rows": [("Income", "$80,216 – $176,410"), ("Household", "1 – 2 people"),
              ("Apply", "On NYC Housing Connect")]},
    {"photo": "65_Dupont_Street.jpg", "agent": "Affordable for NY", "where": "Greenpoint, Brooklyn",
     "name": "Greenpoint Central", "tag": "Studios from", "price": "$3,423", "tag_sub": "22 units open · 2-beds $4,376",
     "note": "22 apartments open right now",
     "rows": [("Income", "$117,360 – $238,160, by unit"), ("Household", "1 – 5 people"),
              ("Apply", "Signed application to Affordable for NY · first come, first served")]},
]

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter+Tight:wght@600;700;800&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@500&family=Caveat:wght@600&display=block');
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { width: 1080px; height: 1350px; overflow: hidden; background: #0d0d0f; }
body { font-family: Inter, sans-serif; color: #fff; -webkit-font-smoothing: antialiased; }
.card { position: relative; width: 1080px; height: 1350px; overflow: hidden; background: #0d0d0f; }
.photo { position: absolute; left: 0; top: 0; width: 1080px; height: 860px; object-fit: cover;
         filter: saturate(.75) contrast(1.05); }
.fade { position: absolute; left: 0; top: 0; width: 1080px; height: 862px;
        background: linear-gradient(180deg, rgba(13,13,15,.55) 0%, rgba(13,13,15,0) 22%, rgba(13,13,15,0) 52%, #0d0d0f 100%); }
.pill { position: absolute; left: 64px; top: 60px; display: flex; align-items: center; gap: 10px;
        background: #fff; color: #e0262b; font: 700 24px 'Inter Tight', sans-serif; padding: 10px 20px; border-radius: 999px; }
.pill i { width: 12px; height: 12px; border-radius: 50%; background: #e0262b; display: block; }
.count { position: absolute; right: 64px; top: 70px; font: 500 24px 'JetBrains Mono', monospace; opacity: .9; letter-spacing: .1em; }
.where { position: absolute; left: 64px; top: 560px; font: 500 24px 'JetBrains Mono', monospace; letter-spacing: .14em;
         text-transform: uppercase; opacity: .92; text-shadow: 0 2px 12px rgba(0,0,0,.6); }
h1 { position: absolute; left: 64px; right: 64px; top: 600px; font: 800 96px/0.98 'Inter Tight', sans-serif;
     letter-spacing: -.03em; text-shadow: 0 4px 30px rgba(0,0,0,.55); }
.tag { position: absolute; right: 56px; top: 330px; transform: rotate(-5deg); background: #e0262b;
       padding: 20px 30px 22px; border-radius: 6px; box-shadow: 0 18px 40px rgba(0,0,0,.45); min-width: 420px; }
.tag b { display: block; font: 600 22px 'JetBrains Mono', monospace; letter-spacing: .14em; text-transform: uppercase; opacity: .92; }
.tag strong { display: block; font: 800 92px/1 'Inter Tight', sans-serif; letter-spacing: -.03em; margin-top: 6px; }
.tag strong small { font-size: 44px; font-weight: 700; }
.tag span { display: block; font: 500 24px Inter, sans-serif; margin-top: 8px; opacity: .95; }
.note { position: absolute; left: 64px; top: 812px; font: 600 44px 'Caveat', cursive; color: #ffd84d; transform: rotate(-1.5deg); }
.rows { position: absolute; left: 64px; right: 64px; top: 900px; }
.row { display: flex; gap: 28px; padding: 22px 0; border-top: 1px solid rgba(255,255,255,.16); }
.row b { flex: 0 0 190px; font: 500 22px 'JetBrains Mono', monospace; letter-spacing: .12em; text-transform: uppercase; opacity: .6; padding-top: 6px; }
.row span { font: 500 33px/1.3 Inter, sans-serif; }
.foot { position: absolute; left: 64px; right: 64px; bottom: 48px; display: flex; justify-content: space-between;
        font: 500 20px 'JetBrains Mono', monospace; letter-spacing: .06em; opacity: .55; }
"""


def card_html(c, i, n, photo_dir):
    img = base64.b64encode((photo_dir / c["photo"]).read_bytes()).decode()
    e = html.escape
    rows = "".join(f'<div class="row"><b>{e(k)}</b><span>{e(v)}</span></div>' for k, v in c["rows"])
    return f"""<div class="card">
<img class="photo" src="data:image/jpeg;base64,{img}"><div class="fade"></div>
<div class="pill"><i></i>Find A Crib · Re-rental</div><div class="count">{i} / {n}</div>
<div class="tag"><b>{e(c['tag'])}</b><strong>{e(c['price'])}<small>/mo</small></strong><span>{e(c['tag_sub'])}</span></div>
<div class="where">{e(c['where'])}</div><h1>{e(c['name'])}</h1>
<div class="note">{e(c['note'])}</div>
<div class="rows">{rows}</div>
<div class="foot"><span>Photo: {e(c['agent'])} listing</span><span>As of {AS_OF} · findacrib.com</span></div>
</div>"""


def main():
    photo_dir = Path(sys.argv[1]).expanduser()
    out = Path(sys.argv[2]).expanduser() if len(sys.argv) > 2 else Path.home() / "Downloads" / "FAC-TikTok-rerentals"
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": W, "height": H})
        for i, c in enumerate(CARDS, 1):
            page.set_content(f"<!doctype html><html><head><meta charset=utf-8><style>{CSS}</style></head>"
                             f"<body>{card_html(c, i, len(CARDS), photo_dir)}</body></html>", wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            path = out / f"{i:02d}-{c['photo'].rsplit('.', 1)[0]}.png"
            page.screenshot(path=str(path))
            print("rendered", path.name)
        b.close()


if __name__ == "__main__":
    main()

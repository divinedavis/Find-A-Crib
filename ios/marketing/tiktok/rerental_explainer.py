"""An 8-slide TikTok explainer: re-rentals, the way into NYC affordable
housing that skips the lottery. Structure follows a ReRentalAlert carousel
the owner sent 2026-10-26 (paper background, taped cards, handwritten
notes, one line running across every slide); the colors, numbers and
words are Find A Crib's own.

    ~/.venvs/dhcr-map/bin/python ios/marketing/tiktok/rerental_explainer.py <photo_dir> [out_dir]

<photo_dir> = the listing photos rerental_cards.py uses. Numbers come from
findacrib.com's featured.json / rerental_pages.json and HPD's marketing
agent list (marketing_agents.json) as of 2026-10-26: 85 HPD-approved
agents, 31 of them re-rental agents, 36 re-rental pages watched, 60
re-rentals open (Brooklyn 28, Bronx 17, Queens 9, Manhattan 4, Staten
Island 1, one unknown), 32 first come, first served. Recount before
re-posting.
"""
import base64
import math
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

W, H = 1080, 1350
TEAL = "#2f7a8a"
LINE_Y, AMP, PERIOD = 1170, 46, 1500  # the wave every slide shares


def wave_path(i):
    """The slice of one long sine wave that falls on slide i, so the line
    joins up when people swipe."""
    pts = []
    for x in range(0, W + 1, 12):
        g = i * W + x
        pts.append(f"{x},{LINE_Y + AMP * math.sin(2 * math.pi * g / PERIOD):.1f}")
    return "M" + " L".join(pts)


def wave_y(i, x):
    return LINE_Y + AMP * math.sin(2 * math.pi * (i * W + x) / PERIOD)


CSS = f"""
@import url('https://fonts.googleapis.com/css2?family=Inter+Tight:wght@700;800&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@500&family=Caveat:wght@600;700&display=block');
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html, body {{ width: 1080px; height: 1350px; overflow: hidden; }}
body {{ font-family: Inter, sans-serif; color: #151515; -webkit-font-smoothing: antialiased; }}
.s {{ position: relative; width: 1080px; height: 1350px; overflow: hidden; background: #f2efe7; }}
.s::before {{ content: ''; position: absolute; inset: 0; opacity: .5; mix-blend-mode: multiply; pointer-events: none;
  background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='400' height='400'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.7' numOctaves='3' stitchTiles='stitch'/><feColorMatrix values='0 0 0 0 .55  0 0 0 0 .5  0 0 0 0 .42  0 0 0 .18 0'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>"); }}
.brand {{ position: absolute; left: 70px; top: 62px; font: 700 26px 'Inter Tight', sans-serif; color: {TEAL}; display: flex; gap: 10px; align-items: center; }}
.brand i {{ width: 26px; height: 26px; border-radius: 7px; background: {TEAL}; display: block; position: relative; }}
.brand i::after {{ content: ''; position: absolute; left: 6px; top: 8px; width: 14px; height: 11px; border: 3px solid #fff; border-top: 0; border-radius: 0 0 3px 3px; }}
.count {{ position: absolute; right: 70px; top: 64px; font: 500 24px 'JetBrains Mono', monospace; opacity: .55; }}
h1 {{ position: absolute; left: 70px; right: 70px; top: 140px; font: 800 86px/1.02 'Inter Tight', sans-serif; letter-spacing: -.03em; }}
h1 .t {{ color: {TEAL}; }}
.hl {{ background: linear-gradient(transparent 52%, #ffd84d 52%, #ffd84d 92%, transparent 92%); padding: 0 4px; }}
.lede {{ position: absolute; left: 70px; right: 120px; font-size: 34px; line-height: 1.38; color: #3a3a3a; }}
.card {{ position: absolute; background: #fff; padding: 30px 34px; box-shadow: 0 14px 30px rgba(40,30,10,.14), 0 2px 4px rgba(40,30,10,.08); }}
.card::before {{ content: ''; position: absolute; left: 50%; top: -18px; width: 140px; height: 36px; transform: translateX(-50%) rotate(-2deg);
  background: rgba(214,200,160,.75); }}
.card b {{ display: block; font: 600 20px 'JetBrains Mono', monospace; letter-spacing: .14em; text-transform: uppercase; color: {TEAL}; }}
.card h3 {{ font: 800 46px/1.05 'Inter Tight', sans-serif; margin-top: 10px; letter-spacing: -.02em; }}
.card p {{ font-size: 27px; line-height: 1.4; color: #444; margin-top: 10px; }}
.hand {{ position: absolute; font: 700 40px/1.1 'Caveat', cursive; color: #1d1d1d; }}
.chip {{ position: absolute; background: #fff; font: 700 30px 'Inter Tight', sans-serif; padding: 16px 24px; box-shadow: 0 8px 18px rgba(40,30,10,.12); }}
.chip.dark {{ background: #151515; color: #fff; }}
.big {{ position: absolute; left: 66px; font: 800 330px/0.85 'Inter Tight', sans-serif; letter-spacing: -.05em; color: {TEAL}; }}
.big small {{ font-size: 110px; color: #151515; letter-spacing: -.03em; }}
table {{ position: absolute; left: 70px; width: 600px; border-collapse: collapse; font-size: 32px; }}
td {{ padding: 16px 0; border-bottom: 2px solid rgba(0,0,0,.12); }}
td:last-child {{ text-align: right; font: 700 34px 'Inter Tight', sans-serif; }}
.sticky {{ position: absolute; background: #ffe066; padding: 26px 28px; font: 700 36px/1.1 'Caveat', cursive; transform: rotate(4deg);
  box-shadow: 0 10px 20px rgba(40,30,10,.15); width: 300px; }}
.pol {{ position: absolute; background: #fff; padding: 16px 16px 20px; box-shadow: 0 14px 28px rgba(40,30,10,.18); width: 300px; }}
.pol img {{ width: 268px; height: 300px; object-fit: cover; display: block; }}
.pol .c {{ font: 700 30px/1.05 'Caveat', cursive; margin-top: 12px; }}
.pol .p {{ font: 600 22px Inter, sans-serif; margin-top: 6px; }}
.pol .p em {{ font-style: normal; color: {TEAL}; }}
.check {{ position: absolute; left: 70px; right: 70px; }}
.check div {{ display: flex; gap: 22px; align-items: flex-start; font-size: 33px; line-height: 1.3; padding: 15px 0; }}
.check div::before {{ content: ''; flex: 0 0 34px; height: 34px; border: 3px solid #151515; border-radius: 4px; margin-top: 2px; }}
.url {{ position: absolute; left: 70px; font: 800 84px 'Inter Tight', sans-serif; letter-spacing: -.03em; }}
.fine {{ position: absolute; left: 70px; right: 70px; font-size: 21px; color: #6a6a6a; }}
svg.line {{ position: absolute; left: 0; top: 0; width: 1080px; height: 1350px; pointer-events: none; }}
.lbl {{ position: absolute; font: 700 34px 'Caveat', cursive; color: #2a2a2a; white-space: nowrap; }}
"""


def img64(p):
    return "data:image/jpeg;base64," + base64.b64encode(p.read_bytes()).decode()


def line(i, dot_x, label, label_dx=-40, end=False):
    y = wave_y(i, dot_x)
    path = wave_path(i)
    svg = (f'<svg class="line" viewBox="0 0 1080 1350"><path d="{path}" fill="none" stroke="{TEAL}" stroke-width="9" stroke-linecap="round"/>')
    if end:
        # The line runs into a little house: that's the way in.
        x0 = dot_x
        svg = (f'<svg class="line" viewBox="0 0 1080 1350"><path d="{wave_path(i).split(" L")[0]} '
               + " L".join(p for p in wave_path(i).split(" L")[1:] if float(p.split(",")[0]) <= x0)
               + f'" fill="none" stroke="{TEAL}" stroke-width="9" stroke-linecap="round"/>'
               f'<path d="M{x0},{y:.0f} L{x0},{y - 60:.0f} L{x0 + 55},{y - 105:.0f} L{x0 + 110},{y - 60:.0f} L{x0 + 110},{y:.0f} Z" '
               f'fill="#f2efe7" stroke="{TEAL}" stroke-width="9" stroke-linejoin="round"/>'
               f'<rect x="{x0 + 42}" y="{y - 40:.0f}" width="26" height="40" fill="{TEAL}"/>')
    else:
        svg += f'<circle cx="{dot_x}" cy="{y:.1f}" r="17" fill="#f2efe7" stroke="{TEAL}" stroke-width="8"/>'
    svg += "</svg>"
    return svg + f'<div class="lbl" style="left:{dot_x + label_dx}px;top:{y + 34:.0f}px">{label}</div>'


def head(i, n):
    return f'<div class="brand"><i></i>Find A Crib</div><div class="count">{i} / {n}</div>'


def slides(photos):
    n = 8
    s = []
    s.append(head(1, n) + """
<h1>There's a way into NYC affordable housing that <span class="hl">skips the lottery.</span></h1>
<div class="card" style="left:110px;top:640px;width:470px;transform:rotate(-3deg)">
  <b>● New re-rental</b><h3>Studio · Sunset Park</h3><p>$2,157/mo · 130% AMI<br>open Oct 26</p></div>
<div class="hand" style="left:640px;top:600px;transform:rotate(-4deg)">most people never<br>see these ↙</div>
<div class="hand" style="left:640px;top:880px;color:#2f7a8a;transform:rotate(-6deg);font-size:54px">no lottery. no waiting.</div>
""" + line(0, 80, "start here, swipe →", -40))
    s.append(head(2, n) + """
<h1>Two doors into the <span class="hl">same buildings.</span></h1>
<div class="card" style="left:70px;top:430px;width:440px;transform:rotate(-2deg);opacity:.9">
  <b style="color:#888">The lottery</b><h3>Wait your turn.</h3><p>Apply in a set window on Housing Connect. Picked at random. The wait can run months.</p></div>
<div class="card" style="left:560px;top:470px;width:450px;transform:rotate(2deg)">
  <b>A re-rental</b><h3>Be early.</h3><p>Posted any day, by the building's marketing agent. No lottery. Often first come, first served.</p></div>
<div class="hand" style="left:600px;top:930px;transform:rotate(-3deg)">↖ the door most people<br>don't know about</div>
""" + line(1, 300, "the other door", -60))
    s.append(head(3, n) + """
<h1>Where do they <span class="hl">come from?</span></h1>
<div class="lede" style="top:420px">When someone who won an affordable apartment moves out, it doesn't go to the open market.</div>
<div class="lede" style="top:610px">It stays affordable, with the same income rules, and the building's <b>marketing agent</b> rents it again. That's a re-rental.</div>
<div class="sticky" style="left:690px;top:850px">same building.<br>same rent rules.<br>no lottery.</div>
""" + line(2, 520, "where they come from", -110))
    s.append(head(4, n) + """
<h1>And they're posted on <span class="t">36 different websites.</span></h1>
<div class="chip" style="left:80px;top:470px;transform:rotate(-3deg)">Affordable for NY</div>
<div class="chip" style="left:470px;top:450px;transform:rotate(2deg)">iAfford NY</div>
<div class="chip" style="left:760px;top:520px;transform:rotate(-2deg)">NYC HDC</div>
<div class="chip" style="left:110px;top:590px;transform:rotate(2deg)">Reside New York</div>
<div class="chip" style="left:470px;top:610px;transform:rotate(-1deg)">MGNY Consulting</div>
<div class="chip" style="left:150px;top:720px;transform:rotate(-2deg)">TF Cornerstone</div>
<div class="chip dark" style="left:520px;top:740px;transform:rotate(3deg)">+ 30 more</div>
<div class="lede" style="top:860px;right:330px;font-size:30px">HPD approves 85 marketing agents. 31 rent re-rentals, each on their own site.</div>
<div class="hand" style="left:760px;top:850px;transform:rotate(-5deg)">nobody checks<br>36 sites a day</div>
""" + line(3, 760, "why it's hard", -60))
    s.append(head(5, n) + """
<div class="lede" style="top:150px;font-size:36px">How many are open right now?</div>
<div class="big" style="top:230px">60 <small>open</small></div>
<div class="lede" style="top:530px;font-size:30px">re-rentals on our list on Oct 26, 2026</div>
<table style="top:610px">
<tr><td>Brooklyn</td><td>28</td></tr><tr><td>Bronx</td><td>17</td></tr><tr><td>Queens</td><td>9</td></tr>
<tr><td>Manhattan</td><td>4</td></tr><tr><td>Staten Island</td><td>1</td></tr></table>
<div class="sticky" style="left:720px;top:640px">32 of them:<br>first come,<br>first served</div>
""" + line(4, 980, "right now", -120))
    s.append(head(6, n) + f"""
<h1>Real ones, <span class="hl">open today.</span></h1>
<div class="pol" style="left:60px;top:390px;transform:rotate(-4deg)"><img src="{img64(photos / '250_Euclid_Ave.jpg')}">
  <div class="c">East New York</div><div class="p">Studio · <em>$1,485/mo</em></div></div>
<div class="pol" style="left:390px;top:350px;transform:rotate(2deg)"><img src="{img64(photos / '465_West_163_Street.jpg')}">
  <div class="c">Washington Heights</div><div class="p">Studio · <em>$1,831/mo</em></div></div>
<div class="pol" style="left:720px;top:400px;transform:rotate(-1deg)"><img src="{img64(photos / '875_4th_Avenue.jpg')}">
  <div class="c">Sunset Park</div><div class="p">Studio · <em>$2,157/mo</em></div></div>
<div class="hand" style="left:120px;top:920px;transform:rotate(-2deg)">each has its own income range. check it first ↑</div>
""" + line(5, 380, "real ones", -50))
    s.append(head(7, n) + """
<h1>Be ready <span class="hl">before</span> you see one.</h1>
<div class="lede" style="top:350px;font-size:30px">Usually asked for:</div>
<div class="check" style="top:410px">
<div>Photo ID for every adult in the household</div>
<div>Proof of income: recent pay stubs or a benefits letter</div>
<div>Last year's tax return</div>
<div>Recent bank statements</div>
<div>Your household size and total income</div></div>
<div class="hand" style="left:640px;top:950px;transform:rotate(-4deg);color:#2f7a8a">first come, first served<br>means hours matter</div>
""" + line(6, 300, "be ready", -40))
    s.append(head(8, n) + """
<h1>We check all 36. <span class="t">You get the alert.</span></h1>
<div class="lede" style="top:360px;font-size:32px">Set where you want to live once. When a new re-rental or lottery opens, we tell you.</div>
<div class="card" style="left:70px;top:560px;width:440px;transform:rotate(-2deg)"><b>Free with an account</b><h3 style="font-size:36px">Re-rental + lottery alerts</h3></div>
<div class="card" style="left:560px;top:580px;width:440px;transform:rotate(2deg)"><b>Also free</b><h3 style="font-size:36px">Every rent-stabilized building</h3></div>
<div class="hand" style="left:70px;top:820px">save this for your next move ↓</div>
<div class="url" style="top:870px"><span class="hl">findacrib.com</span></div>
<div class="fine" style="top:985px">Also on the App Store. Not affiliated with HPD, HDC or the City of New York.</div>
""" + line(7, 760, "…and that's the way in.", -330, end=True))
    return s


def main():
    photos = Path(sys.argv[1]).expanduser()
    out = Path(sys.argv[2]).expanduser() if len(sys.argv) > 2 else Path.home() / "Downloads" / "FAC-TikTok-rerental-explainer"
    out.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": W, "height": H})
        for i, body in enumerate(slides(photos), 1):
            page.set_content(f"<!doctype html><html><head><meta charset=utf-8><style>{CSS}</style></head>"
                             f'<body><div class="s">{body}</div></body></html>', wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            page.screenshot(path=str(out / f"{i:02d}.png"))
        b.close()
    print("rendered", out)


if __name__ == "__main__":
    main()

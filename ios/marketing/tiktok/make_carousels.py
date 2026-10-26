"""Render posts.py to 1080x1350 PNG carousels (TikTok photo mode, 4:5).

    ~/.venvs/dhcr-map/bin/python ios/marketing/tiktok/make_carousels.py [out_dir] [slug-prefix]

Default out_dir: ~/Downloads/FAC-TikTok-carousels. Each post gets its own
folder of numbered slides plus caption.txt; README.txt lists all captions.
Fonts come from Google Fonts, so the first render needs the network.
"""
import base64
import html
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from posts import POSTS  # noqa: E402

RAW = Path(__file__).resolve().parent.parent / "raw"
W, H = 1080, 1350
SHOT_W, SHOT_H = 1320, 2868  # raw screenshot size

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter+Tight:wght@600;700&family=Inter:wght@400;500&family=JetBrains+Mono:wght@500&display=block');
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { width: 1080px; height: 1350px; overflow: hidden; }
body { font-family: Inter, sans-serif; color: #fff; -webkit-font-smoothing: antialiased; }
.slide { position: relative; width: 1080px; height: 1350px; padding: 84px 84px 0; overflow: hidden;
         background: #2340dc; }
.slide::before { content: ''; position: absolute; inset: 0; pointer-events: none; opacity: .22;
                 mix-blend-mode: soft-light; background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='300' height='300'><filter id='n'><feTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='3' stitchTiles='stitch'/></filter><rect width='100%' height='100%' filter='url(%23n)'/></svg>"); }
.slide.cover { background: radial-gradient(120% 80% at 80% 100%, #2340dc 0%, #12256f 45%, #0a1336 100%); }
.top { display: flex; justify-content: space-between; font: 500 22px 'JetBrains Mono', monospace;
       letter-spacing: .14em; text-transform: uppercase; opacity: .78; }
h1 { font: 700 100px/1.0 'Inter Tight', sans-serif; letter-spacing: -.03em; margin-top: 90px; max-width: 912px; }
.cover h1 { font-size: 92px; margin-top: 56px; }
.shot h1 { font-size: 68px; margin-top: 52px; }
.cta h1 { font-size: 80px; margin-top: 90px; }
.hl { text-decoration: underline; text-decoration-thickness: 6px; text-underline-offset: 10px; }
.body p { font-size: 41px; line-height: 1.34; margin-top: 38px; max-width: 880px; color: rgba(255,255,255,.9); }
.shot .body p { font-size: 32px; margin-top: 22px; }
.sub { font-size: 36px; margin-top: 30px; color: rgba(255,255,255,.82); }
.foot { position: absolute; left: 84px; right: 84px; bottom: 62px; display: flex; justify-content: space-between;
        font: 500 21px 'JetBrains Mono', monospace; letter-spacing: .08em; opacity: .72; }
.note { position: absolute; left: 84px; bottom: 110px; font-size: 22px; opacity: .6; }
.phone { position: absolute; left: 50%; transform: translateX(-50%); width: 600px; overflow: hidden;
         border-radius: 44px 44px 0 0; border: 10px solid #0b1022; border-bottom: 0;
         box-shadow: 0 30px 80px rgba(0,0,0,.45); background: #fff; }
.phone img { display: block; width: 100%; }
.cover .phone { width: 640px; }
.box { border: 2px solid rgba(255,255,255,.55); border-radius: 18px; padding: 26px 30px; margin-top: 26px; max-width: 880px; }
.box b { display: block; font: 500 20px 'JetBrains Mono', monospace; letter-spacing: .14em; text-transform: uppercase; opacity: .75; }
.box span { display: block; font-size: 34px; margin-top: 10px; }
.brand { margin-top: 60px; font: 700 40px 'Inter Tight', sans-serif; }
.brand small { display: block; font: 400 28px Inter, sans-serif; opacity: .8; margin-top: 8px; }
.num { position: absolute; right: 70px; bottom: 96px; font: 700 400px/0.8 'Inter Tight', sans-serif;
       letter-spacing: -.05em; color: rgba(255,255,255,.09); }
.bigq { font: 700 560px/0.8 'Inter Tight', sans-serif; letter-spacing: -.05em; opacity: .14; position: absolute; right: 60px; bottom: 40px; }
"""


def rich(text):
    """Escape, then *word* -> underlined highlight."""
    return re.sub(r"\*(.+?)\*", r'<span class="hl">\1</span>', html.escape(text))


def phone(shot, top, height):
    name, y0, y1 = shot
    # Never show past y1: the crops stop above private names and map imagery.
    inner_w = 620 if top >= 700 else 580  # phone width minus its 10px borders
    height = min(height, int((y1 - y0) * inner_w * SHOT_H / SHOT_W))
    top = H - height  # sit on the bottom edge like a phone rising into frame
    data = base64.b64encode((RAW / name).read_bytes()).decode()
    # The phone is 600px (cover 640px) wide inside a 10px border.
    return (f'<div class="phone" style="top:{top}px;height:{height}px">'
            f'<img src="data:image/png;base64,{data}" style="margin-top:calc(-{y0} * 100% * {SHOT_H / SHOT_W:.5f})">'
            f'</div>')


def slide_html(s, i, n):
    kind = s.get("kind", "text")
    count = f"{i} / {n}"
    top = f'<div class="top"><span>{html.escape(s["kicker"])}</span><span>{count}</span></div>'
    foot_next = f'Next: {html.escape(s["next"])} →' if s.get("next") else ("Swipe →" if kind == "cover" else "")
    foot = f'<div class="foot"><span>findacrib.com</span><span>{foot_next}</span></div>'
    note = f'<div class="note">{html.escape(s["note"])}</div>' if s.get("note") else ""
    body = "".join(f"<p>{rich(p)}</p>" for p in s.get("body", []))
    if kind == "cover":
        inner = f'{top}<h1>{rich(s["title"])}</h1><div class="sub">{rich(s["sub"])}</div>'
        if s.get("shot"):
            inner += phone(s["shot"], 760, H - 760)
        else:
            inner += '<div class="bigq">$0</div>'
        return f'<div class="slide cover">{inner}{foot if not s.get("shot") else ""}</div>'
    if kind == "shot":
        return (f'<div class="slide shot">{top}<h1>{rich(s["title"])}</h1><div class="body">{body}</div>'
                f'{phone(s["shot"], 620, H - 620)}</div>')
    if kind == "cta":
        return (f'<div class="slide cta">{top}<h1>{rich(s["title"])}</h1>'
                f'<div class="box" style="margin-top:70px"><b>Save</b><span>{rich(s["save"])}</span></div>'
                f'<div class="box"><b>Send</b><span>{rich(s["send"])}</span></div>'
                f'<div class="brand">Find A Crib<small>{html.escape(s["foot"])}</small></div>'
                f'<div class="foot"><span>findacrib.com</span><span>NYC · LA · SF · DC</span></div></div>')
    return (f'<div class="slide"><div class="num">{i:02d}</div>{top}<h1>{rich(s["title"])}</h1>'
            f'<div class="body">{body}</div>{note}{foot}</div>')


def main():
    out = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path.home() / "Downloads" / "FAC-TikTok-carousels"
    only = sys.argv[2] if len(sys.argv) > 2 else ""
    out.mkdir(parents=True, exist_ok=True)
    readme = []
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": W, "height": H})
        for post in POSTS:
            if not post["slug"].startswith(only):
                continue
            d = out / post["slug"]
            d.mkdir(exist_ok=True)
            n = len(post["slides"])
            for i, s in enumerate(post["slides"], 1):
                page.set_content(f"<!doctype html><html><head><meta charset=utf-8><style>{CSS}</style></head>"
                                 f"<body>{slide_html(s, i, n)}</body></html>", wait_until="networkidle")
                page.evaluate("document.fonts.ready")
                page.screenshot(path=str(d / f"{i:02d}.png"))
            (d / "caption.txt").write_text(post["caption"] + "\n")
            readme.append(f"{post['slug']}\n{post['caption']}\nSources: {'; '.join(post['sources'])}\n")
            print("rendered", post["slug"], n, "slides")
        b.close()
    if not only:
        (out / "README.txt").write_text("\n".join(readme))


if __name__ == "__main__":
    main()

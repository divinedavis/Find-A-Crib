#!/usr/bin/env python3
"""Render the Instagram feed ad for Find A Crib.

Two files come out of one layout, because Meta wants them separately:

    ig-ad-stabilized.png       1080x1080  <- the asset you upload to Ads Manager
    ig-ad-stabilized-feed.png  1080x1362  <- the same creative inside fake IG
                                             chrome, for showing people what the
                                             placement actually looks like

The background is drawn, not photographed. That is deliberate: a stock photo of
a brownstone carries a license, and a housing ad that gets reused for a year is
exactly where an unlicensed image bites you. Everything here is ours.

Layout is a direct copy of the Amex/Resy feed ad's skeleton -- centred stack of
headline, small brand lockup, hero object, bottom line -- because that skeleton
is what makes the format read as an ad rather than a post.

    python3 marketing/ads/build_ig_ad.py

Requires playwright (`pip3 install playwright && playwright install chromium`),
or falls back to the system Google Chrome in headless mode.
"""
import pathlib
import random
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent

# --- copy ------------------------------------------------------------------
HEAD_1 = "GO AHEAD."
HEAD_2 = "CHECK THE ADDRESS."
HEAD_3 = "IS IT STABILIZED?"
KICKER = "THERE&rsquo;S NOTHING LIKE KNOWING."
CAPTION = (
    "Search 47,165 rent-stabilized buildings from the official NYS DHCR "
    "registration list. Free at findacrib.com."
)

BROWNSTONES = [
    # (width, roof_y, body, trim, has_bay)
    (196, 268, "#6d4a37", "#553a2b", True),
    (172, 232, "#7d5943", "#5f4433", False),
    (208, 292, "#5c4132", "#452f24", True),
    (180, 244, "#84634b", "#634a38", False),
    (192, 276, "#6a4837", "#4f3629", True),
    (188, 250, "#77543f", "#5a3f30", False),
]

SIDEWALK_Y = 792
CURB_Y = 856


def facades() -> str:
    """One flat-on row of brownstones. Windows are lit on a fixed seed so the
    render is byte-stable between runs -- a diffable creative is worth more
    than a novel one."""
    rng = random.Random(7)
    out, x = [], -40
    for w, roof, body, trim, bay in BROWNSTONES:
        out.append(
            f'<rect x="{x}" y="{roof}" width="{w}" height="{SIDEWALK_Y - roof}" fill="{body}"/>'
        )
        # cornice
        out.append(
            f'<rect x="{x - 8}" y="{roof}" width="{w + 16}" height="20" fill="{trim}"/>'
        )
        out.append(
            f'<rect x="{x - 8}" y="{roof + 20}" width="{w + 16}" height="6" fill="#00000055"/>'
        )

        # window grid: 3 storeys, 2 bays
        cols = 2
        cw = 46
        gap = (w - cols * cw) / (cols + 1)
        for row in range(3):
            wy = roof + 66 + row * 116
            for c in range(cols):
                wx = x + gap + c * (cw + gap)
                lit = rng.random() < 0.62
                fill = "#ffc978" if lit else "#241c16"
                out.append(
                    f'<rect x="{wx:.0f}" y="{wy}" width="{cw}" height="76" rx="3" fill="{fill}"/>'
                )
                out.append(
                    f'<rect x="{wx:.0f}" y="{wy}" width="{cw}" height="76" rx="3" '
                    f'fill="none" stroke="{trim}" stroke-width="5"/>'
                )
                if lit:
                    out.append(
                        f'<rect x="{wx:.0f}" y="{wy}" width="{cw}" height="76" rx="3" '
                        f'fill="url(#warmGlow)" opacity=".55"/>'
                    )

        # bay window bump-out on some houses, for silhouette variety
        if bay:
            out.append(
                f'<rect x="{x + w * 0.18:.0f}" y="{roof + 300}" width="{w * 0.64:.0f}" '
                f'height="{SIDEWALK_Y - roof - 300}" fill="{trim}" opacity=".55"/>'
            )

        # stoop + doorway
        door_x = x + w * 0.62
        out.append(
            f'<rect x="{door_x:.0f}" y="{SIDEWALK_Y - 150}" width="52" height="150" '
            f'rx="26" fill="#1d1510"/>'
        )
        out.append(
            f'<rect x="{door_x + 6:.0f}" y="{SIDEWALK_Y - 142}" width="40" height="142" '
            f'rx="20" fill="#ffb765" opacity=".85"/>'
        )
        for step in range(6):
            sy = SIDEWALK_Y - step * 9
            sw = 78 + step * 9
            out.append(
                f'<rect x="{door_x + 26 - sw / 2:.0f}" y="{sy - 9}" width="{sw:.0f}" '
                f'height="10" fill="#4a3a30" opacity=".9"/>'
            )
        x += w
    return "".join(out)


def street_lamps() -> str:
    out = []
    for lx in (54, 1014):
        out.append(
            f'<rect x="{lx}" y="{SIDEWALK_Y - 300}" width="7" height="300" fill="#241d18"/>'
        )
        out.append(f'<circle cx="{lx + 3}" cy="{SIDEWALK_Y - 306}" r="17" fill="#ffcf8a"/>')
        out.append(
            f'<circle cx="{lx + 3}" cy="{SIDEWALK_Y - 306}" r="72" fill="url(#lampGlow)"/>'
        )
    return "".join(out)


SCENE = f"""
<svg class="scene" viewBox="0 0 1080 1080" preserveAspectRatio="xMidYMid slice">
  <defs>
    <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%"   stop-color="#080f22"/>
      <stop offset="34%"  stop-color="#1a2748"/>
      <stop offset="62%"  stop-color="#42395a"/>
      <stop offset="82%"  stop-color="#8a5b44"/>
      <stop offset="100%" stop-color="#c98a52"/>
    </linearGradient>
    <radialGradient id="warmGlow">
      <stop offset="0%" stop-color="#fff3d4"/>
      <stop offset="100%" stop-color="#ffb44d" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="lampGlow">
      <stop offset="0%" stop-color="#ffcf8a" stop-opacity=".38"/>
      <stop offset="100%" stop-color="#ffcf8a" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="ground" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%"   stop-color="#2b241f"/>
      <stop offset="100%" stop-color="#0d0a08"/>
    </linearGradient>
    <linearGradient id="scrimTop" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%"   stop-color="#05070f" stop-opacity=".62"/>
      <stop offset="55%"  stop-color="#05070f" stop-opacity=".30"/>
      <stop offset="100%" stop-color="#05070f" stop-opacity="0"/>
    </linearGradient>
    <linearGradient id="scrimBot" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%"   stop-color="#05070f" stop-opacity="0"/>
      <stop offset="100%" stop-color="#05070f" stop-opacity=".8"/>
    </linearGradient>
    <radialGradient id="centreScrim" cx="50%" cy="42%" r="62%">
      <stop offset="0%"   stop-color="#05070f" stop-opacity=".52"/>
      <stop offset="100%" stop-color="#05070f" stop-opacity="0"/>
    </radialGradient>
  </defs>

  <rect width="1080" height="1080" fill="url(#sky)"/>
  {facades()}
  {street_lamps()}

  <!-- sidewalk, curb, roadway -->
  <rect x="0" y="{SIDEWALK_Y}" width="1080" height="{CURB_Y - SIDEWALK_Y}" fill="#3a322c"/>
  <rect x="0" y="{CURB_Y}" width="1080" height="{1080 - CURB_Y}" fill="url(#ground)"/>
  <rect x="0" y="{CURB_Y - 6}" width="1080" height="8" fill="#0000006b"/>

  <rect width="1080" height="1080" fill="url(#centreScrim)"/>
  <rect width="1080" height="560" fill="url(#scrimTop)"/>
  <rect y="620" width="1080" height="460" fill="url(#scrimBot)"/>
</svg>
"""

PHONE = """
<div class="phone">
  <div class="phone-body">
    <div class="screen">
      <svg viewBox="0 0 240 500" class="map">
        <rect width="240" height="500" fill="#eaeef4"/>
        <g stroke="#ffffff" stroke-width="13" stroke-linecap="round">
          <path d="M-20 118 H260"/><path d="M-20 258 H260"/><path d="M-20 392 H260"/>
          <path d="M62 -20 V520"/><path d="M172 -20 V520"/>
        </g>
        <g stroke="#dfe5ee" stroke-width="4">
          <path d="M-20 186 H260"/><path d="M-20 326 H260"/><path d="M118 -20 V520"/>
        </g>
        <g fill="#dde3ec">
          <rect x="8" y="130" width="42" height="42" rx="3"/>
          <rect x="76" y="130" width="30" height="42" rx="3"/>
          <rect x="186" y="272" width="44" height="40" rx="3"/>
          <rect x="8" y="272" width="42" height="40" rx="3"/>
        </g>
        <g fill="#006aff">
          <path d="M96 96 l14 14 -14 14 -14-14z"/>
          <path d="M150 168 l11 11 -11 11 -11-11z"/>
          <path d="M40 214 l11 11 -11 11 -11-11z"/>
          <path d="M196 226 l11 11 -11 11 -11-11z"/>
          <path d="M84 300 l11 11 -11 11 -11-11z"/>
          <path d="M160 344 l11 11 -11 11 -11-11z"/>
        </g>
      </svg>
      <div class="search"><span class="mag">&#9906;</span>Bed-Stuy, Brooklyn</div>
      <div class="callout">
        <div class="co-addr">412 Lafayette Ave</div>
        <div class="co-tag">RENT STABILIZED &middot; 24 units</div>
      </div>
    </div>
  </div>
  <div class="phone-shadow"></div>
</div>
"""

CREATIVE = f"""
<div class="creative">
  {SCENE}
  <div class="stack">
    <div class="headline">
      <div class="h-line">{HEAD_1}</div>
      <div class="h-line">{HEAD_2}</div>
      <div class="h-line h-hero">{HEAD_3}</div>
    </div>
    <div class="lockup">
      <span class="lock-mark">
        <svg viewBox="0 0 100 100"><path d="M50 12 88 50 50 88 12 50z" fill="#fff"/>
        <path d="M50 33 67 50 50 67 33 50z" fill="#006aff"/></svg>
      </span>
      <span class="lock-word">FINDACRIB</span>
    </div>
    {PHONE}
    <div class="kicker">{KICKER}</div>
  </div>
</div>
"""

CSS = """
:root { color-scheme: light dark; }
* { margin:0; padding:0; box-sizing:border-box; }
body { background:#000; }

.post { width:1080px; background:#111214; }

/* --- fake instagram chrome (preview file only) --- */
.chrome { display:flex; align-items:center; gap:20px; padding:22px 30px; background:#111214; }
.chrome .avatar { width:64px; height:64px; border-radius:50%; background:#006aff;
  display:flex; align-items:center; justify-content:center; flex:none; }
.chrome .avatar svg { width:38px; height:38px; }
.chrome .who { flex:1; min-width:0; }
.chrome .handle { display:flex; align-items:center; gap:9px;
  font:700 32px/1.1 -apple-system, "Helvetica Neue", Arial, sans-serif; color:#fff; }
.chrome .verified { width:26px; height:26px; }
.chrome .adlabel { font:400 27px/1.4 -apple-system, "Helvetica Neue", Arial, sans-serif;
  color:#c9ccd1; margin-top:4px; }
.chrome .dots { color:#fff; font-size:34px; letter-spacing:3px; padding-right:6px; }

.caption { padding:34px 62px 44px; background:#111214; text-align:center;
  font:400 29px/1.45 -apple-system, "Helvetica Neue", Arial, sans-serif; color:#e9ebee; }

/* --- the creative itself --- */
.creative { position:relative; width:1080px; height:1080px; overflow:hidden; }
.creative .scene { position:absolute; inset:0; width:100%; height:100%; }

.stack { position:absolute; inset:0; display:flex; flex-direction:column;
  align-items:center; padding:88px 0 64px; }

.headline { text-align:center; color:#fff;
  font-family:"Helvetica Neue", Helvetica, Arial, sans-serif;
  text-transform:uppercase; text-shadow:0 4px 34px rgba(0,0,0,.6); }
/* macOS only ships Helvetica Neue Condensed in Bold/Black, so the two setup
   lines get their condensing from scaleX -- font-stretch there would silently
   snap them to bold and flatten the weight contrast the layout depends on. */
.h-line { font-weight:400; font-size:94px; line-height:1.02; letter-spacing:-1px;
  transform:scaleX(.86); transform-origin:50% 50%; }
.h-hero { font-weight:800; font-stretch:condensed; font-size:112px; line-height:1;
  letter-spacing:-1.5px; transform:none; margin-top:6px; }

.lockup { margin-top:30px; display:inline-flex; align-items:center; gap:12px;
  background:#006aff; border-radius:8px; padding:11px 20px 11px 14px;
  box-shadow:0 6px 22px rgba(0,0,0,.45); }
.lock-mark { width:34px; height:34px; display:block; }
.lock-mark svg { width:100%; height:100%; display:block; }
.lock-word { font:800 31px/1 "Helvetica Neue", Helvetica, Arial, sans-serif;
  color:#fff; letter-spacing:1.4px; }

/* --- hero object: the phone, sat on the sidewalk like the Amex card --- */
.phone { position:relative; margin-top:auto; margin-bottom:38px;
  transform:perspective(1500px) rotateX(13deg) rotateZ(-5deg); }
.phone-body { width:268px; height:462px; border-radius:36px; background:#0b0d12;
  padding:10px; box-shadow:0 30px 44px rgba(0,0,0,.55), 0 0 0 2px #2c313c inset,
  0 2px 0 rgba(255,255,255,.22) inset; }
.screen { position:relative; width:100%; height:100%; border-radius:30px;
  overflow:hidden; background:#eaeef4; }
.map { position:absolute; inset:0; width:100%; height:100%; }
.search { position:absolute; top:16px; left:14px; right:14px; height:46px;
  background:#fff; border-radius:23px; display:flex; align-items:center; gap:8px;
  padding:0 16px; box-shadow:0 3px 10px rgba(10,10,35,.16);
  white-space:nowrap; overflow:hidden;
  font:600 17px/1 -apple-system, "Helvetica Neue", Arial, sans-serif; color:#0a0a23; }
.search .mag { color:#006aff; font-size:20px; }
.callout { position:absolute; left:14px; right:14px; bottom:16px; background:#fff;
  border-radius:16px; padding:15px 17px; box-shadow:0 8px 22px rgba(10,10,35,.24);
  border-left:6px solid #006aff; text-align:left; }
.co-addr { white-space:nowrap; font:700 21px/1.2 -apple-system, "Helvetica Neue", Arial, sans-serif;
  color:#0a0a23; }
.co-tag { margin-top:5px; white-space:nowrap;
  font:700 14px/1.2 -apple-system, "Helvetica Neue", Arial, sans-serif;
  color:#0e8a45; letter-spacing:.4px; }
.phone-shadow { position:absolute; left:-14%; right:-14%; bottom:-20px; height:38px;
  background:radial-gradient(50% 50% at 50% 50%, rgba(0,0,0,.55), rgba(0,0,0,0) 70%); }

.kicker { position:relative; z-index:5; color:#fff; text-align:center;
  font:800 50px/1.05 "Helvetica Neue", Helvetica, Arial, sans-serif;
  font-stretch:condensed; text-transform:uppercase; letter-spacing:-.4px;
  text-shadow:0 0 30px rgba(5,7,15,.95), 0 0 14px rgba(5,7,15,.9),
              0 3px 10px rgba(0,0,0,.8); }
"""

VERIFIED = (
    '<svg class="verified" viewBox="0 0 24 24" fill="#3897f0" aria-hidden="true">'
    '<path d="M12 1.5l2.6 2 3.2-.3 1 3.1 2.7 1.8-1.3 3 .6 3.2-3 1.2-1.8 2.7-3.1-.7'
    "-3.1.7-1.8-2.7-3-1.2.6-3.2-1.3-3L5 3.2l3.2.3z\"/>"
    '<path d="M10.8 15.2l-3-3 1.3-1.3 1.7 1.7 4.1-4.1 1.3 1.3z" fill="#fff"/></svg>'
)

MARK = (
    '<svg viewBox="0 0 100 100"><path d="M50 12 88 50 50 88 12 50z" fill="#fff"/>'
    '<path d="M50 33 67 50 50 67 33 50z" fill="#006aff"/></svg>'
)


def page(with_chrome: bool) -> str:
    chrome = (
        f"""
  <div class="chrome">
    <div class="avatar">{MARK}</div>
    <div class="who">
      <div class="handle">findacrib {VERIFIED}</div>
      <div class="adlabel">Ad</div>
    </div>
    <div class="dots">&middot;&middot;&middot;</div>
  </div>"""
        if with_chrome
        else ""
    )
    caption = f'\n  <div class="caption">{CAPTION}</div>' if with_chrome else ""
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Find A Crib &mdash; Instagram ad</title>
<style>{CSS}</style></head>
<body><div class="post" id="post">{chrome}
  {CREATIVE}{caption}
</div></body></html>"""


def shoot(html_path: pathlib.Path, png_path: pathlib.Path, width: int, height: int) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        _shoot_with_chrome(html_path, png_path, width, height)
        return
    with sync_playwright() as p:
        browser = p.chromium.launch()
        pg = browser.new_page(viewport={"width": width, "height": height},
                              device_scale_factor=1)
        pg.goto(html_path.as_uri())
        pg.locator("#post").screenshot(path=str(png_path))
        browser.close()


def _shoot_with_chrome(html_path, png_path, width, height):
    chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    subprocess.run(
        [chrome, "--headless", "--disable-gpu", "--hide-scrollbars",
         f"--window-size={width},{height}",
         f"--screenshot={png_path}", html_path.as_uri()],
        check=True, capture_output=True,
    )


def main() -> int:
    jobs = [
        ("ig-ad-stabilized", False, 1080, 1080),
        ("ig-ad-stabilized-feed", True, 1080, 1362),
    ]
    for stem, chrome, w, h in jobs:
        html = HERE / f"{stem}.html"
        png = HERE / f"{stem}.png"
        html.write_text(page(chrome), encoding="utf-8")
        shoot(html, png, w, h)
        print(f"  {png.relative_to(HERE.parent.parent)}  ({w}x{h})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

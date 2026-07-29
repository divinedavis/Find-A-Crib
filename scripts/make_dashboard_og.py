#!/usr/bin/env python3
"""Regenerate the link-preview banner for the owner dashboard.

The dashboard is the link that actually gets texted — to Eric for NEMO, and
to myself. Without og: tags iMessage renders a bare grey rectangle with the
domain, which reads like a broken or phishy link and is easy to ignore. This
draws a 1200x630 card in the dashboard's own purple/lime palette so the
preview looks like the page it opens.

Run: python3 scripts/make_dashboard_og.py
"""
import os
from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "dashboard", "og-dashboard.png")

# Dashboard chrome is near-white with a purple accent; the card inverts that
# so it still reads as "ours" against a white or black message bubble.
c1 = (109, 92, 231)     # --purple  #6d5ce7
c2 = (74, 58, 183)
img = Image.new("RGB", (W, H))
px = img.load()
for y in range(H):
    for x in range(W):
        t = (x / W + y / H) / 2
        px[x, y] = (int(c1[0] + (c2[0] - c1[0]) * t),
                    int(c1[1] + (c2[1] - c1[1]) * t),
                    int(c1[2] + (c2[2] - c1[2]) * t))
d = ImageDraw.Draw(img, "RGBA")

for (cx, cy, r, a) in [(980, 110, 60, 22), (1105, 250, 34, 18), (860, 60, 22, 20),
                       (120, 545, 26, 16), (1150, 545, 44, 14)]:
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, a))

BOLD = "/Library/Fonts/Arial Bold.ttf"
if not os.path.exists(BOLD):
    BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
REG = "/System/Library/Fonts/Supplemental/Arial.ttf"
f_title = ImageFont.truetype(BOLD, 82)
f_sub = ImageFont.truetype(REG, 40)
f_stat = ImageFont.truetype(BOLD, 34)
f_pill = ImageFont.truetype(BOLD, 32)

d.polygon([(96, 150), (118, 128), (140, 150), (118, 172)], fill=(255, 255, 255, 255))
d.text((166, 112), "Owner Dashboard", font=f_title, fill="white")
d.text((96, 246), "Web traffic, search rankings & leads —", font=f_sub, fill=(228, 224, 255, 255))
d.text((96, 300), "updated live, every day.", font=f_sub, fill=(228, 224, 255, 255))

# Three chips standing in for the tiles the page actually opens with. Kept as
# labels, not numbers: a preview image is cached by Messages for a long time
# and a stale "26 visitors" baked into a PNG would be worse than no number.
chips = ["Visitors", "Rankings", "Leads"]
x = 96
for label in chips:
    tb = d.textbbox((0, 0), label, font=f_stat)
    tw = tb[2] - tb[0]
    d.rounded_rectangle([x, 396, x + tw + 56, 468], radius=22,
                        fill=(255, 255, 255, 38))
    d.text((x + 28, 404), label, font=f_stat, fill="white")
    x += tw + 56 + 18

pill = "findacrib.com/dashboard"
tb = d.textbbox((0, 0), pill, font=f_pill)
tw, th = tb[2] - tb[0], tb[3] - tb[1]
d.rounded_rectangle([96, 516, 96 + tw + 56, 516 + th + 44], radius=33,
                    fill=(195, 245, 60, 255))          # --lime
d.text((124, 534), pill, font=f_pill, fill=(28, 26, 46, 255))

img.save(OUT, "PNG")
print("wrote", OUT, img.size)

#!/usr/bin/env python3
"""Regenerate the social-share banner (og-image.png) for Find A Crib.

1200x630, blue gradient, diamond accent + brand, subtitle, borough list,
and a white pill with the domain. Run: python3 scripts/make_og_image.py
"""
import os
from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "og-image.png")

# diagonal gradient: deep blue (top-left) -> indigo/violet (bottom-right)
c1 = (43, 57, 200)    # 2b39c8
c2 = (108, 64, 200)   # 6c40c8
img = Image.new("RGB", (W, H))
px = img.load()
for y in range(H):
    for x in range(W):
        t = (x / W + y / H) / 2
        px[x, y] = (int(c1[0] + (c2[0]-c1[0])*t),
                    int(c1[1] + (c2[1]-c1[1])*t),
                    int(c1[2] + (c2[2]-c1[2])*t))
d = ImageDraw.Draw(img, "RGBA")

# subtle decorative dots
import math
def dot(cx, cy, r, a):
    d.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(255, 255, 255, a))
for (cx, cy, r, a) in [(560,95,9,40),(700,150,16,30),(900,210,11,35),
                       (1120,135,13,30),(165,470,12,30),(540,505,9,35),
                       (1130,470,18,28),(890,430,10,30),(640,330,7,30)]:
    dot(cx, cy, r, a)

BOLD = "/Library/Fonts/Arial Bold.ttf"
if not os.path.exists(BOLD):
    BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
REG = "/System/Library/Fonts/Supplemental/Arial.ttf"
f_brand = ImageFont.truetype(BOLD, 76)
f_sub   = ImageFont.truetype(BOLD, 52)
f_boro  = ImageFont.truetype(REG, 34)
f_pill  = ImageFont.truetype(BOLD, 32)

# diamond accent + brand
d.polygon([(110,168),(130,148),(150,168),(130,188)], fill=(255,255,255,255))
d.text((172, 130), "Find A Crib", font=f_brand, fill="white")
# subtitle
d.text((90, 255), "Find NYC rent-stabilized apartments", font=f_sub, fill="white")
# borough list
d.text((92, 332), "Manhattan  ·  Bronx  ·  Brooklyn  ·  Queens  ·  Staten Island",
       font=f_boro, fill=(225, 228, 255, 255))
# domain pill
pill_text = "findacrib.com"
tb = d.textbbox((0,0), pill_text, font=f_pill)
tw, th = tb[2]-tb[0], tb[3]-tb[1]
px0, py0 = 90, 470
padx, pady = 28, 18
d.rounded_rectangle([px0, py0, px0+tw+padx*2, py0+th+pady*2+8],
                    radius=33, fill=(245, 247, 255, 255))
d.text((px0+padx, py0+pady), pill_text, font=f_pill, fill=(60, 70, 210, 255))

img.save(OUT, "PNG")
print("wrote", OUT, img.size)

#!/usr/bin/env python3
"""Regenerate the social-share banner (og-image.png) for Find A Crib — the card
iMessage, Slack and Facebook show for a findacrib.com link.

1200x630: the icon's teal field on the left with the brand, one line of copy,
the cities and the domain; on the right two real screens from the iPhone app
(ios/marketing/raw, recaptured whenever the app's look changes) running off
the bottom edge. Run: python3 scripts/make_og_image.py
"""
import os
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

W, H = 1200, 630
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "og-image.png")
RAW = os.path.join(ROOT, "ios", "marketing", "raw")
FONTS = os.path.join(ROOT, "ios", "FindACrib", "Resources", "Fonts")


def font(name, size, fallback="/System/Library/Fonts/Supplemental/Arial Bold.ttf"):
    p = os.path.join(FONTS, name)
    return ImageFont.truetype(p if os.path.exists(p) else fallback, size)


# diagonal gradient: lit teal (top-left) -> teal rim (bottom-right), the icon's field
c1 = (96, 166, 178)   # the icon's lit teal (scripts/make_icon.py CORE)
c2 = (22, 60, 71)     # SE.navy, the app's chrome
grad = ImageChops.add(Image.linear_gradient("L").rotate(90).resize((W, H)),
                      Image.linear_gradient("L").resize((W, H)), scale=2)
img = Image.composite(Image.new("RGB", (W, H), c2), Image.new("RGB", (W, H), c1), grad)
d = ImageDraw.Draw(img, "RGBA")

f_brand = font("SourceSans3-Black.ttf", 64)
f_head = font("SourceSans3-Bold.ttf", 50)
f_city = font("SourceSans3-Semibold.ttf", 28, "/System/Library/Fonts/Supplemental/Arial.ttf")
f_pill = font("SourceSans3-Bold.ttf", 30)

# the app icon (scripts/make_icon.py) + brand
icon = Image.open(os.path.join(ROOT, "icon-512.png")).convert("RGBA").resize((68, 68), Image.LANCZOS)
img.paste(icon, (72, 96), icon)
d.text((156, 90), "Find A Crib", font=f_brand, fill="white")

y = 214
for line in ["Every rent-stabilized", "building, on one map"]:
    d.text((72, y), line, font=f_head, fill="white")
    y += 60
d.text((74, y + 22), "New York · Los Angeles · San Francisco · DC", font=f_city, fill=(214, 236, 240))

# domain pill + App Store note
pill = "findacrib.com"
tw = d.textlength(pill, font=f_pill)
d.rounded_rectangle([72, 470, 72 + tw + 56, 470 + 64], radius=32, fill=(255, 255, 255))
d.text((100, 482), pill, font=f_pill, fill=(22, 60, 71))
d.text((72 + tw + 80, 484), "+ iPhone app", font=f_pill, fill="white")


def phone(path, w):
    """A real screen as a frameless rounded card with a thin dark rim."""
    shot = Image.open(path).convert("RGB")
    h = int(w * shot.height / shot.width)
    shot = shot.resize((w, h), Image.LANCZOS)
    r, rim = int(w * 0.12), 6
    card = Image.new("RGBA", (w + 2 * rim, h + 2 * rim), (0, 0, 0, 0))
    ImageDraw.Draw(card).rounded_rectangle([0, 0, card.width - 1, card.height - 1], radius=r + rim, fill=(12, 20, 24, 255))
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w - 1, h - 1], radius=r, fill=255)
    card.paste(shot, (rim, rim), m)
    return card


def place(canvas, card, x, y):
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    s = Image.new("RGBA", card.size, (0, 0, 0, 0))
    s.putalpha(card.split()[3].point(lambda v: int(v * 0.45)))
    shadow.alpha_composite(s, (x, y + 18))
    out = Image.alpha_composite(canvas.convert("RGBA"), shadow.filter(ImageFilter.GaussianBlur(22)))
    out.alpha_composite(card, (x, y))
    return out


img = place(img, phone(os.path.join(RAW, "home.png"), 262), 668, 118)
img = place(img, phone(os.path.join(RAW, "map.png"), 276), 900, 58)
img.convert("RGB").save(OUT, "PNG", optimize=True)
print("wrote", OUT, img.size)

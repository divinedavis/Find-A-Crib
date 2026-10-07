#!/usr/bin/env python3
"""App Store creative assets (Asset Library, fall 2026) for Find A Crib, in
the three canvases Apple's templates use:

    header    3840x1646  product page header (and each custom product page's)
    search    3840x2560  search results slot
    universal 5244x2950  16:9 master Apple can crop into either

Same look as make_header.py (teal field, white wordmark, floating building
photos and bubbles), re-laid in fractions of the canvas so the wide header
and the squarer search tile both keep the focal art in the centre safe
area. Apple bans specific prices, URLs and (c) in these assets, so the
old "$1,850 / mo" bubble is gone.

One set per page: "default" for the main product page, then one per custom
product page (see marketing/asc-creative/PLAN.md).

Usage: ~/.venvs/spendcap/bin/python scripts/make_creative_assets.py [OUT_DIR]
"""
import os
import sys
from PIL import Image, ImageDraw, ImageFilter

from make_header import (gradient, font, circle_photo, rounded_tile, bubble,
                         badge_pin, preview, PHOTOS, WHITE, GREEN, YELLOW, NAVY)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANVASES = {"header": (3840, 1646), "search": (3840, 2560), "universal": (5244, 2950)}

PAGES = {
    "default": {
        "tagline": "Rent-stabilized & affordable apartments, mapped",
        "bubbles": [("Lottery open", YELLOW, NAVY), ("Rent-stabilized", WHITE, NAVY, GREEN)],
    },
    "cpp-lotteries": {
        "tagline": "Every NYC housing lottery you can apply for today",
        "bubbles": [("Deadline soon", YELLOW, NAVY), ("Income-restricted", WHITE, NAVY, GREEN)],
    },
    "cpp-stabilized": {
        "tagline": "All 47,000 NYC rent-stabilized buildings",
        "bubbles": [("For rent this week", YELLOW, NAVY), ("Rent-stabilized", WHITE, NAVY, GREEN)],
    },
    "cpp-cities": {
        "tagline": "Rent-limited homes in LA, SF, DC & more",
        "bubbles": [("Los Angeles RSO", YELLOW, NAVY), ("Rent-controlled", WHITE, NAVY, GREEN)],
    },
}


def render(w, h, page):
    s = min(h / 720.0, w / 1280.0)
    base = gradient(w, h).convert("RGBA")
    d = ImageDraw.Draw(base)

    text = "Find A Crib"
    size = 200 * s
    f = font("Black", size)
    while d.textlength(text, font=f) > w * 0.50:
        size -= 4; f = font("Black", size)
    tw = d.textlength(text, font=f)
    asc, desc = f.getmetrics()
    tx, ty = (w - tw) / 2, h * 0.5 - (asc - desc * 0.4) / 2 - 20 * s
    glow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).text((tx, ty), text, font=f, fill=(0, 40, 160, 120))
    base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(int(22 * s))))
    ImageDraw.Draw(base).text((tx, ty), text, font=f, fill=WHITE)

    tag = page["tagline"]
    ts = 34 * s
    tf = font("Semibold", ts)
    while d.textlength(tag, font=tf) > w * 0.62:
        ts -= 2; tf = font("Semibold", ts)
    tw2 = d.textlength(tag, font=tf)
    ImageDraw.Draw(base).text(((w - tw2) / 2, ty + asc + 14 * s), tag, font=tf, fill=(225, 234, 255))

    # Floating pieces in canvas fractions; the outer ones may be cropped on
    # some devices, which is fine — nothing that must be read sits there.
    P = lambda fx, fy: (fx * w, fy * h)
    rounded_tile(base, P(0.20, 0.21), 120 * s, -10, s)
    circle_photo(base, PHOTOS["brownstone"], P(0.11, 0.72), 170 * s, 6 * s, s)
    badge_pin(base, (0.11 * w + 65 * s, 0.72 * h + 65 * s), s)
    circle_photo(base, PHOTOS["brick"], P(0.89, 0.65), 190 * s, 6 * s, s)
    circle_photo(base, PHOTOS["corner"], P(0.79, 0.19), 84 * s, 4 * s, s)
    b1, b2 = page["bubbles"]
    bubble(base, b1[0], P(0.80, 0.42), s, fill=b1[1], ink=b1[2], tail="left", size=28)
    bubble(base, b2[0], P(0.50, 0.87), s, fill=b2[1], ink=b2[2], tail=None, size=24,
           dot=b2[3] if len(b2) > 3 else None)
    return base.convert("RGB")


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "marketing/asc-creative")
    for name, page in PAGES.items():
        canvases = CANVASES if name == "default" else {"header": CANVASES["header"]}
        for kind, (w, h) in canvases.items():
            img = render(w, h, page)
            p = os.path.join(out, name, f"{kind}-{w}x{h}.png")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            img.save(p, optimize=True)
            print("wrote", p)
            if kind == "header":
                preview(img.resize((1280, int(1280 * h / w)), Image.LANCZOS)).save(
                    os.path.join(out, name, "preview-product-page.png"))


if __name__ == "__main__":
    main()

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
    # Round two (owner, 2026-10-13: "add more custom product pages").
    "cpp-vouchers": {
        "tagline": "NYC buildings that take Section 8 & CityFHEPS",
        "bubbles": [("Vouchers welcome", YELLOW, NAVY), ("Section 8", WHITE, NAVY, GREEN)],
    },
    "cpp-building-check": {
        "tagline": "Check any NYC building before you sign",
        "bubbles": [("Bedbugs on file?", YELLOW, NAVY), ("No open violations", WHITE, NAVY, GREEN)],
    },
    "cpp-brooklyn": {
        "tagline": "Rent-stabilized buildings across Brooklyn",
        "bubbles": [("Bed-Stuy · Flatbush", YELLOW, NAVY), ("Rent-stabilized", WHITE, NAVY, GREEN)],
    },
    # Staged until the renter tools ship in an App Store version (a CPP may
    # only show what the live app does).
    "cpp-renter-tools": {
        "tagline": "Repairs, rent increases & your rights as a renter",
        "bubbles": [("Is my increase legal?", YELLOW, NAVY), ("Repair letter ready", WHITE, NAVY, GREEN)],
    },
    "cpp-broker-fee": {
        "tagline": "Check broker fees and your lease before you sign",
        "bubbles": [("FARE Act check", YELLOW, NAVY), ("Lease reviewed", WHITE, NAVY, GREEN)],
    },
    "cpp-cities": {
        "tagline": "Rent-limited homes in LA, SF, DC & more",
        "bubbles": [("Los Angeles RSO", YELLOW, NAVY), ("Rent-controlled", WHITE, NAVY, GREEN)],
    },
}


# Apple's ART SAFE AREA per canvas, (x, y, w, h), from its
# creative_assets-templates.sketch (measured 2026-10-12). An iPhone 17 Pro
# shows only x 1006-2833 of the header, with the back button and the
# mute/share pill over y 490-725 at its edges. The first sets let the
# wordmark run to 50% of the width and the tagline to 62%, so on an iPhone
# both were cut at the sides (owner's screenshot, 2026-10-14). All type now
# goes on its own layer and render() refuses an image whose type leaves
# SAFE or touches BUTTONS. The photos are decoration and may be cropped.
SAFE = {"header": (1097, 493, 1646, 661), "search": (836, 765, 2168, 1030), "universal": (1921, 660, 1402, 962)}
BUTTONS = {"header": [(1006, 490, 1290, 725), (2240, 490, 2833, 725)]}
# Fractions of the safe area: wordmark centre and widest extent, tagline
# centre, widest extent and size; bubbles' row centre (None = no bubbles,
# the header has no room for them under the buttons).
LAYOUT = {
    "header": {"name_cy": 0.50, "name_w": 0.62, "tag_cy": 0.835, "tag_w": 0.92, "tag_size": 0.10, "bub_cy": None},
    "search": {"name_cy": 0.22, "name_w": 0.62, "tag_cy": 0.53, "tag_w": 0.92, "tag_size": 0.075, "bub_cy": 0.84},
    "universal": {"name_cy": 0.22, "name_w": 0.80, "tag_cy": 0.53, "tag_w": 0.94, "tag_size": 0.07, "bub_cy": 0.84, "bub_scale": 0.62},
}


def lines_for(d, text, f, width):
    """The tagline on one line if it fits, else split into two balanced lines."""
    if d.textlength(text, font=f) <= width:
        return [text]
    words = text.split()
    best = min(range(1, len(words)), key=lambda i: max(d.textlength(" ".join(words[:i]), font=f),
                                                       d.textlength(" ".join(words[i:]), font=f)))
    return [" ".join(words[:best]), " ".join(words[best:])]


def check_type(layer, kind):
    box = layer.split()[3].getbbox()
    if not box:
        return
    x0, y0, x1, y1 = box
    sx, sy, sw, sh = SAFE[kind]
    if not (sx <= x0 and x1 <= sx + sw and sy <= y0 and y1 <= sy + sh):
        sys.exit(f"{kind}: type {box} leaves the safe area {SAFE[kind]}")
    for b in BUTTONS.get(kind, []):
        if not (x1 <= b[0] or x0 >= b[2] or y1 <= b[1] or y0 >= b[3]):
            sys.exit(f"{kind}: type {box} sits under an App Store button {b}")


def render(w, h, page, kind):
    s = min(h / 720.0, w / 1280.0)
    base = gradient(w, h).convert("RGBA")
    sx, sy, sw, sh = SAFE[kind]
    L = LAYOUT[kind]
    cx = sx + sw / 2
    d = ImageDraw.Draw(base)

    # Floating pieces in canvas fractions, all outside the safe area.
    P = lambda fx, fy: (fx * w, fy * h)
    rounded_tile(base, P(0.20, 0.21), 120 * s, -10, s)
    circle_photo(base, PHOTOS["brownstone"], P(0.11, 0.72), 170 * s, 6 * s, s)
    badge_pin(base, (0.11 * w + 65 * s, 0.72 * h + 65 * s), s)
    circle_photo(base, PHOTOS["brick"], P(0.89, 0.65), 190 * s, 6 * s, s)
    circle_photo(base, PHOTOS["corner"], P(0.79, 0.19), 84 * s, 4 * s, s)

    type_layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    td = ImageDraw.Draw(type_layer)

    text = "Find A Crib"
    size = sh * 0.40
    f = font("Black", size)
    while d.textlength(text, font=f) > sw * L["name_w"]:
        size -= 2; f = font("Black", size)
    tw = d.textlength(text, font=f)
    x0, y0, x1, y1 = td.textbbox((0, 0), text, font=f)
    tx, ty = cx - tw / 2, sy + sh * L["name_cy"] - (y0 + y1) / 2
    glow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).text((tx, ty), text, font=f, fill=(0, 40, 160, 120))
    base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(int(22 * s))))
    td.text((tx, ty), text, font=f, fill=WHITE)

    ts = sh * L["tag_size"]
    tf = font("Semibold", ts)
    lines = lines_for(d, page["tagline"], tf, sw * L["tag_w"])
    while max(d.textlength(l, font=tf) for l in lines) > sw * L["tag_w"]:
        ts -= 2; tf = font("Semibold", ts)
    step = ts * 1.22
    top = sy + sh * L["tag_cy"] - step * len(lines) / 2
    for i, line in enumerate(lines):
        td.text((cx - d.textlength(line, font=tf) / 2, top + i * step), line, font=tf, fill=(225, 234, 255))

    if L["bub_cy"] is not None:
        b1, b2 = page["bubbles"]
        by = sy + sh * L["bub_cy"]
        bs = s * L.get("bub_scale", 1.0)
        bubble(type_layer, b1[0], (cx - sw * 0.24, by), bs, fill=b1[1], ink=b1[2], tail=None, size=24)
        bubble(type_layer, b2[0], (cx + sw * 0.24, by), bs, fill=b2[1], ink=b2[2], tail=None, size=24,
               dot=b2[3] if len(b2) > 3 else None)

    check_type(type_layer, kind)
    base.alpha_composite(type_layer)
    return base.convert("RGB")


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "marketing/asc-creative")
    for name, page in PAGES.items():
        canvases = CANVASES if name == "default" else {"header": CANVASES["header"]}
        for kind, (w, h) in canvases.items():
            img = render(w, h, page, kind)
            p = os.path.join(out, name, f"{kind}-{w}x{h}.png")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            img.save(p, optimize=True)
            print("wrote", p)
            if kind == "header":
                preview(img.resize((1280, int(1280 * h / w)), Image.LANCZOS)).save(
                    os.path.join(out, name, "preview-product-page.png"))


if __name__ == "__main__":
    main()

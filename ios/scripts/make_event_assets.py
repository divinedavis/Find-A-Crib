#!/usr/bin/env python3
"""In-App Event art for the App Store (Asset Library, fall 2026):
event card 3840x2160 (16:9) and event details page 2160x3840 (9:16).

The event's name and description sit on top of this art in the App Store,
so the art carries no headline: the header's teal field, the app tile,
the street photos and a yellow calendar for the deadline theme.

    ~/.venvs/dhcr-map/bin/python scripts/make_event_assets.py [OUT_DIR]
"""
import os
import sys
from PIL import Image, ImageDraw

from make_header import (gradient, circle_photo, rounded_tile, badge_pin, shadow,
                         PHOTOS, WHITE, YELLOW, NAVY)

OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser(
    "~/Downloads/ASC-creative-assets/findacrib/event-lotteries")
SIZES = {"card": (3840, 2160), "details": (2160, 3840)}


def calendar(base, center, size, s):
    """A yellow tear-off calendar with a navy grid; one square circled."""
    w, h = int(size), int(size * 0.9)
    layer = Image.new("RGBA", (w + int(40 * s), h + int(40 * s)), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    o = int(20 * s)
    r = int(w * 0.12)
    d.rounded_rectangle([o, o, o + w, o + h], radius=r, fill=WHITE + (255,))
    d.rounded_rectangle([o, o, o + w, o + int(h * 0.28)], radius=r, fill=YELLOW + (255,))
    d.rectangle([o, o + int(h * 0.16), o + w, o + int(h * 0.28)], fill=YELLOW + (255,))
    for i in (0.3, 0.7):  # binder rings
        cx = o + w * i
        d.rounded_rectangle([cx - w * 0.04, o - h * 0.06, cx + w * 0.04, o + h * 0.1],
                            radius=int(w * 0.04), fill=NAVY + (255,))
    cols, rows = 5, 3
    gx0, gy0 = o + w * 0.12, o + h * 0.38
    cw, ch = w * 0.76 / cols, h * 0.5 / rows
    for rr in range(rows):
        for cc in range(cols):
            x0, y0 = gx0 + cc * cw + cw * 0.18, gy0 + rr * ch + ch * 0.2
            d.rounded_rectangle([x0, y0, x0 + cw * 0.64, y0 + ch * 0.6], radius=int(cw * 0.12),
                                fill=(NAVY if (rr, cc) == (1, 3) else (210, 222, 226)) + (255,))
    cx, cy = gx0 + 3 * cw + cw * 0.5, gy0 + ch + ch * 0.5
    rad = cw * 0.62
    d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], outline=(230, 60, 60, 255), width=max(4, int(w * 0.022)))
    x, y = int(center[0] - layer.width / 2), int(center[1] - layer.height / 2)
    shadow(base, layer.split()[3], (x, y), int(24 * s), dy=12 * s)
    base.alpha_composite(layer, (x, y))


def render(w, h):
    s = min(w, h) / 720.0
    base = gradient(w, h).convert("RGBA")
    if w > h:
        calendar(base, (w * 0.5, h * 0.5), h * 0.5, s)
        circle_photo(base, PHOTOS["brownstone"], (w * 0.18, h * 0.62), h * 0.3, 6 * s, s)
        badge_pin(base, (w * 0.18 + h * 0.11, h * 0.62 + h * 0.11), s, diam=70)
        circle_photo(base, PHOTOS["brick"], (w * 0.83, h * 0.42), h * 0.34, 6 * s, s)
        circle_photo(base, PHOTOS["corner"], (w * 0.72, h * 0.16), h * 0.13, 5 * s, s)
        rounded_tile(base, (w * 0.12, h * 0.2), h * 0.17, 8, s)
    else:
        calendar(base, (w * 0.5, h * 0.42), w * 0.6, s)
        circle_photo(base, PHOTOS["brownstone"], (w * 0.27, h * 0.75), w * 0.36, 6 * s, s)
        badge_pin(base, (w * 0.27 + w * 0.13, h * 0.75 + w * 0.13), s, diam=70)
        circle_photo(base, PHOTOS["brick"], (w * 0.76, h * 0.68), w * 0.3, 6 * s, s)
        circle_photo(base, PHOTOS["corner"], (w * 0.8, h * 0.13), w * 0.16, 5 * s, s)
        rounded_tile(base, (w * 0.2, h * 0.14), w * 0.2, 8, s)
    return base.convert("RGB")


def main():
    os.makedirs(OUT, exist_ok=True)
    for kind, (w, h) in SIZES.items():
        p = os.path.join(OUT, f"{kind}-{w}x{h}.png")
        render(w, h).save(p, optimize=True)
        print(p)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""In-App Event art for the App Store (Asset Library, fall 2026):
event card 3840x2160 (16:9) and event details page 2160x3840 (9:16).

The event's name and description sit on top of this art in the App Store,
so the art carries no headline: the header's teal field, the app tile,
the street photos and a yellow calendar for the deadline theme.

    ~/.venvs/dhcr-map/bin/python scripts/make_event_assets.py [OUT_DIR] [--theme heat]

--theme heat (2026-10-16, "Heat season" event): a white radiator with red
heat waves in place of the calendar.

--theme logo [--holiday <id>] (owner, 2026-10-24: "we should always have
our logo on the event card and event details"): the real app icon, large
and centred, is the hero; the street photos stay around it. With
--holiday, the field is that day's colours from holidays.json (the tab
colours) instead of the teal; the logo itself never changes.
"""
import json
import math
import os
import sys
from PIL import Image, ImageDraw

from make_header import (gradient, circle_photo, rounded_tile, badge_pin, shadow,
                         PHOTOS, WHITE, YELLOW, NAVY)

ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
THEME = sys.argv[sys.argv.index("--theme") + 1] if "--theme" in sys.argv else "lotteries"
HOLIDAY = sys.argv[sys.argv.index("--holiday") + 1] if "--holiday" in sys.argv else None
ARGS = [a for a in ARGS if a not in (THEME, HOLIDAY)]
OUT = ARGS[0] if ARGS else os.path.expanduser(
    "~/Downloads/ASC-creative-assets/findacrib/event-" + (HOLIDAY or THEME))
# Clean street photos for the logo art: the home shot that PHOTOS crops has
# changed since the first event art (its crops now land on UI).
STREET = {k: os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "marketing/event-photos", k + ".jpg")
          for k in ("brownstone", "brick", "corner")}
HOLIDAYS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "FindACrib/Resources/holidays.json")
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


def radiator(base, center, size, s):
    """A white radiator, navy fins, three red heat waves rising off it."""
    w, h = int(size), int(size * 0.9)
    layer = Image.new("RGBA", (w + int(40 * s), h + int(40 * s)), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    o = int(20 * s)
    top = o + int(h * 0.34)
    d.rounded_rectangle([o, top, o + w, o + h], radius=int(w * 0.08), fill=WHITE + (255,))
    fins = 6
    fw = w * 0.84 / fins
    for i in range(fins):
        x0 = o + w * 0.08 + i * fw + fw * 0.2
        d.rounded_rectangle([x0, top + h * 0.1, x0 + fw * 0.6, o + h - h * 0.1], radius=int(fw * 0.3), fill=NAVY + (255,))
    red = (230, 60, 60, 255)
    lw = max(4, int(w * 0.035))
    for i in (0.25, 0.5, 0.75):
        cx = o + w * i
        pts = []
        for k in range(21):
            t = k / 20
            pts.append((cx + math.sin(t * math.pi * 3) * w * 0.05, top - h * 0.04 - t * h * 0.26))
        d.line(pts, fill=red, width=lw, joint="curve")
    x, y = int(center[0] - layer.width / 2), int(center[1] - layer.height / 2)
    shadow(base, layer.split()[3], (x, y), int(24 * s), dy=12 * s)
    base.alpha_composite(layer, (x, y))


def hexrgb(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def holiday_field(w, h, day):
    """The day's tab colours as a diagonal blend, like the preview's art."""
    cols = [hexrgb(c) for c in next(x for x in json.load(open(HOLIDAYS))["holidays"] if x["id"] == day)["tab"]]
    if len(cols) == 1:
        cols *= 2
    n = 256
    strip = Image.new("RGB", (n, 1))
    for i in range(n):
        t = i / (n - 1) * (len(cols) - 1)
        a, b = cols[min(int(t), len(cols) - 2)], cols[min(int(t), len(cols) - 2) + 1]
        f = t - min(int(t), len(cols) - 2)
        strip.putpixel((i, 0), tuple(int(a[k] + (b[k] - a[k]) * f) for k in range(3)))
    d = int(math.hypot(w, h)) + 2
    big = strip.resize((d, d), Image.BILINEAR).rotate(-math.degrees(math.atan2(h, w)), resample=Image.BICUBIC)
    return big.crop(((d - w) // 2, (d - h) // 2, (d - w) // 2 + w, (d - h) // 2 + h))


def render_logo(w, h):
    s = min(w, h) / 720.0
    base = (holiday_field(w, h, HOLIDAY) if HOLIDAY else gradient(w, h)).convert("RGBA")
    if w > h:
        rounded_tile(base, (w * 0.5, h * 0.5), h * 0.5, 0, s)
        circle_photo(base, STREET["brownstone"], (w * 0.18, h * 0.62), h * 0.3, 6 * s, s)
        badge_pin(base, (w * 0.18 + h * 0.11, h * 0.62 + h * 0.11), s, diam=70)
        circle_photo(base, STREET["brick"], (w * 0.83, h * 0.42), h * 0.34, 6 * s, s)
        circle_photo(base, STREET["corner"], (w * 0.72, h * 0.16), h * 0.13, 5 * s, s)
    else:
        # Apple lays the event's name over the bottom third: the logo sits above it.
        rounded_tile(base, (w * 0.5, h * 0.36), w * 0.5, 0, s)
        circle_photo(base, STREET["brownstone"], (w * 0.2, h * 0.6), w * 0.3, 6 * s, s)
        badge_pin(base, (w * 0.2 + w * 0.11, h * 0.6 + w * 0.11), s, diam=70)
        circle_photo(base, STREET["brick"], (w * 0.8, h * 0.14), w * 0.26, 6 * s, s)
        circle_photo(base, STREET["corner"], (w * 0.84, h * 0.56), w * 0.16, 5 * s, s)
    return base.convert("RGB")


def render(w, h):
    if THEME == "logo":
        return render_logo(w, h)
    s = min(w, h) / 720.0
    base = gradient(w, h).convert("RGBA")
    if w > h:
        (radiator if THEME == "heat" else calendar)(base, (w * 0.5, h * 0.5), h * 0.5, s)
        circle_photo(base, PHOTOS["brownstone"], (w * 0.18, h * 0.62), h * 0.3, 6 * s, s)
        badge_pin(base, (w * 0.18 + h * 0.11, h * 0.62 + h * 0.11), s, diam=70)
        circle_photo(base, PHOTOS["brick"], (w * 0.83, h * 0.42), h * 0.34, 6 * s, s)
        circle_photo(base, PHOTOS["corner"], (w * 0.72, h * 0.16), h * 0.13, 5 * s, s)
        rounded_tile(base, (w * 0.12, h * 0.2), h * 0.17, 8, s)
    else:
        (radiator if THEME == "heat" else calendar)(base, (w * 0.5, h * 0.42), w * 0.6, s)
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

#!/usr/bin/env python3
"""Holiday Home Screen icons (owner, 2026-10-23), cut from the real app icon:
the house in icon-1024.png keeps its own artwork and bevel; only the teal
field behind it changes to the day's colours, in Marracat's icon bands, with the same soft
light the teal field has. One per holiday in Resources/holidays.json.

These are alternate icons for the Home Screen only. The App Store always
shows the primary AppIcon; nothing here changes it.

    ~/.venvs/dhcr-map/bin/python scripts/holiday_app_icons.py OUT_DIR   # PNGs to look at
    ~/.venvs/dhcr-map/bin/python scripts/holiday_app_icons.py --xcassets   # AppIcon-<id> sets

Needs Pillow + numpy.
"""
import json
import pathlib
import sys

import numpy as np
from PIL import Image, ImageChops, ImageFilter

ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "FindACrib/Resources/Assets.xcassets"
ICON = ASSETS / "AppIcon.appiconset/icon-1024.png"


def house_layers():
    """The house (with its bevel) and its shadow, as RGBA layers."""
    src = Image.open(ICON).convert("RGB")
    a = np.asarray(src).astype(float)
    lum, sat = a.mean(axis=2), a.max(axis=2) - a.min(axis=2)
    # The house is near-white and grey; the field is saturated teal.
    mask = Image.fromarray(((lum > 175) & (sat < 60)).astype(np.uint8) * 255)
    mask = mask.filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.8))
    house = src.copy()
    house.putalpha(mask)
    shadow = Image.new("RGBA", src.size, (0, 0, 0, 0))
    shadow.putalpha(mask.point(lambda v: int(v * 0.35)).filter(ImageFilter.GaussianBlur(14)))
    return house, ImageChops.offset(shadow, 0, 10)


def field(bands, size=1024):
    """Marracat's icon bands ([colour, weight], top to bottom), lit like the
    teal field: brighter above the house, darker towards the corners."""
    im = Image.new("RGB", (size, size))
    total, y = sum(w for _, w in bands), 0.0
    for c, w in bands:
        h = size * w / total
        im.paste(tuple(int(c[j:j + 2], 16) for j in (1, 3, 5)), (0, round(y), size, round(y + h)))
        y += h
    yy, xx = np.mgrid[0:size, 0:size]
    d = np.sqrt(((xx - 0.55 * size) / size) ** 2 + ((yy - 0.36 * size) / size) ** 2)
    shade = np.clip(1.12 - d * 0.55, 0.78, 1.12)[..., None]
    return Image.fromarray(np.clip(np.asarray(im).astype(float) * shade, 0, 255).astype(np.uint8))


def icon(h, house, shadow):
    im = field(h["icon_bands"]).convert("RGBA")
    im.alpha_composite(shadow)
    im.alpha_composite(house)
    return im.convert("RGB")   # App Store icons may not carry alpha


def main():
    holidays = json.loads((ROOT / "FindACrib/Resources/holidays.json").read_text())["holidays"]
    house, shadow = house_layers()
    if sys.argv[1:] == ["--xcassets"]:
        for h in holidays:
            d = ASSETS / f"{h['icon']}.appiconset"
            d.mkdir(exist_ok=True)
            icon(h, house, shadow).save(d / "icon-1024.png")
            (d / "Contents.json").write_text(json.dumps({
                "images": [{"filename": "icon-1024.png", "idiom": "universal", "platform": "ios", "size": "1024x1024"}],
                "info": {"author": "xcode", "version": 1}}, indent=2) + "\n")
        print(f"{len(holidays)} icon sets in {ASSETS}")
        return
    out = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    out.mkdir(parents=True, exist_ok=True)
    for h in holidays:
        icon(h, house, shadow).save(out / f"{h['id']}.png")
    Image.open(ICON).convert("RGB").save(out / "everyday.png")
    print(f"{len(holidays) + 1} icons in {out}")


if __name__ == "__main__":
    main()

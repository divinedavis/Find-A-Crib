#!/usr/bin/env python3
"""Compose the App Store screenshots in the house marketing style: five iPhone
portrait panels alternating a yellow accent field and white, an oversized
lowercase headline, the real app screen in a rounded device bezel, the brand
small in the corner, and a continuation cue leading into the next panel.

Input : marketing/raw/{home,results,map,detail,hcr}.png (1320x2868 simulator shots)
Output: marketing/asc-screenshots/0N-*.png at 1320x2868 (App Store 6.9")

    python3 scripts/make_screenshots.py
"""
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1320, 2868
YELLOW = (255, 214, 10)
WHITE = (255, 255, 255)
INK = (18, 18, 22)
NAVY = (14, 42, 110)
ROYAL = (27, 70, 229)
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(HERE, "marketing", "raw")
OUT = os.path.join(HERE, "marketing", "asc-screenshots")
FONT = next((p for p in [
    os.path.join(HERE, "FindACrib/Resources/Fonts/SourceSans3-Black.ttf"),
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/System/Library/Fonts/Helvetica.ttc"] if os.path.exists(p)), None)
FONT_MED = next((p for p in [
    os.path.join(HERE, "FindACrib/Resources/Fonts/SourceSans3-Semibold.ttf"),
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf"] if os.path.exists(p)), None)


def font(size, medium=False):
    p = FONT_MED if medium else FONT
    return ImageFont.truetype(p, size) if p else ImageFont.load_default()


def rounded_mask(size, r):
    m = Image.new("L", size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size[0] - 1, size[1] - 1], radius=r, fill=255)
    return m


def device(path, target_w):
    shot = Image.open(path).convert("RGB")
    sh = int(target_w * shot.height / shot.width)
    shot = shot.resize((target_w, sh), Image.LANCZOS)
    r = int(target_w * 0.11)
    shot.putalpha(rounded_mask((target_w, sh), r))
    bezel = int(target_w * 0.032)
    bw, bh = target_w + 2 * bezel, sh + 2 * bezel
    body = Image.new("RGBA", (bw, bh), (12, 12, 14, 255))
    body.putalpha(rounded_mask((bw, bh), r + bezel))
    frame = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    frame.alpha_composite(body)
    frame.alpha_composite(shot, (bezel, bezel))
    return frame


def paste_with_shadow(img, dev, x, y):
    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sh = Image.new("RGBA", dev.size, (0, 0, 0, 0))
    sh.putalpha(dev.split()[3].point(lambda v: int(v * 0.35)))
    shadow.alpha_composite(sh, (x, y + 40))
    shadow = shadow.filter(ImageFilter.GaussianBlur(50))
    out = Image.alpha_composite(img.convert("RGBA"), shadow)
    out.alpha_composite(dev, (x, y))
    return out.convert("RGB")


def brand(draw, on_yellow):
    # small mark + name in the corner, as the style sheet asks
    f = font(44, medium=True)
    ink = INK if on_yellow else NAVY
    draw.rounded_rectangle([72, 88, 72 + 52, 88 + 52], radius=14, fill=ROYAL)
    draw.ellipse([84, 100, 84 + 28, 100 + 28], outline=WHITE, width=6)
    draw.text((140, 84), "Find A Crib", font=f, fill=ink)


def headline(draw, lines, y, ink, size=150):
    f = font(size)
    for line in lines:
        draw.text((72, y), line, font=f, fill=ink)
        y += int(size * 1.02)
    return y


def sub(draw, text, y, ink):
    draw.text((72, y), text, font=font(50, medium=True), fill=ink)
    return y + 70


def cue(draw, text, ink):
    f = font(54, medium=True)
    w = draw.textbbox((0, 0), text, font=f)[2]
    draw.text((W - 72 - w, H - 190), text, font=f, fill=ink)


def panel(n, name, bg, lines, subline, shot, cue_text=None, dev_w=980):
    on_yellow = bg == YELLOW
    ink = INK if on_yellow else NAVY
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    brand(d, on_yellow)
    y = headline(d, lines, 220, ink)
    y = sub(d, subline, y + 24, (60, 60, 60) if on_yellow else (74, 74, 74))
    dev = device(shot, dev_w)
    img = paste_with_shadow(img, dev, (W - dev.width) // 2, y + 90)
    d = ImageDraw.Draw(img)
    if cue_text:
        # cue sits on a strip over the device bottom so it never fights the screen
        d.rectangle([0, H - 230, W, H], fill=bg)
        cue(d, cue_text, ink)
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{n:02d}-{name}.png")
    img.save(path, optimize=True)
    print("wrote", path)


if __name__ == "__main__":
    panel(1, "home", YELLOW, ["every rent-", "stabilized", "building"],
          "all 47,000 of them, on one map", os.path.join(RAW, "home.png"), "what's available? →")
    panel(2, "results", WHITE, ["what's for", "rent right", "now"],
          "asking rents posted in the last 5 days", os.path.join(RAW, "results.png"), "see it on the map →")
    panel(3, "map", YELLOW, ["search the", "block you", "want"],
          "prices on pins · drag, then tap search this area", os.path.join(RAW, "map.png"), "who runs it? →")
    panel(4, "detail", WHITE, ["know the", "building", "first"],
          "violations, the managing agent, typical rent", os.path.join(RAW, "detail.png"), "apply for a lottery →")
    panel(5, "hcr", YELLOW, ["lotteries &", "waitlists,", "one tap"],
          "HCR affordable housing · Section 8 buildings", os.path.join(RAW, "hcr.png"))

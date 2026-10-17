#!/usr/bin/env python3
"""Compose the App Store screenshots in the house marketing style: five iPhone
portrait panels alternating a yellow accent field and white, an oversized
lowercase headline, the real app screen in a rounded device bezel, the brand
small in the corner, and a continuation cue leading into the next panel.

Input : marketing/raw/{home,results,map,detail,lotteries}.png (1320x2868 simulator shots)
Output: marketing/asc-screenshots/0N-*.png at 1320x2868 (App Store 6.9")

    python3 scripts/make_screenshots.py
    python3 scripts/make_screenshots.py --ipad

--ipad does the same for the iPad 13" set that an iPad-capable app has to
ship (1.2.4 went universal): marketing/raw-ipad/*.png (2064x2752) ->
marketing/asc-screenshots-ipad/. The canvas is squarer than the phone's, so
the headlines are two lines there and the device sits a little smaller.
"""
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H = 1320, 2868      # rebound by --ipad
YELLOW = (255, 214, 10)
WHITE = (255, 255, 255)
INK = (18, 18, 22)
NAVY = (22, 60, 71)     # SE.navy 0x163C47, the app's teal chrome
ROYAL = (47, 122, 138)  # SE.royal 0x2F7A8A
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RAW = os.path.join(HERE, "marketing", "raw")
OUT = os.path.join(HERE, "marketing", "asc-screenshots")
S = 1.0                # type/margin scale, 1.0 on the phone canvas
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


ICON = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "FindACrib/Resources/Assets.xcassets/AppIcon.appiconset/icon-1024.png")


def brand(draw, on_yellow, canvas=None):
    # the app icon + name in the corner, as the style sheet asks
    f = font(int(44 * S), medium=True)
    ink = INK if on_yellow else NAVY
    side, x, y = int(52 * S), int(72 * S), int(88 * S)
    if canvas is not None:
        icon = Image.open(ICON).convert("RGBA").resize((side, side), Image.LANCZOS)
        m = Image.new("L", (side * 4, side * 4), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, side * 4 - 1, side * 4 - 1], radius=int(14 * S) * 4, fill=255)
        icon.putalpha(m.resize((side, side), Image.LANCZOS)); canvas.paste(icon, (x, y), icon)
    else:
        draw.rounded_rectangle([x, y, x + side, y + side], radius=int(14 * S), fill=ROYAL)
    draw.text((x + int(68 * S), y - int(4 * S)), "Find A Crib", font=f, fill=ink)


def headline(draw, lines, y, ink, size=150):
    size = int(size * S)
    margin = int(72 * S)
    # Shrink to fit rather than run off the edge: the iPad canvas is wider in
    # pixels but its headlines are longer, and "every rent-stabilized building
    # in New York" ran off the right on the first render (2026-09-23).
    f = font(size)
    while size > 40 and max(draw.textbbox((0, 0), l, font=f)[2] for l in lines) > W - 2 * margin:
        size = int(size * 0.94)
        f = font(size)
    for line in lines:
        draw.text((int(72 * S), y), line, font=f, fill=ink)
        y += int(size * 1.02)
    return y


def sub(draw, text, y, ink):
    size = int(50 * S)
    while size > 30 and draw.textbbox((0, 0), text, font=font(size, medium=True))[2] > W - int(144 * S):
        size -= 2
    draw.text((int(72 * S), y), text, font=font(size, medium=True), fill=ink)
    return y + int(70 * S)


def cue(draw, text, ink):
    f = font(int(54 * S), medium=True)
    w = draw.textbbox((0, 0), text, font=f)[2]
    draw.text((W - int(72 * S) - w, H - int(190 * S)), text, font=f, fill=ink)


def panel(n, name, bg, lines, subline, shot, cue_text=None, dev_w=980):
    on_yellow = bg == YELLOW
    ink = INK if on_yellow else NAVY
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    brand(d, on_yellow, img)
    y = headline(d, lines, int(220 * S), ink)
    y = sub(d, subline, y + int(24 * S), (60, 60, 60) if on_yellow else (74, 74, 74))
    dev = device(shot, dev_w)
    img = paste_with_shadow(img, dev, (W - dev.width) // 2, y + int(90 * S))
    d = ImageDraw.Draw(img)
    if cue_text:
        # cue sits on a strip over the device bottom so it never fights the screen
        d.rectangle([0, H - int(230 * S), W, H], fill=bg)
        cue(d, cue_text, ink)
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"{n:02d}-{name}.png")
    img.save(path, optimize=True)
    print("wrote", path)


PHONE = [
    ("home",      ["every rent-", "stabilized", "building"], "47,165 in NYC · plus LA, SF & DC",            "find your block →"),
    ("map",       ["search the", "block you", "want"],       "drag the map, then search this area",         "what does it cost? →"),
    ("results",   ["know the", "rent before", "you call"],   "estimated rents, units and open violations",  "look inside →"),
    ("detail",    ["know the", "building", "first"],         "open violations, complaints and pests",       "who runs it? →"),
    ("agent",     ["find who", "runs it"],                   "the managing agent and owner, from HPD",      "apply for a lottery →"),
    ("lotteries", ["lotteries in", "your", "boroughs"],      "Housing Connect lotteries, re-rentals & NJ",  "already have a place? →"),
    ("casa",      ["watch your", "block"],                   "311 calls on your building and crime nearby", "know your rights →"),
    ("rights",    ["know your", "rights"],                   "NYC tenant law in plain words",               "lease ending? →"),
    ("renewal",   ["plan your", "renewal"],                  "your legal increase + an email to negotiate", "something broken? →"),
    ("repair",    ["get repairs", "made"],                   "a letter to your landlord, then 311",         None),
]


def make_ipad():
    """The iPad 13" set: 2064x2752, two-line headlines, a slightly smaller device."""
    g = globals()
    g["W"], g["H"] = 2064, 2752
    g["S"] = 2064 / 1320
    g["RAW"] = os.path.join(HERE, "marketing", "raw-ipad")
    g["OUT"] = os.path.join(HERE, "marketing", "asc-screenshots-ipad")
    old = [f for f in os.listdir(OUT) if f.endswith(".png")] if os.path.isdir(OUT) else []
    for f in old:
        os.remove(os.path.join(OUT, f))
    for n, (name, lines, subline, cue_text) in enumerate(PHONE, 1):
        # Panel 1 shows the iPhone app: iMessage's App Store link card uses the
        # first iPad panel (its 3:4 shape fits the bubble), and the owner wants
        # that card to show the phone (2026-10-09). The renter tools open as a
        # small form sheet on iPad, over Profile and its signed-in name, so
        # they show the phone too (2026-10-17). The rest stay iPad.
        phone = n == 1 or name in ("rights", "renewal", "repair")
        shot = os.path.join(HERE, "marketing", "raw", f"{name}.png") if phone else os.path.join(RAW, f"{name}.png")
        panel(n, name, YELLOW if n % 2 else WHITE, two_lines(lines), subline,
              shot, cue_text, dev_w=int(W * (0.44 if phone else 0.60)))


def two_lines(lines):
    """The phone's three-line headline as two: the iPad canvas is squarer."""
    words = " ".join(lines).replace("- ", "-").split(" ")
    best = min(range(1, len(words)), key=lambda i: (abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))), -i))
    return [" ".join(words[:best]), " ".join(words[best:])]


if __name__ == "__main__":
    import sys
    if "--ipad" in sys.argv:
        make_ipad()
        raise SystemExit
    # Ten panels, one feature each (owner, 2026-10-17: "highlight 10 of our
    # best features"); raw screens from scripts/capture_marketing.sh.
    old = [f for f in os.listdir(OUT) if f.endswith(".png")] if os.path.isdir(OUT) else []
    for f in old:
        os.remove(os.path.join(OUT, f))
    for n, (name, lines, subline, cue_text) in enumerate(PHONE, 1):
        panel(n, name, YELLOW if n % 2 else WHITE, lines, subline, os.path.join(RAW, f"{name}.png"), cue_text)

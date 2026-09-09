#!/usr/bin/env python3
"""App Store "Header and Search Results" banner for Find A Crib — the
Facebook-style treatment the owner asked for on 2026-09-08: one flat brand
field, the wordmark big and white in the middle, and a few small things
floating around it (building photos in circles, a price bubble, a
rent-stabilized badge, the app mark), so it reads as the app before the
name underneath does.

Usage: ~/.venvs/spendcap/bin/python scripts/make_header.py
Writes marketing/asc-header/header-{1280x720,5244x2950}.png plus a
preview.png that mocks the App Store product page under it.
"""
import math
import os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ICON = os.path.join(ROOT, "FindACrib/Resources/Assets.xcassets/AppIcon.appiconset/icon-1024.png")
HOME = os.path.join(ROOT, "marketing/raw/home.png")       # the simulator shot with the photo collage
FONTS = os.path.join(ROOT, "FindACrib/Resources/Fonts")
OUT = os.path.join(ROOT, "marketing/asc-header")
SIZES = [(1280, 720), (5244, 2950)]

BLUE = (96, 166, 178)         # the icon's lit teal (scripts/make_icon.py CORE)
ROYAL = (40, 92, 105)         # its rim
NAVY = (22, 58, 68)
YELLOW = (255, 214, 10)
GREEN = (16, 160, 80)
WHITE = (255, 255, 255)

# Street-level photos cropped out of the home screen's collage (1320-wide
# simulator shot); insets keep the "Maps" attribution out of the circles.
PHOTOS = {
    "brownstone": (250, 615, 640, 845),
    "brick": (1118, 655, 1298, 835),
    "corner": (25, 212, 205, 392),
}


def font(name, size):
    return ImageFont.truetype(os.path.join(FONTS, f"SourceSans3-{name}.ttf"), int(size))


def gradient(w, h):
    """Bright at the top-centre, deeper royal toward the bottom corners."""
    img = Image.new("RGB", (w, h))
    px = img.load()
    cx, cy = w * 0.5, -h * 0.2
    rmax = math.hypot(w * 0.6, h * 1.2)
    for y in range(h):
        for x in range(w):
            t = min(1.0, math.hypot(x - cx, y - cy) / rmax)
            t = t * t
            px[x, y] = tuple(int(BLUE[i] + (ROYAL[i] - BLUE[i]) * t) for i in range(3))
    return img


def shadow(base, mask, pos, blur, alpha=110, dy=0.0):
    sh = Image.new("RGBA", base.size, (0, 0, 0, 0))
    layer = Image.new("RGBA", mask.size, (0, 20, 80, alpha))
    layer.putalpha(mask.point(lambda v: int(v * alpha / 255)))
    sh.alpha_composite(layer, (pos[0], pos[1] + int(dy)))
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    base.alpha_composite(sh)


def circle_photo(base, crop, center, diam, ring, s):
    src = Image.open(HOME).convert("RGB").crop(crop)
    side = min(src.size)
    src = src.crop(((src.width - side) // 2, (src.height - side) // 2,
                    (src.width - side) // 2 + side, (src.height - side) // 2 + side))
    d = int(diam)
    src = src.resize((d, d), Image.LANCZOS)
    mask = Image.new("L", (d, d), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, d - 1, d - 1], fill=255)
    x, y = int(center[0] - d / 2), int(center[1] - d / 2)
    # white ring, then the photo, with a soft shadow under both
    r = int(ring)
    ring_mask = Image.new("L", (d + 2 * r, d + 2 * r), 0)
    ImageDraw.Draw(ring_mask).ellipse([0, 0, d + 2 * r - 1, d + 2 * r - 1], fill=255)
    shadow(base, ring_mask, (x - r, y - r), int(18 * s), dy=10 * s)
    ring_img = Image.new("RGBA", ring_mask.size, WHITE + (255,))
    ring_img.putalpha(ring_mask)
    base.alpha_composite(ring_img, (x - r, y - r))
    photo = src.convert("RGBA"); photo.putalpha(mask)
    base.alpha_composite(photo, (x, y))


def rounded_tile(base, center, size, angle, s):
    """The app mark as a tilted glass tile, like the photo/video icon at the
    top-left of Facebook's banner."""
    icon = Image.open(ICON).convert("RGBA").resize((int(size), int(size)), Image.LANCZOS)
    m = Image.new("L", icon.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, icon.width - 1, icon.height - 1], radius=int(size * 0.22), fill=255)
    icon.putalpha(m)
    icon = icon.rotate(angle, resample=Image.BICUBIC, expand=True)
    x, y = int(center[0] - icon.width / 2), int(center[1] - icon.height / 2)
    shadow(base, icon.split()[3], (x, y), int(16 * s), dy=8 * s)
    base.alpha_composite(icon, (x, y))


def bubble(base, text, center, s, fill=WHITE, ink=NAVY, tail="left", pad=14, size=26, weight="Bold", dot=None):
    """A speech bubble like the hearts over the right-hand photo."""
    f = font(weight, size * s)
    d0 = ImageDraw.Draw(base)
    tw = d0.textlength(text, font=f)
    th = f.getmetrics()[0] + f.getmetrics()[1]
    extra = (th * 0.84 + 8 * s) if dot else 0
    w, h = int(tw + 2 * pad * s + extra), int(th + 1.2 * pad * s)
    layer = Image.new("RGBA", (w + int(40 * s), h + int(40 * s)), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    ox, oy = int(10 * s), int(10 * s)
    d.rounded_rectangle([ox, oy, ox + w, oy + h], radius=h // 2, fill=fill + (255,))
    # tail: a small circle just outside, then a smaller one — the cartoon cue
    if tail:
        tx = ox + (w * 0.18 if tail == "left" else w * 0.82)
        d.ellipse([tx - 9 * s, oy + h + 2 * s, tx + 9 * s, oy + h + 20 * s], fill=fill + (255,))
        d.ellipse([tx - 22 * s, oy + h + 18 * s, tx - 12 * s, oy + h + 28 * s], fill=fill + (255,))
    x, y = int(center[0] - layer.width / 2), int(center[1] - layer.height / 2)
    shadow(base, layer.split()[3], (x, y), int(12 * s), alpha=90, dy=6 * s)
    base.alpha_composite(layer, (x, y))
    d2 = ImageDraw.Draw(base)
    tx0 = x + ox + pad * s
    ty0 = y + oy + (h - th) / 2 - 1 * s
    if dot:
        # a green check disc before the text
        r = th * 0.42
        cx, cy = tx0 + r, ty0 + th / 2
        d2.ellipse([cx - r, cy - r, cx + r, cy + r], fill=dot)
        lw = max(2, int(3.2 * s))
        d2.line([(cx - r * 0.45, cy + r * 0.02), (cx - r * 0.1, cy + r * 0.4), (cx + r * 0.5, cy - r * 0.4)], fill=WHITE, width=lw, joint="curve")
        tx0 += 2 * r + 8 * s
    d2.text((tx0, ty0), text, font=f, fill=ink)


def badge_pin(base, center, s, diam=52):
    """Yellow disc with a white map pin — the cake badge on FB's photo."""
    d = int(diam * s)
    layer = Image.new("RGBA", (d + int(24 * s), d + int(24 * s)), (0, 0, 0, 0))
    dr = ImageDraw.Draw(layer)
    o = int(12 * s)
    dr.ellipse([o, o, o + d, o + d], fill=WHITE + (255,))
    ring = int(4 * s)
    dr.ellipse([o + ring, o + ring, o + d - ring, o + d - ring], fill=YELLOW + (255,))
    cx, cy = o + d / 2, o + d / 2 - d * 0.06
    r = d * 0.2
    dr.ellipse([cx - r, cy - r, cx + r, cy + r], fill=NAVY + (255,))
    dr.polygon([(cx - r * 0.85, cy + r * 0.5), (cx + r * 0.85, cy + r * 0.5), (cx, cy + r * 1.9)], fill=NAVY + (255,))
    dr.ellipse([cx - r * 0.42, cy - r * 0.42, cx + r * 0.42, cy + r * 0.42], fill=YELLOW + (255,))
    x, y = int(center[0] - layer.width / 2), int(center[1] - layer.height / 2)
    shadow(base, layer.split()[3], (x, y), int(10 * s), alpha=90, dy=5 * s)
    base.alpha_composite(layer, (x, y))


def render(w, h):
    s = h / 720.0
    base = gradient(w, h).convert("RGBA")

    # Wordmark: white, black weight, centred, ~62% of the width.
    d = ImageDraw.Draw(base)
    text = "Find A Crib"
    size = 200 * s
    f = font("Black", size)
    while d.textlength(text, font=f) > w * 0.50:
        size -= 4; f = font("Black", size)
    tw = d.textlength(text, font=f)
    asc, desc = f.getmetrics()
    tx, ty = (w - tw) / 2, h * 0.5 - (asc - desc * 0.4) / 2 - 20 * s
    # a soft glow behind the letters keeps them crisp over the gradient
    glow = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(glow).text((tx, ty), text, font=f, fill=(0, 40, 160, 120))
    base.alpha_composite(glow.filter(ImageFilter.GaussianBlur(int(22 * s))))
    ImageDraw.Draw(base).text((tx, ty), text, font=f, fill=WHITE)
    # tagline, small, under the wordmark
    tf = font("Semibold", 34 * s)
    tag = "Every rent-stabilized building in NYC"
    tw2 = ImageDraw.Draw(base).textlength(tag, font=tf)
    ImageDraw.Draw(base).text(((w - tw2) / 2, ty + asc + 14 * s), tag, font=tf, fill=(225, 234, 255))

    # Floating pieces, positions in 1280x720 space.
    rounded_tile(base, (250 * s, 150 * s), 120 * s, -10, s)                  # app mark, top-left
    circle_photo(base, PHOTOS["brownstone"], (140 * s, 520 * s), 170 * s, 6 * s, s)   # left photo
    badge_pin(base, (205 * s, 585 * s), s)                                  # yellow pin on it
    circle_photo(base, PHOTOS["brick"], (1140 * s, 470 * s), 190 * s, 6 * s, s)       # right photo
    bubble(base, "$1,850 / mo", (1060 * s, 320 * s), s, tail="left", size=28)          # price over it
    bubble(base, "Rent-stabilized", (640 * s, 625 * s), s, tail=None, size=24, dot=GREEN)   # centre badge
    circle_photo(base, PHOTOS["corner"], (1010 * s, 140 * s), 84 * s, 4 * s, s)       # small photo, top-right
    return base.convert("RGB")


def preview(banner):
    """What it looks like on the product page: banner, then the black band
    with the icon, name and subtitle the App Store draws itself."""
    w = banner.width
    band = int(w * 0.42)
    img = Image.new("RGB", (w, banner.height + band), (0, 0, 0))
    img.paste(banner, (0, 0))
    s = w / 1280.0
    icon = Image.open(ICON).convert("RGB").resize((int(200 * s), int(200 * s)), Image.LANCZOS)
    m = Image.new("L", icon.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, icon.width - 1, icon.height - 1], radius=int(44 * s), fill=255)
    img.paste(icon, (int(50 * s), banner.height + int(60 * s)), m)
    d = ImageDraw.Draw(img)
    d.text((int(290 * s), banner.height + int(70 * s)), "Find A Crib", font=font("Bold", 54 * s), fill=WHITE)
    d.text((int(290 * s), banner.height + int(140 * s)), "Every rent-stabilized building in NYC", font=font("Regular", 34 * s), fill=(150, 150, 155))
    return img


def main():
    os.makedirs(OUT, exist_ok=True)
    small = None
    for (w, h) in SIZES:
        img = render(w, h)
        p = os.path.join(OUT, f"header-{w}x{h}.png")
        img.save(p)
        print("wrote", p, img.size)
        small = small or img
    preview(small).save(os.path.join(OUT, "preview.png"))
    print("wrote", os.path.join(OUT, "preview.png"))


if __name__ == "__main__":
    main()

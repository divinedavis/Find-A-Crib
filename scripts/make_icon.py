#!/usr/bin/env python3
"""The Find A Crib app icon and every size of it, from one drawing.

Design (asked 2026-09-09, from a reference icon the owner sent): a teal
rounded square with a soft radial light in the middle, and a glossy white,
slightly embossed glyph — here a row of three homes, the tall one in the
middle, read as "many cribs". The glyph gets a top-to-bottom sheen, a hairline
bevel and a soft shadow so it sits on the field the way the reference's letter
does. The homes are one silhouette so the mark still reads at 16px.

    ~/.venvs/dhcr-map/bin/python scripts/make_icon.py

Writes:
  ios/FindACrib/Resources/Assets.xcassets/AppIcon.appiconset/icon-1024.png
      (opaque, square — iOS rounds the corners itself)
  icon-512.png icon-192.png favicon-32.png favicon.ico   (rounded, transparent corners)
  apple-touch-icon.png (180, opaque square, iOS masks it)
  brand/mark.svg  (the same drawing as vector, for the site header)
"""
import math, os
from PIL import Image, ImageDraw, ImageFilter, ImageChops

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IOS_ICON = os.path.join(ROOT, "ios/FindACrib/Resources/Assets.xcassets/AppIcon.appiconset/icon-1024.png")

# Teal field: darker rim, lit centre (sampled off the reference)
RIM = (30, 76, 88)
MID = (56, 122, 136)
CORE = (86, 158, 170)
# Glyph
GLYPH_TOP = (255, 255, 255)
GLYPH_BOT = (226, 236, 238)
BEVEL = (168, 196, 204)     # inner bottom-edge shade only
SHADOW = (14, 44, 54)

S = 1024                      # master size; everything else is a resample
SS = 4                        # supersample for the vector-ish edges


def field(size):
    """Radial teal gradient, slightly brighter above centre like the reference."""
    img = Image.new("RGB", (size, size))
    px = img.load()
    cx, cy = size * 0.5, size * 0.44
    rmax = size * 0.78
    for y in range(size):
        for x in range(size):
            t = min(1.0, math.hypot(x - cx, y - cy) / rmax)
            # ease: hold the core, then fall to the rim
            if t < 0.35:
                k = t / 0.35; a, b = CORE, MID
            else:
                k = (t - 0.35) / 0.65; a, b = MID, RIM
            k = k * k * (3 - 2 * k)
            px[x, y] = tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))
    return img


def homes(size):
    """The glyph as one polygon list in a `size` square: three homes, tall one centred."""
    u = size / 1024
    def P(*pts): return [(x * u, y * u) for x, y in pts]
    base = 760
    centre = P((388, 470), (512, 316), (636, 470), (636, base), (388, base))
    left = P((228, 566), (330, 440), (432, 566), (432, base), (228, base))
    right = P((592, 546), (700, 412), (808, 546), (808, base), (592, base))
    door = P((480, base), (544, base), (544, 664), (480, 664))     # cut out of the centre home
    return [left, right, centre], door


def glyph_mask(size):
    m = Image.new("L", (size * SS, size * SS), 0)
    d = ImageDraw.Draw(m)
    polys, door = homes(size * SS)
    for p in polys: d.polygon(p, fill=255)
    # round the door top
    x0, y0 = door[3]; x1, y1 = door[1]
    d.rectangle([x0, y0, x1, y1], fill=0)
    d.ellipse([x0, y0 - (x1 - x0) / 2, x1, y0 + (x1 - x0) / 2], fill=0)
    return m.resize((size, size), Image.LANCZOS)


def render(size=S):
    img = field(size).convert("RGBA")
    mask = glyph_mask(size)
    u = size / 1024
    # a crisp, close shadow under the glyph (a wide one blurred the edge)
    sh = Image.new("RGBA", (size, size), SHADOW + (0,))
    sh.putalpha(mask.point(lambda v: int(v * 0.5)))
    sh = sh.filter(ImageFilter.GaussianBlur(6 * u))
    sh = ImageChops.offset(sh, 0, int(12 * u))
    img.alpha_composite(sh)
    # the glyph: full mask, pure white edge, a gentle sheen toward the bottom
    sheen = Image.new("RGBA", (size, size))
    sp = sheen.load()
    for y in range(size):
        t = y / size
        t = min(1.0, max(0.0, (t - 0.30) / 0.48))
        c = tuple(int(GLYPH_TOP[i] + (GLYPH_BOT[i] - GLYPH_TOP[i]) * t) for i in range(3))
        for x in range(size): sp[x, y] = c + (255,)
    sheen.putalpha(mask)
    img.alpha_composite(sheen)
    # emboss, inside the shape: a hairline shade along the bottom edges and a
    # light catch along the top edges — the edge itself stays white
    inner = mask.filter(ImageFilter.MinFilter(3))
    bottom = ImageChops.subtract(inner, ImageChops.offset(inner, 0, -int(9 * u)))
    sd = Image.new("RGBA", (size, size), BEVEL + (0,)); sd.putalpha(bottom.filter(ImageFilter.GaussianBlur(2 * u)).point(lambda v: int(v * 0.9)))
    img.alpha_composite(sd)
    hl = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    top = ImageChops.subtract(inner, ImageChops.offset(inner, 0, int(9 * u)))
    hl.putalpha(top)
    img.alpha_composite(hl)
    return img


def rounded(img, radius_frac=0.2237):
    """Apple's continuous-corner look, near enough: a rounded-rect alpha mask."""
    size = img.size[0]
    m = Image.new("L", (size * SS, size * SS), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size * SS - 1, size * SS - 1], radius=int(size * SS * radius_frac), fill=255)
    out = img.copy(); out.putalpha(m.resize((size, size), Image.LANCZOS))
    return out


def svg():
    polys, door = homes(1024)
    def pts(p): return " ".join(f"{x:.0f},{y:.0f}" for x, y in p)
    x0, y0 = door[3]; x1, y1 = door[1]; r = (x1 - x0) / 2
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" width="1024" height="1024">
  <defs>
    <radialGradient id="f" cx="50%" cy="44%" r="78%">
      <stop offset="0" stop-color="rgb{CORE}"/><stop offset=".35" stop-color="rgb{MID}"/><stop offset="1" stop-color="rgb{RIM}"/>
    </radialGradient>
    <linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
      <stop offset=".30" stop-color="rgb{GLYPH_TOP}"/><stop offset=".78" stop-color="rgb{GLYPH_BOT}"/>
    </linearGradient>
    <filter id="s" x="-20%" y="-20%" width="140%" height="140%"><feDropShadow dx="0" dy="14" stdDeviation="9" flood-color="rgb{SHADOW}" flood-opacity=".5"/></filter>
    <clipPath id="c"><rect width="1024" height="1024" rx="229"/></clipPath>
    <mask id="m"><rect width="1024" height="1024" fill="#fff"/><rect x="{x0:.0f}" y="{y0:.0f}" width="{x1 - x0:.0f}" height="{y1 - y0:.0f}" fill="#000"/><circle cx="{(x0 + x1) / 2:.0f}" cy="{y0:.0f}" r="{r:.0f}" fill="#000"/></mask>
  </defs>
  <g clip-path="url(#c)">
    <rect width="1024" height="1024" fill="url(#f)"/>
    <g mask="url(#m)" filter="url(#s)" fill="url(#g)">
      {"".join(f'<polygon points="{pts(p)}"/>' for p in polys)}
    </g>
  </g>
</svg>
'''


if __name__ == "__main__":
    out_dir = os.environ.get("ICON_OUT", ROOT)
    master = render(S)
    os.makedirs(os.path.dirname(IOS_ICON), exist_ok=True) if out_dir == ROOT else None
    ios_path = IOS_ICON if out_dir == ROOT else os.path.join(out_dir, "icon-1024.png")
    master.convert("RGB").save(ios_path, optimize=True)
    for name, size in (("icon-512.png", 512), ("icon-192.png", 192), ("favicon-32.png", 32)):
        rounded(master.resize((size, size), Image.LANCZOS)).save(os.path.join(out_dir, name), optimize=True)
    master.resize((180, 180), Image.LANCZOS).convert("RGB").save(os.path.join(out_dir, "apple-touch-icon.png"), optimize=True)
    rounded(master.resize((48, 48), Image.LANCZOS)).save(os.path.join(out_dir, "favicon.ico"), sizes=[(16, 16), (32, 32), (48, 48)])
    os.makedirs(os.path.join(out_dir, "brand"), exist_ok=True)
    with open(os.path.join(out_dir, "brand", "mark.svg"), "w") as f: f.write(svg())
    # preview: icon at three sizes on the two grounds it lives on
    prev = Image.new("RGB", (1024 + 60 + 256 + 40 + 64 + 40 + 32 + 60, 1100), (245, 245, 245))
    prev.paste(rounded(master), (30, 30), rounded(master))
    x = 1024 + 60
    for s_ in (256, 64, 32):
        im = rounded(master.resize((s_, s_), Image.LANCZOS)); prev.paste(im, (x, 30), im); x += s_ + 40
    prev.save(os.path.join(out_dir, "brand", "icon-preview.png"))
    print("wrote", ios_path, "and the web sizes into", out_dir)

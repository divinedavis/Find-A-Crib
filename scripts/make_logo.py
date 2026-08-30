#!/usr/bin/env python3
"""Generate the "Find a Crib" search-bar wordmark into brand/.

The concept: the standalone word "a" is not set in type at all — it is drawn as
a search field. Its left end is the bowl of the a (with the magnifier sitting in
it), the bar is the stretched counter, and the heavy right terminal is the a's
stem. "Find" and "Crib" stay in Oxanium 800, the face the site header already
self-hosts, so the mark and the running wordmark are the same typeface.

Everything is emitted as outlines — no font dependency in the SVG — by pulling
the glyph contours straight out of fonts/oxanium-800.woff2 (Oxanium, OFL 1.1).

    python3 scripts/make_logo.py            # writes brand/*.svg

Font units: 1000/em, baseline y=0, x-height 532, cap height 690. The SVG is
emitted in those units under a flip transform so every number below can be read
against the font's own metrics.
"""
import os
from fontTools.ttLib import TTFont
from fontTools.pens.svgPathPen import SVGPathPen

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT = os.path.join(ROOT, "fonts", "oxanium-800.woff2")
OUT = os.path.join(ROOT, "brand")

UPEM, XH, CAP = 1000, 532, 690
STEM = 167          # Oxanium 800 stem width, measured off the 'i'
BAR_STROKE = 116    # the search field's outline: lighter than a stem on purpose
INK = "#0a0a23"
BLUE = "#006aff"

_font = TTFont(FONT)
_gs = _font.getGlyphSet()
_cmap = _font.getBestCmap()


def word(text, x):
    """Outline `text` starting at pen position x. Returns (path_data, advance)."""
    d, pen_x = [], x
    for ch in text:
        g = _cmap[ord(ch)]
        pen = SVGPathPen(_gs)
        _gs[g].draw(pen)
        seg = pen.getCommands()
        if seg:
            d.append(f'<path transform="translate({pen_x},0)" d="{seg}"/>')
        pen_x += _gs[g].width
    return "".join(d), pen_x - x


def search_a(x, bar_len, stem=True):
    """The search-field 'a', drawn from x, sitting on the baseline at x-height.

    Left end: a semicircular bowl, the same move a lowercase a makes. Right end:
    either a flat full-weight stem (stem=True — this is what makes the shape
    read as an 'a' rather than as a floating UI chip) or a second round cap
    (stem=False), which is prettier but reads as a pure pill.
    """
    h, r, s = XH, XH / 2, BAR_STROKE
    ir = r - s                            # inner bowl radius
    x0, x1 = x, x + bar_len
    if stem:
        outer = (f"M{x0+r},0 H{x1} V{h} H{x0+r} A{r},{r} 0 0 1 {x0+r},0 Z")
        inner = (f"M{x1-STEM},{s} H{x0+s+ir} A{ir},{ir} 0 0 0 {x0+s+ir},{h-s} "
                 f"H{x1-STEM} Z")
    else:
        outer = (f"M{x0+r},0 H{x1-r} A{r},{r} 0 0 1 {x1-r},{h} H{x0+r} "
                 f"A{r},{r} 0 0 1 {x0+r},0 Z")
        inner = (f"M{x0+s+ir},{s} A{ir},{ir} 0 0 0 {x0+s+ir},{h-s} H{x1-s-ir} "
                 f"A{ir},{ir} 0 0 0 {x1-s-ir},{s} Z")
    # One <path> with evenodd rather than a stroked rect: the outline then
    # survives any scale and any SVG-to-outline export untouched.
    return f'<path fill-rule="evenodd" d="{outer} {inner}"/>', bar_len


def magnifier(cx, cy, r, sw, tail):
    """Lens + handle, drawn as strokes so the weight is independent of scale."""
    hx = 0.7071 * (r + sw / 2)
    return (f'<g fill="none" stroke-width="{sw}" stroke-linecap="round">'
            f'<circle cx="{cx}" cy="{cy}" r="{r}"/>'
            f'<path d="M{cx+hx},{cy-hx} L{cx+hx+tail},{cy-hx-tail}"/>'
            f"</g>")


def wordmark(bar_len=980, gap=90, stem=True, ink=INK, blue=BLUE, pad=60):
    """Full 'Find a Crib' lockup. Returns (svg, width, height) in font units."""
    body = []
    x = 0
    d, adv = word("Find", x); body.append((ink, d)); x += adv + gap
    bar_x = x
    d, adv = search_a(x, bar_len, stem); body.append((blue, d)); x += adv + gap
    d, adv = word("Crib", x); body.append((ink, d)); x += adv

    # The lens rides in the left bowl, on the pill's centre line.
    # Concentric with the bowl — the lens and the bowl share a centre, which is
    # what stops the mark reading as an icon dropped into a box.
    body.append((blue, magnifier(bar_x + XH / 2, XH / 2, 80, 44, 46)))

    top = CAP + 26          # 'F'/'C' cap height, plus a hair of optical room
    w, h = x + 2 * pad, top + 2 * pad
    g = "".join(f'<g fill="{c}" stroke="{c}" stroke-width="0">{d}</g>' for c, d in body)
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
           f'width="{w}" height="{h}" role="img" aria-label="Find a Crib">'
           f'<g transform="translate({pad},{h-pad}) scale(1,-1)">{g}</g></svg>')
    return svg, w, h


def icon(size=512, ink=INK, blue=BLUE, bg=None):
    """Square mark: the search-bar 'a' alone, for the favicon and app icon."""
    bar_len, pad = 700, 96
    d, _ = search_a(0, bar_len, stem=True)
    lens = magnifier(XH / 2, XH / 2, 80, 44, 46)
    box = bar_len + 2 * pad
    y0 = (box - XH) / 2
    plate = (f'<rect width="{box}" height="{box}" rx="{box*0.22}" fill="{bg}"/>'
             if bg else "")
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {box} {box}" '
            f'width="{size}" height="{size}" role="img" aria-label="Find a Crib">'
            f'{plate}<g transform="translate({pad},{box-y0}) scale(1,-1)" '
            f'fill="{blue}" stroke="{blue}" stroke-width="0">{d}{lens}</g></svg>')


VARIANTS = {
    # A — faithful to the reference: a long bar that stretches the wordmark.
    "wordmark-wide":    dict(bar_len=1180, gap=90,  stem=True),
    # B — header-safe: short enough to stay legible at 22px.
    "wordmark-compact": dict(bar_len=820,  gap=80,  stem=True),
    # C — pure pill, no thickened stem, for comparison.
    "wordmark-pill":    dict(bar_len=1180, gap=90,  stem=False),
}

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    made = []
    for name, kw in VARIANTS.items():
        for theme, ink in (("", INK), ("-dark", "#eef0f6")):
            blue = BLUE if not theme else "#5b9bff"
            svg, w, h = wordmark(ink=ink, blue=blue, **kw)
            p = os.path.join(OUT, f"{name}{theme}.svg")
            open(p, "w").write(svg)
            made.append((os.path.basename(p), f"{w}x{h}"))
    for nm, bg, blue, ink in (("icon", None, BLUE, INK),
                              ("icon-plate", BLUE, "#ffffff", "#ffffff")):
        p = os.path.join(OUT, f"{nm}.svg")
        open(p, "w").write(icon(bg=bg, blue=blue, ink=ink))
        made.append((os.path.basename(p), "square"))
    for nm, dim in made:
        print(f"  wrote brand/{nm}  ({dim})")

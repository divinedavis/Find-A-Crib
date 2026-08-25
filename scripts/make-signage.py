#!/usr/bin/env python3
"""Etch-ready artwork for the Find A Crib counter piece.

    python3 scripts/make-signage.py

Writes into marketing/signage/:

  findacrib-counter-4x6-engrave.{svg,pdf,png}   the 4x6 plate: flat line art,
                                                black = engrave, red hairline
                                                = cut path
  findacrib-counter-base.{svg,pdf,png}          the foot it stands in, cut only

One artwork file, several materials. It is deliberately material-agnostic
because the constraint that actually matters is not what the plate is made of:

  THE CODE MUST COME OUT DARK ON LIGHT.  Scanning algorithms look for dark
  modules on a light field. Inverted codes -- a bright mark on a dark plate --
  are read by recent iPhones and missed by older Android cameras and older
  Google Lens versions, and those are disproportionately the phones the people
  this site is for are holding. So two-ply ordered white-cap-over-black-core
  works, laser-annealed stainless works, aluminium engraved and black-filled
  works, and black anodised aluminium -- the one every vendor suggests, because
  it photographs beautifully -- does not, permanently. Everything in the README
  is a consequence of this one line.

Why generated rather than drawn once in a design tool:

  * The URL is the whole point of the object and the one thing that must never
    be wrong. Encoding the code from the same string printed underneath it
    removes the class of mistake where the caption says one address and the
    code goes somewhere else.
  * A QR code cannot be edited. Nudging a module in a design tool destroys it
    silently, and the damage only surfaces when a stranger's phone fails on a
    counter you cannot get back to.

Three decisions worth keeping:

  ERROR CORRECTION IS 'H'.  The URL is short enough that the highest level
  still fits a 29-module version-3 code, so the robustness costs nothing. A
  third of the code can be lost to a thumbprint, a coffee ring, a strip of
  tape or a scratch and it still reads.

  NO FLOOD FILLS.  On two-ply the laser removes the cap layer wherever the art
  is black, so a solid header band is not a colour choice, it is minutes of
  machine time per piece and enough heat to bow a 1/16in sheet. The layout
  carries its structure as line work.

  NO LOGO NEAR THE CODE.  Concentric squares read to a scanner as a QR finder
  pattern. Measured, not assumed -- see mark().

Every render is decoded again at falling resolution before the build is
allowed to succeed, because looking at a QR proves nothing and decoding it
once at 300dpi proves little more.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import tempfile

import segno

PT = 72.0            # points per inch; SVG user units throughout, so PDF is exact
BLEED = 0.125 * PT   # 9pt. Every printer asks for it, none complain about it.

BLUE = "#006AFF"
BLUE_DEEP = "#0052CC"
BLUE_SOFT = "#E8F0FE"
INK = "#0A0A23"
MUTED = "#4A4A68"
WHITE = "#FFFFFF"
BLACK = "#000000"
# Cut-line colour, and it is not cosmetic: it is the instruction. A red
# hairline is the common US laser-shop convention for "cut through" (it is what
# the Epilog and Universal drivers key on), and it is what Laser-CutZ and most
# local shops expect.
#
# PONOKO INVERTS IT. There, blue stroke = cut and RED stroke = line engrave, so
# shipping the red file to Ponoko would engrave a rectangle onto the plate and
# never cut it out. Hence two variants of every cut file rather than one and a
# note nobody reads at the moment of upload.
CUT = "#FF0000"
CUT_PONOKO = "#0000FF"
CUT_W = 0.072        # 0.001in

FONT = "Helvetica Neue, Helvetica, Arial, sans-serif"

# The number is printed on a permanent object, so it is the real row count of
# the dataset the site ships, rounded DOWN to the nearest thousand. Rounding up
# would put a claim on a counter that the map cannot back.
BUILDINGS = "47,000"

OUT = pathlib.Path(__file__).resolve().parent.parent / "marketing" / "signage"


# --------------------------------------------------------------------------
# drawing primitives
# --------------------------------------------------------------------------
def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x, y, s, size, *, fill=INK, weight=400, anchor="middle", spacing=0.0):
    return (
        f'<text x="{x:.2f}" y="{y:.2f}" font-family="{FONT}" font-size="{size:.2f}" '
        f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" '
        f'letter-spacing="{spacing:.2f}">{esc(s)}</text>'
    )


def rect(x, y, w, h, *, fill="none", rx=0.0, stroke=None, sw=1.0):
    s = f' stroke="{stroke}" stroke-width="{sw:.3f}"' if stroke else ""
    return (f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" '
            f'rx="{rx:.2f}" fill="{fill}"{s}/>')


def diamond(cx, cy, half, *, fill="none", stroke=None, sw=1.0):
    s = f' stroke="{stroke}" stroke-width="{sw:.2f}" stroke-linejoin="round"' if stroke else ""
    return (f'<path d="M{cx:.2f},{cy - half:.2f} L{cx + half:.2f},{cy:.2f} '
            f'L{cx:.2f},{cy + half:.2f} L{cx - half:.2f},{cy:.2f} Z" fill="{fill}"{s}/>')


def mark(cx: float, cy: float, size: float, *, outline: bool) -> str:
    """The app mark, as a diamond ring.

    The shipped icon is that ring inside a blue rounded square, but the square
    is dropped in both renderings here and for different reasons. On the print
    card the mark sits ON the blue header, so the square would be blue on blue
    — drawing it would only mean that changing the header colour later makes a
    stray square appear. On the engrave plate it is worse than invisible; see
    the note under `outline`.
    """
    if not outline:
        sw = max(size * 0.075, 1.4)
        return (diamond(cx, cy, size * 0.42, stroke=WHITE, sw=sw)
                + diamond(cx, cy, size * 0.18, fill=WHITE))
    # No bounding square here either, and this one is measured.
    #
    # The square is not a style choice here, it is a decoy finder pattern. A
    # QR's three corner targets are concentric squares, and an outlined rounded
    # square with a shape centred inside it is the same signal: the detector
    # spends its search on the logo. Measured, not guessed — with the square in
    # the header this plate stopped decoding below 80dpi; with only the diamond
    # ring it holds to 25dpi, a 3x margin for the same ink. A diamond is a
    # square rotated 45 degrees and does not trip the same search.
    #
    sw = max(size * 0.075, 1.4)
    return (
        diamond(cx, cy, size * 0.42, stroke=BLACK, sw=sw)
        + diamond(cx, cy, size * 0.18, fill=BLACK)
    )


def mark_icon(cx: float, cy: float, size: float) -> str:
    """The app icon as it actually ships: blue square, white ring, blue centre.

    Only the printed card uses this. It is a solid mark rather than the
    outlined one, which is the whole reason it is allowed near a code: the
    finder-pattern problem that cost the engrave plate two thirds of its scan
    margin comes from CONCENTRIC OUTLINES, and filled shapes do not trip the
    same search. Measured on the earlier colour card at 35dpi page floor
    against 30dpi for its bare code — a rounding error. The decode sweep at
    the end of the build is what actually holds this to account.
    """
    h = size / 2
    return (rect(cx - h, cy - h, size, size, fill=BLUE, rx=size * 0.22)
            + diamond(cx, cy, size * 0.34, fill=WHITE)
            + diamond(cx, cy, size * 0.16, fill=BLUE))


QUIET_MODULES = 4  # the spec minimum, and the thing an eye never catches


def check_quiet(name: str, gap: float, module: float) -> None:
    """Refuse to write artwork whose code is boxed in too tightly.

    A short quiet zone is the one defect that survives every human review. The
    code looks perfect, decodes on the designer's phone held an inch away in
    good light, and fails on a dim counter against a printed edge. Asserting it
    here means a later nudge to the layout breaks the build rather than a
    hundred engraved pieces.
    """
    have = gap / module
    if have < QUIET_MODULES - 0.01:
        raise SystemExit(
            f"{name}: quiet zone is {have:.2f} modules, needs {QUIET_MODULES}. "
            f"Give the code {QUIET_MODULES * module:.1f}pt of clear space, or shrink it."
        )


# A code below about 3/4in stops being reliable at the arm's length somebody
# actually holds a phone at over a counter. Asserted rather than trusted to the
# eye, because the layout is the thing most likely to be nudged later.
MIN_QR_IN = 0.75


def qr(url: str, cx: float, top: float, size: float) -> tuple[str, float, int]:
    """One <path>, one module per subpath, snapped to a whole-unit grid.

    Drawn as a single filled path rather than a grid of <rect>s so no renderer
    can leave hairline seams between neighbouring modules — the artefact that
    turns a valid code into an unreadable one at print resolution, and that a
    laser reproduces faithfully as a gap in the cap layer.
    """
    if size / PT < MIN_QR_IN - 0.001:
        raise SystemExit(f"QR is {size / PT:.2f}in, below the {MIN_QR_IN}in floor.")
    code = segno.make(url, error="h", micro=False)
    m = size / len(code.matrix)
    parts = []
    for r, row in enumerate(code.matrix):
        for c, on in enumerate(row):
            if on:
                x = cx - size / 2 + c * m
                y = top + r * m
                parts.append(f"M{x:.3f},{y:.3f}h{m:.3f}v{m:.3f}h-{m:.3f}z")
    path = f'<path d="{"".join(parts)}" fill="{BLACK}" shape-rendering="crispEdges"/>'
    return path, m, len(code.matrix)


def svg(w: float, h: float, body: str, title: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w / PT:.4f}in" '
        f'height="{h / PT:.4f}in" viewBox="0 0 {w:.2f} {h:.2f}">\n'
        f'<title>{esc(title)}</title>\n{body}\n</svg>\n'
    )


# --------------------------------------------------------------------------
# the piece, twice
# --------------------------------------------------------------------------
# The two questions a plate can ask, keyed by the letter that starts its code.
# A plate coded a3 asks question A and redirects through findacrib.com/c/a3, so
# the dashboard can separate the two without a registry: the arm is the first
# character of the tag. Both questions are true and both are answered by this
# site; what differs is who is standing at the counter. A talks to somebody who
# already has a landlord, which in a laundromat is everybody. B talks to
# somebody mid-move, which is a few percent of most rooms and nearly all of a
# self-storage lobby.
ARMS = {
    "a": ("Is your building", "rent-stabilized?"),
    "b": ("Find rent-stabilized", "apartments"),
}

# Largest headline the plate is drawn at, and the ink margin the longest line
# must leave on each side. The size is a CEILING, not a constant: "Find
# rent-stabilized" is four characters longer than "Is your building" and
# overruns a 4in plate at 27pt. Silently, too — SVG text does not wrap or
# complain, it just walks off the artboard, and the first anyone would know is
# a box of plates with a clipped word on them.
HEAD_MAX = 27.0
HEAD_MARGIN_IN = 0.30


def ink_width_in(line: str, size: float, weight: int, spacing: float) -> float:
    """Width of one line's actual ink, in inches, measured off a render.

    Measured rather than estimated from an advance-width table, and measured
    with rsvg-convert specifically, because that is the renderer that produces
    the proof the shop is sent — a table would be describing a font this
    pipeline may not even be resolving to. Falls back to a deliberately
    pessimistic estimate when the imaging libraries are absent, so a machine
    without them under-fills the plate instead of overrunning it.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return len(line) * 0.62 * size / PT
    w, h = 8 * PT, 2 * size
    body = text(4 * PT, 1.4 * size, line, size, fill=BLACK,
                weight=weight, spacing=spacing)
    with tempfile.TemporaryDirectory() as td:
        svg_p = pathlib.Path(td) / "m.svg"
        png_p = pathlib.Path(td) / "m.png"
        svg_p.write_text(svg(w, h, body, "measure"))
        subprocess.run(["rsvg-convert", "-f", "png", "--dpi-x", "150",
                        "--dpi-y", "150", "-o", str(png_p), str(svg_p)],
                       check=True)
        img = cv2.imread(str(png_p), cv2.IMREAD_UNCHANGED)
        if img is None:
            return len(line) * 0.62 * size / PT
        if img.shape[2] == 4:
            a = img[:, :, 3:4] / 255.0
            img = (img[:, :, :3] * a + 255 * (1 - a)).astype(np.uint8)
        dark = (img.min(axis=2) < 128)
        cols = np.where(dark.any(axis=0))[0]
        if not len(cols):
            return 0.0
        return float(cols[-1] - cols[0] + 1) / 150.0


def fit_head(lines, plate_w: float, spacing: float) -> float:
    """The largest size at or below HEAD_MAX where every line still fits.

    Steps down in whole points rather than solving for a size, because the
    number ends up printed on a permanent object and a round one is easier to
    check against a physical sample with a ruler.
    """
    avail = plate_w / PT - 2 * HEAD_MARGIN_IN
    size = HEAD_MAX
    while size > 12:
        if all(ink_width_in(l, size, 700, spacing) <= avail for l in lines):
            return size
        size -= 1.0
    raise SystemExit(f"headline {lines!r} will not fit a {plate_w / PT:.0f}in plate")


def counter_plate(url: str, shown: str, lines=None,
                  cut: str = CUT) -> tuple[str, float, float, dict]:
    """4 x 6in plate: one question and the code that answers it.

    Everything else came off — the wordmark, the supporting line, the "scan
    me" caption, the printed URL. What is left is the only two things the
    object has to do at counter distance: ask something the person standing
    there wants answered, and give them the way to answer it.

    The subtraction is not only tidier, it is functional. The code went from
    2.33in to 3.00in wide across the same plate, which is the single biggest
    lever on whether this reads from across a counter rather than from over
    it, and on a two-ply plate the removed text is also engraving time off
    every piece.

    One thing genuinely lost: with the URL gone there is no fallback for
    somebody who cannot or will not scan. That is a real trade and it is the
    reason the question is doing all the work — it has to be worth pulling a
    phone out for on its own.

    No bleed: paper is printed oversize and trimmed into the art, but a laser
    cuts to a line, so the canvas IS the finished size and the cut path sits
    on it.
    """
    w, h = 4 * PT, 6 * PT
    cx = w / 2
    r = 10.0
    # White field = the untouched cap layer. Drawn rather than left implicit so
    # the PNG proof shows the finished piece and not a transparent
    # checkerboard that could hide a stray mark.
    b = [rect(0, 0, w, h, fill=WHITE, rx=r)]

    lines = lines or ARMS["a"]
    head = fit_head(lines, w, -0.7)
    b.append(text(cx, 86, lines[0], head, fill=BLACK, weight=700, spacing=-0.7))
    b.append(text(cx, 118, lines[1], head, fill=BLACK, weight=700, spacing=-0.7))

    side = 216.0
    top = 168.0
    code, module, n = qr(url, cx, top, side)
    # Measured against the nearest ink on every side. Cap height is ~0.72 of
    # the point size for this family, so the descender-free baseline at 118
    # is not the bottom of the headline's ink — but the CAP of the line above
    # is what encroaches, and here the gap is measured from the baseline,
    # which is the conservative direction.
    check_quiet("plate, above code", top - 118.0, module)
    check_quiet("plate, beside code", (w - side) / 2, module)
    check_quiet("plate, below code", h - (top + side), module)
    b.append(code)

    # Cut path last so it sits on top of everything in a shop's viewer.
    b.append(rect(0, 0, w, h, rx=r, stroke=cut, sw=CUT_W))
    meta = {"trim": "4 x 6 in", "bleed": "none (cut to line)",
            "canvas": f"{w / PT:.3f} x {h / PT:.3f} in", "head": head,
            "qr_in": side / PT, "quiet": (top - 118.0) / module, "modules": n}
    return "\n".join(b), w, h, meta


def card_black(url: str, shown: str, lines) -> tuple[str, float, float, dict]:
    """4 x 4in black card for a UV-printed acrylic counter stand.

    Square and 4in because that is the size the L-shaped NFC stands these are
    modelled on actually come in, and because a square face is what a folded
    or L-foot stand gives you.

    THE CARD IS BLACK AND THE CODE IS NOT. The QR sits on a white tile, which
    is not a design flourish — it is the entire reason a black card is allowed
    to exist here. A code printed white-on-black is an inverted code: recent
    iPhones read them, older Android cameras and older Google Lens do not, and
    those are disproportionately the phones this is aimed at. Every product
    this is modelled on does the same thing, and it is the one part of the
    look that cannot be copied by eye.

    UV printed rather than engraved, so this file is allowed the flood fill
    that the two-ply artwork is not: on acrylic the black is ink, not an hour
    of laser time.
    """
    w = h = 4 * PT
    cx = w / 2
    b = [rect(0, 0, w, h, fill=BLACK)]

    # Logo lockup, centred as a lockup rather than as two centred things.
    b.append(mark_icon(cx - 54, 30, 26))
    b.append(text(cx - 36, 39, "Find A Crib", 20, fill=WHITE, weight=700,
                  anchor="start", spacing=-0.5))

    b.append(text(cx, 78, lines[0], 17, fill=WHITE, weight=700, spacing=-0.4))
    b.append(text(cx, 99, lines[1], 17, fill=WHITE, weight=700, spacing=-0.4))

    # The white tile. Its margin around the code IS the quiet zone, so it is
    # measured rather than eyeballed — a tile drawn tight to the code is a
    # black card pressing straight up against the finder patterns.
    # Sized so the tile clears the bottom edge by about the margin the logo
    # keeps at the top — the first cut hung it 14pt off the bottom against
    # 21pt at the top, which reads as the card slipping downward.
    panel = 156.0
    px, py = cx - panel / 2, 110.0
    b.append(rect(px, py, panel, panel, fill=WHITE, rx=13))
    side = 122.0
    code, module, n = qr(url, cx, py + (panel - side) / 2, side)
    check_quiet("black card", (panel - side) / 2, module)
    b.append(code)

    meta = {"trim": "4 x 4 in", "bleed": "none",
            "canvas": f"{w / PT:.3f} x {h / PT:.3f} in",
            "qr_in": side / PT, "quiet": ((panel - side) / 2) / module,
            "modules": n, "head": 17}
    return "\n".join(b), w, h, meta


# Plate thickness the base is cut to hold. 1/16in is the standard two-ply
# gauge; change both together or the slot stops gripping.
PLATE_T = 0.0625 * PT

# A laser removes material, so a slot cut on a 1/16in line comes out WIDER
# than 1/16in and the plate rattles. Drawing it undersize by roughly one kerf
# lets the cut open up to a friction fit. Kerf varies by machine and stock,
# which is why this is a named number the shop can move rather than a
# tolerance buried in a path.
KERF = 0.007 * PT


def base_bar(cut: str = CUT) -> tuple[str, float, float, dict]:
    """Cut file for the foot the plate stands in.

    A 4x6 plate on its own is not a counter display, it is a coaster: flat
    stock cannot be bent, so the piece has to be stood up by something. This
    is the something — a bar with a through-slot, the same construction as
    every engraved desk nameplate.

    Cut from 1/4in stock, NOT from the 1/16in two-ply the plate is cut from.
    The weight is the entire point. A foot in the same gauge as the plate
    weighs nothing and goes over the first time somebody puts a bag on the
    counter, which on the counters this is going on is the same afternoon.

    Cut only — nothing here is engraved.
    """
    w, h = 5.0 * PT, 1.75 * PT
    r = 0.1 * PT
    slot_w = PLATE_T - KERF
    slot_l = 4.02 * PT              # plate is 4.00in; the 0.02 is clearance
    sx, sy = (w - slot_l) / 2, 0.62 * PT
    b = [
        rect(0, 0, w, h, rx=r, stroke=cut, sw=CUT_W),
        rect(sx, sy, slot_l, slot_w, rx=slot_w / 2, stroke=cut, sw=CUT_W),
    ]
    meta = {"stock": "1/4 in", "size": f"{w / PT:.2f} x {h / PT:.2f} in",
            "slot": f"{slot_l / PT:.2f} x {slot_w / PT:.4f} in"}
    return "\n".join(b), w, h, meta


README = """Find A Crib — etched counter piece
=========================================

Generated by `scripts/make-signage.py`. **Edit the script, never these files.**
Nudging a QR module in a design tool destroys the code invisibly.

TWO QUESTIONS, ONE PLATE PER COUNTER
------------------------------------
A plate asks one of two things, and its code says which:

  a<n>   "Is your building rent-stabilized?"   -> findacrib.com/c/a<n>
  b<n>   "Find rent-stabilized apartments"     -> findacrib.com/c/b<n>

Both are true and both are answered by this site. What differs is who is
standing at the counter: A talks to somebody who already has a landlord, which
in a laundromat is everybody, and B talks to somebody mid-move, which is a few
percent of most rooms and nearly all of a self-storage lobby. Pick the question
from the ROOM, not from taste — the dashboard's signage card lists the venues
each one is for.

The number is not decoration. One code per counter is what makes a scan
traceable to the plate it came off; two counters sharing a code means neither
one's scans can be read. `make-signage.py a1 a2 b1` writes a run of them.

WHICH FILE GOES WHERE
---------------------
Everything is the same two objects — a 4 x 6 plate and the foot it stands in.
The plate files carry their code in the name; the foot is shared. The formats
differ because the shops differ.

  Ponoko            -engrave-ponoko.svg  +  -base-ponoko.svg
  Laser-CutZ        -cut.dxf  +  -600dpi.png   (cut path + raster art)
  Inland Products   -engrave.pdf  +  -base.pdf (quote form takes PDF)

BLACK = engrave/mark. The hairline rectangle is the CUT path, not artwork.

**The cut line's COLOUR is the instruction, and Ponoko inverts everyone
else's.** Standard shops (Laser-CutZ included) read a red hairline as "cut
through". Ponoko reads BLUE as cut and RED as *line engrave* — send them the
red file and they will engrave a rectangle onto the plate and never cut it
out. That is why there are `-ponoko` variants rather than a warning in a
paragraph nobody re-reads at the moment of upload. On Ponoko you also confirm
each colour's action in a dropdown after upload: blue = cut, black fill = area
engrave.

Send PDF or SVG, never a screenshot. Both carry live text, so a shop without
Helvetica substitutes a font and reflows the layout — ask them to confirm the
proof, or ask for outlines. The QR is a vector path in every format here and
is never at risk from that.

The DXF is cut geometry ONLY, in inches, on a layer called CUT. DXF has no
filled regions, so a QR exported to it is either 400 outlines somebody fills
by hand or a grid of hairlines that engrave as squares — neither is the code.
Pair it with the 600dpi PNG, which is what a raster engraver wants anyway.

THE ONE RULE, WHATEVER THE MATERIAL
-----------------------------------
**The code must come out DARK ON LIGHT.** Scanning algorithms look for dark
modules on a light field. Inverted codes — a bright mark on a dark plate — are
read by recent iPhones and missed by older Android cameras and older Google
Lens. The people this site is for are disproportionately on those phones.

Everything below is just a list of ways to get a dark mark on a light
substrate. Any process that does that works. Any process that does the reverse
is off the table no matter how good it looks.

MATERIALS THAT WORK
-------------------
Plastic — two-ply engraving stock (Rowmark LaserMax or equivalent), 1/16 in:
    Order **WHITE CAP over BLACK CORE**. The laser removes the white cap and
    the black core shows through, so black in the artwork is black on the
    finished plate. Order it the other way round — black cap, white core —
    and every black area comes out white, including the code, and none of it
    scans. Say "white cap, black core" in words on the order.

Metal — stainless steel, laser ANNEALED:
    Annealing oxidises the surface to a dark mark without removing material,
    so it is dark-on-bright, and it leaves the passive layer intact so the
    plate will not corrode. Ask for "laser annealed, dark mark" — not
    "engraved", which means depth. Bead-blasted stock takes the highest
    contrast.

Metal — aluminium, engraved and BLACK PAINT FILLED:
    Cut the art, fill the recess with black. Dark-on-light, and the fill is
    what makes it so.

MATERIALS THAT DO NOT WORK
--------------------------
Black anodised aluminium. This is what every vendor will suggest and what
looks best in a photograph: the laser burns the anodise off to bright metal,
giving a bright mark on a dark plate. That is the inverted case, permanently.

Clear or frosted acrylic. Frosted-on-clear is the lowest-contrast result
available and low contrast is the first cause of scan failure. If acrylic is
the only option, engrave white or black cast acrylic, or engrave and fill.

MAKING IT STAND UP
------------------
A 4 x 6 plate on its own is a coaster. Two ways, by material:

Plastic — cut the base file from **1/4 in stock**, not from the 1/16 in the
    plate is cut from. The weight is the whole point; a foot in plate gauge
    goes over the first time somebody puts a bag on the counter. The slot is
    drawn one kerf undersize for a friction fit — **test-fit the first sample
    before cutting the rest**, since kerf varies by machine and stock, and
    have the shop adjust the slot rather than forcing the plate.

Metal — skip the base and ask for a **1 in return bend at 90 degrees along the
    bottom**, from a 4 x 7 blank. The 4 x 6 face carries the artwork and the
    remaining inch is the foot. One piece, no assembly, heavy enough not to
    tip, and nothing to lose. Metal can be bent; two-ply cannot, which is the
    only reason the base file exists.

An adhesive easel back also works on either and costs cents, but it is the
first thing to peel and the easiest to knock over.

DO NOT ADD A LOGO NEXT TO THE CODE
----------------------------------
Anything built from concentric squares reads to a scanner as a QR finder
pattern — the three corner targets it hunts for before it reads anything — and
it will spend its search on the logo instead. Not theoretical: the first
version of this plate carried the app mark as an outlined rounded square with
a diamond inside, and it dropped the page from decoding at 25dpi to failing
below 80dpi. Same ink, a third of the scan margin. The mark is now the diamond
alone, and `make-signage.py` re-decodes every render at falling resolution and
fails the build if the margin comes back thin.

BEFORE APPROVING A RUN
----------------------
Ask for one physical sample and **decode it with a phone** — at arm's length,
under the shop's own lighting, on an Android as well as an iPhone. Not by eye,
and not from a screen proof.

WHAT IS ETCHED, AND WHAT IS NOT
-------------------------------
The code encodes a short path, not a destination. `findacrib.com/c/a1`
resolves server-side in nginx to /?src=qr-a1, so where it lands can change — a
new landing page, a borough view, an app — without touching a plate already
sitting on a counter, and every scan is counted on the dashboard like a tagged
link. Nothing about the destination is on the object, which is the only reason
a permanent object is safe to make at all.

nginx logs those redirects to a file of their own, so a scan is counted even
when the person closes the tab before any JavaScript runs. That gap is the
measurement: scans are what the QUESTION earned, and the sessions and searches
underneath them are what the SITE earned. A question that pulls scans out of
people with no interest in the answer is worse than one that pulls fewer.
"""


# 90-degree arc as an LWPOLYLINE bulge: tan(angle/4) = tan(22.5deg).
BULGE_90 = 0.41421356237


def _rounded_rect(x, y, w, h, r):
    """CCW vertices with bulges, in inches, for one rounded rectangle.

    The bulge on a vertex describes the segment LEAVING it, which is the part
    that is easy to get one index out; the corners come back square if it is.
    """
    b = BULGE_90
    return [(x + r, y, 0), (x + w - r, y, b), (x + w, y + r, 0),
            (x + w, y + h - r, b), (x + w - r, y + h, 0), (x + r, y + h, b),
            (x, y + h - r, 0), (x, y + r, b)]


def write_dxf(stem: str, page_h: float, shapes) -> None:
    """Cut geometry only, in inches, on a layer called CUT.

    Deliberately not the artwork. DXF has no notion of a filled region, so a
    QR exported to it is either 400-odd outlines a shop has to fill by hand or
    a set of hairlines that engrave as a grid of squares — neither is the code.
    The art travels as PDF or as a raster PNG, which is what the engraver wants
    for it anyway, and this file is the outline the machine cuts.

    SVG measures y downward from the top and DXF upward from the bottom, so
    every y is flipped here rather than in the callers.
    """
    try:
        import ezdxf
    except ImportError:
        print("  !! ezdxf not installed: no DXF written")
        return
    doc = ezdxf.new("R2010", setup=True)
    doc.header["$INSUNITS"] = 1            # inches, so nothing arrives 25.4x off
    doc.layers.add("CUT", color=1)
    msp = doc.modelspace()
    for (x, y, w, h, r) in shapes:
        pts = _rounded_rect(x / PT, (page_h - y - h) / PT, w / PT, h / PT, r / PT)
        msp.add_lwpolyline(pts, format="xyb", close=True, dxfattribs={"layer": "CUT"})
    doc.saveas(OUT / f"{stem}.dxf")


def render(stem: str, markup: str) -> None:
    p = OUT / f"{stem}.svg"
    p.write_text(markup)
    for fmt, extra, suffix in (
            ("pdf", [], ""),
            ("png", ["--dpi-x", "300", "--dpi-y", "300"], ""),
            # A raster engraver reproduces the bitmap it is handed, module for
            # module, so the proof resolution is not enough to hand a machine.
            ("png", ["--dpi-x", "600", "--dpi-y", "600"], "-600dpi")):
        subprocess.run(["rsvg-convert", "-f", fmt, *extra,
                        "-o", str(OUT / f"{stem}{suffix}.{fmt}"), str(p)], check=True)


# The floor each rendered page must still decode at, in dpi. Not a round
# number pulled from the air: both pieces measured well under it, and the one
# layout change that broke it (a logo the detector mistook for a finder
# pattern) pushed a page to 80. Anything above this is a real regression.
DPI_FLOOR = 60


def verify(stem: str, expect: str) -> None:
    """Decode the rendered proof, and keep decoding it at falling resolution.

    Checking that the code "looks right" is worth nothing, and decoding it once
    at 300dpi is worth little more: a phone over a counter is not a scanner,
    and every defect that matters here — a crowded quiet zone, a logo that
    reads as a finder pattern — shows up as a loss of margin long before it
    shows up as a failure on a desk. So this sweeps down until the page stops
    decoding and fails the build if the margin got thin.
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        print(f"  !! opencv-python not installed: {stem} went out UNVERIFIED")
        return
    img = cv2.imread(str(OUT / f"{stem}.png"), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise SystemExit(f"{stem}: proof did not render")
    # Flatten alpha onto white. The engrave plate has rounded corners, and
    # cv2 drops alpha to black — a scan problem white plastic does not have.
    if img.shape[2] == 4:
        a = img[:, :, 3:4] / 255.0
        img = (img[:, :, :3] * a + 255 * (1 - a)).astype(np.uint8)
    det = cv2.QRCodeDetector()
    h, w = img.shape[:2]
    floor_dpi = None
    # Isolated failures on the way down are the resampler, not the artwork: a
    # 33-module code drawn with crispEdges lands its module boundaries between
    # pixels at a few particular scales, and INTER_AREA smears them there and
    # nowhere else. This plate decoded at every step from 300 to 25 except 290
    # and 275, and stopping at the first miss reported its floor as 295 — a
    # ten-fold overstatement that would have failed a build over nothing. A
    # margin that is genuinely thin fails at every scale below the point where
    # it runs out, so the floor is the lowest dpi that still decodes and the
    # sweep only gives up after a run of them.
    RESAMPLE_ARTEFACT_RUN = 4
    misses = 0
    for dpi in range(300, 19, -5):
        s = dpi / 300.0
        small = cv2.resize(img, (max(1, int(w * s)), max(1, int(h * s))),
                           interpolation=cv2.INTER_AREA)
        try:
            got, _, _ = det.detectAndDecode(small)
        except cv2.error:
            got = ""
        if got == expect:
            floor_dpi = dpi
            misses = 0
        else:
            misses += 1
            if misses >= RESAMPLE_ARTEFACT_RUN:
                break
    if floor_dpi is None:
        raise SystemExit(f"{stem}: the rendered code does not decode to {expect} at all.")
    if floor_dpi > DPI_FLOOR:
        raise SystemExit(
            f"{stem}: decodes only down to {floor_dpi}dpi, floor is {DPI_FLOOR}. "
            "Something in the layout is competing with the code — most likely a "
            "shape near it, or a concentric outline anywhere on the page that "
            "reads as a finder pattern."
        )
    print(f"  verified: decodes to {expect} down to {floor_dpi}dpi")


CODE_RE = re.compile(r"^[ab][0-9]{1,3}$")


def parse_codes(argv) -> list:
    """Plate codes off the command line, defaulting to one plate per question.

    A code is the arm letter plus a placement number: a1 is the first plate
    asking question A. The number is not decoration — a scan can only be traced
    to the counter it came off if no two counters share a code, and telling two
    laundromats apart is the whole reason the second one is worth placing.
    """
    codes = [c.strip().lower() for c in argv if c.strip()]
    if not codes:
        return ["a1", "b1"]
    bad = [c for c in codes if not CODE_RE.match(c)]
    if bad:
        raise SystemExit(f"not plate codes: {', '.join(bad)} "
                         "(expected a1, a2, b1 ... — arm letter then placement)")
    if len(set(codes)) != len(codes):
        raise SystemExit("duplicate code: two plates on two counters cannot "
                         "share one, or neither scan can be attributed")
    return codes


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    codes = parse_codes(sys.argv[1:])

    # The foot is the same object whatever the plate says, so it is cut once
    # and the files are not duplicated per code.
    foot, bw, bh, bm = base_bar()
    render("findacrib-counter-base", svg(bw, bh, foot,
           "Find A Crib counter base (cut only)"))
    pfoot, _, _, _ = base_bar(cut=CUT_PONOKO)
    render("findacrib-counter-base-ponoko", svg(bw, bh, pfoot,
           "Find A Crib counter base (Ponoko: blue = cut)"))

    pw = ph = None
    for code in codes:
        lines = ARMS[code[0]]
        # Short path, resolved by nginx to /?src=qr-<code>. The printed string
        # and the encoded string are the same variable on purpose.
        shown = f"findacrib.com/c/{code}"
        url = f"https://{shown}"
        stem = f"findacrib-counter-{code}-4x6-engrave"

        plate, pw, ph, pm = counter_plate(url, shown, lines)
        render(stem, svg(pw, ph, plate,
               f"Find A Crib counter plate {code} 4x6 (engrave)"))

        # Ponoko's colour convention is the reverse of everyone else's, and the
        # colour IS the instruction, so it gets its own file rather than a
        # warning.
        pplate, _, _, _ = counter_plate(url, shown, lines, cut=CUT_PONOKO)
        render(stem + "-ponoko", svg(pw, ph, pplate,
               f"Find A Crib counter plate {code} 4x6 (Ponoko: blue = cut)"))

        write_dxf(f"findacrib-counter-{code}-4x6-cut", ph, [(0, 0, pw, ph, 10.0)])

        # The UV-printed black card. Same code, same question, different
        # manufacturing route entirely — ink on acrylic rather than a laser in
        # two-ply — so it is a separate piece rather than a recolour.
        bstem = f"findacrib-card-{code}-4x4-black"
        bcard, bwd, bht, bm2 = card_black(url, shown, lines)
        render(bstem, svg(bwd, bht, bcard, f"Find A Crib black card {code} 4x4"))
        print(f"  black card {bm2['trim']}, code {bm2['qr_in']:.2f} in, "
              f"{bm2['quiet']:.1f}-module quiet zone")
        verify(bstem, url)

        print(f"plate {code}: \u201c{lines[0]} {lines[1]}\u201d -> {url}")
        print(f"  {pm['trim']}, bleed {pm['bleed']}  ->  {pm['canvas']} artwork, "
              f"headline {pm['head']:.0f}pt")
        print(f"  code {pm['modules']}x{pm['modules']} modules, {pm['qr_in']:.2f} in wide, "
              f"ECC H, {pm['quiet']:.1f}-module quiet zone")
        verify(stem, url)
        verify(stem + "-ponoko", url)

    slot_w = PLATE_T - KERF
    slot_l = 4.02 * PT
    write_dxf("findacrib-counter-base-cut", bh, [
        (0, 0, bw, bh, 0.1 * PT),
        ((bw - slot_l) / 2, 0.62 * PT, slot_l, slot_w, slot_w / 2),
    ])

    (OUT / "README.md").write_text(README)
    print(f"base: {bm['size']} from {bm['stock']} stock, slot {bm['slot']} (cut only)")
    print(f"\nwritten to {OUT}")
    return 0

if __name__ == "__main__":
    sys.exit(main())

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
import subprocess
import sys

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
# Pure red hairline is the universal "cut here, do not engrave" convention on
# a laser bed. Any other red, or any stroke with width, gets engraved instead.
CUT = "#FF0000"
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
HEAD_1 = "Is your building"
HEAD_2 = "rent-stabilized?"
SUB = f"Look it up free. {BUILDINGS} NYC buildings, one map."
CTA = "Scan to check your address"


def counter_plate(url: str, shown: str) -> tuple[str, float, float, dict]:
    """4 x 6in two-ply plate: the same card as line art, plus a cut path.

    No bleed. Paper is printed oversize and trimmed into the art; a laser cuts
    to a line, so the canvas IS the finished size and the cut path sits on it.
    """
    w, h = 4 * PT, 6 * PT
    cx = w / 2
    r = 10.0
    # White field = the untouched cap layer. It is drawn rather than left
    # implicit so the PNG proof shows the finished piece and not a transparent
    # checkerboard that hides a stray mark.
    b = [rect(0, 0, w, h, fill=WHITE, rx=r)]

    b.append(mark(cx - 60, 46, 32, outline=True))
    b.append(text(cx - 38, 53, "Find A Crib", 22, fill=BLACK, weight=700, anchor="start", spacing=-0.5))
    # A rule instead of the printed version's filled band: one thin engraved
    # line where the print piece has 86pt of solid colour.
    b.append(rect(34, 74, w - 68, 1.6, fill=BLACK))

    b.append(text(cx, 122, HEAD_1, 21, fill=BLACK, weight=700, spacing=-0.6))
    b.append(text(cx, 146, HEAD_2, 21, fill=BLACK, weight=700, spacing=-0.6))
    b.append(text(cx, 168, SUB, 10, fill=BLACK))

    # No panel outline. The print piece rings the code with a white card on a
    # tint, which reads as a frame and costs the code nothing. The same frame
    # engraved is a black line a few points from the finder patterns, and it
    # measurably wrecks the code: with a 1.4pt border at 14pt clearance this
    # plate stopped decoding below 80dpi, against 35dpi for the printed card.
    # The clear space around the code IS the frame, and it stays untouched.
    side = 168.0
    top = 206.0
    code, module, n = qr(url, cx, top, side)
    # Measured against the nearest ink on every side, which after the border
    # came out is the subhead above and the caption below.
    check_quiet("counter plate (engrave), above code", top - 168.0, module)
    check_quiet("counter plate (engrave), beside code", (w - side) / 2, module)
    b.append(code)

    cta_baseline = 412.0
    # Cap height is ~0.72 of the point size for this family; the top of the
    # capital S is what encroaches on the code, not the baseline.
    check_quiet("counter plate (engrave), below code",
                (cta_baseline - 14 * 0.72) - (top + side), module)
    b.append(text(cx, cta_baseline, CTA, 14, fill=BLACK, weight=700))
    b.append(text(cx, 430, shown, 11.5, fill=BLACK, weight=700))

    # Cut path last so it sits on top of everything in a shop's viewer.
    b.append(rect(0, 0, w, h, rx=r, stroke=CUT, sw=CUT_W))
    meta = {"trim": "4 x 6 in", "bleed": "none (cut to line)",
            "canvas": f"{w / PT:.3f} x {h / PT:.3f} in",
            "qr_in": side / PT, "quiet": (top - 168.0) / module, "modules": n}
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


def base_bar() -> tuple[str, float, float, dict]:
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
        rect(0, 0, w, h, rx=r, stroke=CUT, sw=CUT_W),
        rect(sx, sy, slot_l, slot_w, rx=slot_w / 2, stroke=CUT, sw=CUT_W),
    ]
    meta = {"stock": "1/4 in", "size": f"{w / PT:.2f} x {h / PT:.2f} in",
            "slot": f"{slot_l / PT:.2f} x {slot_w / PT:.4f} in"}
    return "\n".join(b), w, h, meta


README = """Find A Crib — etched counter piece
=========================================

Generated by `scripts/make-signage.py`. **Edit the script, never these files.**
Nudging a QR module in a design tool destroys the code invisibly.

    findacrib-counter-4x6-engrave.pdf   the plate. 4 x 6 in finished, no bleed.
                                        BLACK = engrave/mark. The red hairline
                                        rectangle is the CUT path, not artwork.
    findacrib-counter-base.pdf          the foot it stands in. Cut only,
                                        nothing engraved. 1/4 in stock.

Send the PDF, not the SVG. The SVG carries live text and a shop without
Helvetica will substitute a font and reflow the layout. The QR is a vector
path in both and is never at risk from that.

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
The code encodes a short path, not a destination. `findacrib.com/c` resolves
server-side in nginx to /?src=qr-counter, so where it lands can change — a new
landing page, a borough view, an app — without touching a plate already
sitting on a counter, and every scan is counted on the dashboard like a tagged
link. Nothing about the destination is on the object, which is the only reason
a permanent object is safe to make at all.
"""


def render(stem: str, markup: str) -> None:
    p = OUT / f"{stem}.svg"
    p.write_text(markup)
    for fmt, extra in (("pdf", []), ("png", ["--dpi-x", "300", "--dpi-y", "300"])):
        subprocess.run(["rsvg-convert", "-f", fmt, *extra,
                        "-o", str(OUT / f"{stem}.{fmt}"), str(p)], check=True)


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
        else:
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


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    # Short path, resolved by nginx to /?src=qr-counter. The printed string and
    # the encoded string are the same variable on purpose.
    shown = "findacrib.com/c"
    url = f"https://{shown}"

    plate, pw, ph, pm = counter_plate(url, shown)
    foot, bw, bh, bm = base_bar()
    render("findacrib-counter-4x6-engrave", svg(pw, ph, plate,
           "Find A Crib counter plate 4x6 (engrave)"))
    render("findacrib-counter-base", svg(bw, bh, foot,
           "Find A Crib counter base (cut only)"))
    (OUT / "README.md").write_text(README)

    stem = "findacrib-counter-4x6-engrave"
    print(f"plate: {url}")
    print(f"  {pm['trim']}, bleed {pm['bleed']}  ->  {pm['canvas']} artwork")
    print(f"  code {pm['modules']}x{pm['modules']} modules, {pm['qr_in']:.2f} in wide, "
          f"ECC H, {pm['quiet']:.1f}-module quiet zone")
    verify(stem, url)
    print(f"base: {bm['size']} from {bm['stock']} stock, slot {bm['slot']} (cut only)")
    print(f"\nwritten to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

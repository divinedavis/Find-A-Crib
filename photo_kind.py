"""Which of the agents' listing photos show the OUTSIDE of the building.

The app's Search banner leads with one of these at full width (owner,
2026-09-23: the re-rentals in the banner "need to be images of the outside of
the building only"), and the marketing agents publish whatever they have — a
facade, a rendering, an empty living room, sometimes just their own logo.

Nothing in this pipeline can see a picture: Jev reads text, and there is no
vision model here. So this is a measurement rather than a classifier, and it
measures the one thing a wall is never made of — sky. A street photo or a
rendering of a building has open sky across the top of the frame; a room has
ceiling and wall up there, and a logo has a flat field.

It is tuned for precision, not recall. Of the 22 photos live on 2026-09-23 it
passes 16 of the 19 exteriors and none of the 2 interiors or the logo; the
three it turns down are a grey-day photo, a dusk skyline and a black-and-white
one. Rejecting an exterior costs nothing — the banner picks another apartment
— while one empty living room across the top of the app is the thing that was
asked not to happen.
"""

import colorsys

# The band that is sky in a photo taken from the street, and ceiling in a room.
TOP_BAND = 0.22
# Share of that band that has to be sky-blue. Measured: interiors and logos
# score 0.000-0.002, the exteriors that pass score 0.137-1.000.
MIN_BLUE = 0.12
# Sky, at any exposure: blue hue, enough colour to not be a grey wall, and not
# a shadow. A painted blue ceiling would pass, and has never turned up.
HUE_LO, HUE_HI = 195, 250
SAT_MIN, VAL_MIN = 0.12, 0.40
# Big enough to measure, small enough that the pure-Python loop stays under a
# tenth of a second per photo.
SAMPLE = 160


def sky_share(path):
    """Share of the top band that is sky-blue, or None if the file can't be read."""
    try:
        from PIL import Image
    except ImportError:
        return None
    try:
        im = Image.open(path).convert("RGB")
        im.thumbnail((SAMPLE, SAMPLE))
    except Exception:
        return None
    w, h = im.size
    if w < 8 or h < 8:
        return None
    px = im.load()
    top = max(1, int(h * TOP_BAND))
    blue = 0
    for y in range(top):
        for x in range(w):
            r, g, b = (v / 255 for v in px[x, y])
            hue, sat, val = colorsys.rgb_to_hsv(r, g, b)
            if HUE_LO <= hue * 360 <= HUE_HI and sat > SAT_MIN and val > VAL_MIN:
                blue += 1
    return blue / (top * w)


def is_exterior(path):
    """True only when the photo is confidently the outside of a building."""
    share = sky_share(path)
    return share is not None and share >= MIN_BLUE

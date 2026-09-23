#!/usr/bin/env python3
"""Unit tests for photo_kind.py — which listing photos are the outside of a
building. No network; the images are drawn here.

    python3 tests/test_photo_kind.py
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import photo_kind as P  # noqa: E402

try:
    from PIL import Image
except ImportError:      # the droplet's scraper venv has it; a bare python may not
    Image = None


def draw(bands, w=400, h=400):
    """Write a PNG stacked from (height fraction, RGB) bands, top first."""
    im = Image.new("RGB", (w, h), bands[-1][1])
    y = 0
    for frac, colour in bands:
        rows = int(h * frac)
        for yy in range(y, min(h, y + rows)):
            for xx in range(w):
                im.putpixel((xx, yy), colour)
        y += rows
    f = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    im.save(f.name)
    return f.name


SKY = (110, 170, 235)       # a clear day
WALL = (238, 234, 228)      # a painted ceiling
BRICK = (150, 90, 70)
FLOOR = (170, 120, 70)      # wood


@unittest.skipIf(Image is None, "Pillow is not installed")
class ExteriorTest(unittest.TestCase):
    def test_sky_over_a_facade_is_an_exterior(self):
        self.assertTrue(P.is_exterior(draw([(0.35, SKY), (0.65, BRICK)])))

    def test_a_room_is_not(self):
        # Ceiling and wall on top, wood on the floor: no sky anywhere.
        self.assertFalse(P.is_exterior(draw([(0.6, WALL), (0.4, FLOOR)])))

    def test_a_logo_on_a_flat_field_is_not(self):
        self.assertFalse(P.is_exterior(draw([(1.0, (245, 245, 245))])))

    def test_a_sliver_of_sky_is_not_enough(self):
        # A window at the top of a room reaching 8% of the band: under MIN_BLUE.
        share = P.sky_share(draw([(0.02, SKY), (0.98, WALL)]))
        self.assertLess(share, P.MIN_BLUE)

    def test_an_unreadable_file_is_not_an_exterior(self):
        f = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        f.write(b"not an image"); f.close()
        self.assertIsNone(P.sky_share(f.name))
        self.assertFalse(P.is_exterior(f.name))
        self.assertFalse(P.is_exterior("/nope/missing.jpg"))


if __name__ == "__main__":
    unittest.main(verbosity=2)

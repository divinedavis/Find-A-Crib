#!/usr/bin/env python3
"""Render promo-15s.html to a 1080x1920 30 fps MP4.

    /usr/bin/python3 marketing/promo/render.py            # full render
    /usr/bin/python3 marketing/promo/render.py --stills   # one PNG per scene, for review

Seeks every CSS animation to each frame's time (window.seek) and screenshots
it, so the output is frame-exact regardless of machine speed.
"""
import argparse
import pathlib
import subprocess
import tempfile

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
PAGE = HERE / "promo-15s.html"
OUT = HERE / "findacrib-promo-15s.mp4"
FPS, DURATION = 30, 15
STILLS = [1.6, 3.9, 6.2, 8.3, 9.2, 10.4, 12.6, 14.6]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stills", action="store_true")
    args = ap.parse_args()

    with sync_playwright() as p, tempfile.TemporaryDirectory() as tmp:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1080, "height": 1920})
        page.goto(PAGE.as_uri())
        page.evaluate("window.ready")
        times = STILLS if args.stills else [i / FPS for i in range(FPS * DURATION)]
        for i, t in enumerate(times):
            page.evaluate(f"seek({t})")
            if args.stills:
                page.screenshot(path=str(HERE / f"still-{t:05.2f}.png"))
            else:
                page.screenshot(path=f"{tmp}/f{i:04d}.png")
        browser.close()
        if args.stills:
            return
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i", f"{tmp}/f%04d.png",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "16", "-preset", "slow",
            "-movflags", "+faststart", str(OUT),
        ], check=True)
    print(OUT)


if __name__ == "__main__":
    main()

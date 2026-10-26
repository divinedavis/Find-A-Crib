#!/usr/bin/env python3
"""Render film.html to a 1920x1080 30 fps MP4.

    /usr/bin/python3 render.py --app fac            # full render
    /usr/bin/python3 render.py --app fac --stills   # a few PNGs for review

Calls window.render(t) for each frame (it seeks the screen video and
places the camera) and screenshots the page, so the export is frame-exact.
"""
import argparse
import pathlib
import subprocess
import tempfile

from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
FPS = 30


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", default="fac")
    ap.add_argument("--stills", action="store_true")
    args = ap.parse_args()
    out = HERE / f"{args.app}-film.mp4"

    with sync_playwright() as p, tempfile.TemporaryDirectory() as tmp:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1920, "height": 1080})
        page.goto((HERE / "film.html").as_uri() + f"?app={args.app}")
        page.evaluate("window.ready")
        duration = page.evaluate("window.DURATION")
        if args.stills:
            times = [duration * f for f in (0.01, 0.04, 0.1, 0.2, 0.3, 0.45, 0.55, 0.7, 0.8, 0.9, 0.99)]
        else:
            times = [i / FPS for i in range(int(duration * FPS))]
        for i, t in enumerate(times):
            page.evaluate(f"render({t})")
            name = HERE / f"still-{t:05.2f}.png" if args.stills else f"{tmp}/f{i:04d}.png"
            page.screenshot(path=str(name))
        browser.close()
        if args.stills:
            return
        subprocess.run([
            "ffmpeg", "-v", "error", "-y", "-framerate", str(FPS), "-i", f"{tmp}/f%04d.png",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "17", "-preset", "slow",
            "-movflags", "+faststart", str(out),
        ], check=True)
    print(out)


if __name__ == "__main__":
    main()

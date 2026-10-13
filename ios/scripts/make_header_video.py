#!/usr/bin/env python3
"""App Store header VIDEO for Find A Crib (owner, 2026-10-13: "show me a
video in downloads first"). Same look as make_header.py's banner — the teal
field and the white wordmark — then three of the app's own screens rise in
on phones while a caption names what each does.

Apple's spec (Asset Library header video): 3840x1646, 30 fps, 5-30 s.

Usage: ~/.venvs/spendcap/bin/python scripts/make_header_video.py [out.mp4]
Default output: marketing/asc-header/header-3840x1646.mp4
"""
import math
import os
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import make_header as H  # noqa: E402  (fonts, colours, the app mark)

W, HT, FPS, SECONDS = 3840, 1646, 30, 15
# Fresh simulator shots (status bar 9:41); override with HEADER_SHOTS=dir.
RAW = os.environ.get("HEADER_SHOTS") or os.path.join(H.ROOT, "marketing/raw")
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(H.OUT, "header-3840x1646.mp4")

# (screen, caption) — what the phone shows and the line beside it.
SCENES = [
    ("home.png", "Every rent-stabilized building in NYC"),
    ("map.png", "47,000 buildings on one map"),
    ("lotteries.png", "Housing lotteries, the minute they open"),
    ("detail.png", "Violations, pests and who owns the building"),
]


def background():
    """The banner's radial teal, drawn small and scaled up (smooth, fast)."""
    sw, sh = 384, 165
    small = Image.new("RGB", (sw, sh))
    px = small.load()
    cx, cy, rmax = sw * 0.5, -sh * 0.2, math.hypot(sw * 0.6, sh * 1.2)
    for y in range(sh):
        for x in range(sw):
            t = min(1.0, math.hypot(x - cx, y - cy) / rmax) ** 2
            px[x, y] = tuple(int(H.BLUE[i] + (H.ROYAL[i] - H.BLUE[i]) * t) for i in range(3))
    return small.resize((W, HT), Image.BICUBIC).convert("RGBA")


def phone(name, height):
    """A screenshot in a rounded black bezel with a soft shadow."""
    shot = Image.open(os.path.join(RAW, name)).convert("RGBA")
    h = int(height * 0.94)
    w = int(shot.width * h / shot.height)
    shot = shot.resize((w, h), Image.LANCZOS)
    m = Image.new("L", shot.size, 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w - 1, h - 1], radius=int(w * 0.12), fill=255)
    shot.putalpha(m)
    bez = int(height * 0.03)
    frame = Image.new("RGBA", (w + 2 * bez, h + 2 * bez), (0, 0, 0, 0))
    ImageDraw.Draw(frame).rounded_rectangle([0, 0, frame.width - 1, frame.height - 1], radius=int(w * 0.14), fill=(12, 18, 22, 255))
    frame.alpha_composite(shot, (bez, bez))
    pad = int(height * 0.08)
    out = Image.new("RGBA", (frame.width + 2 * pad, frame.height + 2 * pad), (0, 0, 0, 0))
    sh = Image.new("RGBA", out.size, (0, 0, 0, 0))
    sh.paste((0, 20, 40, 120), (pad, pad + pad // 3, pad + frame.width, pad + pad // 3 + frame.height), frame.split()[3])
    out.alpha_composite(sh.filter(ImageFilter.GaussianBlur(pad // 2)))
    out.alpha_composite(frame, (pad, pad))
    return out


def ease(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def text_layer(text, size, weight="Black", fill=H.WHITE):
    f = H.font(weight, size)
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    w = int(d.textlength(text, font=f)) + 20
    a, b = f.getmetrics()
    img = Image.new("RGBA", (w, a + b + 20), (0, 0, 0, 0))
    ImageDraw.Draw(img).text((10, 10), text, font=f, fill=fill)
    return img


def faded(img, alpha):
    if alpha >= 1:
        return img
    out = img.copy()
    out.putalpha(img.split()[3].point(lambda v: int(v * max(0.0, alpha))))
    return out


def main():
    bg = background()
    mark = Image.open(H.ICON).convert("RGBA").resize((300, 300), Image.LANCZOS)
    mm = Image.new("L", mark.size, 0)
    ImageDraw.Draw(mm).rounded_rectangle([0, 0, 299, 299], radius=66, fill=255)
    mark.putalpha(mm)
    word = text_layer("Find A Crib", 300)
    phones = [phone(n, 1500) for n, _ in SCENES]
    caps = [text_layer(c, 118, "Bold") for _, c in SCENES]
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{HT}",
                           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high",
                           "-crf", "16", "-movflags", "+faststart", OUT], stdin=subprocess.PIPE)
    n = FPS * SECONDS
    intro, per = 2.5, (SECONDS - 2.5) / len(SCENES)
    for i in range(n):
        t = i / FPS
        f = bg.copy()
        # Intro: the wordmark rises and settles centre-left of the field.
        k = ease(t / 1.2)
        wx = int(W * 0.08)
        wy = int(HT * 0.30 + (1 - k) * 80)
        f.alpha_composite(faded(mark, k), (wx, wy - 330))
        f.alpha_composite(faded(word, k), (wx - 10, wy))
        if t >= intro:
            s = min(len(SCENES) - 1, int((t - intro) / per))
            local = (t - intro) - s * per
            k_in, k_out = ease(local / 0.7), ease((local - (per - 0.5)) / 0.5) if s < len(SCENES) - 1 else 0.0
            ph = phones[s]
            px = int(W * 0.60)
            py = int(HT * 0.12 + (1 - k_in) * HT * 0.9 + k_out * HT * 0.9)
            f.alpha_composite(ph, (px, py))
            cap = faded(caps[s], k_in * (1 - k_out))
            f.alpha_composite(cap, (wx, int(HT * 0.30) + 360))
        ff.stdin.write(f.convert("RGB").tobytes())
    ff.stdin.close()
    ff.wait()
    print(OUT)


if __name__ == "__main__":
    main()

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
RAW = os.environ.get("HEADER_SHOTS") or os.path.join(H.ROOT, "marketing/header-shots")
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


def wrap(text, size, width, weight="Bold"):
    """Caption lines no wider than width, stacked into one layer."""
    f = H.font(weight, size)
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if cur and d.textlength(trial, font=f) > width:
            lines.append(cur); cur = word
        else:
            cur = trial
    lines.append(cur)
    layers = [text_layer(line, size, weight) for line in lines]
    step = int(size * 1.22)
    out = Image.new("RGBA", (max(l.width for l in layers), step * (len(layers) - 1) + layers[-1].height), (0, 0, 0, 0))
    for i, l in enumerate(layers):
        out.alpha_composite(l, (0, i * step))
    return out


# Apple's ART SAFE AREA for the 3840x1646 header (creative_assets-templates
# .sketch): 1646x661, centred. An iPhone 17 Pro shows only x 1006-2833,
# y 232-1410 of the canvas, and the back button and the mute/share pill sit
# over y 490-725 at its left and right edges (measured from the live page,
# 2026-10-12). The first video put the wordmark at x 307 and the phone under
# the pill: the App Store showed "nd A Crib". Type stays inside SAFE and out
# of BUTTONS; main() checks every frame's type before it is written.
SAFE = (1097, 492, 2743, 1153)
BUTTONS = [(1006, 490, 1290, 725), (2240, 490, 2833, 725)]
TEXT_X, TEXT_Y, PHONE_X, PHONE_TOP = 1140, 700, 2210, 760


def check(box):
    x0, y0, x1, y1 = box
    sx0, sy0, sx1, sy1 = SAFE
    assert sx0 <= x0 and x1 <= sx1 and sy0 <= y0 and y1 <= sy1, f"type {box} leaves the safe area {SAFE}"
    for b in BUTTONS:
        assert x1 <= b[0] or x0 >= b[2] or y1 <= b[1] or y0 >= b[3], f"type {box} sits under a button {b}"


def ink(layer, at):
    """The layer's painted box, placed at `at`, in canvas coordinates."""
    x0, y0, x1, y1 = layer.split()[3].getbbox()
    return (at[0] + x0, at[1] + y0, at[0] + x1, at[1] + y1)


def main():
    bg = background()
    text_w = PHONE_X - 60 - TEXT_X
    word = text_layer("Find A Crib", 190)
    phones = [phone(n, 1150) for n, _ in SCENES]
    pad = int(1150 * 0.08)
    caps = [wrap(c, 76, text_w) for _, c in SCENES]
    cap_y = TEXT_Y + 230
    check(ink(word, (TEXT_X - 10, TEXT_Y)))
    for c in caps:
        check(ink(c, (TEXT_X - 10, cap_y)))
    ff = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{HT}",
                           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-profile:v", "high",
                           "-crf", "16", "-movflags", "+faststart", OUT], stdin=subprocess.PIPE)
    n = FPS * SECONDS
    intro, per = 2.5, (SECONDS - 2.5) / len(SCENES)
    for i in range(n):
        t = i / FPS
        f = bg.copy()
        # Intro: the wordmark rises and settles in the safe area's left half
        # (the App Store's icon sits right under the header, so no mark here).
        k = ease(t / 1.2)
        f.alpha_composite(faded(word, k), (TEXT_X - 10, TEXT_Y + int((1 - k) * 80)))
        if t >= intro:
            s = min(len(SCENES) - 1, int((t - intro) / per))
            local = (t - intro) - s * per
            k_in, k_out = ease(local / 0.7), ease((local - (per - 0.5)) / 0.5) if s < len(SCENES) - 1 else 0.0
            # The phone rises from below and stops under the mute/share pill.
            py = int(PHONE_TOP - pad + (1 - k_in) * HT * 0.6 + k_out * HT * 0.6)
            f.alpha_composite(phones[s], (PHONE_X - pad, py))
            f.alpha_composite(faded(caps[s], k_in * (1 - k_out)), (TEXT_X - 10, cap_y))
        ff.stdin.write(f.convert("RGB").tobytes())
    ff.stdin.close()
    ff.wait()
    print(OUT)


if __name__ == "__main__":
    main()

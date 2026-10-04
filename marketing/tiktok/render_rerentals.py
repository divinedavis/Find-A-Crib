#!/usr/bin/env python3
"""Render 15-second vertical TikTok videos for Find A Crib re-rentals.

Style follows the owner's reference ad: alternating dark / light scenes, a big
two-line headline top-left, one photo under it with a slow zoom, a brand title
card, crossfades. Frames are drawn with PIL and piped to ffmpeg.
"""
import json, subprocess, sys, os
from PIL import Image, ImageDraw, ImageFont, ImageFilter

W, H, FPS = 1080, 1920, 30
SCENE, XF = 2.5, 0.35                       # seconds per scene, crossfade
NAVY, CREAM = (22, 60, 71), (246, 240, 234)
TEAL = (47, 122, 138)
WHITE, INK = (255, 255, 255), (16, 34, 40)
MARGIN = 64
RIGHT_SAFE = 150                            # TikTok's like/comment column
SAFE_BOTTOM = 1500                          # below this: TikTok's caption, username and sound
AV = "/System/Library/Fonts/Avenir Next.ttc"
DEMI, BOLD, MED = 2, 0, 5                   # face indexes in the .ttc (checked below)
LOGO = os.path.expanduser("~/projects/dhcr-map/ios/FindACrib/Resources/Assets.xcassets/AppIcon.appiconset/icon-1024.png")


def font(size, face):
    return ImageFont.truetype(AV, size, index=face)


def fit_lines(draw, lines, face, max_w, start=104, min_size=60):
    s = start
    while s > min_size:
        f = font(s, face)
        if all(draw.textlength(l, font=f) <= max_w for l in lines):
            return f
        s -= 4
    return font(min_size, face)


def cover(img, w, h, zoom=1.0, fx=0.5, fy=0.5):
    """Crop img to w x h (cover), zoomed in by `zoom` around focal fx, fy."""
    iw, ih = img.size
    scale = max(w / iw, h / ih) * zoom
    cw, ch = w / scale, h / scale
    # max(0, …) last: when the photo fits exactly, iw - cw can be -1e-13.
    x0 = max(0.0, min(fx * iw - cw / 2, iw - cw))
    y0 = max(0.0, min(fy * ih - ch / 2, ih - ch))
    return img.resize((w, h), Image.LANCZOS, box=(x0, y0, x0 + cw, y0 + ch))


def headline_scene(photo, lines, bg, fg, t, motion, sub=None):
    im = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(im)
    f = fit_lines(d, lines, DEMI, W - MARGIN - RIGHT_SAFE)
    y = 250
    for l in lines:
        d.text((MARGIN, y), l, font=f, fill=fg)
        y += int(f.size * 1.12)
    # The small note sits under the headline, not under the photo: the
    # bottom ~22% of a TikTok is the caption, username and sound line
    # (owner, 2026-10-04: "there is text being overlapped by our caption").
    if sub:
        sf = font(40, MED)
        d.text((MARGIN, y + 6), sub, font=sf, fill=fg)
        y += 6 + int(sf.size * 1.3)
    ph_y = max(y + 40, 560)
    ph_h = min(1000, SAFE_BOTTOM - ph_y)     # the photo ends where the caption starts
    z0, z1, fx0, fx1 = motion
    z = z0 + (z1 - z0) * t
    fx = fx0 + (fx1 - fx0) * t
    im.paste(cover(photo, W, ph_h, z, fx, 0.5), (0, ph_y))
    return im


def pill(d, cx, cy, text, f, bg, fg, pad=(44, 22)):
    tw = d.textlength(text, font=f)
    x0, y0 = cx - tw / 2 - pad[0], cy - f.size / 2 - pad[1]
    d.rounded_rectangle((x0, y0, cx + tw / 2 + pad[0], cy + f.size / 2 + pad[1] + 6), radius=18, fill=bg)
    d.text((cx - tw / 2, y0 + pad[1] - 2), text, font=f, fill=fg)


def title_card(big, small, button):
    im = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(im)
    cx = (W - RIGHT_SAFE + MARGIN) / 2 + 20
    f = fit_lines(d, [big], BOLD, W - 2 * MARGIN - RIGHT_SAFE, start=120)
    d.text((cx - d.textlength(big, font=f) / 2, 700), big, font=f, fill=INK)
    sf = fit_lines(d, [small], MED, W - 2 * MARGIN - RIGHT_SAFE, start=64, min_size=40)
    d.text((cx - d.textlength(small, font=sf) / 2, 700 + f.size + 24), small, font=sf, fill=INK)
    pill(d, cx, 700 + f.size + sf.size + 150, button, font(44, DEMI), NAVY, WHITE)
    return im


def end_card():
    im = Image.new("RGB", (W, H), CREAM)
    d = ImageDraw.Draw(im)
    cx = (W - RIGHT_SAFE + MARGIN) / 2 + 20
    logo = Image.open(LOGO).convert("RGBA").resize((220, 220), Image.LANCZOS)
    m = Image.new("L", logo.size, 0); ImageDraw.Draw(m).rounded_rectangle((0, 0, 220, 220), radius=50, fill=255)
    im.paste(logo, (int(cx - 110), 560), m)
    f = font(104, BOLD)
    d.text((cx - d.textlength("FIND A CRIB", font=f) / 2, 830), "FIND A CRIB", font=f, fill=INK)
    sf = font(50, MED)
    for k, l in enumerate(["Every NYC re-rental,", "updated every day"]):
        d.text((cx - d.textlength(l, font=sf) / 2, 970 + k * 66), l, font=sf, fill=INK)
    pill(d, cx, 1210, "findacrib.com", font(48, DEMI), NAVY, WHITE)
    return im


def render(spec, out):
    photo = Image.open(spec["photo"]).convert("RGB")
    if photo.width < 1200:
        raise SystemExit(f"{spec['photo']}: {photo.width}px wide — too small, it will look pixelated")
    photo.thumbnail((2400, 2400), Image.LANCZOS)   # 6000px originals: same look, 6x faster frames
    fx = spec.get("fx", 0.5)
    scenes = [
        lambda t: headline_scene(photo, spec["hook"], NAVY, WHITE, t, (1.00, 1.10, fx, fx)),
        lambda t: title_card(spec["address"], spec["place"], "Re-renting now"),
        lambda t: headline_scene(photo, ["Affordable", "re-rental"], CREAM, INK, t, (1.12, 1.12, fx - 0.12, fx + 0.12)),
        lambda t: headline_scene(photo, spec["price"], NAVY, WHITE, t, (1.10, 1.02, fx + 0.08, fx - 0.06), sub=spec.get("sub")),
        lambda t: headline_scene(photo, ["Apply directly", "with the agent"], CREAM, INK, t, (1.18, 1.05, fx - 0.05, fx + 0.05)),
        lambda t: end_card(),
    ]
    n = len(scenes)
    total = n * SCENE
    frames = int(total * FPS)
    cache = {}
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                          "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                          "-pix_fmt", "yuv420p", "-movflags", "+faststart", out], stdin=subprocess.PIPE)
    for i in range(frames):
        ts = i / FPS
        k = min(int(ts // SCENE), n - 1)
        local = (ts - k * SCENE) / SCENE
        def draw(idx, lt):
            if idx in (1, 5):                      # static cards: draw once
                if idx not in cache: cache[idx] = scenes[idx](0)
                return cache[idx]
            return scenes[idx](min(max(lt, 0), 1))
        frame = draw(k, local)
        into_next = ts - (k + 1) * SCENE + XF       # crossfade over the last XF s of a scene
        if k + 1 < n and into_next > 0:
            a = into_next / XF
            nxt = draw(k + 1, 0)
            frame = Image.blend(frame, nxt, a)
        p.stdin.write(frame.tobytes())
    p.stdin.close(); p.wait()
    return p.returncode


if __name__ == "__main__":
    specs = json.load(open(sys.argv[1]))
    only = sys.argv[2] if len(sys.argv) > 2 else None
    for s in specs:
        if only and s["slug"] != only: continue
        out = os.path.join(os.path.dirname(sys.argv[1]), "out", f"{s['day']}-{s['slug']}.mp4")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        print(out, render(s, out), flush=True)

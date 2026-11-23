"""go24 technology - 13-second vertical Reel from one news item (1080x1920, 30 fps).

Scenes (each its own encoded file, joined with the concat demuxer):
  1  0.0-3.5s  photo with slow zoom, kicker, Montenegrin headline slides in
  2  3.5-7.5s  key number (item["stat"]) counting up, or the first Montenegrin points
  3  7.5-11.0s English headline and the first English point
  4 11.0-13.0s follow card with the logo
Sound: an original synthesized beat (no third-party music).

Usage: python go24/reel.py <item.json> <out.mp4>
item may carry "stat": {"value": 3.79, "prefix": "", "suffix": " mlrd $", "decimals": 2,
                        "label_me": "prodaja prvog dana", "label_en": "day-one sales"}
"""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from images import attach_image  # noqa: E402
from render import (ACCENT, BG, GREY, M, WHITE, crop_fill, draw_lines, draw_tracked, fit, font,  # noqa: E402
                    grade, vgradient, wordmark, wrap)

W, H, FPS = 1080, 1920, 30
SAFE_TOP, SAFE_BOTTOM = 250, 1480  # keep text clear of Reels UI
SCENES = [3.5, 4.0, 3.5, 2.0]
FADE = 6  # frames of dip-to-dark at scene edges


def ease(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def appear(t: float, start: float, dur: float = 0.45) -> float:
    return ease((t - start) / dur)


def layer_text(base: Image.Image, draw_fn, alpha: float, dy: float = 0):
    """Draws onto a transparent layer, then composites it with alpha and vertical offset."""
    if alpha <= 0:
        return base
    lay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(lay), lay)
    if dy:
        lay = lay.transform(lay.size, Image.AFFINE, (1, 0, 0, 0, 1, -dy))
    if alpha < 1:
        a = lay.getchannel("A").point(lambda v: int(v * alpha))
        lay.putalpha(a)
    base = base.convert("RGBA")
    base.alpha_composite(lay)
    return base.convert("RGB")


def dip(img: Image.Image, frame: int, total: int) -> Image.Image:
    k = 1.0
    if frame < FADE:
        k = frame / FADE
    elif frame >= total - FADE:
        k = (total - 1 - frame) / FADE
    if k >= 1:
        return img
    return Image.blend(Image.new("RGB", img.size, BG), img, max(0.0, k))


class Reel:
    def __init__(self, item: dict):
        self.item = item
        src = item.get("_image")
        self.has_photo = src is not None
        if self.has_photo:
            self.photo = grade(crop_fill(src, int(W * 1.12), int(H * 0.72 * 1.12), (0.5, 0.4)))
            self.blur = grade(crop_fill(src, W, H, (0.5, 0.4))).filter(ImageFilter.GaussianBlur(28))
            self.blur = Image.blend(self.blur, Image.new("RGB", (W, H), BG), 0.72)
        else:
            self.photo = None
            self.blur = Image.new("RGB", (W, H), BG)
        self.fade_mask = vgradient(W, int(H * 0.72), [(0, 0), (0.5, 0), (1, 255)])
        self.top_mask = vgradient(W, int(H * 0.72), [(0, 200), (0.2, 150), (0.32, 0), (1, 0)])

    # ------------------------------------------------------------ backgrounds
    def photo_bg(self, t: float, dur: float) -> Image.Image:
        canvas = Image.new("RGB", (W, H), BG)
        if not self.has_photo:
            return self.blur.copy()
        z = 1.0 + 0.08 * (t / dur)
        pw, ph = self.photo.size
        cw, ch = int(W * 1.12 / z), int(H * 0.72 * 1.12 / z)
        x0, y0 = (pw - cw) // 2, int((ph - ch) * 0.4)
        ph_img = self.photo.crop((x0, y0, x0 + cw, y0 + ch)).resize((W, int(H * 0.72)), Image.BILINEAR)
        shade = Image.new("RGB", ph_img.size, BG)
        ph_img = Image.composite(shade, ph_img, self.top_mask)
        ph_img = Image.composite(shade, ph_img, self.fade_mask)
        canvas.paste(ph_img, (0, 0))
        return canvas

    def header(self, img: Image.Image):
        wordmark(img, M, SAFE_TOP - 20, 1.15)

    # ------------------------------------------------------------ scenes
    def scene1(self, t, dur):
        it = self.item
        img = self.photo_bg(t, dur)
        self.header(img)
        d = ImageDraw.Draw(img)
        f, lines, lh = fit(d, it["title_me"], "InterDisplay-Bold", W - 2 * M, 420, 92, 60, 5, 1.05)
        block = 34 + 34 + lh * len(lines)
        y0 = SAFE_BOTTOM - block

        def k(dr, lay):
            kx = M
            dr.rectangle((kx, y0 + 13, kx + 40, y0 + 16), fill=ACCENT)
            draw_tracked(dr, (kx + 54, y0), it["category"]["me"].upper(), font("Inter-SemiBold", 26), ACCENT, 5)

        def ttl(dr, lay):
            draw_lines(dr, M, y0 + 68, lines, f, lh, WHITE)

        a1, a2 = appear(t, 0.25), appear(t, 0.55, 0.55)
        img = layer_text(img, k, a1, (1 - a1) * 30)
        img = layer_text(img, ttl, a2, (1 - a2) * 60)
        return img

    def scene2(self, t, dur):
        it = self.item
        img = self.blur.copy()
        self.header(img)
        stat = it.get("stat")
        if stat:
            v = stat["value"] * ease(t / 1.6)
            txt = f"{stat.get('prefix', '')}{v:,.{stat.get('decimals', 0)}f}{stat.get('suffix', '')}"
            txt = txt.replace(",", "X").replace(".", ",").replace("X", ".")  # 3,79 style
            fbig = font("InterDisplay-Black", 170)
            while ImageDraw.Draw(img).textlength(txt, font=fbig) > W - 2 * M and fbig.size > 90:
                fbig = font("InterDisplay-Black", fbig.size - 8)

            def num(dr, lay):
                dr.text((M, 620), txt, font=fbig, fill=ACCENT)
                dr.text((M, 620 + fbig.size + 30), stat["label_me"], font=font("InterDisplay-Bold", 64), fill=WHITE)
                dr.text((M, 620 + fbig.size + 120), stat["label_en"], font=font("Inter-Regular", 44), fill=GREY)

            img = layer_text(img, num, appear(t, 0.0, 0.3))
            pts = it["points_me"][1:3]
            y = 1180
        else:
            pts = it["points_me"][:3]
            y = 560
        fp = font("Inter-Medium", 46)
        for i, p in enumerate(pts):
            ls = wrap(ImageDraw.Draw(img), p, fp, W - 2 * M - 50)
            yy = y

            def pt(dr, lay, ls=ls, yy=yy):
                dr.rectangle((M, yy + 30, M + 26, yy + 34), fill=ACCENT)
                draw_lines(dr, M + 50, yy, ls, fp, 64, (232, 235, 240))

            a = appear(t, (1.4 if stat else 0.3) + i * 0.7)
            img = layer_text(img, pt, a, (1 - a) * 30)
            y += 64 * len(ls) + 40
        return img

    def scene3(self, t, dur):
        it = self.item
        img = self.blur.copy()
        self.header(img)
        d = ImageDraw.Draw(img)
        f, lines, lh = fit(d, it["title_en"], "InterDisplay-Bold", W - 2 * M, 400, 88, 58, 5, 1.06)
        fp = font("Inter-Regular", 44)
        pl = wrap(d, it["points_en"][0], fp, W - 2 * M)
        y0 = 560

        def lab(dr, lay):
            dr.rectangle((M, y0 + 13, M + 40, y0 + 16), fill=ACCENT)
            draw_tracked(dr, (M + 54, y0), "IN ENGLISH", font("Inter-SemiBold", 26), ACCENT, 5)

        def ttl(dr, lay):
            draw_lines(dr, M, y0 + 70, lines, f, lh, WHITE)

        def pt(dr, lay):
            draw_lines(dr, M, y0 + 70 + lh * len(lines) + 50, pl, fp, 62, GREY)

        for fn, st in ((lab, 0.1), (ttl, 0.3), (pt, 0.9)):
            a = appear(t, st)
            img = layer_text(img, fn, a, (1 - a) * 40)
        return img

    def scene4(self, t, dur):
        img = Image.new("RGB", (W, H), BG)
        glow = Image.new("RGB", (W, H), BG)
        ImageDraw.Draw(glow).ellipse((W * 0.1, H * 0.25, W * 0.9, H * 0.6), fill=(34, 52, 20))
        img = Image.blend(img, glow.filter(ImageFilter.GaussianBlur(160)), 0.8)
        s = 0.92 + 0.08 * ease(t / 0.6)

        def logo(dr, lay):
            fb = font("InterDisplay-Black", int(250 * s))
            wg, w24 = dr.textlength("go", font=fb), dr.textlength("24", font=fb)
            x = (W - wg - w24) / 2
            y = 640
            dr.text((x, y), "go", font=fb, fill=WHITE)
            dr.text((x + wg, y), "24", font=fb, fill=ACCENT)
            fs = font("Inter-SemiBold", 36)
            tw = sum(dr.textlength(c, font=fs) for c in "TECHNOLOGY") + 14 * 9
            draw_tracked(dr, ((W - tw) / 2, y + int(310 * s)), "TECHNOLOGY", fs, (200, 206, 214), 14)

        def cta(dr, lay):
            for i, (txt, f, col) in enumerate((
                ("Zaprati za dnevne tech vijesti", font("InterDisplay-Bold", 54), WHITE),
                ("Follow for daily tech news", font("Inter-Regular", 42), GREY),
            )):
                tw = dr.textlength(txt, font=f)
                dr.text(((W - tw) / 2, 1130 + i * 80), txt, font=f, fill=col)

        img = layer_text(img, logo, appear(t, 0.0, 0.4))
        a = appear(t, 0.4)
        img = layer_text(img, cta, a, (1 - a) * 30)
        return img

    # ------------------------------------------------------------ output
    def render(self, out: Path):
        tmp = Path(tempfile.mkdtemp(prefix="reel-"))
        parts = []
        for idx, (fn, dur) in enumerate(zip((self.scene1, self.scene2, self.scene3, self.scene4), SCENES), 1):
            n = int(round(dur * FPS))
            part, part_tmp = tmp / f"s{idx}.mp4", tmp / f"s{idx}.part.mp4"
            proc = subprocess.Popen(
                ["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                 "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
                 "-pix_fmt", "yuv420p", "-r", str(FPS), str(part_tmp)],
                stdin=subprocess.PIPE,
            )
            for i in range(n):
                frame = dip(fn(i / FPS, dur), i, n)
                proc.stdin.write(frame.tobytes())
            proc.stdin.close()
            if proc.wait() != 0:
                raise SystemExit(f"scene {idx} failed")
            part_tmp.rename(part)
            parts.append(part)
        lst = tmp / "list.txt"
        lst.write_text("".join(f"file '{p}'\n" for p in parts))
        silent = tmp / "video.mp4"
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                        "-c", "copy", str(silent)], check=True)
        wav = tmp / "beat.wav"
        synth_beat(wav, sum(SCENES))
        out_tmp = out.with_suffix(".part.mp4")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(silent), "-i", str(wav), "-map", "0:v",
                        "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest",
                        "-movflags", "+faststart", str(out_tmp)], check=True)
        out_tmp.rename(out)
        return out


def synth_beat(path: Path, seconds: float, sr: int = 44100, bpm: int = 100):
    """Original, royalty-free background: soft kick, hats and a minor-chord pad."""
    n = int(seconds * sr)
    t = np.arange(n) / sr
    beat = 60 / bpm
    out = np.zeros(n)
    # pad: Am - F - C - G, one chord per bar
    chords = [(220.0, 261.63, 329.63), (174.61, 220.0, 261.63), (130.81, 196.0, 261.63), (196.0, 246.94, 293.66)]
    bar = beat * 4
    for ci in range(int(seconds / bar) + 1):
        s0, s1 = int(ci * bar * sr), min(n, int((ci + 1) * bar * sr))
        if s0 >= n:
            break
        tt = t[s0:s1] - ci * bar
        env = np.minimum(1, tt / 0.4) * np.minimum(1, (bar - tt) / 0.4)
        for f in chords[ci % 4]:
            out[s0:s1] += 0.06 * env * (np.sin(2 * np.pi * f * tt) + 0.5 * np.sin(2 * np.pi * f * 1.003 * tt))
    # kick on every beat, hat on off-beats
    rng = np.random.default_rng(24)
    for bi in range(int(seconds / beat) + 1):
        s0 = int(bi * beat * sr)
        if s0 >= n:
            break
        L = min(int(0.35 * sr), n - s0)
        kt = np.arange(L) / sr
        freq = 50 + 90 * np.exp(-kt * 30)
        out[s0:s0 + L] += 0.5 * np.sin(2 * np.pi * np.cumsum(freq) / sr) * np.exp(-kt * 9)
        h0 = int((bi + 0.5) * beat * sr)
        if h0 < n:
            HL = min(int(0.05 * sr), n - h0)
            hn = rng.standard_normal(HL)
            hn = hn - np.convolve(hn, np.ones(4) / 4, mode="same")
            out[h0:h0 + HL] += 0.08 * hn * np.exp(-np.arange(HL) / sr * 70)
    fade = np.minimum(1, t / 0.5) * np.minimum(1, (seconds - t) / 1.0)
    out *= fade
    out = 0.55 * out / max(1e-9, np.max(np.abs(out)))
    pcm = (np.stack([out, out], axis=1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


if __name__ == "__main__":
    item = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    attach_image(item)
    print(Reel(item).render(Path(sys.argv[2])))

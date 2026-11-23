"""go24 technology - news card renderer (editorial layout).

From one news item it produces Instagram-ready JPEGs:
  feed carousel: cover (photo + MNE/EN headline), MNE detail, EN detail -> 1080x1350
  story: one vertical card                                             -> 1080x1920

Item fields:
  id, date (YYYY-MM-DD), category {"me","en"}, title_me, title_en,
  points_me[], points_en[], story_me, story_en, source,
  image {"url" | "page", "credit"}   (optional; resolved by images.py)
  _image: PIL.Image (set by build_day after download; text-only layout when missing)
"""
from __future__ import annotations

import os
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"
LOGO = ROOT / "brand" / "logo.png"  # optional; text wordmark is drawn when missing

BG = (9, 12, 18)
WHITE = (246, 247, 249)
GREY = (158, 166, 178)
DIM = (110, 118, 130)
RULE = (40, 47, 58)
ACCENT = (182, 255, 59)  # go24 lime

W_FEED, H_FEED = 1080, 1350
W_STORY, H_STORY = 1080, 1920
M = 84  # side margin


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / f"{name}.otf"), size)


# ------------------------------------------------------------------ text
def draw_tracked(draw, xy, text, f, fill, tracking=0):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=f, fill=fill)
        x += draw.textlength(ch, font=f) + tracking
    return x


def tracked_w(draw, text, f, tracking):
    return sum(draw.textlength(c, font=f) for c in text) + tracking * max(0, len(text) - 1)


def _keep_together(text):
    # "30. juna", "5 G" style pairs never split across lines
    text = re.sub(r"(\b\d+\.?)\s+(?=\S)", "\\1\u00a0", text.strip())
    # one-letter words (i, u, a, s, k, o...) never end a line - Montenegrin typography
    return re.sub(r"(?:(?<=\s)|^)([iuaskoIUASKOv])\s+(?=\S)", "\\1\u00a0", text)


def _wrap_greedy(draw, text, f, max_w):
    lines, cur = [], ""
    for w in [t for t in _keep_together(text).split(" ") if t]:
        t = f"{cur} {w}".strip()
        if draw.textlength(t, font=f) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def wrap(draw, text, f, max_w):
    """Greedy wrap; if the last line is a lone word, even the lines out."""
    lines = _wrap_greedy(draw, text, f, max_w)
    if len(lines) < 2 or len([t for t in lines[-1].split(" ") if t]) > 1:
        return lines
    lo, hi = int(max_w * 0.55), max_w
    while lo < hi:
        mid = (lo + hi) // 2
        if len(_wrap_greedy(draw, text, f, mid)) == len(lines):
            hi = mid
        else:
            lo = mid + 1
    return _wrap_greedy(draw, text, f, hi)


def fit(draw, text, font_name, max_w, max_h, size_max, size_min, max_lines, leading):
    for size in range(size_max, size_min - 1, -2):
        f = font(font_name, size)
        lines = wrap(draw, text, f, max_w)
        lh = int(size * leading)
        if len(lines) <= max_lines and lh * len(lines) <= max_h:
            return f, lines, lh
    f = font(font_name, size_min)
    return f, wrap(draw, text, f, max_w)[:max_lines], int(size_min * leading)


def draw_lines(draw, x, y, lines, f, lh, fill):
    for i, line in enumerate(lines):
        draw.text((x, y + i * lh), line, font=f, fill=fill)
    return y + lh * len(lines)


# ------------------------------------------------------------------ image
def crop_fill(img: Image.Image, w: int, h: int, focus=(0.5, 0.45)) -> Image.Image:
    img = img.convert("RGB")
    scale = max(w / img.width, h / img.height)
    nw, nh = int(img.width * scale + 0.5), int(img.height * scale + 0.5)
    img = img.resize((nw, nh), Image.LANCZOS)
    x = int((nw - w) * focus[0])
    y = int((nh - h) * focus[1])
    return img.crop((x, y, x + w, y + h))


def grade(img: Image.Image) -> Image.Image:
    """Gentle, consistent look across very different source photos."""
    img = ImageEnhance.Color(img).enhance(0.92)
    img = ImageEnhance.Contrast(img).enhance(1.05)
    return img


def vgradient(w, h, stops):
    """Vertical alpha mask from [(y_frac, alpha 0-255), ...]."""
    mask = Image.new("L", (1, h))
    px = mask.load()
    for y in range(h):
        t = y / max(1, h - 1)
        for (t0, a0), (t1, a1) in zip(stops, stops[1:]):
            if t0 <= t <= t1:
                k = 0 if t1 == t0 else (t - t0) / (t1 - t0)
                k = k * k * (3 - 2 * k)  # smoothstep
                px[0, y] = int(a0 + (a1 - a0) * k)
                break
    return mask.resize((w, h))


def photo_canvas(item, w, h, photo_h, focus=(0.5, 0.45), dim=0.0, header_y=60) -> Image.Image:
    """Dark canvas with the photo at the top fading into the background."""
    canvas = Image.new("RGB", (w, h), BG)
    src = item.get("_image")
    if src is None:
        glow = Image.new("RGB", (w, h), BG)
        gd = ImageDraw.Draw(glow)
        r = int(w * 0.55)
        gd.ellipse((w - r, -r // 2, w + r, r + r // 2), fill=(30, 44, 22))
        return Image.blend(canvas, glow.filter(ImageFilter.GaussianBlur(r // 2)), 0.6)
    ph = grade(crop_fill(src, w, photo_h, focus))
    if dim:
        ph = Image.blend(ph, Image.new("RGB", ph.size, BG), dim)
    # darken top for logo legibility, fade bottom into background
    shade = Image.new("RGB", (w, photo_h), BG)
    hold, end = (header_y + 90) / photo_h, (header_y + 260) / photo_h
    top = vgradient(w, photo_h, [(0, 200), (min(0.8, hold), 165), (min(0.9, end), 0), (1, 0)])
    ph = Image.composite(shade, ph, top)
    canvas.paste(ph, (0, 0))
    fade = vgradient(w, photo_h, [(0, 0), (0.45, 0), (1, 255)])
    canvas.paste(Image.composite(Image.new("RGB", (w, photo_h), BG), ph, fade), (0, 0))
    return canvas


# ------------------------------------------------------------------ pieces
def wordmark(img, x, y, scale=1.0):
    if LOGO.exists():
        logo = Image.open(LOGO).convert("RGBA")
        th = int(64 * scale)
        logo = logo.resize((int(logo.width * th / logo.height), th), Image.LANCZOS)
        img.paste(logo, (x, y), logo)
        return
    d = ImageDraw.Draw(img)
    f = font("InterDisplay-Black", int(44 * scale))
    d.text((x, y), "go", font=f, fill=WHITE)
    d.text((x + d.textlength("go", font=f) + 1, y), "24", font=f, fill=ACCENT)
    small = font("Inter-SemiBold", int(13 * scale))
    draw_tracked(d, (x + 2, y + int(57 * scale)), "TECHNOLOGY", small, (205, 210, 218), int(5 * scale))


def fmt_date(iso):
    y, m, dd = iso.split("-")
    return f"{dd}.{m}.{y}."


def header(img, item, w, y=60, scale=1.0):
    d = ImageDraw.Draw(img)
    wordmark(img, M, y, scale)
    f = font("Inter-Medium", int(24 * scale))
    ds = fmt_date(item["date"])
    d.text((w - M - d.textlength(ds, font=f), y + int(14 * scale)), ds, font=f, fill=(215, 220, 228))


def kicker(img, x, y, label, scale=1.0):
    """Thin lime rule + small tracked label (no pill, no fill)."""
    d = ImageDraw.Draw(img)
    f = font("Inter-SemiBold", int(22 * scale))
    rule = int(36 * scale)
    d.rectangle((x, y + int(12 * scale), x + rule, y + int(14 * scale)), fill=ACCENT)
    draw_tracked(d, (x + rule + int(14 * scale), y), label.upper(), f, ACCENT, int(4 * scale))
    return y + int(30 * scale)


def credit_line(item):
    if item.get("footer_text"):
        return item["footer_text"]
    parts = []
    img = item.get("image") or {}
    if item.get("_image") is not None and img.get("credit"):
        parts.append(f"Foto: {img['credit']}")
    parts.append(f"Izvor: {item['source']}")
    return "  ·  ".join(parts)


def footer(img, item, w, y, right=None):
    d = ImageDraw.Draw(img)
    f = font("Inter-Regular", 21)
    text = credit_line(item)
    max_w = w - 2 * M - (160 if right else 0)
    while d.textlength(text, font=f) > max_w and len(text) > 10:
        text = text[:-2]
    d.text((M, y), text, font=f, fill=DIM)
    if right:
        fr = font("Inter-Medium", 21)
        d.text((w - M - d.textlength(right, font=fr), y), right, font=fr, fill=GREY)


def save(img, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=92, optimize=True, subsampling=0)


# ------------------------------------------------------------------ cards
def render_cover(item, out: Path):
    W, H = W_FEED, H_FEED
    has_photo = item.get("_image") is not None
    img = photo_canvas(item, W, H, 900, item.get("image", {}).get("focus", (0.5, 0.4)))
    d = ImageDraw.Draw(img)
    header(img, item, W)

    max_w = W - 2 * M
    f_me, l_me, lh_me = fit(d, item["title_me"], "InterDisplay-Bold", max_w, 330, 80, 52, 4, 1.06)
    f_en, l_en, lh_en = fit(d, item["title_en"], "Inter-Regular", max_w, 120, 34, 28, 3, 1.28)

    bottom = H - 120
    block = 30 + 30 + lh_me * len(l_me) + 26 + lh_en * len(l_en)
    y = bottom - block if has_photo else max(300, (H - block) // 2 - 20)
    y = kicker(img, M, y, item["category"]["me"]) + 30
    y = draw_lines(d, M, y, l_me, f_me, lh_me, WHITE) + 26
    draw_lines(d, M, y, l_en, f_en, lh_en, GREY)

    footer(img, item, W, H - 76, "1/3  →")
    save(img, out)


def render_detail(item, lang, page, out: Path):
    W, H = W_FEED, H_FEED
    img = photo_canvas(item, W, H, 330, item.get("image", {}).get("focus", (0.5, 0.4)), dim=0.62)
    d = ImageDraw.Draw(img)
    header(img, item, W)

    label = (item.get("detail_label") or {"me": "Šta se desilo", "en": "What happened"})[lang]
    max_w = W - 2 * M
    y = 300
    y = kicker(img, M, y, label) + 30
    f_t, l_t, lh_t = fit(d, item[f"title_{lang}"], "InterDisplay-Bold", max_w, 190, 50, 38, 3, 1.1)
    y = draw_lines(d, M, y, l_t, f_t, lh_t, WHITE) + 34
    d.line((M, y, W - M, y), fill=RULE, width=2)
    y += 40

    points = item[f"points_{lang}"]
    bottom = H - 140
    for size in range(36, 25, -2):
        fp = font("Inter-Regular", size)
        lh, gap = int(size * 1.4), int(size * 0.8)
        wrapped = [wrap(d, p, fp, max_w - 46) for p in points]
        if y + sum(len(wl) * lh for wl in wrapped) + gap * (len(points) - 1) <= bottom:
            break
    for wl in wrapped:
        d.rectangle((M, y + int(size * 0.62), M + 22, y + int(size * 0.62) + 3), fill=ACCENT)
        y = draw_lines(d, M + 46, y, wl, fp, lh, (226, 230, 236)) + gap

    footer(img, item, W, H - 76, page)
    save(img, out)


def render_story(item, out: Path):
    W, H = W_STORY, H_STORY
    has_photo = item.get("_image") is not None
    img = photo_canvas(item, W, H, 1240, item.get("image", {}).get("focus", (0.5, 0.4)), header_y=230)
    d = ImageDraw.Draw(img)
    header(img, item, W, y=230, scale=1.15)

    max_w = W - 2 * M
    f_me, l_me, lh_me = fit(d, item["title_me"], "InterDisplay-Bold", max_w, 420, 92, 58, 5, 1.05)
    f_en, l_en, lh_en = fit(d, item["title_en"], "Inter-Regular", max_w, 150, 40, 32, 3, 1.28)
    fs = font("Inter-Regular", 34)
    lh_s = int(34 * 1.38)
    s_me = wrap(d, item.get("story_me", ""), fs, max_w) if item.get("story_me") else []

    bottom = 1600
    block = 34 + 34 + lh_me * len(l_me) + 28 + lh_en * len(l_en) + (48 + lh_s * len(s_me) if s_me else 0)
    y = bottom - block if has_photo else max(520, (H - block) // 2)
    y = kicker(img, M, y, item["category"]["me"], scale=1.1) + 34
    y = draw_lines(d, M, y, l_me, f_me, lh_me, WHITE) + 28
    y = draw_lines(d, M, y, l_en, f_en, lh_en, GREY)
    if s_me:
        y += 48
        draw_lines(d, M, y, s_me, fs, lh_s, (226, 230, 236))

    footer(img, item, W, 1660, "Više na profilu  →")
    save(img, out)


def render_item(item: dict, outdir: Path) -> dict:
    base = outdir / item["id"]
    car = [Path(f"{base}-{i}.jpg") for i in (1, 2, 3)]
    story = Path(f"{base}-story.jpg")
    render_cover(item, car[0])
    render_detail(item, "me", "2/3", car[1])
    render_detail(item, "en", "3/3", car[2])
    render_story(item, story)
    rel = lambda p: os.path.relpath(p, ROOT)
    return {"carousel": [rel(p) for p in car], "story": rel(story)}


if __name__ == "__main__":
    import json
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from images import attach_image

    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    outdir = Path(sys.argv[2])
    for it in data if isinstance(data, list) else [data]:
        attach_image(it)
        print(json.dumps(render_item(it, outdir), ensure_ascii=False))

"""go24 technology - news card renderer.

Produces Instagram-ready JPEGs from one news item:
  feed carousel: cover (MNE + EN headline), MNE detail, EN detail  -> 1080x1350
  story: one vertical card                                        -> 1080x1920

Item format (dict):
{
  "id": "2026-11-23-01",
  "date": "2026-11-23",
  "category": {"me": "GAMING", "en": "GAMING"},
  "title_me": "...", "title_en": "...",
  "points_me": ["...", "..."], "points_en": ["...", "..."],
  "story_me": "one short line", "story_en": "one short line",
  "source": "Take-Two Interactive"
}
"""
from __future__ import annotations

import math
import os
from datetime import date as _date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = ROOT / "fonts"
LOGO = ROOT / "brand" / "logo.png"  # optional; wordmark is drawn when missing

# Brand palette
BG = (10, 14, 22)
GRID = (26, 34, 48)
WHITE = (245, 247, 250)
GREY = (150, 160, 175)
ACCENT = (182, 255, 59)      # lime
ACCENT_DARK = (12, 16, 10)

W_FEED, H_FEED = 1080, 1350
W_STORY, H_STORY = 1080, 1920
MARGIN = 80


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / f"{name}.otf"), size)


# ---------------------------------------------------------------- helpers
def text_w(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, tracking: int = 0) -> int:
    if not text:
        return 0
    w = draw.textlength(text, font=f)
    return int(w + tracking * (len(text) - 1))


def draw_tracked(draw, xy, text, f, fill, tracking=0):
    x, y = xy
    if tracking == 0:
        draw.text((x, y), text, font=f, fill=fill)
        return
    for ch in text:
        draw.text((x, y), ch, font=f, fill=fill)
        x += draw.textlength(ch, font=f) + tracking


def wrap(draw, text: str, f, max_w: int) -> list[str]:
    """Greedy wrap; if the last line is a lone word, narrow the box so lines come out even."""
    lines = _wrap_greedy(draw, text, f, max_w)
    if len(lines) < 2 or len(lines[-1].split()) > 1:
        return lines
    lo, hi = int(max_w * 0.55), max_w
    while lo < hi:  # smallest width that keeps the same number of lines
        mid = (lo + hi) // 2
        if len(_wrap_greedy(draw, text, f, mid)) == len(lines):
            hi = mid
        else:
            lo = mid + 1
    return _wrap_greedy(draw, text, f, hi)


def _wrap_greedy(draw, text: str, f, max_w: int) -> list[str]:
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = f"{cur} {w}".strip()
        if draw.textlength(test, font=f) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def fit(draw, text, font_name, max_w, max_h, size_max, size_min, max_lines, leading=1.08):
    """Largest font size whose wrapped text fits in the box."""
    for size in range(size_max, size_min - 1, -2):
        f = font(font_name, size)
        lines = wrap(draw, text, f, max_w)
        lh = int(size * leading)
        if len(lines) <= max_lines and lh * len(lines) <= max_h:
            return f, lines, lh
    f = font(font_name, size_min)
    lines = wrap(draw, text, f, max_w)[:max_lines]
    return f, lines, int(size_min * leading)


def draw_lines(draw, x, y, lines, f, lh, fill):
    for i, line in enumerate(lines):
        draw.text((x, y + i * lh), line, font=f, fill=fill)
    return y + lh * len(lines)


def background(w: int, h: int, glow_xy: tuple[float, float]) -> Image.Image:
    img = Image.new("RGB", (w, h), BG)
    # soft accent glow
    glow = Image.new("RGB", (w, h), BG)
    gd = ImageDraw.Draw(glow)
    gx, gy = int(glow_xy[0] * w), int(glow_xy[1] * h)
    r = int(max(w, h) * 0.42)
    gd.ellipse((gx - r, gy - r, gx + r, gy + r), fill=(40, 62, 22))
    glow = glow.filter(ImageFilter.GaussianBlur(r // 2))
    img = Image.blend(img, glow, 0.55)
    # dot grid
    d = ImageDraw.Draw(img)
    step = 36
    for yy in range(step // 2, h, step):
        for xx in range(step // 2, w, step):
            d.ellipse((xx - 1.5, yy - 1.5, xx + 1.5, yy + 1.5), fill=GRID)
    return img


def wordmark(img: Image.Image, x: int, y: int, scale: float = 1.0) -> int:
    """Draws the logo (or a text wordmark). Returns bottom y."""
    if LOGO.exists():
        logo = Image.open(LOGO).convert("RGBA")
        target_h = int(86 * scale)
        ratio = target_h / logo.height
        logo = logo.resize((int(logo.width * ratio), target_h), Image.LANCZOS)
        img.paste(logo, (x, y), logo)
        return y + target_h
    d = ImageDraw.Draw(img)
    f = font("InterDisplay-Black", int(58 * scale))
    d.text((x, y), "go", font=f, fill=WHITE)
    gx = x + d.textlength("go", font=f) + 2
    d.text((gx, y), "24", font=f, fill=ACCENT)
    small = font("Inter-SemiBold", int(17 * scale))
    draw_tracked(d, (x + 3, y + int(74 * scale)), "TECHNOLOGY", small, GREY, tracking=int(6 * scale))
    return y + int(90 * scale)


def fmt_date(iso: str) -> str:
    y, m, dd = iso.split("-")
    return f"{dd}.{m}.{y}."


def chip(img, x, y, label, scale=1.0) -> int:
    d = ImageDraw.Draw(img)
    f = font("Inter-Bold", int(24 * scale))
    tr = int(3 * scale)
    tw = text_w(d, label, f, tr)
    px, py = int(20 * scale), int(12 * scale)
    h = int(24 * scale) + 2 * py
    d.rounded_rectangle((x, y, x + tw + 2 * px, y + h), radius=h // 2, fill=ACCENT)
    draw_tracked(d, (x + px, y + py - int(3 * scale)), label, f, ACCENT_DARK, tracking=tr)
    return y + h


def top_bar(img, item, w):
    d = ImageDraw.Draw(img)
    wordmark(img, MARGIN, 64)
    f = font("Inter-Medium", 26)
    ds = fmt_date(item["date"])
    d.text((w - MARGIN - d.textlength(ds, font=f), 78), ds, font=f, fill=GREY)


def footer(img, item, h, right_text=None, w=W_FEED, y=None):
    d = ImageDraw.Draw(img)
    f = font("Inter-Medium", 24)
    y = y if y is not None else h - 96
    d.line((MARGIN, y - 28, w - MARGIN, y - 28), fill=(38, 46, 60), width=2)
    src = f"Izvor / Source: {item['source']}"
    lines = wrap(d, src, f, w - 2 * MARGIN - 260)
    d.text((MARGIN, y), lines[0], font=f, fill=GREY)
    if right_text:
        fb = font("Inter-SemiBold", 24)
        d.text((w - MARGIN - d.textlength(right_text, font=fb), y), right_text, font=fb, fill=ACCENT)


def save(img: Image.Image, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG", quality=92, optimize=True, progressive=False, subsampling=0)


# ---------------------------------------------------------------- cards
def render_cover(item: dict, out: Path):
    img = background(W_FEED, H_FEED, (0.95, 0.12))
    d = ImageDraw.Draw(img)
    top_bar(img, item, W_FEED)

    max_w = W_FEED - 2 * MARGIN
    f_me, l_me, lh_me = fit(d, item["title_me"], "InterDisplay-ExtraBold", max_w, 520, 98, 60, 5, 1.06)
    f_en, l_en, lh_en = fit(d, item["title_en"], "Inter-Medium", max_w, 220, 46, 34, 4, 1.22)

    chip_h = 48
    block = chip_h + 44 + lh_me * len(l_me) + 40 + 6 + 36 + lh_en * len(l_en)
    area_top, area_bot = 220, H_FEED - 150
    y = area_top + max(0, (area_bot - area_top - block) // 2)

    y = chip(img, MARGIN, y, f"{item['category']['me']}".upper()) + 44
    y = draw_lines(d, MARGIN, y, l_me, f_me, lh_me, WHITE) + 40
    d.rectangle((MARGIN, y, MARGIN + 90, y + 6), fill=ACCENT)
    y += 6 + 36
    draw_lines(d, MARGIN, y, l_en, f_en, lh_en, GREY)

    footer(img, item, H_FEED, "Prevuci / Swipe  →")
    save(img, out)


def render_detail(item: dict, lang: str, page: str, out: Path):
    img = background(W_FEED, H_FEED, (0.05, 0.92))
    d = ImageDraw.Draw(img)
    top_bar(img, item, W_FEED)

    label = "ŠTA SE DESILO?" if lang == "me" else "WHAT HAPPENED?"
    title = item[f"title_{lang}"]
    points = item[f"points_{lang}"]
    max_w = W_FEED - 2 * MARGIN

    y = 250
    fl = font("Inter-Bold", 26)
    draw_tracked(d, (MARGIN, y), label, fl, ACCENT, tracking=4)
    y += 62
    f_t, l_t, lh_t = fit(d, title, "InterDisplay-Bold", max_w, 200, 56, 40, 3, 1.1)
    y = draw_lines(d, MARGIN, y, l_t, f_t, lh_t, WHITE) + 50

    # bullet points: shrink until they fit above the footer
    bottom = H_FEED - 170
    for size in range(38, 27, -2):
        fp = font("Inter-Regular", size)
        lh = int(size * 1.36)
        gap = int(size * 0.75)
        wrapped = [wrap(d, p, fp, max_w - 44) for p in points]
        total = sum(len(wl) * lh for wl in wrapped) + gap * (len(points) - 1)
        if y + total <= bottom:
            break
    for wl in wrapped:
        d.rectangle((MARGIN, y + int(size * 0.42), MARGIN + 14, y + int(size * 0.42) + 14), fill=ACCENT)
        y = draw_lines(d, MARGIN + 44, y, wl, fp, lh, WHITE) + gap

    footer(img, item, H_FEED, page)
    save(img, out)


def render_story(item: dict, out: Path):
    W, H = W_STORY, H_STORY
    img = background(W, H, (0.9, 0.18))
    d = ImageDraw.Draw(img)
    max_w = W - 2 * MARGIN

    wordmark(img, MARGIN, 250, scale=1.15)
    f = font("Inter-Medium", 28)
    ds = fmt_date(item["date"])
    d.text((W - MARGIN - d.textlength(ds, font=f), 268), ds, font=f, fill=GREY)

    f_me, l_me, lh_me = fit(d, item["title_me"], "InterDisplay-ExtraBold", max_w, 600, 110, 64, 6, 1.05)
    f_en, l_en, lh_en = fit(d, item["title_en"], "Inter-Medium", max_w, 240, 50, 36, 4, 1.22)
    fs = font("Inter-Regular", 36)
    s_me = wrap(d, item.get("story_me", ""), fs, max_w) if item.get("story_me") else []
    s_en = wrap(d, item.get("story_en", ""), fs, max_w) if item.get("story_en") else []
    lh_s = int(36 * 1.36)

    block = 52 + 50 + lh_me * len(l_me) + 44 + 6 + 40 + lh_en * len(l_en)
    if s_me or s_en:
        block += 70 + lh_s * (len(s_me) + len(s_en)) + 24
    area_top, area_bot = 420, 1600
    y = area_top + max(0, (area_bot - area_top - block) // 2)

    y = chip(img, MARGIN, y, item["category"]["me"].upper(), scale=1.1) + 50
    y = draw_lines(d, MARGIN, y, l_me, f_me, lh_me, WHITE) + 44
    d.rectangle((MARGIN, y, MARGIN + 100, y + 6), fill=ACCENT)
    y += 6 + 40
    y = draw_lines(d, MARGIN, y, l_en, f_en, lh_en, GREY)
    if s_me or s_en:
        y += 70
        y = draw_lines(d, MARGIN, y, s_me, fs, lh_s, WHITE) + 24
        draw_lines(d, MARGIN, y, s_en, fs, lh_s, GREY)

    footer(img, item, H, "Više na profilu / More on profile", w=W, y=1640)
    save(img, out)


def render_item(item: dict, outdir: Path) -> dict:
    """Renders all formats. Returns relative file paths."""
    base = outdir / item["id"]
    files = {
        "carousel": [f"{base}-1.jpg", f"{base}-2.jpg", f"{base}-3.jpg"],
        "story": f"{base}-story.jpg",
    }
    render_cover(item, Path(files["carousel"][0]))
    render_detail(item, "me", "2/3", Path(files["carousel"][1]))
    render_detail(item, "en", "3/3", Path(files["carousel"][2]))
    render_story(item, Path(files["story"]))
    rel = lambda p: os.path.relpath(p, ROOT)
    return {"carousel": [rel(p) for p in files["carousel"]], "story": rel(files["story"])}


if __name__ == "__main__":
    import json
    import sys

    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    outdir = Path(sys.argv[2])
    for it in data if isinstance(data, list) else [data]:
        print(json.dumps(render_item(it, outdir), ensure_ascii=False))

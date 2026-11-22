"""go24 technology - fetches the photo for a news item (runs in GitHub Actions).

item["image"] may hold:
  {"url": "https://.../photo.jpg", "credit": "Pexels"}            direct image
  {"page": "https://company.com/press-release", "credit": "Rockstar Games"}
        -> the page's og:image / twitter:image is used (official press visual)
  {"path": "media/2026-11-23/src/x.jpg", "credit": "..."}          already in the repo
Only official company/press pages or free-licence libraries (Pexels, Unsplash,
Wikimedia Commons with attribution) should be used. Never photos from news articles.
On any failure the item renders with the text-only layout.
"""
from __future__ import annotations

import io
import re
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "Mozilla/5.0 (compatible; go24-technology/1.0; +https://github.com/grknozkn97-ctrl/go24-technology)"}
MIN_W, MIN_H = 700, 500


def _og_image(page_url: str) -> str | None:
    import requests

    r = requests.get(page_url, headers=UA, timeout=30)
    r.raise_for_status()
    html = r.text[:600_000]
    for prop in ("og:image:secure_url", "og:image", "twitter:image", "twitter:image:src"):
        for pat in (
            rf'<meta[^>]+(?:property|name)=["\']{re.escape(prop)}["\'][^>]+content=["\']([^"\']+)',
            rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\']{re.escape(prop)}["\']',
        ):
            m = re.search(pat, html, re.I)
            if m:
                return urljoin(page_url, unescape(m.group(1)))
    return None


def _download(url: str) -> Image.Image:
    import requests

    r = requests.get(url, headers=UA, timeout=60)
    r.raise_for_status()
    img = Image.open(io.BytesIO(r.content))
    img.load()
    return img


def trim_borders(img: Image.Image, tol: float = 10.0) -> Image.Image:
    """Removes flat letterbox/pillarbox bands (common on og:images)."""
    g = img.convert("L")
    w, h = g.size
    px = g.load()

    def flat_row(y):
        vals = [px[x, y] for x in range(0, w, max(1, w // 200))]
        m = sum(vals) / len(vals)
        return max(abs(v - m) for v in vals) < tol

    def flat_col(x):
        vals = [px[x, y] for y in range(0, h, max(1, h // 200))]
        m = sum(vals) / len(vals)
        return max(abs(v - m) for v in vals) < tol

    top = 0
    while top < h // 4 and flat_row(top):
        top += 1
    bot = h - 1
    while bot > h * 3 // 4 and flat_row(bot):
        bot -= 1
    left = 0
    while left < w // 4 and flat_col(left):
        left += 1
    right = w - 1
    while right > w * 3 // 4 and flat_col(right):
        right -= 1
    if (top, left, bot, right) != (0, 0, h - 1, w - 1):
        img = img.crop((left, top, right + 1, bot + 1))
    return img


def attach_image(item: dict, save_dir: Path | None = None) -> None:
    spec = item.get("image") or {}
    item["_image"] = None
    try:
        if spec.get("path"):
            img = Image.open(ROOT / spec["path"])
        elif spec.get("url"):
            img = _download(spec["url"])
        elif spec.get("page"):
            src = _og_image(spec["page"])
            if not src:
                raise ValueError("no og:image on page")
            spec["resolved_url"] = src
            img = _download(src)
        else:
            return
        img = trim_borders(img.convert("RGB"))
        if img.width < MIN_W or img.height < MIN_H:
            raise ValueError(f"image too small ({img.width}x{img.height})")
        if max(img.size) > 2000:
            img.thumbnail((2000, 2000), Image.LANCZOS)
        item["_image"] = img
        if save_dir is not None:  # keep the source so cards can be re-rendered later
            save_dir.mkdir(parents=True, exist_ok=True)
            p = save_dir / f"{item['id']}.jpg"
            img.save(p, "JPEG", quality=88)
            spec["path"] = str(p.relative_to(ROOT))
        print(f"  image ok for {item['id']}: {img.width}x{img.height}")
    except Exception as e:  # noqa: BLE001
        spec["error"] = str(e)[:200]
        print(f"  image FAILED for {item['id']}: {e} -> text-only layout")

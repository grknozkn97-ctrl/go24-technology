"""go24 technology - turns a day's draft into images + a publishing queue.

Usage:  python go24/build_day.py drafts/2026-11-23.json

Draft format:
{
  "date": "2026-11-23",
  "items": [ {render item fields..., "caption_me": "...", "caption_en": "...", "hashtags": ["#tech", ...]} ],
  "feed":    [{"item": "<id>", "at": "12:30"}],           # optional, defaults to config feed_times
  "stories": [{"item": "<id>", "at": "08:30"}, ...]       # optional, defaults to config story_times
}
Writes media/<date>/<id>-*.jpg and queue/<date>.json. Existing published ids are never rewritten.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from images import attach_image  # noqa: E402
from render import ROOT, render_item  # noqa: E402

CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
TZ = ZoneInfo(CFG["timezone"])


def at_iso(day: str, hhmm: str) -> str:
    return datetime.fromisoformat(f"{day}T{hhmm}:00").replace(tzinfo=TZ).isoformat()


def caption(item: dict) -> str:
    tags = " ".join(item.get("hashtags", [])[: CFG["hashtags_max"]])
    parts = [
        f"🇲🇪 {item['caption_me'].strip()}",
        f"🇬🇧 {item['caption_en'].strip()}",
        f"Izvor / Source: {item['source']}",
    ]
    if tags:
        parts.append(tags)
    text = "\n\n".join(parts)
    if len(text) > 2200:
        raise SystemExit(f"caption too long for {item['id']}: {len(text)} chars")
    return text


def preview(files: dict, out: Path):
    """Contact sheet of everything rendered today (for a quick visual check)."""
    from PIL import Image

    rows = []
    for f in files.values():
        ims = [Image.open(ROOT / p) for p in f["carousel"]] + [Image.open(ROOT / f["story"])]
        ims = [im.resize((int(im.width * 450 / im.height), 450)) for im in ims]
        row = Image.new("RGB", (sum(i.width for i in ims) + 20 * (len(ims) + 1), 490), (24, 24, 28))
        x = 20
        for im in ims:
            row.paste(im, (x, 20))
            x += im.width + 20
        rows.append(row)
    if not rows:
        return
    sheet = Image.new("RGB", (max(r.width for r in rows), sum(r.height for r in rows)), (24, 24, 28))
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height
    sheet.save(out, "JPEG", quality=80)


def main(draft_path: str):
    draft = json.loads(Path(draft_path).read_text(encoding="utf-8"))
    day = draft["date"]
    items = {it["id"]: it for it in draft["items"]}
    for it in items.values():
        it.setdefault("date", day)
        for k in ("title_me", "title_en", "points_me", "points_en", "caption_me", "caption_en", "source"):
            if not it.get(k):
                raise SystemExit(f"{it['id']}: missing {k}")

    outdir = ROOT / "media" / day
    files = {}
    for iid, it in items.items():
        src = outdir / "src" / f"{iid}.jpg"
        if src.exists():  # photo already downloaded on an earlier build
            it.setdefault("image", {})["path"] = str(src.relative_to(ROOT))
        attach_image(it, save_dir=outdir / "src")
        files[iid] = render_item(it, outdir)
    preview(files, outdir / "preview.jpg")

    ids = list(items)
    feed = draft.get("feed") or [{"item": ids[i], "at": t} for i, t in enumerate(CFG["feed_times"]) if i < len(ids)]
    stories = draft.get("stories") or [
        {"item": ids[i % len(ids)], "at": t} for i, t in enumerate(CFG["story_times"])
    ]

    published = json.loads((ROOT / "state" / "published.json").read_text()) if (ROOT / "state" / "published.json").exists() else {}
    posts = []
    for f in feed:
        pid = f"{day}-feed-{f['item']}"
        posts.append({
            "id": pid, "type": "carousel", "at": at_iso(day, f["at"]),
            "media": files[f["item"]]["carousel"], "caption": caption(items[f["item"]]),
        })
    for s in stories:
        pid = f"{day}-story-{s['item']}-{s['at'].replace(':', '')}"
        posts.append({"id": pid, "type": "story", "at": at_iso(day, s["at"]), "media": [files[s["item"]]["story"]]})

    qf = ROOT / "queue" / f"{day}.json"
    old = json.loads(qf.read_text(encoding="utf-8")).get("posts", []) if qf.exists() else []
    keep = [p for p in old if published.get(p["id"], {}).get("status") == "published"]
    keep_ids = {p["id"] for p in keep}
    posts = keep + [p for p in posts if p["id"] not in keep_ids]
    posts.sort(key=lambda p: p["at"])
    qf.parent.mkdir(parents=True, exist_ok=True)
    qf.write_text(json.dumps({"date": day, "posts": posts}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for p in posts:
        print(f"{p['at'][11:16]}  {p['type']:<8} {p['id']}")


if __name__ == "__main__":
    main(sys.argv[1])

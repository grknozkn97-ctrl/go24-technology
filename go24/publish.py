"""go24 technology - Instagram publisher (runs in GitHub Actions every 15 minutes).

Reads queue/*.json, publishes posts whose time has come through the official
Instagram API (Instagram Login), and records results in state/published.json.

Secrets (GitHub > Settings > Secrets and variables > Actions):
  IG_ACCESS_TOKEN  long-lived Instagram user access token (from the Meta app)
  TOKEN_KEY        any long random phrase; encrypts the auto-refreshed token in state/token.enc
Optional env: POST_ID (publish this id now), DRY_RUN=1 (print only).
The token is never printed or written in plain text.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
STATE = ROOT / "state"
QUEUE = ROOT / "queue"
GRAPH = f"https://graph.instagram.com/{CFG['api_version']}"
REPO = os.environ.get("GITHUB_REPOSITORY", "grknozkn97-ctrl/go24-technology")
BRANCH = os.environ.get("GITHUB_REF_NAME", "main")
NOW = datetime.now(timezone.utc)
DRY = os.environ.get("DRY_RUN") == "1"
FORCE_ID = (os.environ.get("POST_ID") or "").strip()

SUMMARY: list[str] = []


def log(msg: str):
    print(msg, flush=True)
    SUMMARY.append(msg)


class ApiError(Exception):
    pass


# ------------------------------------------------------------------ state
def load_json(p: Path, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def save_json(p: Path, data):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ token
def _fernet():
    key = os.environ.get("TOKEN_KEY")
    if not key:
        return None
    from cryptography.fernet import Fernet

    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(key.encode()).digest()))


def load_token() -> str | None:
    f, enc = _fernet(), STATE / "token.enc"
    if f and enc.exists():
        try:
            return f.decrypt(enc.read_bytes()).decode()
        except Exception:
            log("Note: state/token.enc could not be decrypted, falling back to IG_ACCESS_TOKEN.")
    return os.environ.get("IG_ACCESS_TOKEN") or None


def maybe_refresh(token: str) -> str:
    meta_p = STATE / "token_meta.json"
    meta = load_json(meta_p, {})
    last = meta.get("refreshed_at")
    if last and datetime.fromisoformat(last) > NOW - timedelta(days=CFG["refresh_every_days"]):
        return token
    f = _fernet()
    if not f:
        log("TOKEN_KEY secret missing: token will not be auto-refreshed.")
        return token
    if DRY:
        return token
    r = requests.get(
        "https://graph.instagram.com/refresh_access_token",
        params={"grant_type": "ig_refresh_token", "access_token": token},
        timeout=30,
    )
    body = r.json() if r.content else {}
    if r.ok and body.get("access_token"):
        new = body["access_token"]
        (STATE / "token.enc").write_bytes(f.encrypt(new.encode()))
        meta.update(refreshed_at=NOW.isoformat(), expires_in_days=round(body.get("expires_in", 0) / 86400))
        save_json(meta_p, meta)
        log(f"Token refreshed (valid ~{meta['expires_in_days']} days).")
        return new
    log(f"Token refresh failed: {body.get('error', {}).get('message', r.status_code)}")
    return token


# ------------------------------------------------------------------ api
TOKEN = ""


def api(method: str, path: str, **params):
    params["access_token"] = TOKEN
    url = f"{GRAPH}/{path}"
    if method == "GET":
        r = requests.get(url, params=params, timeout=60)
    else:
        r = requests.post(url, data=params, timeout=120)
    body = r.json() if r.content else {}
    if not r.ok or "error" in body:
        err = body.get("error", {})
        raise ApiError(f"{err.get('message', r.text[:300])} (code {err.get('code')}, sub {err.get('error_subcode')})")
    return body


def wait_ready(container_id: str, timeout_s: int = 300):
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        st = api("GET", container_id, fields="status_code,status").get("status_code")
        if st == "FINISHED":
            return
        if st in ("ERROR", "EXPIRED"):
            raise ApiError(f"container {container_id} status {st}")
        time.sleep(5)
    raise ApiError(f"container {container_id} not ready after {timeout_s}s")


def raw_url(rel: str) -> str:
    return f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{rel}"


def publish(ig_id: str, post: dict) -> str:
    urls = [raw_url(p) for p in post["media"]]
    kind = post["type"]
    if kind == "story":
        c = api("POST", f"{ig_id}/media", image_url=urls[0], media_type="STORIES")["id"]
    elif kind == "image":
        c = api("POST", f"{ig_id}/media", image_url=urls[0], caption=post.get("caption", ""))["id"]
    elif kind == "carousel":
        children = []
        for u in urls:
            cid = api("POST", f"{ig_id}/media", image_url=u, is_carousel_item="true")["id"]
            children.append(cid)
        for cid in children:
            wait_ready(cid)
        c = api(
            "POST", f"{ig_id}/media", media_type="CAROUSEL", children=",".join(children), caption=post.get("caption", "")
        )["id"]
    else:
        raise ApiError(f"unknown type {kind}")
    wait_ready(c)
    return api("POST", f"{ig_id}/media_publish", creation_id=c)["id"]


# ------------------------------------------------------------------ main
def due_posts(published: dict) -> list[dict]:
    posts = []
    for qf in sorted(QUEUE.glob("*.json")):
        for p in load_json(qf, {}).get("posts", []):
            p["_file"] = qf.name
            posts.append(p)
    out = []
    for p in posts:
        rec = published.get(p["id"], {})
        if rec.get("status") in ("published", "skipped_late", "failed"):
            continue
        if FORCE_ID:
            if p["id"] == FORCE_ID:
                out.append(p)
            continue
        at = datetime.fromisoformat(p["at"])
        if at > NOW:
            continue
        if CFG["require_approval"] and not p.get("approved"):
            continue
        if NOW - at > timedelta(minutes=CFG["max_late_minutes"]):
            published[p["id"]] = {"status": "skipped_late", "at": p["at"], "checked": NOW.isoformat()}
            log(f"- {p['id']}: skipped (more than {CFG['max_late_minutes']} min late)")
            continue
        out.append(p)
    return sorted(out, key=lambda p: p["at"])


def main():
    global TOKEN
    pub_p = STATE / "published.json"
    published = load_json(pub_p, {})
    todo = due_posts(published)

    TOKEN = load_token() or ""
    if not TOKEN:
        log("IG_ACCESS_TOKEN is not set yet; nothing will be published.")
        save_json(pub_p, published)
        return finish()
    TOKEN = maybe_refresh(TOKEN)

    if not todo:
        log("No posts due.")
        save_json(pub_p, published)
        return finish()

    if DRY:
        for p in todo:
            log(f"[dry run] would publish {p['id']} ({p['type']}): {', '.join(raw_url(m) for m in p['media'])}")
        return finish()

    me = api("GET", "me", fields="user_id,username")
    ig_id = str(me.get("user_id") or me.get("id"))
    quota = api("GET", f"{ig_id}/content_publishing_limit", fields="quota_usage").get("data", [{}])[0]
    used = quota.get("quota_usage", 0)
    log(f"Account @{me.get('username')} - API posts used in last 24h: {used}")

    gave_up: list[str] = []
    for p in todo:
        if used >= CFG["quota_stop"]:
            log("Daily API quota guard reached; remaining posts wait for the next run.")
            break
        rec = published.get(p["id"], {})
        try:
            media_id = publish(ig_id, p)
            published[p["id"]] = {"status": "published", "media_id": media_id, "at": p["at"], "published": NOW.isoformat()}
            used += 1
            log(f"- {p['id']}: published ({p['type']}) media {media_id}")
        except Exception as e:  # noqa: BLE001
            attempts = rec.get("attempts", 0) + 1
            status = "failed" if attempts >= CFG["max_attempts"] else "retry"
            published[p["id"]] = {"status": status, "attempts": attempts, "error": str(e)[:500], "at": p["at"]}
            log(f"- {p['id']}: ERROR attempt {attempts} -> {status}: {str(e)[:300]}")
            if status == "failed":
                gave_up.append(p["id"])
        save_json(pub_p, published)

    save_json(pub_p, published)
    finish()
    if gave_up:
        sys.exit(1)  # red run -> GitHub e-mails the owner once, when a post is given up on


def finish():
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("### go24 publish run\n\n" + "\n".join(f"- {s}" if not s.startswith("-") else s for s in SUMMARY) + "\n")


if __name__ == "__main__":
    main()

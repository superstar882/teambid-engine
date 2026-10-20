"""Team progress from the results page (status + note per job), stored encrypted in Supabase and synced into TeamBid.

Design (the Supabase anon/publishable key is public on the page, so the database must not trust it):
- every change is AES-256-GCM encrypted with a key derived from the team password (PBKDF2-SHA256, 600,000 iterations,
  separate salt from the results file), so the table only holds unreadable rows;
- rows are append-only (RLS: anon may SELECT and INSERT, never UPDATE or DELETE); the newest row that decrypts wins, so
  junk written by someone with the key is ignored and real history can't be overwritten;
- the row id ("item") is an HMAC of member + job, so the table doesn't reveal who or which job either.

Status mapping into TeamBid: saved -> match shortlisted, skipped -> match skipped, applied/interview/offer/rejected ->
an application with that status, cleared -> match back to new. Notes go to the application.
"""
import base64
import hashlib
import hmac
import json
import os

import requests

from . import config, storage

TABLE = "teambid_progress"
STATUSES = ("", "saved", "applied", "interview", "offer", "rejected", "skipped")


def settings():
    from .export import PUB_FILE, pub_settings
    cfg = pub_settings()
    sb = cfg.get("supabase") or {}
    return sb if sb.get("url") and sb.get("key") else None


def configure(url, key):
    """Save the Supabase project URL + publishable/anon key, a random team id and a progress salt (local only)."""
    from .export import PUB_FILE, pub_settings
    cfg = pub_settings()
    sb = cfg.get("supabase") or {}
    sb.update({"url": url.rstrip("/").removesuffix("/rest/v1"), "key": key})
    sb.setdefault("team", base64.urlsafe_b64encode(os.urandom(12)).decode().rstrip("="))
    sb.setdefault("salt", base64.b64encode(os.urandom(16)).decode())
    sb.setdefault("iterations", 600_000)
    cfg["supabase"] = sb
    PUB_FILE.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    return sb


def keys(password, sb):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    raw = PBKDF2HMAC(algorithm=hashes.SHA256(), length=64, salt=base64.b64decode(sb["salt"]),
                     iterations=sb["iterations"]).derive(password.encode("utf-8"))
    return raw[:32], raw[32:]          # AES key, HMAC key


def item_id(mac_key, member_slug, job_key):
    return hmac.new(mac_key, f"{member_slug}|{job_key}".encode("utf-8"), hashlib.sha256).hexdigest()[:40]


def seal(aes_key, obj):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    iv = os.urandom(12)
    return base64.b64encode(iv + AESGCM(aes_key).encrypt(iv, json.dumps(obj).encode("utf-8"), None)).decode()


def unseal(aes_key, payload):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    raw = base64.b64decode(payload)
    return json.loads(AESGCM(aes_key).decrypt(raw[:12], raw[12:], None))


def _headers(sb):
    return {"apikey": sb["key"], "Authorization": f"Bearer {sb['key']}", "Content-Type": "application/json"}


def fetch(sb, password):
    """Latest valid entry per item -> {item: entry}. Rows that don't decrypt (junk, old password) are skipped."""
    aes, _ = keys(password, sb)
    latest, offset = {}, 0
    while True:
        r = requests.get(f"{sb['url']}/rest/v1/{TABLE}", headers={**_headers(sb), "Range": f"{offset}-{offset + 999}"},
                         params={"team": f"eq.{sb['team']}", "select": "item,payload,created_at", "order": "id.asc"}, timeout=30)
        r.raise_for_status()
        rows = r.json()
        for row in rows:
            try:
                e = unseal(aes, row["payload"])
            except Exception:
                continue
            e["saved_at"] = row["created_at"]
            latest[row["item"]] = e
        if len(rows) < 1000:
            return latest
        offset += 1000


def add(sb, password, member_slug, job_key, entry):
    """Append one change (used by tests and the CLI; the page does the same in the browser)."""
    aes, mac = keys(password, sb)
    body = {"team": sb["team"], "item": item_id(mac, member_slug, job_key), "payload": seal(aes, {**entry, "member": member_slug, "job": job_key})}
    r = requests.post(f"{sb['url']}/rest/v1/{TABLE}", headers={**_headers(sb), "Prefer": "return=minimal"}, json=body, timeout=30)
    r.raise_for_status()


def sync(password=None, log=print):
    """Pull progress from Supabase into TeamBid (statuses, applications, notes)."""
    from .export import get_password
    sb = settings()
    if not sb:
        return {"synced": 0, "reason": "progress sync not set up"}
    password = password or get_password(ask=False)
    entries = fetch(sb, password)
    changed = 0
    with storage.connect() as con:
        slugs = {m["slug"]: m for m in storage.members(con)}
        for e in entries.values():
            m = slugs.get(e.get("member"))
            if not m:
                continue
            job = con.execute("SELECT id, company, title, url FROM jobs WHERE url_key=?", (e.get("job"),)).fetchone()
            if not job:
                continue
            st = e.get("status", "")
            app = con.execute("SELECT id, status, notes FROM applications WHERE member_id=? AND job_id=?", (m["id"], job["id"])).fetchone()
            if st in ("applied", "interview", "offer", "rejected"):
                if not app:
                    aid = storage.create_application(con, m["id"], job["company"], job["title"], job["url"], job["id"], None, None, e.get("note") or None)
                    storage.set_application_status(con, aid, st, e.get("note") or None)
                    changed += 1
                elif app["status"] != st or (e.get("note") and e.get("note") != app["notes"]):
                    storage.set_application_status(con, app["id"], st, e.get("note") or None)
                    changed += 1
            else:
                target = {"saved": "shortlisted", "skipped": "skipped", "": "new"}.get(st, "new")
                cur = con.execute("SELECT status FROM matches WHERE member_id=? AND job_id=?", (m["id"], job["id"])).fetchone()
                if cur and cur["status"] != target:
                    con.execute("UPDATE matches SET status=? WHERE member_id=? AND job_id=?", (target, m["id"], job["id"]))
                    changed += 1
    log(f"progress sync: {len(entries)} entries, {changed} changes applied")
    return {"synced": len(entries), "changed": changed}


def page_config(password):
    """What the results page needs (goes inside the encrypted data, so the Supabase project isn't visible)."""
    sb = settings()
    if not sb:
        return None
    return {"url": sb["url"], "key": sb["key"], "team": sb["team"], "salt": sb["salt"], "iterations": sb["iterations"], "table": TABLE}

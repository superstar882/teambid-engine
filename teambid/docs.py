"""Tailored resume + cover letter on request from the results page, built in the cloud (GitHub Actions).

The page writes an encrypted request into the progress table (kind "docreq", plus "docpart" rows holding the pasted
job text in pieces, since one row holds at most 8,000 characters). The "Tailor documents" workflow checks every 15 minutes:
for each request without a "docdone" row it runs the normal apply step (Claude if a key is set, else the free path),
encrypts the PDF/DOCX files with the team progress key, commits them to the results site under <page>/docs/<request>/,
then writes the "docdone" row (file names, the cover letter text for the copy button, fit summary). The page decrypts
the files in the browser. Nothing readable is stored anywhere.
"""
import os
import subprocess
import time
from pathlib import Path

from . import config, export, progress, service

REQ, PART, DONE = "docreq", "docpart", "docdone"
MIME = {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def queue(entries):
    """-> oldest-first list of requests that have no result yet, each with its pasted text joined."""
    done = {e.get("rid") for e in entries.values() if e.get("kind") == DONE}
    parts = {}
    for e in entries.values():
        if e.get("kind") == PART:
            parts.setdefault(e.get("rid"), {})[int(e.get("n", 0))] = e.get("text", "")
    out = []
    for e in entries.values():
        if e.get("kind") == REQ and e.get("rid") and e["rid"] not in done:
            got = parts.get(e["rid"], {})
            if len(got) < int(e.get("parts", 0)):
                continue                      # still uploading from the page; next run picks it up
            out.append({**e, "text": "".join(got[i] for i in sorted(got))})
    return sorted(out, key=lambda e: e.get("at", ""))


def pending():
    sb = progress.settings()
    if not sb:
        return []
    return queue(progress.fetch(sb, export.get_password(ask=False)))


def _encrypt_file(aes, path):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    iv = os.urandom(12)
    return iv + AESGCM(aes).encrypt(iv, Path(path).read_bytes(), None)


def _git(*args):
    r = subprocess.run(["git", *args], cwd=export.SITE, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {args[0]}: {(r.stderr or r.stdout).strip()[:300]}")
    return r.stdout


def push_site(msg):
    """Commit + push the site repo; on a race with the scan's publish, rebase and retry."""
    cfg = export.pub_settings()
    for k, opt in (("git_name", "user.name"), ("git_email", "user.email")):
        if cfg.get(k):
            _git("config", opt, cfg[k])
    _git("add", "-A")
    if not _git("diff", "--cached", "--name-only").strip():
        return
    _git("commit", "-q", "-m", msg)
    for i in range(4):
        try:
            _git("push", "-q", "origin", "HEAD:main")
            return
        except RuntimeError:
            if i == 3:
                raise
            time.sleep(5 * (i + 1))
            _git("pull", "-q", "--rebase", "origin", "main")


def run_all(rounds=5, log=print):
    """Keep building until nothing is waiting (requests can arrive while a batch builds)."""
    total = {"built": 0, "failed": 0}
    for _ in range(rounds):
        r = run(log=log)
        total["built"] += r.get("built", 0)
        total["failed"] += r.get("failed", 0)
        if not r.get("built") and not r.get("failed"):
            break
    return total


def run(limit=10, log=print):
    sb = progress.settings()
    if not sb:
        return {"built": 0, "reason": "progress (Supabase) not set up"}
    password = export.get_password(ask=False)
    aes, mac = progress.keys(password, sb)
    todo = queue(progress.fetch(sb, password))[:limit]
    if not todo:
        log("no document requests waiting")
        return {"built": 0}
    page = export.pub_settings()["page"]
    results = []
    for req in todo:
        rid, slug = req["rid"], req.get("member")
        log(f"building documents for {slug}: {req.get('company') or '?'} / {req.get('title') or '?'}")
        try:
            r = service.apply(slug, url=req.get("url") or None, jd_text=req.get("text") or None,
                              company=req.get("company") or None, title=req.get("title") or None, polish=True)
            out_dir = export.SITE / page / "docs" / rid
            out_dir.mkdir(parents=True, exist_ok=True)
            files = {}
            for key, path in (("resume_pdf", r["files"]["pdf"]), ("resume_docx", r["files"]["docx"]),
                              ("letter_pdf", r["files"]["letter_pdf"]), ("letter_docx", r["files"]["letter_docx"])):
                (out_dir / f"{key}.enc").write_bytes(_encrypt_file(aes, path))
                ext = Path(path).suffix.lstrip(".")
                files[key] = {"name": Path(path).name, "type": MIME[ext]}
            results.append({"kind": DONE, "rid": rid, "member": slug, "company": r["jd"].get("company") or req.get("company") or "",
                            "title": r["jd"].get("title") or req.get("title") or "", "files": files, "letter": r["letter"][:3500],
                            "fit": {"verdict": r["fit"]["verdict"], "coverage": r["fit"]["coverage"]},
                            "keywords": r["keywords"]["pct"], "pages": r["files"]["pages"],
                            "checks": (r["problems"] or [])[:4], "notes": [n for n in (r.get("resume_ai"), r.get("polish")) if n],
                            "at": config.now().isoformat(timespec="seconds")})
        except Exception as e:
            log(f"  failed: {e}")
            results.append({"kind": DONE, "rid": rid, "member": slug, "error": str(e)[:400],
                            "at": config.now().isoformat(timespec="seconds")})
    if any("files" in x for x in results):
        push_site(f"Documents for {sum('files' in x for x in results)} request(s)")
    for x in results:                            # files are live first, then the page learns they're ready
        progress.put(sb, password, DONE, x["rid"], x)
    log(f"built {sum('files' in x for x in results)} of {len(results)} request(s)")
    return {"built": sum("files" in x for x in results), "failed": sum("error" in x for x in results)}

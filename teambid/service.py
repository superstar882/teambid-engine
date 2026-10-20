"""High-level actions used by both the CLI (tb.py) and the web UI (server.py)."""
import base64
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from . import analyze, config, cover, llm, render, resume_parse, storage, tailor, vault, writing
from .jobs import jd as JD, matcher, scanner


# ---------------------------------------------------------------- members
def onboard(name, resume_path=None, resume_b64=None, filename=None, email=None, prefs=None, use_llm=False):
    """Parse a resume, audit it, save the member with default preferences, and build their vault."""
    config.ensure_dirs()
    slug = storage.slugify(name)
    folder = config.member_dir(slug)
    if resume_b64 is not None:
        dst = folder / "resume" / Path(filename or "resume.pdf").name
        dst.write_bytes(base64.b64decode(resume_b64.split(",")[-1]))
    else:
        src = Path(resume_path)
        dst = folder / "resume" / src.name
        if src.resolve() != dst.resolve():
            shutil.copy(src, dst)
    profile = resume_parse.parse_file(dst)
    note = ""
    if use_llm and llm.available():
        roles, note = llm.refine_profile(profile["raw_text"], profile)
        if roles:
            for r in roles:
                r.setdefault("bullets", [])
                r["bullets"] = [{"text": b} if isinstance(b, str) else b for b in r["bullets"]]
                r.update({"current": r.get("end") == "Present", "months": 0, "stack_line": ""})
                resume_parse.finish_role(r)
            profile["roles"] = roles
            resume_parse.derive(profile)
    if not profile.get("name"):
        profile["name"] = name
    base = matcher.default_prefs(profile)
    base.update({k: v for k, v in (prefs or {}).items() if v not in (None, "", [])})
    base["countries"] = matcher.norm_countries(base.get("countries")) or matcher.default_prefs(profile)["countries"]
    with storage.connect() as con:
        mid, slug = storage.save_member(con, name, profile, base, str(dst), email or profile["contact"].get("email"), slug)
        m = storage.member(con, slug)
        matched = None
        if con.execute("SELECT 1 FROM jobs LIMIT 1").fetchone():      # jobs from an earlier scan: match right away
            matched = matcher.match_member(con, m, log=lambda *_: None)
        v = vault.build(con, m)
    return {"slug": slug, "id": mid, "profile": profile, "prefs": base, "vault": v, "llm": note, "matched": matched}


def update_member(slug, profile=None, prefs=None):
    with storage.connect() as con:
        m = storage.member(con, slug)
        if not m:
            raise KeyError(slug)
        if profile:
            for r in profile.get("roles", []):
                r["bullets"] = [{"text": b} if isinstance(b, str) else {"text": b["text"]} for b in r.get("bullets", [])]
                r.setdefault("kind", "job")
                r.setdefault("stack_line", " | ".join(r.get("stack", [])))
                resume_parse.finish_role(r)
            raw = m["profile"].get("raw_text", "")
            profile["raw_text"] = raw
            bullet_text = "\n".join(b["text"] for r in profile["roles"] for b in r["bullets"])
            profile["metrics"] = sorted(set(resume_parse.metrics(bullet_text + "\n" + profile.get("summary", ""))))
            resume_parse.derive(profile)
        merged = {**m["prefs"], **(prefs or {})}
        if "countries" in merged:
            merged["countries"] = matcher.norm_countries(merged["countries"]) or m["prefs"].get("countries") or ["US"]
        storage.save_member(con, m["name"], profile or m["profile"], merged, slug=slug)
        m = storage.member(con, slug)
        return vault.build(con, m)


def rematch(slug, days=None):
    with storage.connect() as con:
        m = storage.member(con, slug)
        return matcher.match_member(con, m, days=days, log=lambda *_: None)


def member_matches(slug, status=None, tier=None, limit=200, new_only=False):
    with storage.connect() as con:
        m = storage.member(con, slug)
        q = ("SELECT m.*, j.company, j.title, j.location, j.url, j.posted, j.source, j.ats FROM matches m JOIN jobs j ON j.id=m.job_id "
             "WHERE m.member_id=?")
        args = [m["id"]]
        if status:
            q += " AND m.status=?"
            args.append(status)
        if tier:
            q += " AND m.tier=?"
            args.append(tier)
        if new_only:
            q += " AND m.first_matched=(SELECT max(first_matched) FROM matches WHERE member_id=?)"
            args.append(m["id"])
        q += " ORDER BY m.first_matched DESC, m.score DESC LIMIT ?"
        args.append(limit)
        rows = [dict(r) for r in con.execute(q, args)]
    for r in rows:
        r["reasons"] = json.loads(r["reasons"] or "[]")
    return rows


# ---------------------------------------------------------------- apply (Quick Bid)
def apply(slug, job_id=None, url=None, jd_text=None, company=None, title=None, polish=False):
    """Analyze a job, build the tailored resume + cover letter + answers, save an application folder."""
    with storage.connect() as con:
        m = storage.member(con, slug)
        if job_id:
            j = dict(con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
            url, company, title = j["url"], company or j["company"], title or j["title"]
            jd_text = jd_text or storage.get_jd(con, job_id)
    if not jd_text and url:
        try:
            res = JD.fetch(url)
        except Exception as e:
            raise ValueError(f"Couldn't read the job page ({type(e).__name__}: {str(e)[:80]}). Some sites block automated "
                             "reading (LinkedIn, Indeed, Himalayas pages). Open the link, copy the job text, and paste it instead.")
        jd_text = res["text"]
        company = company or res.get("company", "").replace("-", " ").title()
        title = title or res.get("title", "")
    if not jd_text:
        raise ValueError("Need a job link that can be read, or the pasted job text.")
    company, title = (company or "Company").strip(), (title or "Role").strip()
    # names guessed from a link come out as "Launchdarkly" or "Addepar1": use the spelling the post itself uses
    company = re.sub(r"(?<=[A-Za-z])\d+$", "", company)
    hit = re.search(r"\b" + re.escape(company) + r"\b", jd_text, re.I)
    if hit and hit.group(0).lower() == company.lower() and hit.group(0) != company and not hit.group(0).isupper():
        company = hit.group(0)
    p = m["profile"]
    jd = tailor.analyze_jd(jd_text, title, company)
    fit = tailor.fit(p, jd)
    spec = tailor.build_resume(p, jd)
    resume_note = ""
    if llm.available():               # with a Claude key: reword the chosen bullets toward the post (facts kept)
        spec, resume_note = llm.rewrite_resume(spec, p, jd_text)
    problems = tailor.validate(spec, p)
    kw = tailor.keyword_report(spec, jd)
    letter, letter_check = cover.draft_letter(p, jd, fit)
    polish_note = ""
    if llm.available():               # with a Claude key: Claude writes the letter; the fact-only draft is the fallback
        letter, polish_note = llm.write_letter(p, jd_text, company, title, letter)
        letter_check = writing.check(letter)
    elif polish:
        letter, polish_note = llm.polish_letter(letter, p, jd_text, company, prefer=polish if isinstance(polish, str) else "auto")
        letter_check = writing.check(letter)
    answers = cover.answers(p, m["prefs"], jd)
    from . import region as RG
    job_loc = ""
    if job_id:
        with storage.connect() as con:
            jr = con.execute("SELECT location FROM jobs WHERE id=?", (job_id,)).fetchone()
            job_loc = jr["location"] if jr else ""
    # documents follow the job's location (a US job gets Letter / 1 page / US date); fall back to the member's region
    reg = RG.job_region(job_loc, jd_text, jd.get("salary", "")) or m["prefs"].get("region") or "US"
    date_prefs = dict(m["prefs"], region=reg)
    day = str(RG.today(m["prefs"]))
    safe = lambda s: re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")[:40]
    folder = config.member_dir(slug) / "applications" / f"{day}-{safe(company)}-{safe(title)}"
    folder.mkdir(parents=True, exist_ok=True)
    base = f"{safe(m['name']).replace('-', '_')}_Resume_{safe(company)}"
    files = render.write_resume(spec, folder, base, p.get("years_experience", 0), reg)
    lfiles = render.write_letter(p.get("name") or m["name"], p.get("contact", {}), letter, folder,
                                 f"{safe(m['name']).replace('-', '_')}_Cover_Letter_{safe(company)}", RG.letter_date(date_prefs),
                                 RG.paper(reg))
    (folder / "job.md").write_text(f"# {title} at {company}\n\n{url or ''}\n\n{jd_text}\n", encoding="utf-8")
    (folder / "cover-letter.md").write_text(letter + "\n", encoding="utf-8")
    report = ["# Fit report", "", f"**{fit['verdict']}**: covers {fit['coverage']}% of the must-have skills.", ""] + \
             [f"- {n}" for n in fit["notes"]] + ["", f"Resume keyword coverage: {kw['pct']}% (missing: {', '.join(kw['missing']) or 'none'})",
             f"Resume pages: {files['pages']}", f"Fact check: {'OK' if not problems else '; '.join(problems)}", "",
             "## Answers", ""] + [f"### {q}\n\n{a['answer']}\n" for q, a in answers.items()]
    (folder / "report.md").write_text("\n".join(report), encoding="utf-8")
    (folder / "spec.json").write_text(json.dumps(spec, indent=1), encoding="utf-8")
    with storage.connect() as con:
        if not job_id and url:
            job_id = storage.add_manual_job(con, url, company, title)
        app_id = storage.create_application(con, m["id"], company, title, url, job_id, str(folder), fit["coverage"])
    return {"application_id": app_id, "folder": str(folder), "jd": jd, "fit": fit, "ranking": spec.get("ranking"), "doc_region": reg, "spec": spec, "problems": problems, "keywords": kw,
            "letter": letter, "letter_check": letter_check, "answers": answers, "files": {**files, "letter_pdf": lfiles["pdf"], "letter_docx": lfiles["docx"]},
            "polish": polish_note, "resume_ai": resume_note}


def applications(slug):
    with storage.connect() as con:
        m = storage.member(con, slug)
        return [dict(r) for r in con.execute("SELECT * FROM applications WHERE member_id=? ORDER BY updated DESC", (m["id"],))]


def team_overview():
    with storage.connect() as con:
        out = []
        for m in storage.members(con):
            c = {r["status"]: r["n"] for r in con.execute("SELECT status, count(*) n FROM applications WHERE member_id=? GROUP BY status", (m["id"],))}
            last = con.execute("SELECT max(first_matched) d FROM matches WHERE member_id=?", (m["id"],)).fetchone()["d"]
            new = con.execute("SELECT count(*) n FROM matches WHERE member_id=? AND first_matched=?", (m["id"], last)).fetchone()["n"] if last else 0
            out.append({"slug": m["slug"], "name": m["name"], "level": m["prefs"].get("level") or m["profile"].get("level"),
                        "lanes": m["prefs"].get("lanes") or m["profile"].get("lanes"), "years": m["profile"].get("years_experience"),
                        "audit": analyze.audit(m["profile"], m["prefs"].get("region", "US"))["score"], "new_matches": new,
                        "last_match_day": last, "applications": c, "region": m["prefs"].get("region", "US")})
        runs = [dict(r) for r in con.execute("SELECT id, kind, started, finished, secs, stats FROM runs ORDER BY id DESC LIMIT 15")]
        jobs = con.execute("SELECT count(*) n, max(last_seen) d FROM jobs WHERE source NOT IN ('manual','quickbid')").fetchone()
    for r in runs:
        r["stats"] = json.loads(r["stats"] or "{}")
    from . import local_ai
    return {"members": out, "runs": runs, "jobs": jobs["n"], "last_scan_day": jobs["d"], "scan_running": scanner.running() is not None,
            "llm": llm.available(), "local_ai": local_ai.status()}


def start_scan_background(days=2, limit=None):
    """Start a scan in a separate process (keeps running if the UI closes). Output: workspace/cache/scan.log."""
    config.ensure_dirs()
    if scanner.running():
        return {"started": False, "reason": "a scan is already running"}
    log = open(config.CACHE / "scan.log", "a", encoding="utf-8")
    args = [sys.executable, "-u", str(config.PROJECT / "tb.py"), "scan", "--days", str(days)] + (["--limit", str(limit)] if limit else [])
    flags = 0x00000008 | 0x00000200 if sys.platform == "win32" else 0   # DETACHED_PROCESS | NEW_PROCESS_GROUP
    subprocess.Popen(args, stdout=log, stderr=log, cwd=str(config.PROJECT), creationflags=flags)
    return {"started": True}


def stop_scan():
    """Stop the running scan. Finished boards stay in today's checkpoint, so the next scan today resumes from there."""
    info = scanner.running()
    if not info:
        return {"stopped": False, "reason": "no scan is running"}
    pid = info.get("pid")
    if not pid and sys.platform == "win32":          # scan started by an older version: find it by its command line
        r = subprocess.run(["powershell", "-NoProfile", "-Command",
                            "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { $_.CommandLine -match 'tb.py' -and "
                            "$_.CommandLine -match ' scan' }).ProcessId"], capture_output=True, text=True)
        pids = [int(x) for x in r.stdout.split() if x.strip().isdigit()]
        pid = pids[0] if pids else None
    if not pid:
        scanner.LOCK.unlink(missing_ok=True)
        return {"stopped": False, "reason": "could not find the scan process; cleared the lock"}
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
    else:
        import os
        import signal
        os.kill(int(pid), signal.SIGTERM)
    scanner.LOCK.unlink(missing_ok=True)
    with storage.connect() as con:
        con.execute("UPDATE runs SET finished=?, stats=? WHERE finished IS NULL",
                    (config.now().isoformat(timespec="seconds"), json.dumps({"problems": ["stopped by user"], "stopped": True})))
    with open(config.CACHE / "scan.log", "a", encoding="utf-8") as f:
        f.write(f"stopped by user at {config.now():%Y-%m-%d %H:%M} (progress kept; the next scan today resumes)\n")
    return {"stopped": True, "pid": pid}


def scan_log_tail(n=30):
    f = config.CACHE / "scan.log"
    return f.read_text(encoding="utf-8", errors="replace").splitlines()[-n:] if f.exists() else []


def import_quickbid(member_key, db_path):
    """Copy Quick Bid applications into a member's TeamBid applications. Safe to re-run (matches on job URL, else company+title)."""
    import sqlite3
    qb = sqlite3.connect(str(db_path))
    qb.row_factory = sqlite3.Row
    rows = qb.execute("SELECT company, title, url, status, fit, folder, notes FROM jobs "
                      "WHERE status IN ('shortlisted','applied','interview','offer','rejected','closed','withdrawn')").fetchall()
    qb.close()
    added = updated = 0
    with storage.connect() as con:
        m = storage.member(con, member_key)
        if not m:
            raise ValueError(f"no member {member_key}")
        for r in rows:
            url = r["url"] if (r["url"] or "").startswith("http") else None
            status = "drafting" if r["status"] == "shortlisted" else r["status"]
            job_id = storage.add_manual_job(con, url, r["company"], r["title"], source="quickbid") if url else None
            old = con.execute("SELECT id, status FROM applications WHERE member_id=? AND "
                              "((job_id IS NOT NULL AND job_id=?) OR (company=? AND title=?))",
                              (m["id"], job_id, r["company"], r["title"])).fetchone()
            if old:
                if old["status"] != status:
                    storage.set_application_status(con, old["id"], status)
                    updated += 1
                continue
            fit = r["fit"] if isinstance(r["fit"], int) else None
            app = storage.create_application(con, m["id"], r["company"], r["title"], url=url, job_id=job_id,
                                             folder=r["folder"], fit=fit, notes="from Quick Bid")
            if status != "drafting":
                storage.set_application_status(con, app, status)
            added += 1
    return {"member": m["slug"], "added": added, "updated": updated, "seen": len(rows)}


def reparse(slug):
    """Read the member's resume file again (after reader fixes). Keeps their preferences; rebuilds the profile,
    resume audit, vault and matches."""
    with storage.connect() as con:
        m = storage.member(con, slug)
    if not m:
        raise KeyError(slug)
    # the stored path can be from another computer (PC vs cloud): look in the member's own resume folder
    files = sorted(f for f in (config.member_dir(slug) / "resume").iterdir() if f.suffix.lower() in (".pdf", ".docx", ".txt", ".md"))
    if not files:
        raise ValueError(f"no resume file for {slug}")
    profile = resume_parse.parse_file(files[0])
    if not profile.get("name"):
        profile["name"] = m["name"]
    with storage.connect() as con:
        storage.save_member(con, m["name"], profile, m["prefs"], str(files[0]), m["email"], slug)
        m = storage.member(con, slug)
        matched = matcher.match_member(con, m, log=lambda *_: None)
        v = vault.build(con, m)
    return {"slug": slug, "roles": len(profile["roles"]), "bullets": sum(len(r["bullets"]) for r in profile["roles"]),
            "education": len(profile.get("education", [])), "certifications": len(profile.get("certifications", [])),
            "audit": v["audit"]["score"], "matches": matched["matches"] if matched else 0}

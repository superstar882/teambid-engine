"""Team changes made on the results page: add a member (resume upload) and edit a member's profile and preferences.

The page writes an encrypted request into the progress table ("adminreq" + "adminpart" rows; the body is base64 of the
UTF-8 JSON, cut into pieces because one row holds at most 8,000 characters). Every workflow that changes the workspace
(daily scan, Maintenance) runs:

  apply    after pulling the workspace: run each new request, record the result in workspace/admin-applied.json
  confirm  after pushing the workspace: write an "admindone" row for every recorded result

The record travels with the workspace, so a request is never applied twice, even if a run stops between the two steps.
"""
import base64
import datetime as dt
import json
import re

from . import config, export, progress, resume_parse, storage, vault
from .jobs import matcher

REQ, PART, DONE = "adminreq", "adminpart", "admindone"
APPLIED = config.WORKSPACE / "admin-applied.json"
MAX_FILE = 1_500_000          # bytes of resume file accepted from the page


def queue(entries):
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
                continue                              # still uploading
            try:
                body = json.loads(base64.b64decode("".join(got[i] for i in sorted(got))).decode("utf-8")) if got else {}
            except ValueError:
                body = None
            out.append({**e, "body": body})
    return sorted(out, key=lambda e: e.get("at", ""))


def _entries():
    sb = progress.settings()
    return (sb, progress.fetch(sb, export.get_password(ask=False))) if sb else (None, {})


def pending():
    return queue(_entries()[1])


def _applied():
    return json.loads(APPLIED.read_text(encoding="utf-8")) if APPLIED.exists() else {}


# ---------------------------------------------------------------- edits
def _ym(value):
    """'2022-04', 'Apr 2022', '04/2022', '2022' -> 'YYYY-MM'; 'Present' -> 'Present'; else ''."""
    v = str(value or "").strip()
    if not v:
        return ""
    if re.fullmatch(r"(?i)present|current|now", v):
        return "Present"
    if re.fullmatch(r"\d{4}-\d{2}", v):
        return v
    d = resume_parse.parse_date(v)
    return f"{d[0]:04d}-{d[1]:02d}" if d else ""


def _lines(v, limit=60, size=400):
    items = v if isinstance(v, list) else str(v or "").split("\n")
    return [str(x).strip()[:size] for x in items if str(x).strip()][:limit]


def _words(v, limit=40):
    items = v if isinstance(v, list) else re.split(r"[,\n]", str(v or ""))
    return list(dict.fromkeys(str(x).strip()[:80] for x in items if str(x).strip()))[:limit]


def edit_profile(old, data):
    """Apply the page's edits to a stored profile. Facts are only what the member typed; skills, stacks, level and
    lanes are recomputed the same way as for a parsed resume."""
    from . import skills as SK
    p = json.loads(json.dumps(old))
    for k in ("headline", "summary"):
        if k in data:
            p[k] = str(data[k] or "").strip()[:1500]
    if isinstance(data.get("contact"), dict):
        p["contact"] = {k: str(v).strip()[:200] for k, v in data["contact"].items()
                        if k in ("email", "phone", "location", "linkedin", "github", "website") and str(v or "").strip()}
    if isinstance(data.get("roles"), list):
        roles = []
        for r in data["roles"][:25]:
            title, company = str(r.get("title", "")).strip()[:120], str(r.get("company", "")).strip()[:120]
            if not (title or company):
                continue
            start, end = _ym(r.get("start")), _ym(r.get("end")) or "Present"
            role = {"title": title, "company": company, "location": str(r.get("location", "")).strip()[:120], "start": start,
                    "end": end, "current": end == "Present", "bullets": [{"text": b} for b in _lines(r.get("bullets"), 12)],
                    "stack_line": ", ".join(_words(r.get("stack"), 20))}
            a = tuple(int(x) for x in start.split("-")) if start else None
            b = (dt.date.today().year, dt.date.today().month) if end == "Present" else (tuple(int(x) for x in end.split("-")) if end else None)
            role["months"] = resume_parse.months_between(a, b) if a and b else 0
            resume_parse.finish_role(role)
            roles.append(role)
        p["roles"] = roles
    if isinstance(data.get("education"), list):
        p["education"] = [{"school": str(e.get("school", "")).strip()[:150], "degree": str(e.get("degree", "")).strip()[:80],
                           "field": str(e.get("field", "")).strip()[:120], "start": str(e.get("start", "")).strip()[:10],
                           "end": str(e.get("end", "")).strip()[:10], "gpa": str(e.get("gpa", "")).strip()[:10], "notes": []}
                          for e in data["education"][:8] if str(e.get("school", "")).strip() or str(e.get("degree", "")).strip()]
    if "certifications" in data:
        p["certifications"] = _lines(data["certifications"], 20, 200)
    # skills: what the member lists + what their bullets prove
    listed_words = _words(data.get("skills"), 80) if "skills" in data else \
        (p.get("skills", {}).get("listed_only", []) + p.get("skills", {}).get("other_listed", []))
    listed = SK.find(", ".join(listed_words), trusted=True)
    bullet_text = "\n".join(b["text"] for r in p["roles"] for b in r["bullets"]) + "\n" + \
                  "\n".join(r.get("stack_line", "") for r in p["roles"])
    proven = SK.find(bullet_text, with_counts=True)
    p["skills"] = {"proven": [s for s, _ in proven.most_common()], "listed_only": [s for s in listed if s not in proven],
                   "other_listed": [w for w in listed_words if not SK.find(w, trusted=True)][:40],
                   "all": list(dict.fromkeys([s for s, _ in proven.most_common()] + listed))}
    # the fact guards compare generated text with raw_text: the member's own edits are facts too
    typed = "\n".join([p.get("summary", ""), bullet_text, ", ".join(listed_words), "\n".join(p.get("certifications", []))])
    p["raw_text"] = (old.get("raw_text", "") + "\n\n[edited on the team page]\n" + typed)[-60000:]
    p["metrics"] = sorted(set(resume_parse.metrics(bullet_text + "\n" + p.get("summary", ""))))
    p["edited"] = config.now().isoformat(timespec="seconds")
    resume_parse.derive(p)
    return p


PREF_LISTS = ("target_titles", "avoid_companies", "target_companies", "exclude_words", "home_cities")


def edit_prefs(old, data):
    pr = dict(old)
    for k in PREF_LISTS:
        if k in data:
            pr[k] = _words(data[k], 30)
    if "countries" in data:
        pr["countries"] = matcher.norm_countries(_words(data["countries"], 20)) or old.get("countries") or ["US"]
        from . import region as RG
        implied = RG.from_countries(pr["countries"])
        if implied and implied["region"] != pr.get("region"):        # e.g. a CV with no location defaulted to US
            pr["region"] = implied["region"]
            if implied["timezone"]:
                pr["timezone"] = implied["timezone"]
    if "onsite_ok" in data:
        pr["onsite_ok"] = bool(data["onsite_ok"])
    if "min_score" in data:
        try:
            pr["min_score"] = max(0, min(95, int(data["min_score"])))
        except (TypeError, ValueError):
            pass
    for k in ("work_auth", "salary_min"):
        if k in data:
            pr[k] = str(data[k] or "").strip()[:120]
    return pr


# ---------------------------------------------------------------- run
def _add(req, body):
    from . import service
    name = str(body.get("name", "")).strip()[:80]
    if not name or not body.get("file_b64"):
        raise ValueError("name and resume file are required")
    raw = base64.b64decode(str(body["file_b64"]).split(",")[-1])
    if len(raw) > MAX_FILE:
        raise ValueError("resume file is too big (max 1.5 MB)")
    with storage.connect() as con:
        if storage.member(con, storage.slugify(name)):
            raise ValueError(f"{name} is already a member: edit their profile instead")
    prefs = {"countries": _words(body.get("countries"), 20)} if body.get("countries") else None
    r = service.onboard(name, resume_b64=base64.b64encode(raw).decode(), filename=str(body.get("filename") or "resume.pdf")[-80:],
                        email=str(body.get("email") or "").strip() or None, prefs=prefs)
    return {"ok": True, "slug": r["slug"], "msg": f"added {name}: {len(r['profile']['roles'])} jobs read from the resume, "
            f"resume score {r['vault']['audit']['score']}/100, {(r.get('matched') or {}).get('matches', 0)} matches. Check the profile."}


def _edit(req, body):
    slug = str(req.get("member") or "")
    with storage.connect() as con:
        m = storage.member(con, slug)
        if not m:
            raise ValueError(f"no member {slug}")
        profile = edit_profile(m["profile"], body.get("profile") or {}) if body.get("profile") else m["profile"]
        prefs = edit_prefs(m["prefs"], body.get("prefs") or {}) if body.get("prefs") else m["prefs"]
        storage.save_member(con, m["name"], profile, prefs, m["resume_file"], m["email"], slug)
        m = storage.member(con, slug)
        matched = matcher.match_member(con, m, log=lambda *_: None)
        v = vault.build(con, m)
    return {"ok": True, "slug": slug, "msg": f"saved: {len(profile['roles'])} jobs, resume score {v['audit']['score']}/100, "
            f"{matched['matches'] if matched else 0} matches"}


def _delete(req, body):
    """Remove a member everywhere: database rows (matches, applications, history) and their folder (resume, vault)."""
    import shutil
    slug = str(req.get("member") or "")
    with storage.connect() as con:
        m = storage.member(con, slug)
        if not m:
            raise ValueError(f"no member {slug} (already deleted?)")
        storage.delete_member(con, m["id"])
    folder = (config.MEMBERS / slug).resolve()
    if folder.parent == config.MEMBERS.resolve():          # never anything outside the members folder
        shutil.rmtree(folder, ignore_errors=True)
    return {"ok": True, "slug": slug, "msg": f"deleted {m['name']}: profile, resume file, matches and applications removed"}


def apply(log=print):
    reqs = pending()
    applied = _applied()
    n = 0
    for req in reqs:
        if req["rid"] in applied:
            continue
        try:
            if req.get("body") is None:
                raise ValueError("the request didn't arrive complete; please send it again")
            res = {"add": _add, "edit": _edit, "delete": _delete}[req.get("action")](req, req["body"])
        except Exception as e:
            res = {"ok": False, "msg": str(e)[:300]}
        res.update({"action": req.get("action"), "member": res.get("slug") or req.get("member") or (req.get("body") or {}).get("name", ""),
                    "at": config.now().isoformat(timespec="seconds")})
        applied[req["rid"]] = res
        n += 1
        log(f"{req.get('action')} {res['member']}: {res['msg']}")
    if n:
        config.ensure_dirs()
        APPLIED.write_text(json.dumps(applied, indent=1), encoding="utf-8")
    return {"applied": n, "waiting": len([r for r in reqs if r["rid"] not in applied])}


def confirm(log=print):
    sb, entries = _entries()
    if not sb:
        return {"confirmed": 0}
    done = {e.get("rid") for e in entries.values() if e.get("kind") == DONE}
    n = 0
    for rid, res in _applied().items():
        if rid not in done:
            progress.put(sb, export.get_password(ask=False), DONE, rid, {"kind": DONE, "rid": rid, **res})
            n += 1
    log(f"confirmed {n} team change(s)")
    return {"confirmed": n}

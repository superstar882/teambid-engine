"""Per-job facts from the description (and, for the top candidates, the application form).

Computed once per scan for every engineering job whose description arrives with the board's own list (Ashby, Lever,
Greenhouse with content, Recruitee, and the feeds), and on demand for the rest. Only this compact summary is kept, not
the text (330k descriptions would not fit in the cloud copy). Every member is scored against the same facts:

  must / nice   skills the post requires / prefers (canonical names)
  years         years of experience it asks for (smallest number mentioned), or None
  regions       country groups and region words the post mentions, "worldwide", and "<group>_tz" for time-zone hints
  restrict      country groups whose work rights the post requires
  us_only       "US residents only", "US time zones", ...
  in_office / full_remote / no_sponsor
  form          set once the application form was read: {"questions": [...], "restrict": [...], "us_only": bool}
"""
import json
import re

ENG_TITLE = re.compile(r"(?i)\b(engineer(ing)?|developer|programmer|architect|SRE|site reliability|devops|dev ?ops|"
                       r"data scientist|scientist|machine learning|ML|AI|analytics engineer|technical staff|tech lead|"
                       r"full[- ]?stack|back[- ]?end|front[- ]?end|software|platform|infrastructure|SDET|QA|test automation|"
                       r"mobile|iOS|Android|cloud|security engineer|data)\b")


def is_engineering(title):
    from .matcher import NON_ENG
    return bool(ENG_TITLE.search(title or "")) and not NON_ENG.search(title or "")


def analyze(text, title=""):
    from .. import tailor
    from . import matcher as M
    text = text or ""
    jd = tailor.analyze_jd(text, title)
    regions = {c for c, pat in M.COUNTRY.items() if pat.search(text)}
    if M.WORLDWIDE.search(text):
        regions.add("worldwide")
    regions |= {f"{c}_tz" for c, pat in M.TZ_EVIDENCE.items() if pat.search(text)}
    return {"must": jd["required"][:20], "nice": jd["preferred"][:15], "years": jd["years"],
            "regions": sorted(regions), "restrict": [c for c, pat in M.RESTRICT.items() if pat.search(text)],
            "us_only": bool(M.US_ONLY.search(text)), "in_office": bool(M.IN_OFFICE.search(text)),
            "full_remote": bool(M.FULL_REMOTE.search(text)), "no_sponsor": bool(M.NO_SPONSOR.search(text)),
            "chars": len(text)}


def _ensure(con):
    con.execute("CREATE TABLE IF NOT EXISTS job_facts (job_id INTEGER PRIMARY KEY, data TEXT NOT NULL, day TEXT)")


def save(con, rows, day):
    """rows: [(job_id, facts dict)]"""
    _ensure(con)
    con.executemany("INSERT INTO job_facts (job_id, data, day) VALUES (?,?,?) ON CONFLICT(job_id) DO UPDATE SET "
                    "data=excluded.data, day=excluded.day", [(j, json.dumps(f, separators=(",", ":")), day) for j, f in rows])


def load(con, job_ids=None):
    _ensure(con)
    if job_ids is None:
        rows = con.execute("SELECT job_id, data FROM job_facts")
    else:
        ids = list(job_ids)
        out = {}
        for i in range(0, len(ids), 900):
            part = ids[i:i + 900]
            for r in con.execute(f"SELECT job_id, data FROM job_facts WHERE job_id IN ({','.join('?' * len(part))})", part):
                out[r["job_id"]] = json.loads(r["data"])
        return out
    return {r["job_id"]: json.loads(r["data"]) for r in rows}


def prune(con, keep_day):
    """Drop facts of jobs that are gone (not seen in the latest scan)."""
    _ensure(con)
    con.execute("DELETE FROM job_facts WHERE job_id IN (SELECT f.job_id FROM job_facts f JOIN jobs j ON j.id=f.job_id WHERE j.last_seen < ?)",
                (keep_day,))


def _work(args):
    job_id, text, title = args
    try:
        return job_id, analyze(text, title)
    except Exception:
        return job_id, None


def build(con, jobs, day, log=print, processes=None):
    """Analyze engineering jobs that came with a description and weren't analyzed before. -> (new, already known)"""
    import os
    from concurrent.futures import ProcessPoolExecutor
    from .. import storage
    _ensure(con)
    todo = {storage.url_key(j["url"]): j for j in jobs if j.get("description") and j.get("url")}
    keys, ids = list(todo), {}
    for i in range(0, len(keys), 900):
        part = keys[i:i + 900]
        for r in con.execute(f"SELECT id, url_key FROM jobs WHERE url_key IN ({','.join('?' * len(part))})", part):
            ids[r["url_key"]] = r["id"]
    have = {r[0] for r in con.execute("SELECT job_id FROM job_facts")}
    args = [(ids[k], todo[k]["description"], todo[k].get("title", "")) for k in keys if k in ids and ids[k] not in have]
    kept = sum(1 for k in keys if k in ids and ids[k] in have)
    if not args:
        return 0, kept
    rows = []
    try:
        with ProcessPoolExecutor(processes or os.cpu_count()) as ex:
            rows = [r for r in ex.map(_work, args, chunksize=100) if r[1]]
    except Exception as e:                      # e.g. no process support: do it in this process
        log(f"  (analysis in one process: {type(e).__name__})")
        rows = [r for r in map(_work, args) if r[1]]
    save(con, rows, day)
    return len(rows), kept

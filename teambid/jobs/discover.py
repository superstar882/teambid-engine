"""Find the company's own careers page for jobs that only came from a feed (Himalayas, Jobicy, 4dayweek, ...).

Feeds link back to themselves, not to the company, and re-date jobs they list again. With the company's own board in
the scan, the matcher can compare the two copies (real posting date, still open or not). Each day, for feed companies
the scan doesn't cover, try likely board names on the job systems that use plain names, and keep a board only if it
lists one of the same job titles the feed showed (so "Acme" on Greenhouse is the right Acme). Found boards are saved
with a small company profile in WORKSPACE/found-boards.json and scanned every day after that, under the feed's
company name. Misses are remembered too and tried again after RETRY_DAYS.
"""
import datetime as dt
import json
import re
from concurrent.futures import ThreadPoolExecutor

from .. import config
from . import ats
from .matcher import dedupe_key

REGISTRY = config.WORKSPACE / "found-boards.json"
RETRY_DAYS = 30
# most common first; Workday and iCIMS need a tenant + site name, which can't be guessed from the company name
SYSTEMS = ("greenhouse", "lever", "ashby", "workable", "smartrecruiters", "recruitee", "breezy", "bamboohr",
           "teamtailor", "personio", "pinpoint")
CAREERS = {"greenhouse": "https://job-boards.greenhouse.io/{}", "lever": "https://jobs.lever.co/{}",
           "ashby": "https://jobs.ashbyhq.com/{}", "workable": "https://apply.workable.com/{}",
           "smartrecruiters": "https://jobs.smartrecruiters.com/{}", "recruitee": "https://{}.recruitee.com",
           "breezy": "https://{}.breezy.hr", "bamboohr": "https://{}.bamboohr.com/careers",
           "teamtailor": "https://{}.teamtailor.com/jobs", "personio": "https://{}.jobs.personio.de",
           "pinpoint": "https://{}.pinpointhq.com"}
SUFFIX = re.compile(r"(?i)\b(inc|llc|ltd|limited|gmbh|corp|corporation|co|company|holdings?|group|plc|s\.?a|b\.?v|ag|"
                    r"technologies|technology|labs?|software|solutions)\b\.?")


def load():
    try:
        d = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d.setdefault("boards", {})
    d.setdefault("misses", {})
    return d


def save(d):
    REGISTRY.write_text(json.dumps(d, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def boards():
    """{(ats, slug): company name} of every board found so far."""
    return {(b["ats"], b["slug"]): b["name"] for b in load()["boards"].values()}


def slugs(name):
    """Likely board names: "AutoRABIT Holding Inc." -> autorabitholdinginc, autorabit, autorabit-holding-inc, ..."""
    base = re.sub(r"\(.*?\)", "", name).replace("&", "and")
    words = [w.lower() for w in re.findall(r"[A-Za-z0-9]+", base)]
    core = [w.lower() for w in re.findall(r"[A-Za-z0-9]+", SUFFIX.sub(" ", base))] or words
    return [s for s in dict.fromkeys(["".join(core), "-".join(core), "".join(words), "-".join(words),
                                      core[0] if core and len(core[0]) >= 4 else ""]) if s][:4]


def _probe(name, titles):
    """-> (ats, slug, jobs) of the first board that lists one of these titles, or None."""
    for s in slugs(name):
        for a in SYSTEMS:
            try:
                js = ats.fetch(s, a)
            except Exception:
                continue
            if js and any(dedupe_key(name, j.get("title"))[1] in titles for j in js):
                return a, s, js
    return None


def run(feed_jobs, covered, day, log=print, limit=200, workers=32):
    """Look for the boards of feed companies whose names no scanned board carries today.

    covered: company keys (dedupe_key(...)[0]) seen on company boards in this scan. A board we already scan under
    another name ("Driveempower" for the feed's "Empower") is found again and saved, so it carries the feed's name.
    -> board jobs from boards found now (company = the feed's name), to add to today's scan."""
    reg = load()
    today = dt.date.fromisoformat(day)
    todo = {}
    for j in feed_jobs:
        name = (j.get("company") or "").strip()
        ck, tk = dedupe_key(name, j.get("title"))
        if len(ck) < 2 or ck in covered or ck in reg["boards"]:
            continue
        tried = reg["misses"].get(ck)
        if tried and (today - dt.date.fromisoformat(tried)).days < RETRY_DAYS:
            continue
        t = todo.setdefault(ck, {"name": name, "titles": set(), "via": j.get("source")})
        t["titles"].add(tk)
    items = sorted(todo.items(), key=lambda kv: -len(kv[1]["titles"]))[:limit]     # companies with most jobs first
    if not items:
        return []
    log(f"looking for the careers pages of {len(items):,} companies seen only on job feeds...")
    with ThreadPoolExecutor(workers) as ex:
        found = list(ex.map(lambda kv: _probe(kv[1]["name"], kv[1]["titles"]), items))
    new_jobs, hits = [], 0
    for (ck, t), f in zip(items, found):
        if not f:
            reg["misses"][ck] = day
            continue
        a, s, js = f
        hits += 1
        reg["misses"].pop(ck, None)
        reg["boards"][ck] = {"name": t["name"], "ats": a, "slug": s, "careers": CAREERS[a].format(s),
                             "via": t["via"], "found": day, "open_jobs": len(js)}
        for job in js:
            new_jobs.append(dict(job, company=t["name"], ats=a, source="Company board"))
    save(reg)
    log(f"found {hits:,} careers pages ({len(reg['boards']):,} saved so far), {len(new_jobs):,} jobs from them")
    return new_jobs

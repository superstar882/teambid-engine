"""Application-form questions for the top candidates: they often say what the description doesn't ("Are you legally
authorized to work in the United States?", "Do you hold a valid work permit for France?", "Do you speak fluent French?").

Allowed sources only:
  Greenhouse  official boards API with ?questions=true
  Lever       the public /apply page (robots.txt: Allow /, Crawl-delay 1, so one request a second)
  Workable    apply.workable.com/api/v1/jobs/{code}/form (robots.txt allows everything)
  Ashby       NOT read: jobs.ashbyhq.com/robots.txt disallows /api/, where its form lives. Ashby's official job API
              already gives the full description and the workplace type (Remote / Hybrid / On-site).
"""
import re
import time

import requests

from .. import config

H = {"User-Agent": config.USER_AGENT}
RELEVANT = re.compile(r"(?i)(authori[sz]ed|work permit|right to work|eligib|visa|sponsor|located|location|reside|residen|"
                      r"based in|relocat|time ?zone|country|city, state|citizen|clearance|fluent|speak|language|on-?site|hybrid|"
                      r"office|commute)")
LANG = re.compile(r"(?i)\b(?:fluent|native|proficient|business[- ]level|C1|C2)\b[^?]{0,40}?\b(German|French|Dutch|Spanish|Italian|"
                  r"Portuguese|Polish|Swedish|Danish|Norwegian|Finnish|Czech|Hebrew|Japanese|Korean|Mandarin|Chinese|Arabic|Turkish)\b|"
                  r"\b(?:speak|write)\b[^?]{0,20}\b(German|French|Dutch|Spanish|Italian|Portuguese|Polish|Swedish|Danish|Norwegian|"
                  r"Finnish|Czech|Hebrew|Japanese|Korean|Mandarin|Chinese|Arabic|Turkish)\b")
_last_lever = [0.0]


def greenhouse(url):
    m = re.search(r"greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)/jobs/(\d+)", url) or None
    if not m:
        return None
    r = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{m[1]}/jobs/{m[2]}", params={"questions": "true"}, headers=H, timeout=20)
    if not r.ok:
        return None
    j = r.json()
    out = []
    for q in (j.get("questions") or []) + (j.get("location_questions") or []):
        label = (q.get("label") or "").strip()
        opts = [v.get("label", "") for f in q.get("fields") or [] for v in (f.get("values") or [])]
        if label and label.lower() not in ("longitude", "latitude"):
            out.append(label + (" [" + " / ".join(o for o in opts[:6] if o) + "]" if opts and RELEVANT.search(label) else ""))
    return out


def lever(url):
    m = re.match(r"(https://jobs\.(?:eu\.)?lever\.co/[\w.-]+/[\w-]{36})", url)
    if not m:
        return None
    wait = 1.05 - (time.monotonic() - _last_lever[0])          # robots.txt: Crawl-delay 1
    if wait > 0:
        time.sleep(wait)
    _last_lever[0] = time.monotonic()
    r = requests.get(m[1] + "/apply", headers=H, timeout=20)
    if not r.ok:
        return None
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>|✱", " ", x)).strip()
            for x in re.findall(r'<div class="application-label[^"]*"[^>]*>(.*?)</div>', r.text, re.S)]


def workable(url):
    m = re.search(r"apply\.workable\.com/(?:[\w-]+/)?j/([A-Z0-9]{6,})", url)
    if not m:
        return None
    r = requests.get(f"https://apply.workable.com/api/v1/jobs/{m[1]}/form", headers={**H, "Accept": "application/json"}, timeout=20)
    if not r.ok:
        return None
    out = []
    for sec in r.json() if isinstance(r.json(), list) else []:
        for f in sec.get("fields") or []:
            label = (f.get("label") or "").strip()
            if label and f.get("id") not in ("firstname", "lastname", "email", "phone", "address", "avatar", "resume", "cover_letter"):
                out.append(label)
    return out


def read(url):
    """-> list of question texts, or None when the form can't (or may not) be read."""
    try:
        if "greenhouse.io" in url:
            return greenhouse(url)
        if "lever.co" in url:
            return lever(url)
        if "apply.workable.com" in url:
            return workable(url)
    except requests.RequestException:
        return None
    return None


def analyze(questions):
    """Questions -> {"questions": the relevant ones, "restrict": country groups it requires, "us_only", "languages"}."""
    from .matcher import COUNTRY, US_ONLY
    rel = [q for q in questions if RELEVANT.search(q)]
    restrict, us_only, langs, office = set(), False, set(), ""
    for q in rel:
        about_rights = re.search(r"(?i)authori[sz]ed|work permit|right to work|eligib|reside|residen|located|based in|citizen", q)
        if about_rights:
            for c, pat in COUNTRY.items():
                if pat.search(q.split(" [")[0]):          # the question itself, not its answer options
                    restrict.add(c)
        if re.search(r"(?i)city, state|\b(US|U\.S\.) state\b", q) or US_ONLY.search(q):
            us_only = True
        for m in LANG.finditer(q):
            langs.add((m.group(1) or m.group(2)).title())
        # "Are you available to work in a hybrid model...", "Our office is in Penang, are you fine to work there?"
        if not office and re.search(r"(?i)\b(hybrid|on-?site|in[- ]office|office (is |located |based )?(at|in)|work (in|from) (our|the) office|"
                                    r"days? (a|per) week (in|at)|commute|come (in)?to the office)\b", q) \
                and not re.search(r"(?i)\b(fully remote|remote[- ]first|100% remote)\b", q):
            office = q.split(" [")[0][:140]
    return {"questions": rel[:10], "restrict": sorted(restrict), "us_only": us_only, "languages": sorted(langs), "office": office}


def read_all(con, day, log=print, minutes=30, workers=12):
    """Read the application form of every engineering job that has one we may read and haven't read yet (newest first).
    Greenhouse and Workable in parallel; Lever one request a second alongside. Stops after `minutes`; the next scan
    continues where this one stopped, since each form is kept with the job's facts."""
    import json
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from . import facts as F
    F._ensure(con)
    rows = con.execute("SELECT j.id, j.url, j.posted, f.data FROM jobs j JOIN job_facts f ON f.job_id=j.id WHERE j.last_seen=? AND "
                       "(j.url LIKE '%greenhouse.io%' OR j.url LIKE '%lever.co%' OR j.url LIKE '%apply.workable.com%')", (day,)).fetchall()
    todo = [(r["id"], r["url"], r["posted"] or "", json.loads(r["data"])) for r in rows]
    todo = sorted([t for t in todo if "form" not in t[3]], key=lambda t: t[2], reverse=True)
    if not todo:
        return 0
    deadline = time.monotonic() + minutes * 60
    done, lock = [], threading.Lock()

    def one(t):
        if time.monotonic() > deadline:
            return
        qs = read(t[1])
        if qs is not None:
            t[3]["form"] = analyze(qs)
            with lock:
                done.append((t[0], t[3]))
    lever = [t for t in todo if "lever.co" in t[1]]
    others = [t for t in todo if "lever.co" not in t[1]]
    lv = threading.Thread(target=lambda: [one(t) for t in lever], daemon=True)     # Crawl-delay 1 is enforced in lever()
    lv.start()
    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, others))
    lv.join(max(0, deadline - time.monotonic()))
    with lock:
        rows = list(done)
    F.save(con, rows, day)
    log(f"read {len(rows):,} application forms ({len(todo) - len(rows):,} left for the next scan)")
    return len(rows)

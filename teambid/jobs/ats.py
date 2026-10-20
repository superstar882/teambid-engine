"""Readers for 10 job systems' public job feeds (no login, no scraping of LinkedIn/Indeed/Google).

Greenhouse, Ashby, Lever, SmartRecruiters, Workable, Recruitee, Breezy, BambooHR: public JSON feeds.
Workday: the public CXS search API (keyword searches; multi-location jobs are opened to read every location).
iCIMS: the public search page (HTML; about half of iCIMS sites use the layout this reader understands).

Hardening learned in production (Quick Bid, 2026-10): one Session per thread (connection reuse), short connect
timeout, browser headers for Workday/iCIMS (older Chrome versions get 405/429), Workday 429 retries, day-first and
month-first dates, and a per-board guard so one malformed board never stops a scan.
"""
import datetime as dt
import re
import threading
import time

import requests

from .. import config

UA = {"User-Agent": config.USER_AGENT, "Accept": "application/json"}
WD_H = {"User-Agent": config.USER_AGENT, "Accept": "application/json", "Content-Type": "application/json", "Accept-Language": "en-US"}
ICIMS_H = {"User-Agent": config.USER_AGENT, "Accept": "text/html", "Accept-Language": "en-US"}
TIMEOUT = (5, 20)
SYSTEMS = ("greenhouse", "ashby", "lever", "smartrecruiters", "workable", "recruitee", "breezy", "bamboohr", "icims", "workday")
TECH_TITLE = re.compile(r"(?i)\b(engineer|developer|programmer|software|data|machine learning|ml|ai|scientist|analyst|devops|sre|"
                        r"architect|platform|cloud|security|qa|sdet|mobile|ios|android|frontend|backend|full[- ]?stack|web)\b")
BLOCKED = {}
_tls = threading.local()


def http():
    s = getattr(_tls, "s", None)
    if s is None:
        s = _tls.s = requests.Session()
    return s


def get(url, **kw):
    try:
        r = http().get(url, headers=kw.pop("headers", UA), timeout=TIMEOUT, **kw)
        return r.json() if r.ok else None
    except (requests.RequestException, ValueError):
        return None


def iso(ts):
    """Any timestamp -> 'YYYY-MM-DD' (UTC date) or None."""
    if ts in (None, ""):
        return None
    try:
        if isinstance(ts, (int, float)):
            d = dt.datetime.fromtimestamp(ts / 1000 if ts > 1e11 else ts, dt.timezone.utc)
        else:
            d = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return d.date().isoformat()
    except (ValueError, OverflowError, OSError):
        m = re.match(r"(\d{4}-\d{2}-\d{2})", str(ts))
        return m[1] if m else None


def fetch(slug, ats, queries=("software engineer", "data engineer", "machine learning", "developer")):
    """All open jobs on one company board -> list of dicts (title, location, url, posted, company, ats)."""
    s, jobs = slug, []
    company = slug.split("|")[0].replace("-", " ").replace("_", " ").title()
    if ats == "greenhouse":
        for j in (get(f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs") or {}).get("jobs", []):
            jobs.append({"title": j.get("title", ""), "location": (j.get("location") or {}).get("name", ""),
                         "url": j.get("absolute_url"), "posted": iso(j.get("first_published") or j.get("updated_at"))})
    elif ats == "ashby":
        for j in (get(f"https://api.ashbyhq.com/posting-api/job-board/{s}") or {}).get("jobs", []):
            loc = " / ".join(filter(None, [j.get("location", ""), *[x.get("location", "") for x in j.get("secondaryLocations") or []],
                                           "Remote" if j.get("isRemote") or j.get("workplaceType") == "Remote" else ""]))
            jobs.append({"title": j.get("title", ""), "location": loc, "url": j.get("jobUrl"), "posted": iso(j.get("publishedAt"))})
    elif ats == "lever":
        for j in get(f"https://api.lever.co/v0/postings/{s}?mode=json") or []:
            c = j.get("categories") or {}
            loc = " / ".join(filter(None, [c.get("location", ""), *(c.get("allLocations") or []),
                                           "Remote" if j.get("workplaceType") == "remote" else ""]))
            jobs.append({"title": j.get("text", ""), "location": loc, "url": j.get("hostedUrl"), "posted": iso(j.get("createdAt"))})
    elif ats == "smartrecruiters":
        for j in (get(f"https://api.smartrecruiters.com/v1/companies/{s}/postings", params={"limit": 100}) or {}).get("content", []):
            loc = j.get("location") or {}
            where = ", ".join(filter(None, [loc.get("city"), loc.get("region"), (loc.get("country") or "").upper()]))
            jobs.append({"title": j.get("name", ""), "location": ("Remote " if loc.get("remote") else "") + where,
                         "url": f"https://jobs.smartrecruiters.com/{s}/{j.get('id')}", "posted": iso(j.get("releasedDate"))})
    elif ats == "workable":
        for j in (get(f"https://apply.workable.com/api/v1/widget/accounts/{s}") or {}).get("jobs", []):
            where = ", ".join(filter(None, [j.get("city"), j.get("state"), j.get("country")]))
            jobs.append({"title": j.get("title", ""), "location": ("Remote " if j.get("telecommuting") else "") + where,
                         "url": j.get("url") or j.get("shortlink"), "posted": iso(j.get("published_on"))})
    elif ats == "recruitee":
        for j in (get(f"https://{s}.recruitee.com/api/offers/") or {}).get("offers", []):
            jobs.append({"title": j.get("title", ""), "location": ("Remote " if j.get("remote") else "") + (j.get("location") or ""),
                         "url": j.get("careers_url"), "posted": iso(j.get("published_at"))})
    elif ats == "breezy":
        d = get(f"https://{s}.breezy.hr/json")
        for j in d if isinstance(d, list) else []:
            loc = j.get("location") or {}
            jobs.append({"title": j.get("name", ""), "location": ("Remote " if loc.get("is_remote") else "") + (loc.get("name") or ""),
                         "url": j.get("url"), "posted": iso(j.get("published_date"))})
    elif ats == "bamboohr":
        for j in (get(f"https://{s}.bamboohr.com/careers/list") or {}).get("result", []):
            loc = j.get("location") or {}
            jobs.append({"title": j.get("jobOpeningName", ""), "location": ("Remote " if j.get("isRemote") else "") +
                         ", ".join(filter(None, [loc.get("city"), loc.get("state")])),
                         "url": f"https://{s}.bamboohr.com/careers/{j.get('id')}", "posted": None})
    elif ats == "icims":
        jobs = _icims(s)
    elif ats == "workday":
        jobs = _workday(s, queries)
    for j in jobs:
        j["company"], j["ats"] = company, ats
    return [j for j in jobs if j.get("url") and j.get("title")]


def _icims(s):
    jobs, seen = [], set()
    for q in ("engineer", "developer", "data"):
        try:
            r = http().get(f"https://{s}.icims.com/jobs/search", params={"ss": 1, "searchKeyword": q, "in_iframe": 1},
                           headers=ICIMS_H, timeout=TIMEOUT)
            page = r.text if r.ok else ""
        except requests.RequestException:
            page = ""
        for card in page.split('class="iCIMS_JobCardItem"')[1:]:
            a = re.search(r'href="(https://[\w.-]+\.icims\.com/jobs/\d+/[^"?]+/job)[^"]*"[^>]*>.*?<h3[^>]*>\s*([^<]+?)\s*</h3>', card, re.S)
            if not a or a[1] in seen:
                continue
            seen.add(a[1])
            loc = re.search(r'>(?:Job )?Locations?</span>\s*<span[^>]*>\s*([^<]+?)\s*</span>', card)
            kind = re.search(r'>(?:Location Type|Remote)</dt>.*?<span[^>]*>\s*([^<]+?)\s*</span>', card, re.S)
            where = " ".join(filter(None, [kind[1] if kind and "remote" in kind[1].lower() else "", loc[1] if loc else ""]))
            posted = None
            if (w := re.search(r'title="(\d{1,2})/(\d{1,2})/(\d{4})', card)):
                a_, b_, y = int(w[1]), int(w[2]), int(w[3])
                m, d = (a_, b_) if a_ <= 12 else (b_, a_)
                try:
                    posted = dt.date(y, m, d).isoformat()
                except ValueError:
                    posted = None
            jobs.append({"title": a[2], "location": where, "url": a[1], "posted": posted})
    return jobs


def _workday(slug, queries):
    parts = slug.split("|")
    if len(parts) != 3:
        return []
    tenant, wd, site = parts
    api = f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    jobs, seen = [], set()
    for qi, q in enumerate(queries):
        posts = []
        for wait in (0, 3, 10):
            time.sleep(wait)
            try:
                r = http().post(api, json={"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": q}, headers=WD_H, timeout=TIMEOUT)
                if r.status_code == 429:
                    continue
                posts = r.json().get("jobPostings", []) if r.ok else []
            except (requests.RequestException, ValueError):
                pass
            break
        else:
            BLOCKED["workday"] = BLOCKED.get("workday", 0) + 1
            break
        if not posts and qi == 0:
            break
        for p in posts:
            path = p.get("externalPath", "")
            if path in seen:
                continue
            seen.add(path)
            txt = p.get("postedOn", "")
            days = 0 if "Today" in txt else int((re.search(r"(\d+)", txt) or [0, 99])[1])
            if "30+" in txt:
                days = 31
            job = {"title": p.get("title", ""), "location": p.get("locationsText", ""),
                   "url": f"https://{tenant}.{wd}.myworkdayjobs.com/{site}{path}",
                   "posted": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).date().isoformat()}
            if re.fullmatch(r"\d+ Locations", job["location"]) and TECH_TITLE.search(job["title"]):
                try:
                    info = http().get(f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}{path}",
                                      headers=WD_H, timeout=TIMEOUT).json().get("jobPostingInfo", {})
                    job["location"] = " / ".join(filter(None, [info.get("location"), *(info.get("additionalLocations") or []), info.get("remoteType")]))
                    job["posted"] = iso(info.get("startDate")) or job["posted"]
                except (requests.RequestException, ValueError, AttributeError):
                    pass
            jobs.append(job)
    return jobs


def discover_company(name):
    """Find which public job system a company uses by trying its likely board names."""
    base = re.sub(r"\(.*?\)", "", name).replace("&", "and").strip()
    words = re.findall(r"[A-Za-z0-9]+", base)
    cands = list(dict.fromkeys(c for c in ["".join(words).lower(), "-".join(words).lower(), (words[0].lower() if words else "")] if c))
    for s in cands:
        if (j := get(f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs")) and j.get("jobs"):
            return "greenhouse", s
        if (j := get(f"https://api.ashbyhq.com/posting-api/job-board/{s}")) and j.get("jobs"):
            return "ashby", s
        if isinstance(j := get(f"https://api.lever.co/v0/postings/{s}?mode=json"), list) and j:
            return "lever", s
        if (j := get(f"https://apply.workable.com/api/v1/widget/accounts/{s}")) and j.get("jobs"):
            return "workable", s
    return None, None


class NetWatch:
    """Checks the internet every 20 s during a scan and records outage windows (start, end) in epoch seconds,
    so boards checked while offline can be re-checked instead of trusted as empty."""
    PROBES = ("https://www.gstatic.com/generate_204", "https://cloudflare.com/cdn-cgi/trace")

    def __init__(self):
        self.down_secs, self.windows, self._open, self._last_ok = 0, [], None, time.time()
        self._stop = threading.Event()
        threading.Thread(target=self._loop, daemon=True).start()

    def _probe(self):
        for url in self.PROBES:              # up if any probe answers: one slow or blocked host isn't an outage
            try:
                requests.get(url, timeout=15)
                return True
            except requests.RequestException:
                continue
        return False

    def _loop(self):
        fails = 0
        while not self._stop.wait(20):
            if self._probe():
                if self._open is not None:   # back online: close the window
                    self.windows.append((self._open, time.time()))
                    self._open = None
                fails, self._last_ok = 0, time.time()
                continue
            fails += 1
            if fails < 2:                    # one failed check on a busy, slow link is noise: wait for a second one
                continue
            self.down_secs += 40 if fails == 2 else 20
            if self._open is None:           # it may have dropped right after the last good check
                self._open = self._last_ok

    def stop(self):
        self._stop.set()
        if self._open is not None:
            self.windows.append((self._open, time.time()))
            self._open = None
        return self.down_secs

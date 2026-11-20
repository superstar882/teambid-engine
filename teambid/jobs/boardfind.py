"""More company boards from public lists of job links.

A job link names its job system and the company's board on it (jobs.ashbyhq.com/acme/...), so every list of job links
is also a list of boards. Boards the scan doesn't read yet are checked on the job system's own API and, when they list
open jobs, saved with the boards found through feeds (discover.py's registry, WORKSPACE/found-boards.json) and read
every day after that. Only the board addresses come from a list; the jobs come from each company's own board.

Lists (both public, and allowed for this):
- Simplify's GitHub lists (New-Grad-Positions and the internship list), every day. The simplify.jobs site itself
  forbids automated reading (Terms of Use, 2026-08-19); these lists are published on GitHub for anyone to use.
- Common Crawl's URL index (index.commoncrawl.org, an open dataset), once a week, a few index pages per job system (a
  different part each week) and best effort: the index is often busy, and then it is tried again the next day.
A board that lists no open jobs is tried again after RETRY_DAYS.
"""
import datetime as dt
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, unquote

import requests

from .. import config
from . import ats, discover

RETRY_DAYS = 30
CRAWL_DAYS = 7
FRESH_DAYS = 180              # listings closed longer ago than this aren't checked (their company may have left the system)
NOT_A_BOARD = {"www", "api", "app", "apps", "jobs", "careers", "career", "embed", "static", "help", "support", "blog", "docs",
               "status", "assets", "cdn", "boards", "job-boards", "apply", "admin", "login", "en", "search"}
PATTERNS = (    # job systems whose board is a path or a sub-domain name
    ("greenhouse", r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_(?:app|board)\?(?:[^#]*&)?for=)?([\w-]*)"),
    ("lever", r"jobs\.(?:eu\.)?lever\.co/([\w.-]*)"),
    ("ashby", r"jobs\.ashbyhq\.com/([^/?#]*)"),
    ("smartrecruiters", r"(?:jobs|careers)\.smartrecruiters\.com/([\w-]*)"),
    ("workable", r"apply\.workable\.com/([\w-]*)"),
    ("rippling", r"ats\.rippling\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]*)"),
    ("gem", r"jobs\.gem\.com/([\w-]*)"),
    ("recruitee", r"//([\w-]+)\.recruitee\.com"),
    ("breezy", r"//([\w-]+)\.breezy\.hr"),
    ("bamboohr", r"//([\w-]+)\.bamboohr\.com"),
    ("icims", r"//([\w-]+)\.icims\.com"),
    ("teamtailor", r"//([\w-]+)\.teamtailor\.com"),
    ("personio", r"//([\w-]+)\.jobs\.personio\.(?:de|com)"),
    ("pinpoint", r"//([\w-]+)\.pinpointhq\.com"),
    ("zohorecruit", r"//([\w-]+)\.zohorecruit\.com"),
)
WORKDAY = re.compile(r"//([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)")
ORACLE = re.compile(r"//([\w.-]+\.oraclecloud\.com)/hcmUI/CandidateExperience/[\w-]+/sites/([\w-]+)")
CRAWL = ("jobs.ashbyhq.com/*", "job-boards.greenhouse.io/*", "boards.greenhouse.io/*", "jobs.lever.co/*", "jobs.eu.lever.co/*",
         "apply.workable.com/*", "jobs.smartrecruiters.com/*", "ats.rippling.com/*", "jobs.gem.com/*", "*.myworkdayjobs.com",
         "*.icims.com", "*.breezy.hr", "*.recruitee.com", "*.bamboohr.com", "*.teamtailor.com", "*.pinpointhq.com",
         "*.jobs.personio.de")
INDEX = "https://index.commoncrawl.org/CC-MAIN-2026-43-index"        # the newest one is looked up (_newest_index)
H = {"User-Agent": config.USER_AGENT}


def board_of(url):
    """A job link -> (job system, board) or None: "https://jobs.ashbyhq.com/acme/1" -> ("ashby", "acme"),
    "https://acme.wd5.myworkdayjobs.com/en-US/Ext/job/..." -> ("workday", "acme|wd5|Ext")."""
    u = url or ""
    if (m := WORKDAY.search(u)) and m[3].lower() != "wday":
        return "workday", f"{m[1].lower()}|{m[2]}|{m[3]}"
    if (m := ORACLE.search(u)):
        return "oracle", f"{m[1].lower()}|{m[2]}"
    for system, pat in PATTERNS:
        if (m := re.search(pat, u, re.I)):
            slug = unquote(m[1]).strip().lower()
            return (system, slug) if slug and slug not in NOT_A_BOARD else None
    return None


def careers(system, slug):
    if system == "workday":
        tenant, wd, site = slug.split("|")
        return f"https://{tenant}.{wd}.myworkdayjobs.com/{site}"
    if system == "oracle":
        host, site = slug.split("|")
        return f"https://{host}/hcmUI/CandidateExperience/en/sites/{site}/requisitions"
    if system == "icims":
        return f"https://{slug}.icims.com/jobs"
    return discover.CAREERS[system].format(quote(slug))           # "hippocratic ai" -> hippocratic%20ai


def _name(slug):
    s = re.sub(r"(?i)^careers?-|-(careers?|jobs)$", "", slug.split("|")[0])
    return s.replace("-", " ").replace("_", " ").title()


def scanned():
    """(job system, board) of every board the scan reads, lowercase."""
    try:
        data = json.loads(config.BOARDS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    out = {(system, str(s).lower()) for system, slugs in data.items() for s in slugs}
    return out | {(a, s.lower()) for a, s in discover.boards()}


def _lists():
    """Simplify's public GitHub lists -> their listings (company_name, url, active, date_updated, ...)."""
    y = config.today().year
    out = []
    for repo in ("New-Grad-Positions", f"Summer{y + 1}-Internships", f"Summer{y}-Internships"):
        try:
            r = ats.http().get(f"https://raw.githubusercontent.com/SimplifyJobs/{repo}/dev/.github/scripts/listings.json",
                               headers=H, timeout=(5, 120))
            if r.ok:
                out += r.json()
        except (requests.RequestException, ValueError):
            continue
    return out


def _newest_index():
    try:
        return f"https://index.commoncrawl.org/{ats.http().get('https://index.commoncrawl.org/collinfo.json', headers=H, timeout=(5, 30)).json()[0]['id']}-index"
    except (requests.RequestException, ValueError, KeyError, IndexError):
        return None


def _crawl_host(pattern, week, api=None, pages=3):
    """Boards in a few pages of the crawl index for one URL pattern (a different part of the index each week).
    -> set, or None when the index didn't answer."""
    api, q = api or INDEX, {"url": pattern, "output": "json"}
    try:
        r = ats.http().get(api, params={**q, "showNumPages": "true"}, headers=H, timeout=(10, 90))
        if r.status_code != 200:
            return None
        n = int(json.loads(r.text.splitlines()[0])["pages"])
    except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
        return None
    out = set()
    for i in range(min(n, pages)):
        try:
            r = ats.http().get(api, params={**q, "fl": "url", "page": (week * pages + i) % n}, headers=H, timeout=(10, 120))
        except requests.RequestException:
            continue
        for line in r.text.splitlines() if r.status_code == 200 else []:
            try:
                b = board_of(json.loads(line)["url"])
            except (ValueError, KeyError, TypeError):
                continue
            if b:
                out.add(b)
    return out


def _crawl(week, log, minutes=10):
    """{(job system, board): ""} from the newest crawl index, or None when it didn't answer at all."""
    api = _newest_index()
    if not api:
        return None
    found, answered, stop = {}, False, time.monotonic() + minutes * 60
    for pattern in CRAWL:
        if time.monotonic() > stop:
            break
        got = _crawl_host(pattern, week, api)
        if got is None:
            continue
        answered = True
        for b in got:
            found.setdefault(b, "")
    if answered:
        log(f"crawl index: {len(found):,} boards in this week's part")
    return found if answered else None


def run(day, log=print, workers=32, limit=800):
    """Check the boards the lists name that the scan doesn't read yet; keep those with open jobs. -> boards found."""
    reg = discover.load()
    today = dt.date.fromisoformat(day)
    fresh = dt.datetime.combine(today - dt.timedelta(days=FRESH_DAYS), dt.time(), config.TZ).timestamp()
    cands = {}                                            # board -> (company name, list); Simplify's first, it names them
    for x in _lists():
        if isinstance(x, dict) and (x.get("active") or (x.get("date_updated") or 0) >= fresh):
            if (b := board_of(x.get("url"))):
                cands.setdefault(b, ((x.get("company_name") or "").strip(), "Simplify list"))
    last = reg.get("crawl_day")
    if not last or (today - dt.date.fromisoformat(last)).days >= CRAWL_DAYS:
        got = _crawl(today.toordinal() // 7, log)
        if got is not None:
            reg["crawl_day"] = day
            for b in got:
                cands.setdefault(b, ("", "Common Crawl"))
    have, todo = scanned(), []
    for (system, slug), (name, via) in cands.items():
        key = f"{system}:{slug}"
        if (system, slug.lower()) in have or key in reg["boards"] or (system == "oracle" and not name):
            continue                                      # an Oracle site's address doesn't say whose it is
        tried = reg["misses"].get(key)
        if tried and (today - dt.date.fromisoformat(tried)).days < RETRY_DAYS:
            continue
        todo.append((system, slug, name, via))
    todo = todo[:limit]
    found = 0
    if todo:
        log(f"checking {len(todo):,} company boards named in public job lists...")

        def check(t):
            try:
                return ats.fetch(t[1], t[0])
            except Exception:
                return []
        with ThreadPoolExecutor(workers) as ex:
            results = list(ex.map(check, todo))
        for (system, slug, name, via), js in zip(todo, results):
            key = f"{system}:{slug}"
            if not js:
                reg["misses"][key] = day
                continue
            found += 1
            reg["misses"].pop(key, None)
            reg["boards"][key] = {"name": name or _name(slug), "ats": system, "slug": slug, "careers": careers(system, slug),
                                  "via": via, "found": day, "open_jobs": len(js)}
        log(f"found {found:,} more company boards ({len(todo) - found:,} had no open jobs)")
    discover.save(reg)
    return found

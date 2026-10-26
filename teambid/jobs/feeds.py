"""Free remote-job feeds (no key): Himalayas (credit himalayas.app), RemoteOK, Remotive (cached, they ask for few calls),
Hacker News 'Who is hiring' (monthly thread)."""
import datetime as dt
import html
import json
import re

from .. import config
from .ats import get, iso


def _daily_cache(name, fetch):
    config.CACHE.mkdir(parents=True, exist_ok=True)
    f = config.CACHE / f"{name}-{config.today()}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    data = fetch()
    f.write_text(json.dumps(data), encoding="utf-8")
    return data


def himalayas(queries):
    out = []
    for q in queries[:10]:
        for sen in ("Entry-level", "Mid-level", "Senior"):
            d = get("https://himalayas.app/jobs/api/search", params={"q": q, "seniority": sen, "sort": "recent"})
            for j in (d or {}).get("jobs", []):
                locs = j.get("locationRestrictions") or []
                out.append({"company": j.get("companyName", ""), "title": j.get("title", ""),
                            "location": "Remote " + ", ".join(locs if isinstance(locs, list) else [str(locs)]),
                            "url": j.get("applicationLink") or j.get("guid"), "posted": iso(j.get("pubDate")),
                            # Himalayas lists on-site jobs too ("Location: Atlanta, GA"): the post is the only place it shows
                            "description": _txt(j.get("description")), "source": "Himalayas", "ats": "feed"})
    return out


def remoteok():
    d = get("https://remoteok.com/api") or []
    return [{"company": j.get("company", ""), "title": j.get("position", ""), "location": "Remote " + (j.get("location") or ""),
             "url": j.get("url"), "posted": iso(j.get("date")), "description": _txt(j.get("description")), "source": "RemoteOK", "ats": "feed"}
            for j in d if isinstance(j, dict) and j.get("position")]


def remotive():
    d = _daily_cache("remotive", lambda: get("https://remotive.com/api/remote-jobs") or {})
    return [{"company": j.get("company_name", ""), "title": j.get("title", ""), "location": "Remote " + (j.get("candidate_required_location") or ""),
             "url": j.get("url"), "posted": iso(j.get("publication_date")), "description": _txt(j.get("description")),
             "source": "Remotive", "ats": "feed"} for j in d.get("jobs", [])]


def hackernews():
    hits = (get("https://hn.algolia.com/api/v1/search_by_date", params={"tags": "story,author_whoishiring", "query": "who is hiring"}) or {}).get("hits", [])
    story = next((h for h in hits if h.get("title", "").startswith("Ask HN: Who is hiring?")), None)
    if not story:
        return []
    item = _daily_cache(f"hn-{story['objectID']}", lambda: get(f"https://hn.algolia.com/api/v1/items/{story['objectID']}") or {})
    out = []
    for c in item.get("children", []):
        text = html.unescape(re.sub(r"<[^>]+>", "\n", c.get("text") or ""))
        first = text.strip().split("\n")[0][:200]
        if "|" not in first:
            continue
        parts = [p.strip() for p in first.split("|")]
        out.append({"company": parts[0][:60], "title": " | ".join(parts[1:])[:140],
                    "location": first if re.search(r"(?i)remote", first) else "", "posted": None,
                    "url": f"https://news.ycombinator.com/item?id={c.get('id')}", "description": text[:12000],
                    "source": "HN Who is hiring", "ats": "feed"})
    return out


# ---------------------------------------------------------------- sources added for members outside the US
# Each was checked for free, public, allowed access (official API / feed / open data) on 2026-10-21.
# Feed jobs carry their description, so the "open to your region?" check can read it without another request.
import xml.etree.ElementTree as ET

from .ats import http, UA

EUROPE_LATAM_GEOS = ("europe", "emea", "uk", "poland", "serbia", "denmark", "sweden", "norway", "finland", "germany", "netherlands",
                     "czechia", "romania", "ukraine", "croatia", "hungary", "bulgaria", "portugal", "spain", "brazil", "latam")


def _txt(s, n=12000):
    return html.unescape(re.sub(r"<[^>]+>", " ", s or "")).strip()[:n]


def _rss(url, **kw):
    try:
        r = http().get(url, headers={**UA, "Accept": "application/rss+xml, application/xml, text/xml"}, timeout=30, **kw)
        return ET.fromstring(r.content) if r.ok else None
    except Exception:
        return None


def jobicy():
    """jobicy.com: remote jobs tagged by country/region (credit: keep the Jobicy URL; at most one pass an hour)."""
    out, seen = [], set()
    for geo in EUROPE_LATAM_GEOS:
        d = get("https://jobicy.com/api/v2/remote-jobs", params={"count": 100, "geo": geo, "industry": "engineering"}) or {}
        for j in d.get("jobs", []):
            if j.get("url") in seen:
                continue
            seen.add(j.get("url"))
            out.append({"company": j.get("companyName", ""), "title": html.unescape(j.get("jobTitle", "")),
                        "location": "Remote " + (j.get("jobGeo") or ""), "url": j.get("url"), "posted": iso(j.get("pubDate")),
                        "description": _txt(j.get("jobDescription")), "source": "Jobicy", "ats": "feed"})
    return out


def himalayas_countries(queries, countries=("GB", "PL", "RS", "DK", "BR", "SE", "NO", "FI", "DE", "NL", "PT", "ES", "RO", "CZ")):
    """Himalayas filtered by country (the plain search is US-heavy)."""
    out, seen = [], set()
    for c in countries:
        for q in queries[:4]:
            for page in (1, 2):
                d = get("https://himalayas.app/jobs/api/search", params={"q": q, "country": c, "sort": "recent", "page": page}) or {}
                for j in d.get("jobs", []):
                    url = j.get("applicationLink") or j.get("guid")
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    locs = j.get("locationRestrictions") or []
                    out.append({"company": j.get("companyName", ""), "title": j.get("title", ""),
                                "location": "Remote " + (", ".join(locs) if isinstance(locs, list) and locs else "Worldwide"),
                                "url": url, "posted": iso(j.get("pubDate")), "description": _txt(j.get("description")),
                                "source": "Himalayas", "ats": "feed"})
    return out


def fourdayweek(pages=20):
    """4dayweek.io v2: remote engineering jobs with countries per job (attribution: link back)."""
    out = []
    for page in range(1, pages + 1):
        d = get("https://4dayweek.io/api/v2/jobs", params={"work_arrangement": "remote", "category": "engineering", "limit": 100, "page": page}) or {}
        for j in d.get("data", []):
            locs = [x.get("country") or x.get("continent") or "" for x in j.get("locations") or [] if isinstance(x, dict)]
            comp = j.get("company") if isinstance(j.get("company"), dict) else {}
            out.append({"company": comp.get("name", "") or "", "title": j.get("title", ""),
                        "location": "Remote " + ", ".join(dict.fromkeys(l for l in locs if l)), "url": j.get("url"),
                        "posted": iso(j.get("posted_at")), "description": _txt(j.get("description")), "source": "4dayweek", "ats": "feed"})
        if not d.get("has_more"):
            break
    return [j for j in out if j["url"] and j["company"]]


def workingnomads():
    d = get("https://www.workingnomads.com/api/exposed_jobs/") or []
    return [{"company": j.get("company_name", ""), "title": j.get("title", ""), "location": "Remote " + (j.get("location") or ""),
             "url": j.get("url"), "posted": iso(j.get("pub_date")), "description": _txt(j.get("description")),
             "source": "Working Nomads", "ats": "feed"}
            for j in d if isinstance(j, dict) and re.search(r"(?i)develop|engineer|data|devops|sysadmin", j.get("category_name") or "")]


def getonboard(categories=("programming", "data-science-analytics", "sysadmin-devops-qa", "mobile-developer")):
    """Get on Board (LatAm): keep fully remote, and remote within a country (the location says which)."""
    out = []
    for cat in categories:
        for page in range(1, 6):
            d = get(f"https://www.getonbrd.com/api/v0/categories/{cat}/jobs", params={"per_page": 100, "page": page, "expand": '["company"]'}) or {}
            rows = d.get("data", [])
            for j in rows:
                a = j.get("attributes", {})
                mod = a.get("remote_modality") or ""
                if mod not in ("fully_remote", "remote_local"):
                    continue
                comp = a.get("company") if isinstance(a.get("company"), str) else \
                    ((((a.get("company") or {}).get("data") or {}).get("attributes") or {}).get("name", ""))
                countries = [c for c in a.get("countries") or [] if c and c.lower() != "remote"]
                # remote_local = remote, but only from the board's LatAm countries
                where = "Remote " + (", ".join(countries) if countries else ("Worldwide" if mod == "fully_remote" else "LATAM"))
                out.append({"company": comp or "LatAm company", "title": a.get("title", ""), "location": where,
                            "url": (j.get("links") or {}).get("public_url"), "posted": iso(a.get("published_at")),
                            "description": _txt(a.get("description")), "source": "Get on Board", "ats": "feed"})
            if len(rows) < 100:
                break
    return [j for j in out if j["url"] and j["title"]]


def djinni(keywords=("Python", "JavaScript", "Java", "Golang", "DevOps", "Data Engineer", "React.js", "Node.js", ".NET", "PHP",
                     "iOS", "Android", "Data Science", "Scala", "Rust", "QA")):
    """Djinni (Central/Eastern Europe) RSS, one feed per stack keyword."""
    out, seen = [], set()
    for k in keywords:
        root = _rss("https://djinni.co/jobs/rss/", params={"primary_keyword": k, "employment": "remote"})
        for it in (root.findall(".//item") if root is not None else []):
            url = (it.findtext("link") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            title = it.findtext("title") or ""
            m = re.match(r"(.+?)\s+at\s+(.+)$", title)
            out.append({"company": (m.group(2) if m else "") or "Djinni employer", "title": (m.group(1) if m else title)[:200],
                        "location": "Remote", "url": url, "posted": iso(it.findtext("pubDate")),
                        "description": _txt(it.findtext("description")), "source": "Djinni", "ats": "feed"})
    return out


def jobindex_dk():
    """Jobindex (Denmark) RSS, programming category, remote / home-office searches. Title is 'Title, Company'."""
    out, seen = [], set()
    for q in ("remote", "hjemmearbejde", "fuldt remote"):
        for page in (1, 2, 3):
            root = _rss("https://www.jobindex.dk/jobsoegning.rss", params={"subid": 1, "q": q, "page": page})
            items = root.findall(".//item") if root is not None else []
            for it in items:
                url = (it.findtext("link") or "").strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                t = it.findtext("title") or ""
                title, _, company = t.rpartition(",")
                out.append({"company": company.strip() or "Danish employer", "title": (title or t).strip(), "location": "Remote Denmark",
                            "url": url, "posted": iso(it.findtext("pubDate")), "description": _txt(it.findtext("description")),
                            "source": "Jobindex", "ats": "feed"})
            if len(items) < 20:
                break
    return out


def jobtech_se():
    """Arbetsformedlingen JobTech (Sweden, CC0 open data): IT ads that likely allow remote work."""
    d = get("https://jobsearch.api.jobtechdev.se/search", params={"remote": "true", "occupation-field": "apaJ_2ja_LuF", "limit": 100}) or {}
    return [{"company": (j.get("employer") or {}).get("name", ""), "title": j.get("headline", ""), "location": "Remote Sweden",
             "url": j.get("webpage_url"), "posted": iso(j.get("publication_date")), "description": _txt((j.get("description") or {}).get("text")),
             "source": "JobTech SE", "ats": "feed"} for j in d.get("hits", []) if j.get("webpage_url")]


def github_br(repos=("backend-br/vagas", "frontendbr/vagas", "soujava/vagas-java", "react-brasil/vagas")):
    """Brazilian community job boards on GitHub: issues labelled 'Remoto'. Title often '[Remoto] Role na Company'."""
    out = []
    for repo in repos:
        d = get(f"https://api.github.com/repos/{repo}/issues", params={"state": "open", "per_page": 100}) or []
        for i in d if isinstance(d, list) else []:
            labels = " ".join(l.get("name", "") for l in i.get("labels") or [])
            if "pull_request" in i or not re.search(r"(?i)remot", labels + " " + (i.get("title") or "")):
                continue
            t = re.sub(r"\[[^\]]*\]\s*", "", i.get("title") or "").strip()
            m = re.match(r"(.+?)\s+(?:na|no|at|@)\s+(.+)$", t)
            out.append({"company": (m.group(2) if m else "") or "Empresa (Brasil)", "title": (m.group(1) if m else t)[:200],
                        "location": "Remote Brazil", "url": i.get("html_url"), "posted": iso(i.get("created_at")),
                        "description": _txt(i.get("body")), "source": "GitHub BR", "ats": "feed"})
    return out


def weworkremotely(cats=("remote-programming-jobs", "remote-full-stack-programming-jobs", "remote-back-end-programming-jobs",
                         "remote-front-end-programming-jobs", "remote-devops-sysadmin-jobs")):
    """We Work Remotely RSS (attribution). Title is 'Company: Title'; <region> says who can apply."""
    out, seen = [], set()
    for c in cats:
        root = _rss(f"https://weworkremotely.com/categories/{c}.rss")
        for it in (root.findall(".//item") if root is not None else []):
            url = (it.findtext("link") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            company, _, title = (it.findtext("title") or "").partition(":")
            out.append({"company": company.strip(), "title": title.strip() or company.strip(), "location": "Remote " + (it.findtext("region") or ""),
                        "url": url, "posted": iso(it.findtext("pubDate")), "description": _txt(it.findtext("description")),
                        "source": "We Work Remotely", "ats": "feed"})
    return out

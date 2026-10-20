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
                            "source": "Himalayas", "ats": "feed"})
    return out


def remoteok():
    d = get("https://remoteok.com/api") or []
    return [{"company": j.get("company", ""), "title": j.get("position", ""), "location": "Remote " + (j.get("location") or ""),
             "url": j.get("url"), "posted": iso(j.get("date")), "source": "RemoteOK", "ats": "feed"}
            for j in d if isinstance(j, dict) and j.get("position")]


def remotive():
    d = _daily_cache("remotive", lambda: get("https://remotive.com/api/remote-jobs") or {})
    return [{"company": j.get("company_name", ""), "title": j.get("title", ""), "location": "Remote " + (j.get("candidate_required_location") or ""),
             "url": j.get("url"), "posted": iso(j.get("publication_date")), "source": "Remotive", "ats": "feed"} for j in d.get("jobs", [])]


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
                    "url": f"https://news.ycombinator.com/item?id={c.get('id')}", "source": "HN Who is hiring", "ats": "feed"})
    return out

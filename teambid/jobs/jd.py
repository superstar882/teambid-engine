"""Job-post text from a URL: Greenhouse, Lever, Ashby and Workday public APIs, then schema.org JobPosting data,
then plain page text. LinkedIn/Indeed/Glassdoor block bots: paste the text instead."""
import html
import json
import re

import requests

from .. import config

UA = {"User-Agent": config.USER_AGENT, "Accept": "application/json", "Accept-Language": "en-US"}
BLOCKED = ("linkedin.com", "indeed.com", "glassdoor.com")


def strip_html(s):
    s = re.sub(r"(?is)<(script|style).*?</\1>", "", s or "")
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>|</div>", "\n", s)
    s = re.sub(r"(?i)<li[^>]*>", "- ", s)
    s = html.unescape(re.sub(r"<[^>]+>", "", s))
    return re.sub(r"\n\s*\n+", "\n\n", re.sub(r"[ \t]+", " ", s)).strip()


def greenhouse(url):
    m = re.search(r"greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)/jobs/(\d+)", url) or re.search(r"[?&]gh_jid=(\d+)", url)
    if not m or m.lastindex < 2:
        return None
    j = requests.get(f"https://boards-api.greenhouse.io/v1/boards/{m[1]}/jobs/{m[2]}", headers=UA, timeout=20).json()
    return {"title": j.get("title", ""), "company": m[1], "location": (j.get("location") or {}).get("name", ""),
            "text": strip_html(html.unescape(j.get("content", "")))}


def lever(url):
    m = re.search(r"jobs\.lever\.co/([\w-]+)/([\w-]{36})", url)
    if not m:
        return None
    j = requests.get(f"https://api.lever.co/v0/postings/{m[1]}/{m[2]}", headers=UA, timeout=20).json()
    parts = [j.get("descriptionPlain", "")] + [l.get("text", "") + "\n" + strip_html(l.get("content", "")) for l in j.get("lists", [])]
    parts.append(j.get("additionalPlain", ""))
    return {"title": j.get("text", ""), "company": m[1], "location": (j.get("categories") or {}).get("location", ""),
            "text": "\n\n".join(p for p in parts if p)}


def ashby(url):
    m = re.search(r"jobs\.ashbyhq\.com/([\w.-]+)/([\w-]{36})", url)
    if not m:
        return None
    board = requests.get(f"https://api.ashbyhq.com/posting-api/job-board/{m[1]}?includeCompensation=true", headers=UA, timeout=20).json()
    for j in board.get("jobs", []):
        if j.get("id") == m[2] or m[2] in j.get("jobUrl", ""):
            comp = (j.get("compensation") or {}).get("compensationTierSummary", "")
            return {"title": j.get("title", ""), "company": m[1], "location": j.get("location", ""),
                    "text": (j.get("descriptionPlain") or strip_html(j.get("descriptionHtml", ""))) + (f"\n\nCompensation: {comp}" if comp else "")}
    return None


def workday(url):
    m = re.match(r"https://([\w-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Z]{2}/)?([\w-]+)/job/([^?#]+?)(?:/apply.*)?(?:[?#].*)?$", url)
    if not m:
        return None
    tenant, wd, site, path = m.groups()
    r = requests.get(f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/job/{path}", headers=UA, timeout=20)
    if r.status_code in (403, 404):
        raise RuntimeError("Workday says this posting is closed or not public. Check the link, or paste the text.")
    j = r.json()["jobPostingInfo"]
    return {"title": j.get("title", ""), "company": tenant, "location": j.get("location", "") + (" / " + j["remoteType"] if j.get("remoteType") else ""),
            "text": strip_html(j.get("jobDescription", "")) + (f"\n\nPosted: {j['startDate']}" if j.get("startDate") else "")}


def generic(url):
    r = requests.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=20)
    r.raise_for_status()
    for block in re.findall(r'(?is)<script[^>]+application/ld\+json[^>]*>(.*?)</script>', r.text):
        try:
            data = json.loads(block)
        except ValueError:
            continue
        for d in data if isinstance(data, list) else data.get("@graph", [data]):
            if isinstance(d, dict) and d.get("@type") == "JobPosting":
                org = d.get("hiringOrganization") or {}
                return {"title": d.get("title", ""), "company": org.get("name", "") if isinstance(org, dict) else "",
                        "location": json.dumps(d.get("jobLocation", ""))[:200], "text": strip_html(d.get("description", ""))}
    title = re.search(r"(?is)<title>(.*?)</title>", r.text)
    return {"title": strip_html(title[1]) if title else "", "company": "", "location": "", "text": strip_html(r.text)[:20000]}


def fetch(url):
    if any(b in url for b in BLOCKED):
        raise RuntimeError(f"{url.split('/')[2]} blocks automated reading. Paste the job text instead.")
    for f in (greenhouse, lever, ashby, workday):
        try:
            if (res := f(url)):
                return res
        except RuntimeError:
            raise
        except Exception:
            continue
    return generic(url)

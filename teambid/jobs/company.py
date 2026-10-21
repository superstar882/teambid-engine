"""Where a company is based, from the office locations across all of its open postings.

Job systems have no "headquarters" field, but a board lists every posting's office: Mintive's jobs all say San Mateo or
San Francisco, so the company is in the Bay Area. Per company (company boards only, not feeds), count the office
locations of the day's postings, skipping remote/worldwide entries. A place marked HQ wins; city-level places count
double over country-only ones. Fully remote companies list no office, so they get no "based in".
"""
import json
import re
from collections import Counter

from .matcher import COUNTRY, REMOTE

SKIP = re.compile(r"(?i)^(remote|anywhere|worldwide|global|multiple locations?|various( locations)?|flexible|tbd|n/?a|"
                  r"distributed|hybrid|on-?site|in[- ]office|home ?based|work from home|wfh|emea|apac|amer|americas|latam|"
                  r"europe|eu|north america|us|usa|u\.s\.|united states|uk|\[hybrid\]|\[on-site\])$")
REGION = re.compile(r"(?i)(\bother (countries|locations|cities)\b|^(us|usa|u\.s\.|europe|eu|uk|apac|emea|americas?|asia)\s*[-–]?\s*"
                    r"(west|east|central|north|south|north ?east|south ?east|north ?west|south ?west|midwest|wide|only|based)$|"
                    r"^(east|west|central|north|south) (coast|us|europe)$|\btime ?zones?\b|\b(est|pst|cet|gmt|utc)\b|"
                    r"^(apac|emea|amer|latam)\s*[-–]\s*)")
HQ = re.compile(r"(?i)\b(hq|headquarters|head office)\b")


def _places(location):
    for part in re.split(r"\s*/\s*|\s*;\s*|\s+\|\s+|\s*·\s*|\n", location or ""):
        p = re.sub(r"\s+", " ", re.sub(r"(?i)\b(remote|hybrid|on-?site|in[- ]office|\(.*?\))\b", "", part)).strip(" ,-–()")
        p = re.sub(r"\[.*?\]", "", p).strip(" ,-–")
        p = re.sub(r"^[A-Z]{2,3}\s+-\s+", "", p)                     # "UK - London" -> "London"
        if len(p) < 3 or SKIP.match(p) or REMOTE.fullmatch(p) or REGION.search(p) or p.startswith("&"):
            continue
        yield p, bool(HQ.search(part))


def offices(locations):
    """-> list of (place, weight) best first."""
    score, hq = Counter(), set()
    for loc in locations:
        for place, is_hq in _places(loc):
            key = HQ.sub("", place).strip(" ,-")
            if not key:
                continue
            country_only = any(pat.fullmatch(key) for pat in COUNTRY.values())
            score[key] += 1 if country_only else 2
            if is_hq:
                hq.add(key)
    ranked = sorted(score.items(), key=lambda kv: (kv[0] not in hq, -kv[1], kv[0]))
    return ranked


def refresh(con, day):
    """Rebuild the companies table from the day's company-board postings."""
    con.execute("CREATE TABLE IF NOT EXISTS companies (name TEXT PRIMARY KEY, based_in TEXT, offices TEXT, postings INTEGER, day TEXT)")
    locs = {}
    for r in con.execute("SELECT company, location FROM jobs WHERE last_seen=? AND (source IS NULL OR source='Company board')", (day,)):
        locs.setdefault(r["company"], []).append(r["location"] or "")
    rows = []
    for name, ls in locs.items():
        ranked = offices(ls)
        if ranked:
            rows.append((name, ranked[0][0], json.dumps([p for p, _ in ranked[:4]]), len(ls), day))
    con.execute("DELETE FROM companies")
    con.executemany("INSERT INTO companies VALUES (?,?,?,?,?)", rows)
    return len(rows), len(locs)


def lookup(con, day):
    """company name -> {"based_in", "offices"}; refreshes first if the table is from another day."""
    try:
        have = con.execute("SELECT max(day) d FROM companies").fetchone()["d"]
    except Exception:
        have = None
    if have != day:
        refresh(con, day)
    return {r["name"]: {"based_in": r["based_in"], "offices": json.loads(r["offices"])}
            for r in con.execute("SELECT name, based_in, offices FROM companies")}

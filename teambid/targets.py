"""Target companies per member: seed companies in their lanes, plus companies that keep producing matches for them,
each marked with whether its job board is in the daily scan."""
import json
import re
from collections import Counter

import yaml

from . import config


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def board_index():
    if not config.BOARDS.exists():
        return {}
    idx = {}
    for ats, slugs in json.loads(config.BOARDS.read_text(encoding="utf-8")).items():
        for s in slugs:
            idx.setdefault(_norm(s.split("|")[0]), ats)
    return idx


def for_member(con, member, limit=40):
    seed = yaml.safe_load(config.SEED_COMPANIES.read_text(encoding="utf-8")) if config.SEED_COMPANIES.exists() else {}
    lanes = member["prefs"].get("lanes") or member["profile"].get("lanes", [])
    idx = board_index()
    rows, seen = [], set()
    for rank, lane in enumerate(lanes):
        for c in seed.get(lane, []):
            if c["name"] in seen:
                continue
            seen.add(c["name"])
            rows.append({"company": c["name"], "why": f"{lane} lane", "remote": c.get("remote", "?"),
                         "scanned": idx.get(_norm(c["name"]), ""), "matches": 0, "rank": rank})
    hits = Counter()
    for r in con.execute("SELECT j.company FROM matches m JOIN jobs j ON j.id=m.job_id WHERE m.member_id=?", (member["id"],)):
        hits[r["company"]] += 1
    for comp, n in hits.most_common(25):
        if comp in seen:
            for r in rows:
                if r["company"] == comp:
                    r["matches"] = n
            continue
        seen.add(comp)
        rows.append({"company": comp, "why": "keeps matching your profile", "remote": "?", "scanned": "yes", "matches": n, "rank": -1})
    rows.sort(key=lambda r: (-r["matches"], r["rank"]))
    return rows[:limit]


def to_markdown(name, rows):
    L = [f"# Target companies: {name}", "", "Seed list for your lanes plus companies that keep matching you. "
         "'Scanned' = its job board is in the daily scan (otherwise check its careers page by hand). "
         "Remote: first = remote-first, roles = some remote roles, office = mostly on-site.", "",
         "| Company | Why | Remote | Scanned | Matches so far |", "|---|---|---|---|---|"]
    L += [f"| {r['company']} | {r['why']} | {r['remote']} | {r['scanned'] or 'no'} | {r['matches']} |" for r in rows]
    return "\n".join(L) + "\n"

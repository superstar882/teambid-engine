"""Per-member matching over the shared job table.

Filters (any one drops the job): title not in the member's lanes, wrong level for their experience, non-engineering
or gig work, wrong place (not remote in an allowed country and not in their home area), too old, blocked company.
Score 0-100 from: lane rank, target-title phrase, skills named in the title (theirs: +, not theirs: -), level fit,
freshness, remote/home-area fit and target company. For the best matches the job description is fetched and the
share of its skills the member has ("coverage") adjusts the score.
"""
import datetime as dt
import json
import re
from collections import Counter

from .. import config, storage
from .. import skills as SK
from .. import local_ai
from . import jd as JD

NON_ENG = re.compile(r"(?i)\b(sales|account executive|account manager|recruiter|recruiting|talent|marketing|seo|copywriter|writer|"
                     r"designer|nurse|teacher|tutor\w*|instructor|trainer\w*|annotat\w*|rater\w*|label\w*|evaluator\w*|paid tasks|"
                     r"customer success|customer support|support specialist|paralegal|attorney|accountant|bookkeeper|driver|"
                     r"cashier|warehouse|technician|electrician|mechanic|chef|cook|receptionist|flexible hours|freelance|gig)\b")
LEVEL_WORDS = {
    "intern": re.compile(r"(?i)\b(intern|internship|co-op|apprentice)\b"),
    "junior": re.compile(r"(?i)\b(junior|jr\.?|entry|new grad|graduate|early career|associate|I)\b(?![-/])"),
    "mid": re.compile(r"(?i)\b(II|2|mid)\b"),
    "senior": re.compile(r"(?i)\b(senior|sr\.?|III|3)\b"),
    "staff": re.compile(r"(?i)\b(staff|principal|distinguished|fellow|IV|architect)\b"),
    "lead": re.compile(r"(?i)\b(lead|manager|director|head|vp|vice president|chief)\b"),
}
BLOCK_BY_LEVEL = {   # title levels a member at this level should not see
    "entry": {"senior", "staff", "lead"}, "junior": {"senior", "staff", "lead"}, "mid": {"staff", "lead"},
    "senior": {"intern", "junior"}, "staff": {"intern", "junior", "mid"},
}
US = re.compile(r"\b(US|USA|U\.S\.|United States|Americas|North America)\b|,\s*(A[LKZR]|C[AOT]|D[CE]|FL|GA|HI|I[ADLN]|K[SY]|LA|M[ADEINOST]|"
                r"N[CDEHJMVY]|O[HKR]|PA|RI|S[CD]|T[NX]|UT|V[AT]|W[AIVY])\b")
COUNTRY = {
    "US": US,
    "Canada": re.compile(r"(?i)\b(Canada|Ontario|Toronto|Vancouver|Montreal|Quebec|Alberta|Calgary|British Columbia)\b"),
    "UK": re.compile(r"(?i)\b(UK|United Kingdom|England|London|Manchester|Edinburgh|Scotland)\b"),
    "India": re.compile(r"(?i)\b(India|Bangalore|Bengaluru|Hyderabad|Pune|Chennai|Mumbai|Delhi|Gurgaon|Noida)\b"),
    "Germany": re.compile(r"(?i)\b(Germany|Berlin|Munich|Hamburg|Frankfurt)\b"),
    "Japan": re.compile(r"(?i)\b(Japan|Tokyo|Osaka)\b"),
    "Singapore": re.compile(r"(?i)\bSingapore\b"),
    "Australia": re.compile(r"(?i)\b(Australia|Sydney|Melbourne)\b"),
    "Europe": re.compile(r"(?i)\b(Europe|European|EMEA|EU|EEA|CET|CEST|EET|Nordics?|Scandinavia|DACH|Benelux|Baltics|"
                         r"Netherlands|Amsterdam|Rotterdam|Ireland|Dublin|Spain|Madrid|Barcelona|France|Paris|Lyon|Poland|Warsaw|Krakow|"
                         r"Portugal|Lisbon|Porto|Italy|Milan|Rome|Sweden|Stockholm|Gothenburg|Denmark|Copenhagen|Aarhus|Norway|Oslo|"
                         r"Finland|Helsinki|Switzerland|Zurich|Geneva|Austria|Vienna|Belgium|Brussels|Czech|Czechia|Prague|Romania|"
                         r"Bucharest|Ukraine|Kyiv|Greece|Athens|Estonia|Tallinn|Latvia|Riga|Lithuania|Vilnius|Hungary|Budapest|"
                         r"Croatia|Slovenia|Slovakia|Bulgaria|Serbia|Luxembourg|Iceland)\b"),
    "LATAM": re.compile(r"(?i)\b(LATAM|LatAm|Latin America|South America|Americas|Brazil|Brasil|Mexico|Argentina|Colombia|Chile|Peru|"
                        r"Uruguay|Costa Rica|S[ãa]o Paulo|Rio de Janeiro|Buenos Aires|Bogot[áa]|Medell[ií]n)\b"),
    "APAC": re.compile(r"(?i)\b(APAC|Asia|Philippines|Vietnam|Indonesia|Malaysia|Thailand|Korea|Seoul|China|Taiwan|Hong Kong|Myanmar)\b"),
    "MEA": re.compile(r"(?i)\b(Israel|UAE|Dubai|Turkey|Egypt|Nigeria|Kenya|South Africa|Pakistan|Saudi)\b"),
}
CLEARANCE = re.compile(r"(?i)\b(TS/SCI|top secret|secret clearance|security clearance|clearance required|active clearance|"
                       r"polygraph|public trust|DoD clearance)\b")
REMOTE = re.compile(r"(?i)remote|anywhere|distributed|work from home|wfh|worldwide|global")
NOT_REMOTE_TAG = re.compile(r"\[(Hybrid|On-site)\]")
# the job post itself says the work is in an office (checked for the top matches, whose posts are read anyway)
IN_OFFICE = re.compile(r"(?i)\b(location type:?\s*(hybrid|on-?site)|hybrid (role|position|schedule|work|model|environment|setup)|"
                       r"this (role|position|job) is (a )?(hybrid|on-?site|in[- ]office|in[- ]person)|we work in[- ]person|"
                       r"\d\s*(days?|x) (a|per) week (in|at) (the|our) (office|hq)|in[- ]office \d|"
                       r"(must|required to|expected to) (be )?(work )?(in|from) (the|our) office|on-?site (role|position|only)|"
                       r"in[- ]person (role|position|team|company|culture))\b")
FULL_REMOTE = re.compile(r"(?i)\b(fully remote|100% remote|remote[- ]first|remote[- ]friendly|work from anywhere|remote (or|/) hybrid|"
                         r"hybrid (or|/) remote|open to remote|can be (done|performed|worked) remotely)\b")
WORLDWIDE = re.compile(r"(?i)\b(anywhere|worldwide|global|globally|any location|any country|work from anywhere|fully distributed|hire (from )?(anywhere|globally|internationally|worldwide)|international(ly)? remote)\b")
# job-post sentences that limit a remote job to people already allowed to work in one country
RESTRICT = {
    "US": re.compile(r"(?i)(must (?:be )?(?:located|based|reside|residing|live) in the (?:US|U\.S\.|United States)|"
                     r"(?:US|U\.S\.)[- ]based (?:candidates|applicants) only|authorized to work in the (?:US|U\.S\.|United States)|"
                     r"(?:US|U\.S\.) (?:citizens|residents) only|(?:US|U\.S\.) work authorization|remote within the (?:US|United States)|"
                     r"(?:US|United States) only)"),
    "UK": re.compile(r"(?i)(right to work in the UK|must be (?:based|located) in the UK|UK[- ]based (?:candidates|applicants) only|UK only)"),
    "Europe": re.compile(r"(?i)(right to work in the (?:EU|EEA)|must be (?:based|located) in (?:the )?(?:EU|Europe)|EU work permit|EU only)"),
}
NO_SPONSOR = re.compile(r"(?i)(no (?:visa )?sponsorship|not (?:able to |able |)sponsor|unable to sponsor|cannot sponsor|"
                        r"does not (?:provide|offer) (?:visa )?sponsorship|without (?:the need for )?sponsorship)")
# extra "US only" wording that RESTRICT doesn't cover
US_ONLY = re.compile(r"(?i)(\b(US|U\.S\.|United States)[- ](based )?(candidates|applicants|residents|citizens|persons|individuals)\b(?! or)|\b(US|U\.S\.|United States) (residents|citizens) only\b|"
                     r"\b(reside|residing|live|living|located|based) (in|within) the (US|U\.S\.|United States)\b(?! or)|"
                     r"\bUS time ?zones?\b|\b(Pacific|Eastern|Central|Mountain) (Standard )?Time\b|\b(PST|EST|CST|MST|PT|ET)\b.{0,25}\b(hours|time ?zone)|"
                     r"\bremote,? (US|USA|United States) only\b)")
TZ_EVIDENCE = {
    "Europe": re.compile(r"(?i)\b(CET|CEST|EET|EEST|WET|GMT|BST|European time ?zones?|UTC ?[+]? ?[0-3](:00)?)\b"),
    "UK": re.compile(r"(?i)\b(GMT|BST|UK time ?zone|UTC ?[+]? ?[0-1](:00)?)\b"),
    "LATAM": re.compile(r"(?i)\b(BRT|ART|UTC ?-[3-6]|GMT ?-[3-6]|Latin American time ?zones?)\b"),
}


US_PLACE = re.compile(r"(?i)(\b(Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming|District of Columbia)\b|\b(San Francisco|SF Bay Area|Bay Area|Silicon Valley|Palo Alto|Mountain View|San Jose|Sunnyvale|Menlo Park|Seattle|Bellevue|Redmond|Portland|Los Angeles|San Diego|Austin|Dallas|Houston|Denver|Boulder|Chicago|Boston|Cambridge, MA|Atlanta|Miami|Nashville|Raleigh|Durham|Charlotte|Pittsburgh|Philadelphia|Phoenix|Salt Lake City|Minneapolis|Detroit|NYC|Brooklyn|Manhattan)\b|^(US|USA)\b|\b[A-Z]{2}\s*-\s*(?=[A-Z])|,\s*(A[LKZR]|C[AOT]|D[CE]|FL|GA|HI|I[ADLN]|K[SY]|LA|M[ADEINOST]|N[CDEHJMVY]|O[HKR]|PA|RI|S[CD]|T[NX]|UT|V[AT]|W[AIVY])\b)")


def us_centred(offices):
    """True when at least 60% of a company's posting offices are in the US (one Mexico office doesn't change that)."""
    if not offices:
        return False
    us = sum(1 for o in offices if US_PLACE.search(o) or US.search(o))
    return us / len(offices) >= 0.6

def open_to(text, allowed):
    """What in a job post says people in `allowed` can take it -> short label or ''."""
    for c in allowed:
        pat = COUNTRY.get(c)
        if pat and pat.search(text):
            return pat.search(text).group(0)
        tz = TZ_EVIDENCE.get(c)
        if tz and tz.search(text):
            return tz.search(text).group(0) + " time zone"
    m = WORLDWIDE.search(text)
    return m.group(0) if m else ""


def _prefetch_jds(con, jobs, workers=16):
    """Fetch the missing job posts in parallel (cached in the jd table, shared by every member)."""
    from concurrent.futures import ThreadPoolExecutor
    todo = [j for j in jobs if j.get("ats") != "feed" and storage.get_jd(con, j["id"]) is None]

    def get(j):
        try:
            res = JD.fetch(j["url"])
            return j["id"], (res.get("text", "") if res else "")
        except Exception:
            return j["id"], ""
    if todo:
        with ThreadPoolExecutor(workers) as ex:
            for jid, text in ex.map(get, todo):
                storage.save_jd(con, jid, text or "")
    return len(todo)


ONSITE_ONLY = re.compile(r"(?i)\b(on-?site only|in-office|in office 5)\b")


ALIASES = {"usa": "US", "united states": "US", "america": "US", "u.s.": "US", "u.s.a.": "US", "united kingdom": "UK",
           "great britain": "UK", "britain": "UK", "england": "UK", "scotland": "UK", "wales": "UK", "eu": "Europe", "eea": "Europe",
           "emea": "Europe", "europe": "Europe", "nordics": "Europe", "scandinavia": "Europe", "dach": "Europe", "benelux": "Europe"}


def norm_countries(items):
    """Whatever a member types ('Denmark', 'usa', 'United Kingdom') -> the matcher's country groups ('Europe', 'US', 'UK').
    A country inside a group maps to the group, so 'Denmark' means 'Europe' (and Germany jobs count too)."""
    out = []
    for raw in items or []:
        t = str(raw).strip()
        if not t:
            continue
        key = next((k for k in COUNTRY if k.lower() == t.lower()), None) or ALIASES.get(t.lower())
        if not key:
            key = next((k for k, pat in COUNTRY.items() if pat.fullmatch(t) or pat.search(t)), None)
        if key and key not in out:
            out.append(key)
    if "Germany" in out and "Europe" not in out:
        out.append("Europe")
    return out


def default_prefs(profile):
    """Sensible preferences from a parsed profile; members adjust them in the UI.
    Region (US / EU / UK / other), countries and time zone come from the CV location: a Berlin member gets
    countries ["Germany", "Europe"] so pan-European remote jobs ("Remote - EMEA") match too."""
    from .. import region as RG
    loc = profile.get("contact", {}).get("location", "")
    reg = RG.detect(loc)
    city = loc.split(",")[0].strip() if loc else ""
    return {"target_titles": profile.get("target_titles", []), "lanes": profile.get("lanes", []), "level": profile.get("level", "mid"),
            "region": reg["region"], "timezone": reg["timezone"],
            "countries": reg["countries"], "remote_ok": True, "onsite_ok": False, "home_cities": [city] if city else [],
            "target_companies": [], "avoid_companies": [], "include_words": [], "exclude_words": [], "days": 2, "min_score": 40,
            "clearance_ok": False,
            "work_auth": "", "salary_min": "", "notes": ""}


def _lane_pattern(lanes):
    pats = [(i, l, re.compile(rf"(?i)\b({SK.TITLE_WORDS[l]})\b")) for i, l in enumerate(lanes) if l in SK.TITLE_WORDS]
    return pats


def title_level(title):
    return [k for k, p in LEVEL_WORDS.items() if p.search(title)]


def place_ok(loc, title, prefs):
    """-> (ok, kind) kind in remote / home / unknown."""
    text = f"{loc} {title}"
    allowed = set(norm_countries(prefs.get("countries")) or ["US"])
    if "Europe" in allowed:                     # Germany has its own pattern but is part of Europe
        allowed.add("Germany")
    mentions = {c for c, p in COUNTRY.items() if p.search(text)}
    bad = mentions - set(allowed)
    good = mentions & set(allowed)
    remote = bool(REMOTE.search(text)) and not NOT_REMOTE_TAG.search(loc or "")
    homes = [h for h in prefs.get("home_cities", []) if h]
    if prefs.get("onsite_ok") and homes and re.search("|".join(re.escape(h) for h in homes), text, re.I):
        return True, "home"
    if bad and not good:
        return False, "abroad"
    if remote and prefs.get("remote_ok", True):
        return True, "remote"
    return False, "place"


def score_job(job, member, lane_pats, today):
    prefs, prof = member["prefs"], member["profile"]
    title = job["title"]
    if NON_ENG.search(title) and not any(re.search(rf"(?i)\b{re.escape(w)}\b", title) for w in prefs.get("include_words", [])):
        return None, "type"
    if CLEARANCE.search(f"{title} {job.get('location') or ''}") and not prefs.get("clearance_ok"):
        return None, "clearance"
    for w in prefs.get("exclude_words", []):
        if w and re.search(rf"(?i)\b{re.escape(w)}\b", title):
            return None, "excluded word"
    if any(c and c.lower() in job["company"].lower() for c in prefs.get("avoid_companies", [])):
        return None, "avoided company"
    lane_hit = next(((i, l) for i, l, p in lane_pats if p.search(title)), None)
    tt = [t for t in prefs.get("target_titles", []) if t and t.lower() in title.lower()]
    if not lane_hit and not tt:
        return None, "title"
    lv = title_level(title)
    blocked = BLOCK_BY_LEVEL.get(prefs.get("level", "mid"), set())
    if "intern" in lv and prefs.get("level") not in ("entry",):
        return None, "level"
    if set(lv) & blocked:
        return None, "level"
    ok, kind = place_ok(job.get("location") or "", title, prefs)
    if not ok:
        return None, kind
    posted = job.get("posted")
    age = None
    if posted:
        try:
            age = (today - dt.date.fromisoformat(posted[:10])).days
        except ValueError:
            age = None
    if age is not None and age > prefs.get("days", 2):
        return None, "old"
    reasons = []
    s = 0
    if lane_hit:
        s += (30, 24, 18, 14)[min(lane_hit[0], 3)]
        reasons.append(f"lane: {SK.LANES.get(lane_hit[1], (lane_hit[1],))[0]}")
    if tt:
        s += 15
        reasons.append(f"target title: {tt[0]}")
    title_sk = SK.find(title)
    have = set(prof.get("skills", {}).get("proven", [])) | set(prof.get("skills", {}).get("listed_only", []))
    plus = [k for k in title_sk if k in have]
    minus = [k for k in title_sk if k not in have and SK.category(k) in ("language", "frontend", "backend", "mobile", "ai", "ml", "data")]
    s += min(12, 6 * len(plus)) - 6 * len(minus)
    if plus:
        reasons.append("title names your skills: " + ", ".join(plus))
    if minus:
        reasons.append("title names skills you don't list: " + ", ".join(minus))
    level = prefs.get("level", "mid")
    if ("junior" in lv and level in ("entry", "junior")) or ("mid" in lv and level in ("junior", "mid")) or \
       ("senior" in lv and level in ("senior", "staff")):
        s += 8
        reasons.append("level fits")
    elif "senior" in lv and level == "mid":
        yrs = member["profile"].get("years_experience", 0) or 0
        s -= 15 if yrs < 4 else 5
        reasons.append("senior title: a stretch")
    s += {0: 10, 1: 8, 2: 6}.get(age, 2 if age is not None and age <= 7 else 4 if age is None else 0)
    if kind == "remote":
        nc = norm_countries(prefs.get("countries")) or ["US"]
        allowed = nc + (["Germany"] if "Europe" in nc else [])
        where = f"{job.get('location') or ''} {title}"
        if any(COUNTRY[c].search(where) for c in allowed if c in COUNTRY):
            s += 5
        elif WORLDWIDE.search(where):
            s += 5
            reasons.append("remote worldwide")
        else:
            s -= 3
            reasons.append("remote, country not stated")
    elif kind == "home":
        s += 3
        reasons.append("in your home area")
    if any(c and c.lower() in job["company"].lower() for c in prefs.get("target_companies", [])):
        s += 10
        reasons.append("target company")
    return max(0, min(100, s + 20)), reasons


def match_member(con, member, day=None, days=None, log=print, enrich=15, geo_check=400):
    today = config.today()
    day = day or con.execute("SELECT max(last_seen) d FROM jobs WHERE source NOT IN ('manual','quickbid')").fetchone()["d"]
    if not day:
        return {"name": member["name"], "matches": 0, "new": 0, "best": 0}
    prefs = dict(default_prefs(member["profile"]), **{k: v for k, v in member["prefs"].items() if v not in (None, "")})
    if days:
        prefs["days"] = days
    member = dict(member, prefs=prefs)
    lanes = prefs.get("lanes") or member["profile"].get("lanes") or ["backend"]
    lane_pats = _lane_pattern(lanes)
    reasons = Counter()
    hits, rejected = [], set()          # rejected: seen in this scan and failed a real test (not just the date window)
    for job in con.execute("SELECT * FROM jobs WHERE last_seen=?", (day,)):
        job = dict(job)
        sc, why = score_job(job, member, lane_pats, today)
        if sc is None:
            reasons[why] += 1
            if why != "old":
                rejected.add(job["id"])
            continue
        hits.append((sc, why, job))
    hits.sort(key=lambda x: -x[0])
    # dedupe the same role listed on several boards/feeds
    seen, uniq = set(), []
    for sc, why, job in hits:
        k = (re.sub(r"\W", "", job["company"].lower()), re.sub(r"\W", "", job["title"].lower()))
        if k in seen:
            reasons["duplicate"] += 1
            continue
        seen.add(k)
        uniq.append([sc, why, job])
    # job-description coverage for the top matches (cached in the jd table), plus a meaning match from local
    # embeddings when Ollama runs: similarity between the member's strongest bullets and the job post
    have = set(member["profile"].get("skills", {}).get("all", []))
    prof_text = " ".join(b["text"] for r in member["profile"].get("roles", [])[:3] for b in r["bullets"][:4])[:2000]
    prof_vec = local_ai.embed([prof_text], "document") if prof_text else None
    allowed = set(norm_countries(prefs.get("countries")) or ["US"])
    us_ok = "US" in allowed

    def unknown_place(job):          # "Remote" with no country, region or "worldwide"
        t = f"{job.get('location') or ''} {job['title']}"
        return not any(p.search(t) for p in COUNTRY.values()) and not WORLDWIDE.search(t)
    # members who can't work in the US: every "Remote"-only job must show it is open to them, so read those posts too
    checks = uniq[:enrich] + ([it for it in uniq[enrich:] if unknown_place(it[2])][:geo_check] if not us_ok else [])
    fetched = _prefetch_jds(con, [it[2] for it in checks])
    offices = {}
    if not us_ok:
        from . import company
        offices = company.lookup(con, day)
    for idx, item in enumerate(checks):
        sc, why, job = item
        text = storage.get_jd(con, job["id"]) or ""
        loc = job.get("location") or ""
        if text and place_ok(loc, job["title"], prefs)[1] == "remote" and IN_OFFICE.search(text) and not FULL_REMOTE.search(text):
            item[0] = 0                       # listed as remote, but the post says hybrid / in office: drop it
            why.append("job post says hybrid / in office, not remote")
            continue
        ok_here = open_to(text, allowed) if text else ""
        blocked = [c for c, pat in RESTRICT.items() if c not in allowed and pat.search(text)]
        if not us_ok and "US" not in blocked and US_ONLY.search(text):
            blocked.append("US")
        if blocked:
            if ok_here:                       # "US or Europe": keep, but say it
                item[0] = max(0, item[0] - 10)
                why.append(f"post mentions work rights in {', '.join(blocked)} but also {ok_here}")
            else:
                item[0] = 0
                why.append(f"post limits it to people already allowed to work in: {', '.join(blocked)}")
                continue
            if NO_SPONSOR.search(text):
                why.append("says no visa sponsorship")
        if not us_ok and unknown_place(job):
            if ok_here:
                item[0] = min(100, item[0] + 5)
                why.append(f"post says open to {ok_here}")
            else:
                offs = (offices.get(job["company"]) or {}).get("offices", [])
                us_offices = us_centred(offs)
                if us_offices:
                    item[0] = 0
                    why.append("post doesn't say it's open outside the US and every office is in the US")
                    continue
                item[0] = max(0, item[0] - 15)
                why.append("post doesn't say which countries can apply" + (f" (offices: {', '.join(offs[:2])})" if offs else ""))
        if idx < enrich and text:
            need = SK.find(text, with_counts=True)
            if need:
                cov = sum(1 for k in need if k in have) / len(need)
                item[0] = max(0, min(100, int(item[0] + (cov - 0.5) * 30)))     # on top of the checks above, not the raw score
                why.append(f"description coverage {cov:.0%} of {len(need)} skills")
            if prof_vec:
                qv = local_ai.embed([text[:2000]], "query")
                if qv:
                    sim = local_ai.cosine(prof_vec[0], qv[0])
                    item[0] = max(0, min(100, int(item[0] + (sim - 0.55) * 40)))
                    why.append(f"meaning match {sim:.2f}")
    if fetched:
        log(f"  {member['name']}: read {fetched} job posts to check location rules")
    stamp = str(today)
    new = best = 0
    min_score = int(prefs.get("min_score", 40))
    for sc, why, job in uniq:
        if sc < min_score:
            reasons["low score"] += 1
            rejected.add(job["id"])
            continue
        tier = "best" if sc >= 60 else "consider"
        cur = con.execute("SELECT 1 FROM matches WHERE member_id=? AND job_id=?", (member["id"], job["id"])).fetchone()
        if cur:
            con.execute("UPDATE matches SET score=?, tier=?, reasons=?, last_matched=? WHERE member_id=? AND job_id=?",
                        (sc, tier, json.dumps(why), stamp, member["id"], job["id"]))
        else:
            con.execute("INSERT INTO matches (member_id, job_id, score, tier, reasons, first_matched, last_matched) VALUES (?,?,?,?,?,?,?)",
                        (member["id"], job["id"], sc, tier, json.dumps(why), stamp, stamp))
            new += 1
        best += tier == "best"
    # jobs that matched before but now fail a real test (a fixed filter, a changed preference, a hybrid label) leave
    # the list, unless the member already acted on them (saved, skipped, applying). Jobs that only aged out stay.
    con.execute("CREATE TEMP TABLE IF NOT EXISTS rejected_now (id INTEGER PRIMARY KEY)")
    con.execute("DELETE FROM rejected_now")
    con.executemany("INSERT OR IGNORE INTO rejected_now VALUES (?)", [(i,) for i in rejected])
    gone = con.execute("DELETE FROM matches WHERE member_id=? AND status='new' AND job_id IN (SELECT id FROM rejected_now)",
                       (member["id"],)).rowcount
    if gone:
        log(f"  {member['name']}: {gone} earlier matches no longer fit and were removed")
    total = sum(1 for sc, _, _ in uniq if sc >= min_score)
    write_member_report(con, member, stamp, reasons, total)
    log(f"  {member['name']}: {total} matches ({new} new, {best} best)")
    return {"name": member["name"], "matches": total, "new": new, "best": best, "filtered": dict(reasons)}


def match_all(days=None, log=print):
    out = []
    with storage.connect() as con:
        for m in storage.members(con):
            out.append(match_member(con, m, days=days, log=log))
    return out


REASON_TEXT = {"clearance": "Needs a security clearance", "title": "Title outside your lanes", "level": "Wrong level for your experience", "type": "Not an engineering job",
               "abroad": "Outside your countries", "place": "Not remote and not in your home area", "old": "Older than your date window",
               "duplicate": "Same job on another board", "low score": "Below your minimum score", "excluded word": "Has a word you excluded",
               "avoided company": "Company you avoid"}


def write_member_report(con, member, day, reasons, total):
    d = config.member_dir(member["slug"]) / "reports"
    rows = con.execute("SELECT m.*, j.company, j.title, j.location, j.url, j.posted, j.source FROM matches m JOIN jobs j ON j.id=m.job_id "
                       "WHERE m.member_id=? AND m.first_matched=? ORDER BY m.score DESC", (member["id"], day)).fetchall()
    L = [f"# Job matches for {member['name']}: {day}", "", f"{total} jobs match your profile today; {len(rows)} are new.", "",
         "| Score | Tier | Posted | Company | Title | Location | Why | Link |", "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        why = "; ".join(json.loads(r["reasons"] or "[]"))[:140]
        L.append(f"| {r['score']} | {r['tier']} | {r['posted'] or '?'} | {r['company']} | {r['title']} | {(r['location'] or '')[:40]} | {why} | {r['url']} |")
    L += ["", "## Why other jobs were filtered out", "", "| Reason | Jobs |", "|---|---|"]
    L += [f"| {REASON_TEXT.get(k, k)} | {v:,} |" for k, v in reasons.most_common()]
    (d / f"{day}.md").write_text("\n".join(L) + "\n", encoding="utf-8")

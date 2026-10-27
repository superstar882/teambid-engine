"""Job-post analysis, fit verdict and tailored-resume building with hard fact guards.

Tailoring only selects, orders and groups what the member's resume already says:
- bullets are kept word for word (no rewriting means no invented claims), ranked by how many of the job's skills
  they prove, with a bonus for numbers;
- skills are re-grouped with the job's must-haves first, but only skills the member already lists or proves;
- the summary is assembled from the member's own facts (lane, proven skills, best bullet).
The validator still checks the result: every number must come from the resume, no skill outside the profile,
no AI buzzwords.
"""
import re
from collections import Counter

from . import local_ai
from . import skills as SK
from . import writing

REQ_HEAD = re.compile(r"(?im)^\W*(requirements|required|qualifications|minimum qualifications|basic qualifications|what you('|’)ll (bring|need)|"
                      r"what we('|’)re looking for|you have|must[- ]haves?|who you are|about you|skills|your experience)\W*$")
PREF_HEAD = re.compile(r"(?im)^\W*(preferred|nice[- ]to[- ]haves?|bonus( points)?|preferred qualifications|pluses|it('|’)s a plus|"
                       r"good to have|desired|extra credit)\W*.*$")
OTHER_HEAD = re.compile(r"(?im)^\W*(benefits|perks|about us|about the company|compensation|salary|equal opportunity|what we offer|"
                        r"responsibilities|what you('|’)ll do|the role|about the role)\W*$")
YEARS = re.compile(r"(?i)(\d{1,2})\s*(?:[-–]\s*\d{1,2})?\s*\+?\s*(?:years|yrs)")
_CUR = r"(?:\$|€|£|USD|EUR|GBP|CHF)"
SALARY = re.compile(rf"{_CUR}\s?\d{{2,3}}(?:[,.]\d{{3}})?\s?[kK]?\s?(?:-|–|to)\s?{_CUR}?\s?\d{{2,3}}(?:[,.]\d{{3}})?\s?[kK]?(?:\s?{_CUR})?|"
                    rf"\d{{2,3}}(?:[,.]\d{{3}})?\s?[kK]?\s?(?:-|–|to)\s?\d{{2,3}}(?:[,.]\d{{3}})?\s?[kK]?\s?{_CUR}")


def analyze_jd(text, title="", company=""):
    text = text or ""
    lines = text.splitlines()
    zone, req_txt, pref_txt = "body", [], []
    for l in lines:
        if PREF_HEAD.match(l):
            zone = "pref"
            continue
        if REQ_HEAD.match(l):
            zone = "req"
            continue
        if OTHER_HEAD.match(l):
            zone = "body"
            continue
        if zone == "req":
            req_txt.append(l)
        elif zone == "pref":
            pref_txt.append(l)
        if re.search(r"(?i)\b(preferred|nice to have|bonus|a plus)\b", l) and zone != "req":
            pref_txt.append(l)
    allc = SK.find(text, with_counts=True)
    req = SK.find("\n".join(req_txt)) if req_txt else [s for s, n in allc.most_common() if n >= 1][:15]
    pref = [s for s in SK.find("\n".join(pref_txt)) if s not in req]
    years = [int(m) for m in YEARS.findall(text) if 0 < int(m) < 20]
    sal = SALARY.search(text)
    focus = "\n".join(req_txt + pref_txt) or text
    return {"title": title, "company": company, "required": req, "preferred": pref, "all": dict(allc),
            "focus": f"{title}\n{focus}"[:2500],
            "years": min(years) if years else None, "remote": bool(re.search(r"(?i)\bremote\b", text)),
            "salary": sal.group(0) if sal else "", "chars": len(text)}


def fit(profile, jd):
    proven = set(profile.get("skills", {}).get("proven", []))
    listed = set(profile.get("skills", {}).get("listed_only", []))
    have = proven | listed
    req = jd["required"] or list(jd["all"])
    got = [s for s in req if s in have]
    proved = [s for s in req if s in proven]
    missing = [s for s in req if s not in have]
    cov = len(got) / len(req) if req else 0.0
    yrs = profile.get("years_experience", 0) or 0
    notes = []
    years_gap = jd.get("years") and yrs + 0.5 < jd["years"]
    if years_gap:
        notes.append(f"Asks for {jd['years']}+ years; you have about {yrs} (internships excluded). Apply only if the rest is strong.")
    if missing:
        notes.append("Missing from your resume: " + ", ".join(missing[:8]) + ". Don't claim these; mention adjacent experience if asked.")
    t = (jd.get("title") or "").lower()
    lvl = profile.get("level", "mid")
    if lvl in ("entry", "junior", "mid") and re.search(r"\b(staff|principal|director|head of)\b", t):
        notes.append("Title is staff/principal/director level: usually a stretch at your level.")
    if cov >= 0.7 and not years_gap:
        verdict = "GO"
    elif cov >= 0.45:
        verdict = "CAUTION"
    else:
        verdict = "SKIP"
    if years_gap and jd["years"] - yrs >= 3 and verdict == "GO":
        verdict = "CAUTION"
    return {"verdict": verdict, "coverage": round(cov * 100), "have": got, "proven": proved, "missing": missing,
            "nice_have": [s for s in jd["preferred"] if s in have], "nice_missing": [s for s in jd["preferred"] if s not in have],
            "notes": notes}


def _bullet_score(text, weights, sem=None):
    sk = SK.find(text)
    s = sum(weights.get(k, 0) for k in sk)
    if sem and text in sem:          # meaning match from local embeddings: about -3..+3 on top of keywords
        s += max(-3.0, min(3.0, 12 * (sem[text] - sem["_mean"])))
    if re.search(r"\d", text):
        s += 1.5
    if len(text) > 230:
        s -= 1
    return s


def _signature(profile, skill):
    """How central a skill is to this person: named in their own CV headline (top lines) counts most, then how many
    bullets use it, recent jobs weighted higher."""
    head = "\n".join(profile.get("raw_text", "").splitlines()[:6])
    score = 10.0 if SK.find(head, trusted=True) and skill in SK.find(head, trusted=True) else 0.0
    for i, r in enumerate(profile.get("roles", [])):
        w = max(0.3, 1.0 - 0.15 * i)
        score += w * sum(1 for b in r.get("bullets", []) if skill in SK.find(b["text"], trusted=True))
        score += 0.5 * w * (skill in r.get("stack", []))
    return score


# skill lines on the resume: label -> skill categories (skills.py)
SKILL_LINES = (("Languages", ("language",)), ("Backend & APIs", ("backend",)), ("Data Engineering", ("data", "analytics")),
               ("AI & LLMs", ("ai", "ml")), ("Databases & Cloud", ("database", "cloud", "devops")),
               ("Frontend & Mobile", ("frontend", "mobile")))


def build_resume(profile, jd, max_bullets=(4, 3, 3, 2, 2, 2, 1)):
    """-> resume spec dict (render.py turns it into DOCX/PDF)."""
    weights = Counter()
    for s in jd["required"]:
        weights[s] += 3
    for s in jd["preferred"]:
        weights[s] += 1.5
    for s, n in jd["all"].items():
        weights[s] += min(n, 3) * 0.5
    have = list(dict.fromkeys(profile["skills"].get("proven", []) + profile["skills"].get("listed_only", [])))
    texts = [b["text"] for r in profile.get("roles", []) for b in r["bullets"]] + \
            [b["text"] for p in profile.get("projects", []) for b in p["bullets"]]
    sims = local_ai.similarities(jd.get("focus", ""), texts) if texts and jd.get("focus") else None
    sem = dict(zip(texts, sims)) if sims else None
    if sem:
        sem["_mean"] = sum(sims) / len(sims)
    roles = []
    for i, r in enumerate(profile.get("roles", [])):
        k = max_bullets[min(i, len(max_bullets) - 1)]
        if r.get("kind") == "intern":
            k = min(k, 2)
        ranked = sorted(r["bullets"], key=lambda b: -_bullet_score(b["text"], weights, sem))
        keep = ranked[:k] if ranked else []
        stack = [s for s in sorted(r.get("stack", []), key=lambda x: -weights.get(x, 0))][:8]
        roles.append({"company": r["company"], "title": r["title"], "location": r.get("location", ""), "start": r["start"],
                      "end": r["end"], "bullets": [b["text"] for b in keep], "stack": stack,
                      "scores": [round(_bullet_score(b["text"], weights, sem), 3) for b in keep]})   # page fitting drops the lowest
    projects = []
    for p in profile.get("projects", []):
        sc = sum(weights.get(s, 0) for s in p.get("stack", []))
        if sc > 0:
            ranked = sorted(p["bullets"], key=lambda b: -_bullet_score(b["text"], weights, sem))
            projects.append((sc, {"name": p["name"], "link": p.get("link", ""), "bullets": [b["text"] for b in ranked[:2]],
                                  "stack": p.get("stack", [])[:6]}))
    projects = [p for _, p in sorted(projects, key=lambda x: -x[0])[:2]]
    # skills: every skill the member lists, on a few standard lines (what a recruiter expects to scan). The lines most
    # relevant to the job come first; inside a line the job's skills lead, then the ones the bullets prove.
    groups = []
    for label, cats in SKILL_LINES:
        items = [x for x in have if SK.category(x) in cats]
        if items:
            items.sort(key=lambda x: (-weights.get(x, 0), -_signature(profile, x)))
            groups.append((label, items, sum(weights.get(x, 0) for x in items)))
    known = {c for _, cats in SKILL_LINES for c in cats}
    other = [x for x in have if SK.category(x) not in known]
    if other:
        groups.append(("Tools & practices", sorted(other, key=lambda x: -weights.get(x, 0)), sum(weights.get(x, 0) for x in other)))
    core = list(dict.fromkeys(x for x in jd["required"] + jd["preferred"] if x in have))   # the summary names these first
    order = {g[0]: i for i, g in enumerate(groups)}
    groups = [(lab, items) for lab, items, w in sorted(groups, key=lambda g: (g[0] != "Languages", -g[2], order[g[0]]))]
    # headline + summary from the member's own facts
    lane = (profile.get("lanes") or ["backend"])[0]
    headline = jd.get("title") if _title_fits(profile, jd.get("title", "")) else (profile.get("headline") or SK.LANES[lane][1][0])
    tech = ("language", "frontend", "backend", "data", "ai", "ml", "cloud", "database", "mobile", "devops")
    proven = sorted([x for x in profile["skills"].get("proven", []) if SK.category(x) in tech], key=lambda x: -_signature(profile, x))
    top = list(dict.fromkeys([x for x in core if x in proven] + proven))[:3]
    yrs = profile.get("years_experience", 0)
    lead = {"ai": "AI engineer", "ml": "Machine learning engineer", "data": "Data engineer", "backend": "Backend engineer",
            "frontend": "Frontend engineer", "fullstack": "Full-stack engineer", "mobile": "Mobile engineer",
            "devops": "DevOps engineer", "security": "Security engineer", "qa": "QA engineer"}.get(lane, "Software engineer")
    first = f"{lead} working with {', '.join(top[:-1]) + ' and ' + top[-1] if len(top) > 1 else (top[0] if top else 'modern tools')}"
    if yrs >= 2:
        first += f", {int(yrs)}+ years in production"
    best = max((b for r in roles for b in r["bullets"]), key=lambda b: _bullet_score(b, weights, sem), default="")
    summary = first + "." + (f" {best.rstrip('.')}." if best else "")
    spec = {"name": profile.get("name", ""), "contact": profile.get("contact", {}), "headline": headline, "summary": summary,
            "skills": groups, "roles": roles, "projects": projects, "education": profile.get("education", []),
            "certifications": profile.get("certifications", [])[:4], "awards": profile.get("awards", [])[:3],
            "ranking": "keywords + meaning (local AI)" if sem else "keywords"}
    return spec


def _title_fits(profile, title):
    if not title:
        return False
    lv = profile.get("level", "mid")
    if lv in ("entry", "junior", "mid") and re.search(r"(?i)\b(senior|sr\.?|staff|principal|lead|manager|director)\b", title):
        return False
    for l in profile.get("lanes", []):
        if l in SK.TITLE_WORDS and re.search(rf"(?i)\b({SK.TITLE_WORDS[l]})\b", title):
            return True
    return False


def validate(spec, profile):
    """Hard checks. -> list of problems (empty = safe to send)."""
    problems = []
    allowed_numbers = set(profile.get("metrics", []))
    text_numbers = re.findall(r"\$?\d[\d,.]*\s?[%kKmMbB+x]?", spec["summary"])
    raw = re.sub(r"\s+", " ", profile.get("raw_text", ""))
    for n in text_numbers:
        core = n.strip().rstrip("+.,")
        if core and core not in raw and not any(core in a for a in allowed_numbers):
            problems.append(f"Summary number '{n}' is not in your resume")
    have = set(profile["skills"].get("all", [])) | set(profile["skills"].get("proven", [])) | set(profile["skills"].get("listed_only", []))
    for _, items in spec["skills"]:
        for s in items:
            if s not in have:
                problems.append(f"Skill '{s}' is not in your profile")
    for w in writing.BANNED:
        if re.search(rf"\b{re.escape(w)}\b", spec["summary"].lower()):
            problems.append(f"Summary uses AI-style word '{w}'")
    for r in spec["roles"]:
        for b in r["bullets"]:
            orig = spec.get("rewritten", {}).get(b, b)        # Claude rewordings map back to the resume's own bullet
            if not any(orig == x["text"] for pr in profile["roles"] for x in pr["bullets"]):
                problems.append(f"Bullet not from your resume: {b[:60]}")
    if re.search(r"(?i)\b(fine-?tun|trained (a|the|our) (model|llm))", spec["summary"]):
        problems.append("Summary claims model training/fine-tuning: only keep if your bullets prove it")
    return problems


def keyword_report(spec, jd):
    text = " ".join([spec["headline"], spec["summary"]] + [s for _, items in spec["skills"] for s in items] +
                    [b for r in spec["roles"] for b in r["bullets"]] + [b for p in spec["projects"] for b in p["bullets"]])
    found = set(SK.find(text, trusted=True))
    req = jd["required"] or list(jd["all"])
    covered = [s for s in req if s in found]
    return {"covered": covered, "missing": [s for s in req if s not in found], "pct": round(100 * len(covered) / len(req)) if req else 0}

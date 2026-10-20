"""Resume audit: an ATS and recruiter-eye review with a score and a prioritized fix list.

Checks are based on recruiter eye-tracking and ATS-parsing research (Ladders 2018: ~7 s first pass; Jobscan / Workday /
Greenhouse parsing guides: single column, standard headers, no tables or text in images; XYZ bullet formula; numbers
in bullets). Every finding says what to change and why.
"""
import datetime as dt
import re

from . import skills as SK
from . import writing


def audit(profile, region="US"):
    findings = []      # (severity 1-3, area, message)
    score = 100

    def add(sev, area, msg, cost):
        nonlocal score
        findings.append({"severity": sev, "area": area, "message": msg})
        score -= cost

    c = profile.get("contact", {})
    meta = profile.get("source", {})
    for k, label in (("email", "an email"), ("phone", "a phone number"), ("linkedin", "a LinkedIn URL")):
        if not c.get(k):
            add(2, "Contact", f"No {label} found. Recruiters and ATS forms expect it in the header.", 4)
    if not c.get("location"):
        add(2, "Contact", "No location found. Many recruiters filter by location; add 'City, ST' (US) or 'City, Country'.", 3)
    if meta.get("columns"):
        add(3, "Format", "Two-column layout detected. Many ATS parsers read columns out of order. Use one column.", 10)
    if meta.get("tables"):
        add(2, "Format", "Tables found. ATS parsers often drop table text. Use plain lines.", 6)
    if meta.get("images"):
        add(1, "Format", "Images or icons found. Text inside images is invisible to ATS.", 2)
    pages = meta.get("pages", 1)
    yrs = profile.get("years_experience", 0)
    if region in ("EU", "UK"):
        if pages > 2:
            add(2, "Length", f"{pages} pages. In Europe 1-2 pages is the norm; cut to two.", 6)
        elif pages == 2 and yrs < 2:
            add(1, "Length", "2 pages with under 2 years of experience. One page usually reads better.", 2)
    elif pages > 2 or (pages == 2 and yrs < 7):
        add(2, "Length", f"{pages} pages. In the US, under ~7-10 years of experience, one page reads best.", 6)

    roles = profile.get("roles", [])
    if not roles:
        add(3, "Experience", "No jobs with dates were found. Use 'Company | Title | Mon YYYY - Mon YYYY' lines.", 20)
    bullets = [b for r in roles for b in r["bullets"]]
    if roles and not bullets:
        add(3, "Experience", "Jobs have no bullet points. Each job needs 2-5 bullets with results.", 15)
    with_num = sum(1 for b in bullets if b.get("metrics"))
    if bullets:
        share = with_num / len(bullets)
        if share < 0.4:
            add(2, "Impact", f"Only {with_num}/{len(bullets)} bullets have a number. Aim for at least half: scale, time saved, %, $, users.", 8)
        weak = [b["text"][:60] for b in bullets if writing.WEAK_STARTS.match(b["text"])]
        if weak:
            add(2, "Wording", f"{len(weak)} bullets start weak ('responsible for', 'helped'...). Lead with a strong verb: {weak[0]}...", 2 + len(weak))
        long_b = [b for b in bullets if len(b["text"]) > 230]
        if long_b:
            add(1, "Wording", f"{len(long_b)} bullets run past 2 lines. Cut to 1-2 lines each.", min(6, len(long_b)))
        pron = [b for b in bullets if re.match(r"(?i)^(i|my|we)\b", b["text"])]
        if pron:
            add(1, "Wording", "Bullets start with 'I'/'my'/'we'. Drop pronouns in resumes.", 2)
        firsts = [b["text"].split()[0].lower() for b in bullets if b["text"].split()]
        rep = sorted({w for w in firsts if firsts.count(w) >= 3})
        if rep:
            add(1, "Wording", f"Same opening verb 3+ times: {', '.join(rep)}. Vary verbs.", 2)
        buzz = sorted({w for b in bullets for w in writing.BANNED if re.search(rf"\b{w}\b", b['text'].lower())})
        if buzz:
            add(2, "Wording", f"AI/buzzwords in bullets: {', '.join(buzz[:6])}. Replace with plain verbs.", 2 + len(buzz))
    for r in roles:
        if len(r["bullets"]) > 6:
            add(1, "Experience", f"{r['company'] or r['title']}: {len(r['bullets'])} bullets. Keep the best 3-5.", 2)
        if not r.get("start"):
            add(2, "Experience", f"{r['company'] or r['title']}: no dates found.", 3)
    # gaps between jobs
    spans = sorted([(r["start"], r["end"]) for r in roles if r.get("start")], reverse=True)
    for (s1, _), (_, e2) in zip(spans, spans[1:]):
        if e2 and e2 != "Present" and s1:
            y1, m1 = map(int, s1.split("-"))
            y2, m2 = map(int, e2.split("-"))
            gap = (y1 - y2) * 12 + (m1 - m2)
            if gap > 6:
                add(1, "Timeline", f"{gap}-month gap before {s1}. Be ready to explain it (study, project, family) in one line.", 1)
    sk = profile.get("skills", {})
    if len(sk.get("all", [])) < 6:
        add(2, "Skills", "Few recognizable skills found. Add a 'Skills' section with the tools you actually use.", 6)
    if len(sk.get("listed_only", [])) > 12:
        add(1, "Skills", f"{len(sk['listed_only'])} listed skills never appear in a bullet. Back the important ones with proof in a bullet.", 3)
    if not profile.get("summary") and yrs >= 2:
        add(1, "Summary", "No summary. A 2-line summary with your main lane and best result helps the 7-second scan.", 2)
    if not profile.get("education"):
        add(1, "Education", "No education section found.", 2)
    score = max(0, min(100, score))
    findings.sort(key=lambda f: -f["severity"])
    grade = "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 55 else "E"
    return {"score": score, "grade": grade, "findings": findings,
            "facts": {"roles": len(roles), "bullets": len(bullets), "bullets_with_numbers": with_num,
                      "skills_found": len(sk.get("all", [])), "years_experience": yrs, "level": profile.get("level"),
                      "lanes": profile.get("lanes", [])},
            "checked": dt.date.today().isoformat()}


def to_markdown(name, res):
    sev = {3: "High", 2: "Medium", 1: "Low"}
    f = res["facts"]
    lines = [f"# Resume audit: {name}", "", f"**Score {res['score']}/100 (grade {res['grade']})**, checked {res['checked']}.", "",
             f"{f['roles']} jobs, {f['bullets']} bullets ({f['bullets_with_numbers']} with a number), {f['skills_found']} skills recognized, "
             f"{f['years_experience']} years of professional experience (internships excluded), level **{f['level']}**, "
             f"lanes: {', '.join(f['lanes'])}.", "", "## Fix list (most important first)", "",
             "| Priority | Area | What to change |", "|---|---|---|"]
    lines += [f"| {sev[x['severity']]} | {x['area']} | {x['message']} |" for x in res["findings"]] or ["| - | - | Nothing major. |"]
    return "\n".join(lines) + "\n"

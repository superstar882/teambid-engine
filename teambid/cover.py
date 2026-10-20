"""Cover letters and application answers from a member's own facts.

Without an API key: a fact-only draft. It quotes the member's real bullets (as first-person sentences) that best
prove the job's must-have skills, names the role and company, and ends with one plain line. 150-250 words, which
tailored-letter studies found works best (ResumeGo 2019: tailored letters got ~53% more callbacks than none).
With ANTHROPIC_API_KEY: llm.write_letter() polishes the draft under the same rules, and the result is rejected if it
adds a number that isn't in the resume.
Every draft goes through writing.check(); fix all warnings before sending.
"""
import re

from . import local_ai
from . import skills as SK
from . import writing


NOT_VERBS = {"i", "we", "the", "a", "an", "our", "my", "this", "it", "they", "he", "she", "team", "as", "at", "in", "on", "for"}


def _first_person(bullet):
    """'Processed 150K files. Co-built an app.' -> 'I processed 150K files. I co-built an app.'"""
    out = []
    for sent in re.split(r"(?<=\.)\s+(?=[A-Z])", bullet.strip()):
        s = sent.strip().rstrip(".")
        if not s:
            continue
        first = s.split()[0].lower()
        out.append((s if first in NOT_VERBS or s[:2].isupper() else "I " + s[0].lower() + s[1:]) + ".")
    return " ".join(out)


def _a(word):
    return "an" if re.match(r"(?i)[aeiou]", word or "") else "a"


def _best_bullets(profile, wanted, n=2, focus=""):
    """The member's strongest proof for this job: skill overlap, a number, and (with local embeddings) meaning."""
    allb = [(r, b) for r in profile.get("roles", []) for b in r["bullets"]]
    sims = local_ai.similarities(focus, [b["text"] for _, b in allb]) if focus and allb else None
    mean = sum(sims) / len(sims) if sims else 0
    scored = []
    for i, (r, b) in enumerate(allb):
        sk = set(b.get("skills") or SK.find(b["text"]))
        hit = len(sk & set(wanted))
        sem = 15 * (sims[i] - mean) if sims else 0
        if hit or b.get("metrics") or sem > 0:
            scored.append((hit * 3 + (1 if b.get("metrics") else 0) + sem, r, b))
    scored.sort(key=lambda x: -x[0])
    out, used = [], set()
    for sc, r, b in scored:
        if r["company"] in used:
            continue
        used.add(r["company"])
        out.append((r, b))
        if len(out) == n:
            break
    return out


def draft_letter(profile, jd, fit_res):
    company = jd.get("company") or "your team"
    title = jd.get("title") or "this role"
    have = fit_res.get("have", [])[:3]
    picks = _best_bullets(profile, jd["required"] or list(jd["all"]), focus=jd.get("focus", ""))
    p1 = f"I'm applying for the {title} role at {company}."
    if have:
        p1 += f" Your post asks for {', '.join(have[:-1]) + ' and ' + have[-1] if len(have) > 1 else have[0]}, which is the work I do."
    paras = [f"Hi {company} team,", p1]
    for r, b in picks:
        lead = f"At {r['company']}" if r.get("company") else "In a recent role"
        paras.append(f"{lead} I work{'ed' if r.get('end') != 'Present' else ''} as {_a(r['title'] or 'engineer')} {r['title'] or 'engineer'}. {_first_person(b['text'])}")
    proj = next((p for p in profile.get("projects", []) if set(p.get("stack", [])) & set(jd["required"])), None)
    if proj and proj["bullets"]:
        paras.append(f"On my own time I built {proj['name']}. {_first_person(proj['bullets'][0]['text'])}")
    topic = picks[0][0]["company"] if picks else "my recent work"
    paras.append(f"Happy to walk you through the work at {topic} anytime." if picks else "Happy to talk anytime.")
    paras.append(profile.get("name", ""))
    text = "\n\n".join(p for p in paras if p)
    return text, writing.check(text)


def answers(profile, prefs, jd=None):
    """Short drafts for the questions most forms ask. [CONFIRM] marks what only the member can fill in."""
    name = profile.get("name", "")
    roles = profile.get("roles", [])
    cur = roles[0] if roles else {}
    best = max((b for r in roles for b in r["bullets"]), key=lambda b: len(b.get("metrics", [])), default=None)
    lanes = profile.get("lanes", ["backend"])
    lane_word = {"ai": "AI", "ml": "machine learning", "data": "data", "backend": "backend", "frontend": "frontend",
                 "fullstack": "full-stack", "mobile": "mobile", "devops": "DevOps", "security": "security", "qa": "QA"}.get(lanes[0], "software")
    tops = profile.get("skills", {}).get("proven", [])[:4]
    company = (jd or {}).get("company") or "[Company]"
    out = {
        "Tell me about yourself": (
            f"I'm a {lane_word} engineer" + (f", currently {cur.get('title')} at {cur.get('company')}" if cur else "") + ". "
            + (f"I work mostly with {', '.join(tops[:3])}. " if tops else "")
            + (f"{_first_person(best['text'])}" if best else "")),
        "Why do you want to work here?": f"[CONFIRM: one real reason only {company} has: their product, a problem in the post, or a team you know]. "
                                         f"It lines up with my {lane_word} work" + (f" at {cur.get('company')}" if cur else "") + ".",
        "Are you authorized to work in this country?": prefs.get("work_auth") or "[CONFIRM: work authorization, e.g. 'Yes, U.S. citizen' / 'Yes, permanent resident' / 'Yes, will need sponsorship later']",
        "Desired salary": (f"{prefs['salary_min']} base, flexible depending on the full package" if prefs.get("salary_min")
                           else "[CONFIRM: a number near the top of the posted range]"),
        "When can you start?": "[CONFIRM: start date or notice period]",
        "Most impressive achievement": _first_person(best["text"]) if best else "[CONFIRM: your best result with a number]",
    }
    for sk in (jd or {}).get("required", [])[:4]:
        months = sum(r["months"] for r in roles if sk in r.get("stack", []) and r.get("kind") == "job")
        intern = sum(r["months"] for r in roles if sk in r.get("stack", []) and r.get("kind") == "intern")
        if months or intern:
            yrs = f"about {months / 12:.1f} years in full-time roles" if months else ""
            extra = f"{' plus ' if yrs else ''}{intern} months in internships" if intern else ""
            where = ", ".join(r["company"] for r in roles if sk in r.get("stack", []))[:80]
            out[f"How many years of experience with {sk}?"] = f"{yrs}{extra} ({where})."
        else:
            out[f"How many years of experience with {sk}?"] = f"[CONFIRM: not on your resume. Answer honestly; don't round up.]"
    return {q: {"answer": a, "check": writing.check(a) if "[CONFIRM" not in a else None} for q, a in out.items()}

"""Build a member's personal knowledge vault (plain markdown, works in Obsidian or any editor).

  00 Profile.md            identity, contact, level, lanes, preferences
  01 Experience.md         every role and bullet with its stack and metrics: the source of truth for all writing
  02 Skills.md             proven (in bullets) / listed only / what the market asks that you lack
  03 Resume Audit.md       score and prioritized fixes
  04 Search Plan.md        target titles, LinkedIn/Google boolean searches, filters, weekly rhythm
  05 Target Companies.md   ranked list, which ones the daily scan covers
  06 Story Bank.md         STAR outlines seeded from the strongest bullets (fill in the gaps)
  07 Answer Bank.md        drafts for common application questions ([CONFIRM] = only you can fill)
  08 Writing Rules.md      team writing rules + banned words
  09 Market Insights.md    skills that show up in your matched job posts vs your skills
  prompts/                 copy-paste prompt packs for Claude Code / claude.ai (tailor, cover letter, answers, interview prep)
  knowledge/ -> shared team research (data/knowledge)
"""
import json
from collections import Counter

from . import analyze, config, cover, targets, writing
from . import skills as SK


def build(con, member):
    d = config.member_dir(member["slug"]) / "vault"
    (d / "prompts").mkdir(exist_ok=True)
    p, prefs, name = member["profile"], member["prefs"], member["name"]
    files = {}
    c = p.get("contact", {})
    files["00 Profile.md"] = "\n".join([
        f"# {name}", "", f"- Headline: {p.get('headline') or '-'}", f"- Location: {c.get('location') or '-'}",
        f"- Email: {c.get('email') or '-'} | Phone: {c.get('phone') or '-'}", f"- LinkedIn: {c.get('linkedin') or '-'} | GitHub: {c.get('github') or '-'} | Site: {c.get('website') or '-'}",
        f"- Professional experience: **{p.get('years_experience', 0)} years** (internships excluded, {p.get('intern_months', 0)} intern/research months on top)",
        f"- Level: **{prefs.get('level') or p.get('level')}** | Lanes: **{', '.join(prefs.get('lanes') or p.get('lanes', []))}**",
        f"- Target titles: {', '.join(prefs.get('target_titles') or p.get('target_titles', []))}",
        f"- Countries: {', '.join(prefs.get('countries', []))} | Remote OK: {prefs.get('remote_ok')} | On-site/hybrid near: {', '.join(prefs.get('home_cities', [])) or '-'}",
        f"- Work authorization: {prefs.get('work_auth') or '[CONFIRM]'} | Salary floor: {prefs.get('salary_min') or '[CONFIRM]'}",
        f"- Region: {prefs.get('region', 'US')} (paper {'A4' if prefs.get('region') in ('EU', 'UK') else 'Letter'}) | Time zone: {prefs.get('timezone', '-')}",
        "", "## Education", ""] + [f"- {e.get('school')}: {e.get('degree')} {e.get('field')} {e.get('end')} {('GPA ' + e['gpa']) if e.get('gpa') else ''}" for e in p.get("education", [])]
        + ["", "## Certifications, awards, languages", ""] + [f"- {x}" for x in p.get("certifications", []) + p.get("awards", [])]
        + ([f"- Languages: {', '.join(p['languages'])}"] if p.get("languages") else []) + [""])
    exp = [f"# Experience: {name}", "", "Every claim in a resume, letter or answer must trace back to this file. Edit it here or in the app.", ""]
    for r in p.get("roles", []):
        exp += [f"## {r['title']}, {r['company']} ({r['start']} - {r['end']}){' [internship/research]' if r.get('kind') == 'intern' else ''}",
                f"Stack: {', '.join(r.get('stack', [])) or '-'}", ""]
        exp += [f"- {b['text']}" + (f"  _(metrics: {', '.join(b['metrics'])})_" if b.get("metrics") else "") for b in r["bullets"]] + [""]
    if p.get("projects"):
        exp += ["## Projects", ""]
        for pj in p["projects"]:
            exp += [f"### {pj['name']}", f"Stack: {', '.join(pj.get('stack', [])) or '-'}"] + [f"- {b['text']}" for b in pj["bullets"]] + [""]
    exp += ["## Allowed numbers", "", "Only these numbers may appear in tailored writing: " + (", ".join(p.get("metrics", [])) or "none found"), ""]
    files["01 Experience.md"] = "\n".join(exp)
    sk = p.get("skills", {})
    market = market_skills(con, member)
    gaps = [s for s, _ in market.most_common(25) if s not in set(sk.get("all", []))]
    files["02 Skills.md"] = "\n".join([f"# Skills: {name}", "",
        "**Proven** (appear in a bullet, safe to lead with):", ", ".join(sk.get("proven", [])) or "-", "",
        "**Listed only** (on the resume but not shown in a bullet; add proof or expect questions):", ", ".join(sk.get("listed_only", [])) or "-", "",
        "**Other listed items** (not in the taxonomy):", ", ".join(sk.get("other_listed", [])) or "-", "",
        "**Asked for in your matched jobs but missing from your resume** (learn or show adjacent work; never claim):",
        ", ".join(gaps[:15]) or "(run a scan first)", ""])
    res = analyze.audit(p, prefs.get("region", "US"))
    files["03 Resume Audit.md"] = analyze.to_markdown(name, res)
    titles = prefs.get("target_titles") or p.get("target_titles", [])
    q = " OR ".join(f'"{t}"' for t in titles[:5])
    lvl = prefs.get("level") or p.get("level")
    neg = "-senior -staff -principal -lead -manager" if lvl in ("entry", "junior", "mid") else "-intern -junior"
    files["04 Search Plan.md"] = "\n".join([f"# Search plan: {name}", "",
        f"Target titles: {', '.join(titles)}", "", "## Searches", "",
        f"- LinkedIn Jobs: ({q}) {neg.replace('-', 'NOT ')}  · filters: Past 24 hours, Remote, Entry/Associate/Mid-Senior as fits",
        f"- Google: ({q}) (site:job-boards.greenhouse.io OR site:jobs.lever.co OR site:jobs.ashbyhq.com) {neg} remote",
        "- The daily scan already reads ~27K company boards; use these for sites it can't read (custom career pages, LinkedIn).", "",
        "## Weekly rhythm (research: referrals and tailored applications beat volume)", "",
        "- Every day: check new matches (10 min), tailor 2-4 applications for GO/CAUTION jobs.",
        "- Every week: 5-10 referral asks to people at target companies, 2-3 follow-ups, update the tracker.",
        "- Skip SKIP verdicts fast. Five tailored applications beat thirty quick ones.", ""])
    rows = targets.for_member(con, member)
    files["05 Target Companies.md"] = targets.to_markdown(name, rows)
    story = [f"# Story bank: {name}", "", "Behavioral interviews score Situation, Task, Action, Result. Each outline starts from a real bullet; "
             "fill the [ ] parts in your own words and keep each story under 2 minutes.", ""]
    picks = sorted([(len(b.get("metrics", [])), r, b) for r in p.get("roles", []) for b in r["bullets"]], key=lambda x: -x[0])[:6]
    for i, (_, r, b) in enumerate(picks, 1):
        story += [f"## {i}. {r['company']}: {b['text'][:70]}", "", f"- Situation: [what was going on at {r['company']}, why it mattered]",
                  "- Task: [what you owned]", f"- Action: {b['text']} [the 2-3 decisions you made and why]",
                  f"- Result: {', '.join(b.get('metrics', [])) or '[measurable result]'} [and what you learned]",
                  "- Good for: [conflict / failure / ownership / ambiguity / impact]", ""]
    files["06 Story Bank.md"] = "\n".join(story)
    ans = cover.answers(p, prefs)
    files["07 Answer Bank.md"] = "\n".join([f"# Answer bank: {name}", "", "Drafts from your own facts. Replace every [CONFIRM] and run the checker before using.", ""] +
                                           [f"## {qq}\n\n{a['answer']}\n" for qq, a in ans.items()])
    files["08 Writing Rules.md"] = writing.RULES_MD
    files["09 Market Insights.md"] = "\n".join([f"# Market insights: {name}", "",
        "Skills named in the job descriptions of your top matches (fetched during scans).", "",
        "| Skill | Job posts | You have it |", "|---|---|---|"] +
        [f"| {s} | {n} | {'yes' if s in set(sk.get('all', [])) else '**no**'} |" for s, n in market.most_common(30)] + [""])
    facts = (d / "01 Experience.md")
    prompts = {
        "tailor-resume.md": f"""You are tailoring {name}'s resume for one job. Use ONLY facts from "01 Experience.md" (attached).
Rules: keep every bullet's facts; you may shorten or reorder words but never add numbers, tools or results that are not there.
Put the job's must-have skills first in Skills, only if they appear in the experience file. One page. Plain US English.
Output: headline, 2-line summary, skills lines, then for each role the 2-4 most relevant bullets.
JOB POST:
[paste]""",
        "cover-letter.md": f"""Write a 150-250 word cover letter for {name}. Facts: only from "01 Experience.md". Style rules: "08 Writing Rules.md".
Structure: 1) the role + one specific thing about this company from the post; 2) one proof story with a real number;
3) a second relevant proof; 4) one plain closing line. No em dashes, no semicolons, no buzzwords, no "excited/passionate".
JOB POST:
[paste]""",
        "answer-question.md": f"""Answer this application question for {name} in the shortest true way. Facts only from "01 Experience.md".
Answer in the first sentence, then one concrete detail. Under the box limit. Mixed sentence lengths, nothing over 25 words.
QUESTION (and limit):
[paste]""",
        "interview-prep.md": f"""Prepare {name} for an interview. Use "01 Experience.md" and "06 Story Bank.md".
Give: 6 likely questions for this job with a 4-sentence answer outline each (from real stories only), 3 smart questions to ask,
and the 3 gaps between the job and the resume with an honest way to address each.
JOB POST:
[paste]""",
    }
    for fname, body in prompts.items():
        (d / "prompts" / fname).write_text(body + "\n", encoding="utf-8")
    for fname, body in files.items():
        (d / fname).write_text(body, encoding="utf-8")
    (d / "knowledge.md").write_text(f"Shared team research lives in: {config.KNOWLEDGE}\n\n" +
                                    (config.KNOWLEDGE / "README.md").read_text(encoding="utf-8") if (config.KNOWLEDGE / "README.md").exists() else "", encoding="utf-8")
    (config.member_dir(member["slug"]) / "profile.json").write_text(json.dumps({"profile": p, "prefs": prefs}, indent=1, default=str), encoding="utf-8")
    return {"folder": str(d), "files": sorted(files) + [f"prompts/{x}" for x in prompts], "audit": res}


def market_skills(con, member):
    c = Counter()
    for r in con.execute("SELECT jd.text FROM matches m JOIN jd ON jd.job_id=m.job_id WHERE m.member_id=? AND jd.text != ''", (member["id"],)):
        for s in set(SK.find(r["text"])):
            c[s] += 1
    return c

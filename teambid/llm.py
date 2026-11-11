"""Optional AI helpers. TeamBid works fully without them.

Providers: the Claude API (ANTHROPIC_API_KEY set) or a free local model through Ollama (local_ai.py).
Every generated text goes through guard(): it is rejected, and the fact-only draft is kept, if it adds a number,
a skill/tool, or a buzzword that isn't backed by the member's resume, or if it drifts in length or drops the company.
"""
import json
import re

import requests

from . import config, local_ai, writing
from . import skills as SK

API = "https://api.anthropic.com/v1/messages"
# the choices on the results page ("free" = no AI, the fact-only template)
MODELS = {"haiku": ("claude-haiku-5-5", "Claude Haiku 5.5"), "sonnet": ("claude-sonnet-5-5", "Claude Sonnet 5.5")}


def available():
    return bool(config.ANTHROPIC_KEY)


def provider(prefer="auto"):
    """'claude', 'local' or None."""
    if prefer in ("auto", "claude") and available():
        return "claude"
    if prefer in ("auto", "local") and local_ai.chat_available():
        return "local"
    return None


def _call(system, user, max_tokens=16000, model=None, timeout=300):
    """max_tokens covers the model's thinking too (it thinks before it answers), so it is set well above the reply."""
    r = requests.post(API, timeout=timeout, headers={"x-api-key": config.ANTHROPIC_KEY, "anthropic-version": "2023-06-01",
                                                     "content-type": "application/json"},
                      json={"model": model or config.MODEL, "max_tokens": max_tokens, "system": system,
                            "messages": [{"role": "user", "content": user}]})
    r.raise_for_status()
    data = r.json()
    if data.get("stop_reason") == "max_tokens":     # half a letter or half the JSON: never used
        raise RuntimeError(f"the reply was cut off at the {max_tokens:,}-token limit")
    return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


def _json(out):
    """The JSON object in a reply (Claude may wrap it in ```json fences or a sentence)."""
    found = re.search(r"\{.*\}", out, re.S)
    if not found:
        raise ValueError("no JSON in Claude's reply")
    return json.loads(found.group(0))


def _numbers(text):
    return {n.rstrip(".,+") for n in re.findall(r"\$?\d[\d,.]*[%kKmMbB+]?", text) if re.search(r"\d", n)}


COMMON = set("""about above across after again against also although always another anyone anything around because become
before being below between bring build built could daily doing during each either enough every first focus focused focuses
great happy having however implemented include including instead into itself known later least leave level little made
make making many maybe might model models months more most much must never next often other others overall people perhaps
place please points post posted quite rather really recent recently right role roles same should since since small some
someone something still such sure taking team teams thank thanks their them then there these they thing things think this
those though three through today together toward under until using very want wants welcome well were what when where which
while whole with within without work worked working works would write years your yours chance discuss excited glad hello
looking strong strongly closely directly mostly mainly especially exactly anytime walk through applying apply""".split())


def claims_to_check(new, draft, profile, jd_text=""):
    """Words a generated text attaches to a job that the member's resume doesn't support there.

    Attribution-aware: a paragraph that names one of the member's companies may only use words from that company's
    own bullets, its title and the draft's paragraph about it (so "fault tolerance" moved from one job to another is
    caught). Other paragraphs are checked against the whole resume, the draft and the job post. A flagged word isn't
    proof of a false claim; it marks a sentence to verify before sending."""
    def words(t):
        return {w for w in re.findall(r"[a-z][a-z'-]{4,}", t.lower()) if w not in COMMON}

    def known(w, src):
        return w in src or w.rstrip("s") in src or (w.endswith("ing") and w[:-3] in src) or (w.endswith("ed") and w[:-2] in src)

    roles = [r for r in profile.get("roles", []) if r.get("company")]
    draft_paras = draft.split("\n\n")
    everything = " ".join([profile.get("raw_text", ""), draft, jd_text]).lower()
    flagged = []
    for para in new.split("\n\n"):
        named = [r for r in roles if r["company"].lower() in para.lower()]
        if named:
            src = " ".join([" ".join(b["text"] for b in r["bullets"]) + " " + r["title"] + " " + r["company"] for r in named] +
                           [d for d in draft_paras if any(r["company"].lower() in d.lower() for r in named)] +
                           [jd_text[:0]]).lower()
            pool = src
        else:
            pool = everything
        for w in sorted(words(para)):
            if not known(w, pool) and w not in flagged:
                flagged.append(w)
    return flagged


OUTCOME = re.compile(r"^(improv|increas|reduc|boost|enhanc|faster|quality|reliab|perform|efficien|accura|scal|optimi|robust|secur|stabil|"
                     r"grow|revenue|saving|savings|cost|speed|latency|uptime|fault|resilien)")


def guard(new, draft, profile, company="", jd_text=""):
    """Problems with a generated letter (empty list = safe to use)."""
    problems = []
    drift = [w for w in claims_to_check(new, draft, profile, jd_text) if OUTCOME.match(w)]
    if drift:
        problems.append("claims results the resume doesn't show for that job: " + ", ".join(drift[:6]))
    style = writing.check(new)["warnings"]
    if style:
        problems.append("writing check: " + "; ".join(style[:3]))
    facts = profile.get("raw_text", "") + "\n" + draft
    extra_nums = {n for n in _numbers(new) - _numbers(draft) if n not in facts}
    if extra_nums:
        problems.append(f"added numbers not in the resume: {', '.join(sorted(extra_nums)[:5])}")
    have = set(profile.get("skills", {}).get("all", [])) | set(SK.find(draft, trusted=True))
    extra_sk = [s for s in SK.find(new) if s not in have]
    if extra_sk:
        problems.append(f"added skills/tools not in the resume: {', '.join(extra_sk[:5])}")
    buzz = sorted(w for w in writing.BANNED if re.search(rf"\b{re.escape(w)}\b", new.lower()))
    if buzz:
        problems.append(f"used AI-style words: {', '.join(buzz[:5])}")
    n = len(re.findall(r"[A-Za-z']+", new))
    if not 90 <= n <= 320:
        problems.append(f"length {n} words (keep 120-250)")
    if company and company.lower() not in new.lower():
        problems.append("dropped the company name")
    return problems


READ_RULES = (
    "You read one resume and return its structure as JSON. Copy every string EXACTLY as it appears in the resume text: "
    "same words, punctuation, capitals and numbers. Join words that a line break split, but never reword, shorten, merge, "
    "split, add or drop anything.\n"
    "headline: the title line under the name (\"\" if there is none). summary: the whole profile or summary paragraph "
    "(\"\" if none). jobs: every work-experience entry (full-time, part-time, contract, consulting), in the order they "
    "appear, each with title, company, location (\"\" if none), start and end as YYYY-MM (end \"Present\" for a current "
    "job, YYYY-01 when only the year is given) and bullets: every bullet under that job, in order. skills: each labeled "
    "line of the skills section as {label, items} with the items split at the commas ([] when the skills aren't labeled "
    "lines).\n"
    "Return ONLY JSON: {\"headline\": \"...\", \"summary\": \"...\", \"jobs\": [{\"title\": \"...\", \"company\": \"...\", "
    "\"location\": \"...\", \"start\": \"YYYY-MM\", \"end\": \"YYYY-MM or Present\", \"bullets\": [\"...\"]}], "
    "\"skills\": [{\"label\": \"...\", \"items\": [\"...\"]}]}")


def read_resume(text, model=None):
    """Claude reads the whole resume once (at upload) and returns its structure. -> (dict or None, note).
    keep_style.confirm() then keeps only the strings that really are in the text."""
    if not available():
        return None, "no Claude API key"
    try:
        out = _call(READ_RULES, f"RESUME TEXT:\n{text[:60000]}", 32000, model or MODELS["sonnet"][0], timeout=600)
        return _json(out), "read by Claude"
    except Exception as e:
        return None, f"Claude reading skipped: {e}"


LETTER_RULES = ("You edit cover letters. Rules: 150-250 words, 3-4 short paragraphs, plain US English, contractions OK. "
                "No em dashes, semicolons or exclamation marks. Never use: " + ", ".join(sorted(writing.BANNED)[:45]) + ". "
                "Keep every fact exactly as given: do not add numbers, tools, titles, companies or claims, and do not drop the "
                "company name. Keep the greeting and the sign-off name. Return only the letter.")


def polish_letter(draft, profile, jd_text, company="", prefer="auto"):
    """-> (text, note). Keeps the draft unless the polished version passes guard()."""
    who = provider(prefer)
    if not who:
        return draft, "no AI available (set ANTHROPIC_API_KEY or run Ollama)"
    facts = "\n".join(f"- {r['title']} at {r['company']}: " + " / ".join(b['text'] for b in r['bullets'])
                      for r in profile.get("roles", []))
    user = f"FACTS (the only allowed facts):\n{facts}\n\nJOB POST (for tone and priorities only):\n{jd_text[:5000]}\n\nDRAFT TO EDIT:\n{draft}"
    label = "Claude API" if who == "claude" else f"local {local_ai.CHAT_MODEL}"
    ask = lambda u: (_call(LETTER_RULES, u) if who == "claude" else local_ai.chat(LETTER_RULES, u, max_tokens=600)).strip().strip("`").strip()
    try:
        out = ask(user)
        problems = guard(out, draft, profile, company, jd_text)
        if problems:      # one retry that names the exact problems (small models usually fix a named mistake)
            out = ask(user + "\n\nYOUR LAST VERSION WAS REJECTED FOR: " + "; ".join(problems) +
                      ". Fix exactly these problems and change nothing else.\n\nLAST VERSION:\n" + out)
            problems = guard(out, draft, profile, company, jd_text)
    except Exception as e:
        return draft, f"{who} error: {e}"
    if problems:
        return draft, f"{label} version rejected twice ({'; '.join(problems)}); kept the fact-only draft"
    novel = claims_to_check(out, draft, profile, jd_text)
    note = f"polished by {label}, passed the fact and writing checks"
    if novel:
        note += f". Verify the sentences with these words (not in your resume): {', '.join(novel[:12])}"
    return out, note


# ---------------------------------------------------------------- Claude writes (used when an API key is set)
def _facts(profile):
    lines = [f"Name: {profile.get('name', '')}"]
    for r in profile.get("roles", []):
        lines.append(f"- {r['title']} at {r['company']} ({r.get('start', '')} to {r.get('end', '')}): " +
                     " / ".join(b["text"] for b in r["bullets"]))
    for p in profile.get("projects", []):
        lines.append(f"- Project {p['name']}: " + " / ".join(b["text"] for b in p["bullets"]))
    for e in profile.get("education", []):
        lines.append(f"- Education: {e.get('degree', '')} {e.get('school', '')} {e.get('end', '')}".strip())
    return "\n".join(lines)


WRITE_RULES = (
    "You write cover letters for real job applications. Use ONLY the facts given about the candidate: never add a number, "
    "tool, title, company, result or claim that is not in the facts, and never move a result from one job to another. "
    "Shape: 'Hi {company} team,' then 3-4 short paragraphs, 150-250 words, then the candidate's full name on its own line. "
    "P1: the role and one specific thing about this company's product or problem, in the job post's own words (why them). "
    "P2: one proof story from the facts that fits the post best: the hard part, a decision, how it turned out. "
    "P3: one more relevant result with its number, tied to what the post cares about. "
    "Close with one plain line (e.g. 'Happy to walk you through it.'). No 'thank you for considering', no 'excited to apply'. "
    "Plain US English like a real engineer typing: contractions, mixed sentence lengths, nothing over 25 words. "
    "No em dashes, semicolons, exclamation marks, bold or bullet lists. Never use these words: "
    + ", ".join(sorted(writing.BANNED)) + ". Return only the letter.")


def write_letter(profile, jd_text, company, title, draft, model=None):
    """Claude writes the letter from the facts. -> (text, note). Falls back to the fact-only draft if the guard rejects it twice."""
    if not available():
        return draft, "no Claude API key"
    user = (f"ROLE: {title} at {company}\n\nCANDIDATE FACTS (the only allowed facts):\n{_facts(profile)}\n\n"
            f"JOB POST:\n{jd_text[:12000]}")
    try:
        out = _call(WRITE_RULES.replace("{company}", company), user, model=model).strip().strip("`").strip()
        problems = guard(out, draft, profile, company, jd_text)
        if problems:
            out = _call(WRITE_RULES.replace("{company}", company), user + "\n\nYOUR LAST VERSION WAS REJECTED FOR: " +
                        "; ".join(problems) + ". Fix exactly these problems.\n\nLAST VERSION:\n" + out, model=model).strip().strip("`").strip()
            problems = guard(out, draft, profile, company, jd_text)
    except Exception as e:
        return draft, f"Claude error: {e}"
    if problems:
        return draft, f"Claude letter rejected twice ({'; '.join(problems)}); kept the fact-only draft"
    novel = claims_to_check(out, draft, profile, jd_text)
    label = next((n for m, n in MODELS.values() if m == model), "Claude")
    note = f"letter written by {label}, passed the fact and writing checks"
    if novel:
        note += f". Verify the sentences with these words (not in your resume): {', '.join(novel[:12])}"
    return out, note


RESUME_RULES = (
    "You are a senior engineering recruiter editing one candidate's resume for one job post. You get the summary and "
    "the experience bullets already picked from their real resume, each with its role. Rewrite them so a hiring manager "
    "for THIS job sees the match in a 6-second skim.\n"
    "How a strong bullet reads: past-tense action verb first, then what was built or changed, then the result. Concrete "
    "nouns, plain words, the way a sharp engineer talks. Example: 'Worked on dashboard performance improvements using "
    "React' becomes 'Cut dashboard load time from 6 s to 1.8 s by moving reports to React Query'. Only when those facts "
    "are already in the original.\n"
    "Use the job post's own term when the bullet truly shows it ('ETL' vs 'data pipelines', 'LLM' vs 'AI model'). Lead "
    "with the part of the bullet that matters most to this job. One or two job terms per bullet at most. Never stuff "
    "keywords, never list tools the bullet doesn't use.\n"
    "Hard rules: keep every number exactly as written. Keep the same facts, scope and seniority (no 'led' if they "
    "'helped'). Never add a tool, skill, company, metric or result that isn't in the original. Keep each bullet about "
    "the same length, under 120 characters when the original is. No em dashes, no semicolons, no first person. If a "
    "bullet is already strong for this job, return it unchanged.\n"
    "Summary: 1-2 sentences, facts from the summary and bullets only, aimed at this job's main need.\n"
    "Never use these words: " + ", ".join(sorted(writing.BANNED)) + ".\n"
    "Return ONLY JSON: {\"summary\": \"...\", \"bullets\": {\"<id>\": \"...\"}}.")


def _bullet_ok(new, old, have):
    if not new or new == old:
        return False
    if _numbers(new) != _numbers(old):
        return False
    if [s for s in SK.find(new) if s not in have and s not in SK.find(old, trusted=True)]:
        return False
    if any(re.search(rf"\b{re.escape(w)}\b", new.lower()) for w in writing.BANNED) or re.search(r"[—;]", new):
        return False
    gained = [w for w in re.findall(r"[a-z]{5,}", new.lower()) if OUTCOME.match(w) and w not in old.lower()]
    return not gained and 0.7 <= len(new) / max(1, len(old)) <= 1.3


def _summary_ok(new, old, profile, lo=0.6, hi=1.4):
    """A reworded summary keeps to the resume's numbers and tools, avoids the banned words and stays about as long."""
    have = set(profile.get("skills", {}).get("all", []))
    raw = profile.get("raw_text", "") + " " + old
    return bool(new and new != old and all(n in raw for n in _numbers(new))
                and not [s for s in SK.find(new) if s not in have]
                and not any(re.search(rf"\b{re.escape(w)}\b", new.lower()) for w in writing.BANNED)
                and lo <= len(new) / max(1, len(old)) <= hi)


def rewrite_resume(spec, profile, jd_text, model=None):
    """Claude rewords the chosen bullets + summary toward the job post. Each change must pass _bullet_ok; the rest stay
    verbatim. Accepted rewordings are recorded in spec['rewritten'] (new -> original) for validate(). -> (spec, note)."""
    if not available():
        return spec, "no Claude API key"
    ids = {f"r{i}b{j}": b for i, r in enumerate(spec["roles"]) for j, b in enumerate(r["bullets"])}
    roles = "\n\n".join(f"{r['title']} at {r['company']}:\n" + "\n".join(f"r{i}b{j}: {b}" for j, b in enumerate(r["bullets"]))
                        for i, r in enumerate(spec["roles"]) if r["bullets"])
    user = f"JOB POST:\n{jd_text[:12000]}\n\nSUMMARY:\n{spec.get('summary', '')}\n\nBULLETS BY ROLE:\n{roles}"
    try:
        data = _json(_call(RESUME_RULES, user, model=model))
    except Exception as e:
        return spec, f"Claude resume step skipped: {e}"
    have = set(profile.get("skills", {}).get("all", []))
    spec = json.loads(json.dumps(spec))
    spec.setdefault("rewritten", {})
    took = 0
    for i, r in enumerate(spec["roles"]):
        for j, b in enumerate(r["bullets"]):
            new = str(data.get("bullets", {}).get(f"r{i}b{j}", "")).strip()
            if _bullet_ok(new, b, have):
                r["bullets"][j] = new
                spec["rewritten"][new] = b
                took += 1
    s_new, s_old = str(data.get("summary", "")).strip(), spec.get("summary", "")
    if _summary_ok(s_new, s_old, profile):
        spec["summary"] = s_new
        took += 1
    return spec, f"Claude reworded {took} of {len(ids) + 1} lines toward the job post (each kept its numbers and facts)"


TAILOR_RULES = (
    "You are a senior engineering recruiter tailoring one candidate's resume to one job post. You edit the text inside "
    "their own resume file, so the layout stays theirs. You get their headline, summary, every bullet of every job "
    "(each with an ID) and their skills lines. Make a hiring manager for THIS job see the match in a 6-second skim.\n"
    "Bullets: past-tense action verb first, then what was built or changed, then the result. Use the job post's own "
    "term when the bullet truly shows it. Lead with the part that matters most to this job. One or two job terms per "
    "bullet at most, never stuff keywords. Return EVERY bullet not marked (fixed) under its ID, reworded toward this "
    "job; keep a bullet's words only when it already reads as a perfect match for this job. Each bullet stays about "
    "its original length, best the same or a little shorter: never more than 10% longer or 25% shorter (it must fit "
    "the same lines in their file). Words wrapped in ** are bold in the file: you may bold tool or skill names the "
    "same way, only in bullets that already use **. Bullets marked (fixed) can move but keep their text.\n"
    "order: for every job, list ALL of its bullet IDs exactly once, the most relevant to this job first.\n"
    "headline: the job post's title when the candidate has held that kind of role at that level, else their own "
    "headline, in the same capital-letter style as the original. Never a higher level (lead, staff, principal, "
    "manager, architect, head) than a title they have held, never a lower level than their own headline, and keep "
    "every technology their headline names (else keep their headline as it is).\n"
    "summary: the same facts, aimed at this job's main need, within 10% of its length (best the same or a little "
    "shorter: it must fit the same lines).\n"
    "A word broken at a line end in the file shows as \"de- ploying\": always write it whole (\"deploying\", or "
    "\"database-driven\" for a compound).\n"
    "skills: every line with exactly the same items, the ones this job asks for first. skill_lines: every line ID "
    "once, the lines this job cares about first.\n"
    "Hard rules: keep every number exactly as written. Keep the same facts, scope and seniority (no 'led' if they "
    "'helped'). Never add a tool, skill, company, metric or result that isn't in the original. No em dashes, no "
    "semicolons, no first person.\n"
    "Never use these words: " + ", ".join(sorted(writing.BANNED)) + ".\n"
    "Return ONLY JSON: {\"headline\": \"...\", \"summary\": \"...\", \"bullets\": {\"<id>\": \"...\"}, "
    "\"order\": {\"<job id>\": [\"<bullet id>\", ...]}, \"skills\": {\"<line id>\": [\"...\"]}, "
    "\"skill_lines\": [\"<line id>\", ...]}")


def tailor_in_place(doc, jd_text, model=None):
    """Claude rewrites and reorders the pieces of the member's own file (keep_style doc) for one job post.
    -> (reply dict or None, note). keep_style.check() decides what of it is used."""
    if not available():
        return None, "no Claude API key"
    lines = [f"JOB POST:\n{jd_text[:12000]}", ""]
    if doc.get("headline"):
        lines.append(f"HEADLINE{' (fixed)' if doc['headline']['fixed'] else ''}: {doc['headline']['text']}")
    if doc.get("summary"):
        lines.append(f"SUMMARY{' (fixed)' if doc['summary']['fixed'] else ''}: {doc['summary']['text']}")
    lines.append("\nJOBS:")
    for j in doc["jobs"]:
        lines.append(f"{j['id']}: {j['title']} at {j['company']} ({j['start']} - {j['end']})")
        lines += [f"  {b['id']}{' (fixed)' if b['fixed'] else ''}: {b['text']}" for b in j["bullets"]]
    if doc.get("skills"):
        lines.append("\nSKILLS:")
        lines += [f"{l['id']}{' (fixed)' if l.get('fixed') else ''} - {l['label']}: {', '.join(l['items'])}"
                  for l in doc["skills"]]
    try:
        return _json(_call(TAILOR_RULES, "\n".join(lines), 32000, model, timeout=600)), "ok"
    except Exception as e:
        return None, f"Claude resume step skipped: {e}"

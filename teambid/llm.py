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


def _call(system, user, max_tokens=1500, model=None):
    r = requests.post(API, timeout=120, headers={"x-api-key": config.ANTHROPIC_KEY, "anthropic-version": "2023-06-01",
                                                 "content-type": "application/json"},
                      json={"model": model or config.MODEL, "max_tokens": max_tokens, "system": system,
                            "messages": [{"role": "user", "content": user}]})
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")


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


def refine_profile(raw_text, profile):
    """Ask Claude to fix company/title/date/bullet splits. -> (roles or None, message). Only structure changes are accepted."""
    if not available():
        return None, "no API key"
    system = ("You fix resume parsing. Return ONLY JSON with key 'roles': a list of {company, title, location, start (YYYY-MM), "
              "end (YYYY-MM or Present), bullets: [exact bullet text]}. Copy text exactly from the resume. Never add or reword facts.")
    try:
        out = _call(system, f"RESUME TEXT:\n{raw_text[:15000]}\n\nCURRENT PARSE:\n{json.dumps(profile.get('roles', []))[:8000]}", 4000)
        data = json.loads(re.search(r"\{.*\}", out, re.S).group(0))
        roles = data.get("roles", [])
        src = re.sub(r"\s+", " ", raw_text)
        ok = all(re.sub(r"\s+", " ", b)[:40] in src for r in roles for b in r.get("bullets", []))
        if not roles or not ok:
            return None, "model output changed bullet text; kept the original parse"
        return roles, "refined"
    except Exception as e:
        return None, f"API error: {e}"


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
        out = _call(WRITE_RULES.replace("{company}", company), user, 2000, model).strip().strip("`").strip()
        problems = guard(out, draft, profile, company, jd_text)
        if problems:
            out = _call(WRITE_RULES.replace("{company}", company), user + "\n\nYOUR LAST VERSION WAS REJECTED FOR: " +
                        "; ".join(problems) + ". Fix exactly these problems.\n\nLAST VERSION:\n" + out, 2000, model).strip().strip("`").strip()
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
    "You tailor resume wording to a job post. You get the summary and bullets already chosen from the candidate's real "
    "resume. Reword them so the job post's own terms show up where the bullet truly supports them. Hard rules: keep every "
    "number exactly as written, keep the same facts and scope, never add a tool, skill, company, result or claim, keep "
    "each bullet about the same length (one line stays one line), start bullets with a strong past-tense verb, no em "
    "dashes or semicolons. If a bullet can't be improved honestly, return it unchanged. Never use these words: "
    + ", ".join(sorted(writing.BANNED)) + ". Return ONLY JSON: {\"summary\": \"...\", \"bullets\": {\"<id>\": \"...\"}}.")


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


def rewrite_resume(spec, profile, jd_text, model=None):
    """Claude rewords the chosen bullets + summary toward the job post. Each change must pass _bullet_ok; the rest stay
    verbatim. Accepted rewordings are recorded in spec['rewritten'] (new -> original) for validate(). -> (spec, note)."""
    if not available():
        return spec, "no Claude API key"
    ids = {f"r{i}b{j}": b for i, r in enumerate(spec["roles"]) for j, b in enumerate(r["bullets"])}
    user = (f"JOB POST:\n{jd_text[:12000]}\n\nSUMMARY:\n{spec.get('summary', '')}\n\nBULLETS:\n" +
            "\n".join(f"{k}: {v}" for k, v in ids.items()))
    try:
        out = _call(RESUME_RULES, user, 3000, model)
        data = json.loads(re.search(r"\{.*\}", out, re.S).group(0))
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
    raw = profile.get("raw_text", "") + " " + s_old
    if (s_new and s_new != s_old and all(n in raw for n in _numbers(s_new))
            and not [s for s in SK.find(s_new) if s not in have]
            and not any(re.search(rf"\b{re.escape(w)}\b", s_new.lower()) for w in writing.BANNED)
            and 0.6 <= len(s_new) / max(1, len(s_old)) <= 1.4):
        spec["summary"] = s_new
        took += 1
    return spec, f"Claude reworded {took} of {len(ids) + 1} lines toward the job post (each kept its numbers and facts)"

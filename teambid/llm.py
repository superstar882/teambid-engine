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


def available():
    return bool(config.ANTHROPIC_KEY)


def provider(prefer="auto"):
    """'claude', 'local' or None."""
    if prefer in ("auto", "claude") and available():
        return "claude"
    if prefer in ("auto", "local") and local_ai.chat_available():
        return "local"
    return None


def _call(system, user, max_tokens=1500):
    r = requests.post(API, timeout=120, headers={"x-api-key": config.ANTHROPIC_KEY, "anthropic-version": "2023-06-01",
                                                 "content-type": "application/json"},
                      json={"model": config.MODEL, "max_tokens": max_tokens, "system": system,
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

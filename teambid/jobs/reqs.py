"""What a job post asks of the person, read by Claude: once per job, shared by every member, kept with the job's facts
(facts.py, key "req").

The rules in tailor.analyze_jd miss most of it: posts name their requirement sections in hundreds of ways ("What we need
to see", "Your expertise") and ask for things no skills list knows (device drivers, multicore hardware). So Claude reads
the post and lists each requirement with the terms a resume would show it by, and code keeps only the ones whose quote
really is in the post: nothing is invented. matcher.score_job then checks every requirement against each member's resume.

  required   [{"name": "Rust, Python, Go or Node.js", "any": ["Rust", "Python", "Go", "Node.js"], "core": true}, ...]
  preferred  [{"name": "OpenTelemetry", "any": ["OpenTelemetry", "tracing"]}, ...]
  years      the smallest number of years of experience the post asks for, or None
  by         the model that read it
"""
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import requests

from .. import llm

MODEL = llm.MODELS["haiku"][0]       # about $0.0015 a post: 2,000 tokens in, 3,000 out with its thinking
MAX_CHARS = 12000                    # what the scan keeps of a post (scanner._with_facts)
PAUSE = 5                            # seconds before asking a busy API again (x3 the next time)
RUN_MINUTES = float(os.environ.get("TEAMBID_REQ_MINUTES", "45"))     # Claude reading per run, all members together
RUN_POSTS = int(os.environ.get("TEAMBID_REQ_POSTS", "4000"))          # and at most this many posts (about $6)
RULES = (
    "You read one job post and list what the job requires of the person, as JSON. Leave out the company blurb, benefits, "
    "pay, equal-opportunity text, degrees, soft skills (communication, ownership, teamwork, leadership), years, location, "
    "travel and work authorization.\n"
    "required: what the post says the person must have (requirements, qualifications, \"what we need to see\", \"you "
    "have\", \"you bring\"). preferred: what it calls a plus, a bonus, nice to have or a way to stand out. Duties under "
    "\"what you'll do\" count only when they name a skill the person must already have.\n"
    "Each item: {\"name\": the short label a recruiter would use (1-5 words), \"any\": 1-8 terms, any ONE of which on a "
    "resume shows the item: the alternatives the post allows (\"one of Rust, Python, Go or Node.js\" is one item with all "
    "four) plus the usual names and specific tools for the same thing (containers: Docker, Podman). Use the words a resume "
    "would use. Each term must mean this item on any resume, out of context: \"BGP\" or \"network routing\", not "
    "\"routing\" (web apps have routing too); never a generic word any engineer's resume has (AI, software, debugging, "
    "optimization, programming, design). "
    "\"quote\": the post's own words that state it (3-12 words, copied exactly). \"core\": true only for the 1-3 things "
    "the whole job is built around (its main language, platform or field), without which nobody would be considered}.\n"
    "years: the smallest number of years of experience the post requires, or null.\n"
    "Return ONLY JSON: {\"required\": [...], \"preferred\": [...], \"years\": n or null}")
RETRY = (408, 429, 500, 502, 503, 504, 529)
_run = {"start": None, "posts": 0}
_lock = threading.Lock()


def available():
    return llm.available()


def _words(s):
    return " ".join(re.findall(r"[a-z0-9+#]+", (s or "").lower()))


def confirm(data, text):
    """Claude's reply -> the requirements whose quote is in the post (markup, quote marks and dashes aside), at most
    three of them core; years only when the post has that number."""
    post = f" {_words(text)} "
    out = {}
    for key in ("required", "preferred"):
        rows = []
        for it in data.get(key) or []:
            if not isinstance(it, dict):
                continue
            terms = it.get("any")
            terms = [terms] if isinstance(terms, str) else terms if isinstance(terms, list) else []
            terms = list(dict.fromkeys(str(t).strip()[:60] for t in terms if str(t).strip()))[:8]
            name, quote = str(it.get("name") or "").strip()[:80], _words(str(it.get("quote") or ""))
            if not name or not terms or len(quote.split()) < 2 or f" {quote} " not in post:
                continue
            row = {"name": name, "any": terms}
            if key == "required":
                row["core"] = bool(it.get("core")) and sum(r["core"] for r in rows) < 3
            rows.append(row)
        out[key] = rows[:15]
    years = data.get("years")
    ok = isinstance(years, (int, float)) and not isinstance(years, bool) and 0 < years < 20
    out["years"] = int(years) if ok and re.search(rf"\b{int(years)}\b", text or "") else None
    out["by"] = MODEL
    return out


def read(text, title=""):
    """-> the post's requirements (see confirm), or None when Claude couldn't read it: no key, an error, a reply without
    JSON. A busy API, a timeout or a broken reply is tried again twice."""
    if not available() or not (text or "").strip():
        return None
    user = (f"JOB TITLE: {title}\n\n" if title else "") + f"JOB POST:\n{text[:MAX_CHARS]}"
    for attempt in range(3):
        wait = PAUSE * 3 ** attempt
        try:
            return confirm(llm._json(llm._call(RULES, user, 8000, MODEL, timeout=180)), text)
        except requests.HTTPError as e:
            if getattr(e.response, "status_code", 0) not in RETRY:
                return None
            try:
                wait = max(wait, min(60.0, float((e.response.headers or {}).get("retry-after", 0))))
            except (TypeError, ValueError):
                pass
        except (requests.RequestException, ValueError, RuntimeError):
            pass
        if attempt < 2:
            time.sleep(wait)
    return None


def read_all(posts, workers=12):
    """posts: [(key, title, text)] -> {key: requirements} for the ones Claude read, in parallel, within the run's budget
    (RUN_MINUTES and RUN_POSTS for all members together). The rest keep the rules' reading until the next run."""
    with _lock:
        if _run["start"] is None or time.monotonic() - _run["start"] > 6 * 3600:     # a new run (or a long-lived app)
            _run.update(start=time.monotonic(), posts=0)
        deadline = _run["start"] + RUN_MINUTES * 60
    out, lock = {}, threading.Lock()

    def one(post):
        with _lock:
            if time.monotonic() > deadline or _run["posts"] >= RUN_POSTS:
                return
            _run["posts"] += 1
        got = read(post[2], post[1])
        if got is not None:
            with lock:
                out[post[0]] = got
    if posts:
        with ThreadPoolExecutor(workers) as ex:
            list(ex.map(one, posts))
    return out

"""Tailor each member's resume inside their own file, so it keeps their look (icons, links, fonts, layout).

Claude reads the resume once at upload (read); code keeps only what really is in the text (confirm) and saves it next
to the file (pieces.json). For each job post Claude rewrites and reorders those pieces, code checks every change
(check), and the file's handler puts the text back and builds the PDF (tailor). Anything that fails falls back to the
RenderCV resume. Design: docs/superpowers/specs/2026-11-05-keep-original-style-design.md
"""
import datetime as dt
import hashlib
import json
import re
from pathlib import Path

from . import config, llm, resume_parse
from .style_text import key

MAX_MISSED = 0.25            # more bullets than this not found word for word: don't trust the reading at all
YM = re.compile(r"\d{4}-\d{2}")


def _follows(hay, keys, start, gap=3):
    """True if every key in keys is found in order, each starting at most `gap` characters after the previous one
    ends (the gap leaves room for punctuation key() keeps, like ":" "," "." "("). Empty keys fail."""
    pos = start
    for k in keys:
        if not k:
            return False
        i = hay.find(k, pos, pos + gap + len(k))
        if i < 0:
            return False
        pos = i + len(k)
    return True


def confirm(reading, text):
    """Keep only what was copied word for word from the resume text (line breaks, hyphen splits, dash and quote styles
    ignored); bullets must also come in reading order. -> (pieces or None, note)."""
    reading = reading if isinstance(reading, dict) else {}
    hay = key(text)

    def at(s, start=0, shortest=3):
        k = key(s)
        return hay.find(k, start) if len(k) >= shortest else -1

    jobs, total, missed, pos = [], 0, 0, 0
    for j in reading.get("jobs") or []:
        if not isinstance(j, dict):
            continue
        kept = []
        for b in j.get("bullets") or []:
            b = str(b).strip()
            total += 1
            i = at(b, pos)
            if i < 0:
                missed += 1
                continue
            pos = i + len(key(b))
            kept.append(b)
        jobs.append({**{k: str(j.get(k) or "").strip() for k in ("title", "company", "location", "start", "end")},
                     "bullets": kept})
    if not total:
        return None, "no job bullets found in the resume"
    if missed > MAX_MISSED * total:
        return None, f"{missed} of {total} bullets weren't word for word in the resume"
    skills = []
    for line in reading.get("skills") or []:
        if not isinstance(line, dict):
            continue
        label = str(line.get("label") or "").strip()
        items = [str(x).strip() for x in line.get("items") or [] if str(x).strip()]
        lk, item_keys = key(label), [key(x) for x in items]
        # the label's own key can also show up earlier (e.g. in the summary), so try every occurrence; a line only
        # counts when, right after one of them, its items chain in order (a short invented item can't just be a
        # substring of some unrelated word elsewhere in the resume)
        if (label and len(items) >= 2 and lk
                and any(_follows(hay, item_keys, m.end()) for m in re.finditer(re.escape(lk), hay))):
            skills.append({"label": label, "items": items})
    head, summ = (str(reading.get(k) or "").strip() for k in ("headline", "summary"))
    pieces = {"headline": head if at(head) >= 0 else "", "summary": summ if at(summ) >= 0 else "",
              "jobs": jobs, "skills": skills}
    return pieces, f"read {total - missed} of {total} bullets in {len(jobs)} jobs"


def read(text):
    """Claude reads the resume text -> (confirmed pieces or None, note)."""
    data, note = llm.read_resume(text)
    if not data:
        return None, note
    return confirm(data, text)


def pieces_from_profile(profile):
    """The rule-based parse in the same shape (used when Claude isn't available or its reading was rejected)."""
    return {"headline": profile.get("headline", ""), "summary": profile.get("summary", ""), "skills": [],
            "jobs": [{"title": r.get("title", ""), "company": r.get("company", ""), "location": r.get("location", ""),
                      "start": r.get("start", ""), "end": r.get("end", ""),
                      "bullets": [b["text"] for b in r.get("bullets", [])]} for r in profile.get("roles", [])]}


def apply_to_profile(profile, pieces):
    """Claude's confirmed reading replaces the rule-based jobs, headline and summary; years, level and lanes are worked
    out again from it."""
    today = dt.date.today()
    roles = []
    for j in pieces.get("jobs", []):
        start = j["start"] if YM.fullmatch(j["start"]) else ""
        end = "Present" if re.fullmatch(r"(?i)present|current|now", j["end"]) else (j["end"] if YM.fullmatch(j["end"]) else "")
        a = tuple(int(x) for x in start.split("-")) if start else None
        b = (today.year, today.month) if end == "Present" else (tuple(int(x) for x in end.split("-")) if end else None)
        r = {"company": j["company"], "title": j["title"], "location": j["location"], "start": start, "end": end,
             "current": end == "Present", "months": resume_parse.months_between(a, b) if a and b else 0,
             "bullets": [{"text": t} for t in j["bullets"]], "stack_line": ""}
        resume_parse.finish_role(r)
        roles.append(r)
    if roles:
        profile["roles"] = roles
    for k in ("headline", "summary"):
        if pieces.get(k):
            profile[k] = pieces[k]
    text = "\n".join(b["text"] for r in profile["roles"] for b in r["bullets"])
    profile["metrics"] = sorted(set(resume_parse.metrics(text + "\n" + profile.get("summary", ""))))
    resume_parse.derive(profile)
    return profile


def _pieces_path(slug):
    return config.member_dir(slug) / "resume" / "pieces.json"


def _sha(src):
    return hashlib.sha1(Path(src).read_bytes()).hexdigest()


def save_pieces(slug, src, pieces):
    data = {"source": Path(src).name, "sha": _sha(src), **pieces}
    _pieces_path(slug).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def load_pieces(slug, src):
    """The saved pieces, if they were read from this exact file."""
    try:
        data = json.loads(_pieces_path(slug).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if data.get("sha") == _sha(src) else None

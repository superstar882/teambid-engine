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
from pathlib import Path, PureWindowsPath

from . import config, llm, resume_parse, style_pdf, style_tex
from . import skills as SK
from . import tailor as TL
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


def _list(v):
    """v if it's a list, else [] (a malformed reply field is "no answer", not a crash)."""
    return v if isinstance(v, list) else []


def confirm(reading, text):
    """Keep only what was copied word for word from the resume text (line breaks, hyphen splits, dash and quote styles
    ignored); bullets must also come in reading order. -> (pieces or None, note)."""
    reading = reading if isinstance(reading, dict) else {}
    hay = key(text)

    def at(s, start=0, shortest=3):
        k = key(s)
        return hay.find(k, start) if len(k) >= shortest else -1

    jobs, total, missed, pos = [], 0, 0, 0
    for j in _list(reading.get("jobs")):
        if not isinstance(j, dict):
            continue
        kept = []
        for b in _list(j.get("bullets")):
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
    for line in _list(reading.get("skills")):
        if not isinstance(line, dict):
            continue
        label = str(line.get("label") or "").strip()
        items = [str(x).strip() for x in _list(line.get("items")) if str(x).strip()]
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
    """Claude reads the resume text -> (confirmed pieces or None, note). Any failure here only skips the reading: the
    upload goes on with the rule-based parse. The pieces say they came from Claude ("by")."""
    try:
        data, note = llm.read_resume(text)
        if not data:
            return None, note
        pieces, note = confirm(data, text)
        if pieces:
            pieces["by"] = "claude"
        return pieces, note
    except Exception as e:
        return None, f"Claude reading skipped: {e}"


def pieces_from_profile(profile):
    """The rule-based parse in the same shape (used when Claude isn't available or its reading was rejected)."""
    return {"headline": profile.get("headline", ""), "summary": profile.get("summary", ""), "skills": [],
            "jobs": [{"title": r.get("title", ""), "company": r.get("company", ""), "location": r.get("location", ""),
                      "start": r.get("start", ""), "end": r.get("end", ""),
                      "bullets": [b["text"] for b in r.get("bullets", [])]} for r in profile.get("roles", [])]}


def rule_pieces(profile, text):
    """The rule-based parse's pieces that confirm against the text, marked "by": "rules", or None. Its bullets can be
    pieces of a bullet (a wrapped line read as two), so a PDF only reorders them (see tailor)."""
    pieces = confirm(pieces_from_profile(profile), text)[0]
    if pieces:
        pieces["by"] = "rules"
    return pieces


def _ym(value, end=False):
    """A date as the resume writes it ('2022-04', 'June 2023', '04/2022', '2022') -> 'YYYY-MM', else '' (like
    admin._ym). Without this a job ending 'June 2023' would count as running to today."""
    v = str(value or "").strip()
    if YM.fullmatch(v):
        return v
    d = None if re.fullmatch(resume_parse.NOW, v, re.I) else resume_parse.parse_date(v, end=end)
    return f"{d[0]:04d}-{d[1]:02d}" if d else ""


def apply_to_profile(profile, pieces):
    """Claude's confirmed reading replaces the rule-based jobs, headline and summary; years, level and lanes are worked
    out again from it."""
    today = dt.date.today()
    roles = []
    for j in pieces.get("jobs", []):
        start = _ym(j["start"])
        end = "Present" if re.fullmatch(resume_parse.NOW, j["end"], re.I) else _ym(j["end"], end=True)
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


def save_rule_pieces(slug, src, profile):
    """Save the rule-based pieces (when Claude's reading was rejected or Claude isn't available), so tailoring doesn't
    read the file again for every job. A reading of this same file that isn't rule-based is kept."""
    saved = load_pieces(slug, src)
    if saved and saved.get("by", "claude") != "rules":        # an older reading without "by" came from Claude too
        return
    pieces = rule_pieces(profile, profile.get("raw_text", ""))
    if pieces:
        save_pieces(slug, src, pieces)


LENGTH = (0.75, 1.10)        # a reworded bullet or summary: at most 25% shorter, at most 10% longer
LEVEL = r"lead|staff|principal|manager|architect|head|director|vp|chief"


def clean_bold(new, old):
    """Strip any markup but **bold**. Bold stays only around tool/skill names or words the original had in bold, and
    only when the original used bold at all."""
    new = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", str(new or ""))         # markdown links -> their text
    new = re.sub(r"\s+", " ", re.sub(r"[\\`<>{}]", "", new)).strip()
    if "**" not in old or new.count("**") % 2:
        return new.replace("**", "")
    was_bold = {key(x) for x in old.split("**")[1::2]}
    return "".join(f"**{p}**" if i % 2 and p.strip() and (key(p) in was_bold or SK.find(p, trusted=True)) else p
                   for i, p in enumerate(new.split("**")))


def _chars_ok(new, old):
    """Every character is printable ASCII or one the original already has. pdflatex can fail on one it doesn't know
    (an arrow, an emoji, a zero-width space), and that would send the whole resume to RenderCV."""
    return all(" " <= c <= "~" or c in old for c in new)


def _bullet_new(new, old, have):
    """Claude's rewording of one bullet if it passes the fact checks and the length limits, else None."""
    new = clean_bold(new, old)
    n, o = new.replace("**", ""), old.replace("**", "")
    ok = _chars_ok(n, o) and llm._bullet_ok(n, o, have) and LENGTH[0] <= len(n) / max(1, len(o)) <= LENGTH[1]
    return new if ok else None


def headline_ok(new, old, profile, job_title):
    """The new headline in the original's capital-letter style, or None. Its words must come from titles the member
    held or the job's title, with no level above one they held and no tool they don't list."""
    new = re.sub(r"\s+", " ", re.sub(r"[\\`<>{}*]", "", str(new or ""))).strip()
    if not new or key(new) == key(old) or len(new) > max(60, 1.5 * len(old)) or not _chars_ok(new, old):
        return None
    held = " ".join(r.get("title", "") for r in profile.get("roles", [])) + " " + old
    pool = set(re.findall(r"[a-z0-9.+#]+", (held + " " + job_title).lower()))
    if any(w not in pool for w in re.findall(r"[a-z0-9.+#]+", new.lower())):
        return None
    for lvl in re.findall(rf"(?i)\b({LEVEL})\b", new):
        if not re.search(rf"(?i)\b{lvl}\b", held):
            return None
    if re.search(r"(?i)\b(senior|sr)\b", new) and not re.search(rf"(?i)\b(senior|sr|{LEVEL})\b", held):
        return None
    have = set(profile.get("skills", {}).get("all", []))
    if [s for s in SK.find(new) if s not in have]:
        return None
    return new.upper() if old.isupper() else new


def default_plan(doc, jd):
    """What changes without Claude: bullets ordered by relevance to the job (tailor's score), skills by the job's
    weights. Ties keep the original order."""
    w = TL.jd_weights(jd)
    weight = lambda item: sum(w.get(s, 0) for s in SK.find(item, trusted=True))
    plan = {"headline": None, "summary": None, "text": {}, "order": {}, "skills": {}, "skill_lines": []}
    for j in doc["jobs"]:
        if j["reorder"]:
            ranked = sorted(j["bullets"], key=lambda b: -TL._bullet_score(b["text"].replace("**", ""), w))
            plan["order"][j["id"]] = [b["id"] for b in ranked]
    for line in doc["skills"]:
        plan["skills"][line["id"]] = sorted(line["items"], key=lambda x: -weight(x))
    if doc.get("skills_move"):
        plan["skill_lines"] = [l["id"] for l in sorted(doc["skills"], key=lambda l: -sum(weight(x) for x in l["items"]))]
    return plan


def check(doc, reply, profile, jd):
    """Claude's reply -> the plan that passed every check. A piece that fails keeps its original text, and an order
    that isn't exactly the original IDs keeps the relevance order (so no bullet is ever lost or added)."""
    plan = default_plan(doc, jd)
    reply = reply if isinstance(reply, dict) else {}
    texts = reply.get("bullets") if isinstance(reply.get("bullets"), dict) else {}
    orders = reply.get("order") if isinstance(reply.get("order"), dict) else {}
    have = set(profile.get("skills", {}).get("all", []))
    for j in doc["jobs"]:
        got = [str(x) for x in _list(orders.get(j["id"]))]
        if j["reorder"] and sorted(got) == sorted(b["id"] for b in j["bullets"]):
            plan["order"][j["id"]] = got
        for b in j["bullets"]:
            new = _bullet_new(texts.get(b["id"]), b["text"], have)
            if new and not b["fixed"]:
                plan["text"][b["id"]] = new
    s = doc.get("summary")
    if s and not s["fixed"]:
        new = clean_bold(reply.get("summary"), s["text"])
        n, o = new.replace("**", ""), s["text"].replace("**", "")
        if _chars_ok(n, o) and llm._summary_ok(n, o, profile, *LENGTH):
            plan["summary"] = new
    h = doc.get("headline")
    if h and not h["fixed"]:
        plan["headline"] = headline_ok(reply.get("headline"), h["text"], profile, jd.get("title", ""))
    lines = reply.get("skills") if isinstance(reply.get("skills"), dict) else {}
    for line in doc["skills"]:
        got = [str(x).strip() for x in _list(lines.get(line["id"]))]
        if got and sorted(map(key, got)) == sorted(map(key, line["items"])):
            plan["skills"][line["id"]] = got
    got = [str(x) for x in _list(reply.get("skill_lines"))]
    if doc.get("skills_move") and got and sorted(got) == sorted(l["id"] for l in doc["skills"]):
        plan["skill_lines"] = got
    return plan


HANDLERS = {".tex": style_tex, ".pdf": style_pdf}      # .docx comes in part 2 (after PDFs: the team uploads PDFs)


def source_file(slug, member):
    """The member's own resume file a handler can edit, or None (today's RenderCV resume is used then). Only the file
    they uploaded last: a .tex left from an earlier upload must never beat their current resume."""
    # the stored path may be another computer's (PC vs cloud): only its name counts, split at either slash
    f = config.member_dir(slug) / "resume" / PureWindowsPath(str((member or {}).get("resume_file") or "")).name
    return f if f.suffix.lower() in HANDLERS and f.is_file() else None


def pieces_for(slug, profile, src):
    """The confirmed pieces of the member's file: the saved ones while the file is unchanged (whoever read them), else
    read again (Claude when a key is set, the rule-based parse if not) and saved."""
    saved = load_pieces(slug, src)
    if saved:
        return saved
    text, _ = resume_parse.extract_text(src)
    pieces = read(text)[0] if llm.available() else None
    if not pieces:
        pieces = rule_pieces(profile, text)
    if pieces:
        save_pieces(slug, src, pieces)
    return pieces


def _build(handler, doc, plan, folder, base):
    """Build the file. While it has more pages than the original, put back the original text of the piece that grew
    the most (5 times at most). -> (files, how many were put back)."""
    olds = {b["id"]: b["text"] for j in doc["jobs"] for b in j["bullets"]}
    for reverted in range(6):
        files = handler.build(doc, plan, folder, base)
        if files["pages"] <= doc["pages"]:
            return files, reverted
        grown = [(len(t) - len(olds[i]), i) for i, t in plan["text"].items()]
        if plan.get("summary") and doc.get("summary"):
            grown.append((len(plan["summary"]) - len(doc["summary"]["text"]), "summary"))
        grown = sorted(g for g in grown if g[0] > 0)
        if not grown or reverted == 5:
            break
        worst = grown[-1][1]
        if worst == "summary":
            plan["summary"] = None
        else:
            del plan["text"][worst]
    for k in ("pdf", "source"):          # the RenderCV resume is used instead: no stale tailored file next to it
        if files.get(k):
            Path(files[k]).unlink(missing_ok=True)
    raise ValueError(f"the tailored file has {files['pages']} pages, the original {doc['pages']}")


def report_spec(doc, plan):
    """The tailored text in the shape tailor.validate / keyword_report read; spec.json keeps it with the plan."""
    roles, rewritten = [], {}
    for j in doc["jobs"]:
        by_id = {b["id"]: b for b in j["bullets"]}
        texts = []
        for bid in plan["order"].get(j["id"]) or list(by_id):
            t = (plan["text"].get(bid) or by_id[bid]["text"]).replace("**", "")
            rewritten[t] = by_id[bid]["piece"]          # validate() traces every bullet back to the resume
            texts.append(t)
        roles.append({"company": j["company"], "title": j["title"], "bullets": texts})
    lines = {l["id"]: l for l in doc["skills"]}
    skills = [(lines[i]["label"], SK.find(", ".join(plan["skills"].get(i) or lines[i]["items"]), trusted=True))
              for i in (plan["skill_lines"] or list(lines))]
    head = plan.get("headline") or (doc.get("headline") or {}).get("text", "")
    summary = (plan.get("summary") or (doc.get("summary") or {}).get("text", "")).replace("**", "")
    return {"headline": head, "summary": summary, "skills": skills, "roles": roles, "projects": [],
            "rewritten": rewritten, "style": {"source": doc["ext"], "plan": plan}}


def tailor(slug, member, profile, jd, jd_text, model, folder, base):
    """Tailor the member's own resume file for one job post. model None = no Claude: bullets and skills are only
    reordered. -> {"files", "spec", "note"}; {"note": why} when it fell back; {} when there's no file to edit."""
    src = source_file(slug, member) if (config.MEMBERS / slug / "resume").exists() else None   # never creates folders
    if not src:
        return {}
    handler = HANDLERS[src.suffix.lower()]
    kept = []
    try:
        pieces = pieces_for(slug, profile, src)
        if not pieces:
            return {"note": "original style skipped: couldn't read the resume's parts"}
        doc = handler.find(src, pieces)
        if not doc["jobs"]:
            return {"note": "original style skipped: couldn't find the job bullets in the file"}
        plan, why, reply = default_plan(doc, jd), "no Claude: reordered only", None
        if model and handler is style_pdf and pieces.get("by") != "claude":
            # the rule-based parse can cut a bullet in two (a wrapped line read as its own bullet): a rewording drawn
            # over half a bullet would garble the PDF, so those pieces are only reordered (older saved pieces too)
            model, why = None, "read without Claude: reordered only"
        if model:
            reply, why = llm.tailor_in_place(doc, jd_text, model)
            if reply:
                plan, why = check(doc, reply, profile, jd), ""
        files, reverted = _build(handler, doc, plan, Path(folder), base)
        kept = files.pop("kept", [])
        for bid in kept:                           # rewordings the file couldn't fit kept their original text
            plan["text"].pop(bid, None)
        used = files.pop("order", None)            # the PDF handler says the order it really drew (.tex builds don't)
        if used is not None:
            plan["order"].update(used)
            same = lambda j: used.get(j["id"], [b["id"] for b in j["bullets"]]) == [b["id"] for b in j["bullets"]]
            if not plan["text"] and all(same(j) for j in doc["jobs"]):
                Path(files["pdf"]).unlink(missing_ok=True)       # the tailored RenderCV resume is used instead
                return {"note": "original style skipped: nothing in the file could be tailored safely"}
    except Exception as e:                       # any failure: today's RenderCV resume is used instead
        return {"note": f"original style skipped: {str(e)[:160]}"}
    total = sum(len(j["bullets"]) for j in doc["jobs"])
    moved = sum(1 for j in doc["jobs"] if plan["order"].get(j["id"], [b["id"] for b in j["bullets"]]) != [b["id"] for b in j["bullets"]])
    note = (f"Resume style: original ({doc['ext']}). {len(plan['text'])} of {total} bullets reworded, "
            f"{total - len(plan['text'])} kept as written, order changed in {moved} jobs, "
            f"{files['pages']} page(s) (original {doc['pages']})")
    if reverted:
        note += f", put back {reverted} longer piece(s) to keep the page count"
    if kept:
        note += f", {len(kept)} reworded bullet(s) kept their original text to fit"
    if why:
        note += f" ({why})"
    spec = report_spec(doc, plan)
    spec["style"]["claude_reply"] = reply        # spec.json shows what Claude sent next to what passed the checks
    return {"files": files, "spec": spec, "note": note}

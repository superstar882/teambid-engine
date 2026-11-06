"""Tailor a member's own LaTeX resume in place: find the pieces, put the new text back, build the PDF.

Only the text of the pieces changes (bullets, summary, headline, the order of skills). The preamble, header, links,
icons and every other byte of the file stay as they were.
Design: docs/superpowers/specs/2026-11-05-keep-original-style-design.md
"""
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

from .style_text import key

# control symbols that print one character (\% -> %); others (\\ line break, ...) make a piece move-only
ESCAPES = {"%": "%", "&": "&", "#": "#", "_": "_", "$": "$", "{": "{", "}": "}", " ": " ", ",": " ", ";": " ", "/": ""}
SKIP_ARG = {"vspace", "hspace", "label", "color", "phantom"}          # their argument isn't text
TEX_ESC = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_", "{": r"\{", "}": r"\}",
           "~": r"\textasciitilde{}", "^": r"\textasciicircum{}", "<": r"\textless{}", ">": r"\textgreater{}",
           "|": r"\textbar{}", "–": "--", "—": "---"}     # < > | print as other glyphs in the default OT1 font


def _mask(src):
    """src with comments blanked out, same length, so a position found in it is the same position in src."""
    return re.sub(r"(?<!\\)%[^\n]*", lambda m: " " * len(m.group(0)), src)


def _close(s, i):
    """s[i] is '{' -> index of the matching '}'."""
    depth, j = 0, i
    while j < len(s):
        c = s[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return j
        j += 1
    raise ValueError("unbalanced braces in the .tex file")


def to_plain(src):
    """A LaTeX snippet -> (plain text with **bold**, simple). simple is False when the snippet uses anything besides
    \\textbf and escaped characters (a link, italics, a line break): such a piece may move but is never reworded."""
    s = _mask(src)
    out, i, simple = [], 0, True
    while i < len(s):
        c = s[i]
        if c == "\\":
            m = re.match(r"\\([A-Za-z]+)\*?\s*|\\(.)", s[i:], re.S)
            name, after = m.group(1), i + m.end()
            if name in {"textbf", "href", "url"} | SKIP_ARG and s.startswith("{", after):
                j = _close(s, after)
                if name == "href" and s.startswith("{", j + 1):        # \href{url}{text}: only the text shows
                    after, j = j + 1, _close(s, j + 1)
                inner, ok = to_plain(s[after + 1:j]) if name not in SKIP_ARG else ("", True)
                out.append(f"**{inner}**" if name == "textbf" and inner else inner)
                simple = simple and ok and name == "textbf"
                i = j + 1
                continue
            if name:
                simple = False
            elif m.group(2) in ESCAPES:
                out.append(ESCAPES[m.group(2)])
            else:
                simple = False
            i = after
            continue
        if c in "{}":
            i += 1
            continue
        for tok, rep in (("---", "—"), ("--", "–"), ("``", '"'), ("''", '"'), ("~", " ")):
            if s.startswith(tok, i):
                out.append(rep)
                i += len(tok)
                break
        else:
            out.append(c)
            i += 1
    text = re.sub(r"\s+", " ", "".join(out)).strip()
    return re.sub(r"\*\*(\s*)\*\*", r"\1", text), simple        # **A** **B** -> **A B**


def to_tex(text):
    """Plain text with **bold** -> LaTeX. Special characters are escaped, so the result always compiles."""
    parts = str(text).split("**")
    if len(parts) % 2 == 0:              # an unpaired ** : drop the marks, keep the words
        parts = ["".join(parts)]
    out = []
    for i, part in enumerate(parts):
        esc = "".join(TEX_ESC.get(c, c) for c in part)
        out.append(f"\\textbf{{{esc}}}" if i % 2 and part else esc)
    return "".join(out)


KINDS = (("experience", re.compile(r"(?i)experience|employment|work history|career")),
         ("summary", re.compile(r"(?i)profile|summary|about|objective")),
         ("skills", re.compile(r"(?i)skill")))


def _sections(mask):
    """-> ([{kind, title, start, end}], (header start, header end)). The header is the body before the first section."""
    found = mask.find("\\begin{document}")
    body = found + len("\\begin{document}") if found >= 0 else 0
    end = mask.find("\\end{document}")
    end = end if end >= 0 else len(mask)
    heads = []
    for m in re.finditer(r"\\section\*?\s*\{", mask[body:end]):
        a = body + m.end() - 1
        b = _close(mask, a)
        heads.append((body + m.start(), b + 1, to_plain(mask[a + 1:b])[0]))
    out = []
    for n, (s, e, title) in enumerate(heads):
        stop = heads[n + 1][0] if n + 1 < len(heads) else end
        kind = next((k for k, rx in KINDS if title and rx.search(title)), "")
        out.append({"kind": kind, "title": title, "start": e, "end": stop})
    return out, (body, heads[0][0] if heads else end)


def _macros(mask):
    """-> (one-argument macros that make a list item, like Jake's \\resumeItem; macros that open, close or head a list).
    Both end a plain \\item's text."""
    defs = {}
    for m in re.finditer(r"\\(?:re)?newcommand\*?\s*\{?\\([A-Za-z]+)\}?\s*(?:\[(\d)\])?\s*\{", mask):
        defs[m.group(1)] = (m.group(2), mask[m.end():_close(mask, m.end() - 1)])
    items = {n for n, (argc, body) in defs.items() if argc == "1" and re.search(r"\\item\b", body)}
    grew = True
    while grew:                          # \resumeSubItem{#1} = \resumeItem{#1}...
        new = {n for n, (argc, body) in defs.items() if n not in items and argc == "1"
               and any(re.search(rf"\\{x}\b", body) for x in items)}
        items |= new
        grew = bool(new)
    lists = {n for n, (_, body) in defs.items() if n not in items and re.search(r"\\(begin|end)\s*\{|\\item\b", body)}
    return items, lists


def _items(mask, start, end, macros, lists):
    """List items between start and end -> [(token start, text start, text end)] in order."""
    names = "|".join(sorted(macros | lists, key=len, reverse=True))
    stop = re.compile(r"\\(item\b|end\s*\{|begin\s*\{|section|subsection" + (f"|(?:{names})\\b" if names else "") + ")")
    call = re.compile(r"\\item\b(?:\s*\[[^\]]*\])?" +
                      (f"|\\\\({'|'.join(sorted(macros, key=len, reverse=True))})\\s*\\{{" if macros else ""))
    out, i = [], start
    while True:
        m = call.search(mask, i, end)
        if not m:
            return out
        tok = m.start()
        if m.group(0).startswith("\\item"):
            a = m.end()
            n = stop.search(mask, a, end)
            b = n.start() if n else end
            i = b
        else:                            # \resumeItem{...}: the text is the argument
            a = m.end()
            b = _close(mask, a - 1)
            i = b + 1
        while a < b and mask[a].isspace():
            a += 1
        while b > a and mask[b - 1].isspace():
            b -= 1
        if b > a:
            out.append((tok, a, b))


def _groups(mask, items):
    """Items with nothing but whitespace between them are one job's list."""
    groups = []
    for tok, a, b in items:
        if groups and not mask[groups[-1][-1][1]:tok].strip(" \t\r\n}"):
            groups[-1].append((a, b))
        else:
            groups.append([(a, b)])
    return groups


def _trim(mask, a, b):
    """Whitespace, and braces that open or close outside the span (\\item{ ... } around several lines)."""
    while True:
        while a < b and mask[a].isspace():
            a += 1
        while b > a and mask[b - 1].isspace():
            b -= 1
        if a < b and mask[a] == "{":
            try:
                inside = _close(mask, a) < b
            except ValueError:
                inside = False
            if not inside:
                a += 1
                continue
        depth, j = 0, a
        while j < b:
            if mask[j] == "\\":
                j += 2
                continue
            depth += {"{": 1, "}": -1}.get(mask[j], 0)
            j += 1
        if depth < 0 and mask[b - 1] == "}":
            b -= 1
            continue
        return a, b


def _skill_line(src, mask, a, b):
    """'{Label:} a, b, c.' or '\\textbf{Label}{: a, b}' -> {label, items: [(start, end)], span, frame} or None."""
    a, b = _trim(mask, a, b)
    colon = mask.find(":", a, b)
    if colon < 0:
        return None
    label = to_plain(src[a:colon])[0].replace("**", "").strip(" {}")
    i = colon + 1
    while i < b and mask[i] in "} \t\n":     # the label's own closing brace
        i += 1
    spans, depth, start, j = [], 0, i, i
    while j < b:
        c = mask[j]
        if c == "\\":
            if mask.startswith("\\\\", j):
                break
            j += 2
            continue
        if c in "{(":
            depth += 1
        elif c in "})":
            depth -= 1
            if depth < 0:
                break
        elif c == "," and depth == 0:
            spans.append((start, j))
            start = j + 1
        j += 1
    spans.append((start, j))
    out = []
    for n, (x, y) in enumerate(spans):
        while x < y and mask[x].isspace():
            x += 1
        while y > x and mask[y - 1].isspace():
            y -= 1
        if n == len(spans) - 1 and y > x and mask[y - 1] == ".":
            y -= 1
        if y > x:
            out.append((x, y))
    if not label or len(out) < 2:
        return None
    # the markup around the label and items: lines may only swap places when theirs is the same
    frame = (re.sub(r"[^\\{}]+", "", re.sub(r"\\[^A-Za-z]", "", src[a:colon])), src[colon + 1:out[0][0]].strip(),
             src[out[-1][1]:b].strip())
    return {"label": label, "items": out, "span": (a, b), "frame": frame}


def locate(src, pieces):
    """Find the confirmed pieces (keep_style.confirm) in the .tex source. -> doc (shape: see the plan's File Map),
    each piece's position in src kept under "_span". Pieces that can't be found aren't in the doc: they stay as written."""
    mask = _mask(src)
    sections, (head_a, head_b) = _sections(mask)
    macros, lists = _macros(mask)
    doc = {"ext": ".tex", "_src": src, "headline": None, "summary": None, "jobs": [], "skills": [], "skills_move": False}
    # headline: a run of plain text in the header that reads exactly like the confirmed headline
    want = key(pieces.get("headline", ""))
    if want:
        cmd = re.sub(r"\\[A-Za-z]+\*?", lambda m: " " * len(m.group(0)), mask[head_a:head_b])
        for m in re.finditer(r"[^{}\\\n]+", cmd):
            run = m.group(0)
            a = head_a + m.start() + (len(run) - len(run.lstrip()))
            b = head_a + m.end() - (len(run) - len(run.rstrip()))
            if b > a and key(src[a:b]) == want:
                doc["headline"] = {"text": to_plain(src[a:b])[0], "fixed": False, "_span": (a, b)}
                break
    # summary: the body of the profile / summary section
    want = key(pieces.get("summary", ""))
    for s in sections:
        if s["kind"] == "summary" and want:
            a, b = s["start"], s["end"]
            while a < b and mask[a].isspace():
                a += 1
            while b > a and mask[b - 1].isspace():
                b -= 1
            text, simple = to_plain(src[a:b])
            if key(text) == want:
                doc["summary"] = {"text": text, "fixed": not simple, "_span": (a, b)}
                break
    # jobs: each run of list items in the experience section(s), matched to a confirmed job by its bullets
    index = {}
    for ji, job in enumerate(pieces.get("jobs", [])):
        for bi, text in enumerate(job.get("bullets", [])):
            index.setdefault(key(text), (ji, bi))
    used = set()
    for s in sections:
        if s["kind"] != "experience":
            continue
        for group in _groups(mask, _items(mask, s["start"], s["end"], macros, lists)):
            found = []
            for a, b in group:
                text, simple = to_plain(src[a:b])
                found.append((index.get(key(text)), text, simple, (a, b)))
            hits = Counter(f[0][0] for f in found if f[0])
            if not hits:
                continue
            ji = hits.most_common(1)[0][0]
            if ji in used:
                continue
            used.add(ji)
            job = pieces["jobs"][ji]
            bullets = [{"id": f"r{ji}b{f[0][1]}", "text": f[1], "fixed": not f[2], "piece": job["bullets"][f[0][1]],
                        "_span": f[3]} for f in found if f[0] and f[0][0] == ji]
            doc["jobs"].append({"id": f"r{ji}", "title": job.get("title", ""), "company": job.get("company", ""),
                                "start": job.get("start", ""), "end": job.get("end", ""), "bullets": bullets,
                                "reorder": len(bullets) == len(found) and len({b["id"] for b in bullets}) == len(bullets)})
    # skills: "Label: a, b, c" lines in the skills section, one per \item or per \\-separated line
    want = {key(l.get("label", "")): l for l in pieces.get("skills", [])}
    for s in sections:
        if s["kind"] != "skills":
            continue
        for _, a, b in _items(mask, s["start"], s["end"], macros, lists):
            breaks = list(re.finditer(r"\\\\", mask[a:b]))
            for x, y in zip([a] + [a + m.end() for m in breaks], [a + m.start() for m in breaks] + [b]):
                line = _skill_line(src, mask, x, y)
                if not line or key(line["label"]) not in want:
                    continue
                items = [to_plain(src[i:j])[0] for i, j in line["items"]]
                if sorted(map(key, items)) != sorted(map(key, want[key(line["label"])].get("items", []))):
                    continue
                doc["skills"].append({"id": f"s{len(doc['skills'])}", "label": line["label"], "items": items,
                                      "_span": line["span"], "_items": line["items"], "_frame": line["frame"]})
    doc["skills_move"] = len({l["_frame"] for l in doc["skills"]}) == 1
    return doc


def render_source(doc, plan):
    """The .tex source with the plan applied. Reordering swaps the texts between the original slots, so every \\item,
    blank line and comment stays where it was; an order that isn't exactly the original IDs is ignored."""
    src = doc["_src"]
    edits = []
    for part in ("headline", "summary"):
        p, new = doc.get(part), plan.get(part)
        if p and new and not p["fixed"]:
            edits.append((*p["_span"], to_tex(new)))
    for job in doc["jobs"]:
        by_id = {b["id"]: b for b in job["bullets"]}
        order = plan.get("order", {}).get(job["id"]) if job["reorder"] else None
        if not order or sorted(order) != sorted(by_id):
            order = list(by_id)
        for slot, bid in zip(job["bullets"], order):
            b = by_id[bid]
            new = plan.get("text", {}).get(bid)
            content = to_tex(new) if new and not b["fixed"] else src[b["_span"][0]:b["_span"][1]]
            if content != src[slot["_span"][0]:slot["_span"][1]]:
                edits.append((*slot["_span"], content))
    lines = {}
    for line in doc["skills"]:
        a, b = line["_span"]
        order = plan.get("skills", {}).get(line["id"]) or line["items"]
        pos = {key(t): n for n, t in enumerate(line["items"])}
        if sorted(map(key, order)) != sorted(pos):
            order = line["items"]
        text = src[a:b]
        for (i, j), name in sorted(zip(line["_items"], order), reverse=True):
            x, y = line["_items"][pos[key(name)]]
            text = text[:i - a] + src[x:y] + text[j - a:]
        lines[line["id"]] = text
    line_order = plan.get("skill_lines") or list(lines)
    if not doc["skills_move"] or sorted(line_order) != sorted(lines):
        line_order = list(lines)
    for slot, lid in zip(doc["skills"], line_order):
        if lines[lid] != src[slot["_span"][0]:slot["_span"][1]]:
            edits.append((*slot["_span"], lines[lid]))
    out, last = src, len(src) + 1
    for a, b, text in sorted(edits, reverse=True):       # from the end, so earlier positions stay right
        if b > last:
            raise ValueError("two edits overlap in the .tex file")
        out, last = out[:a] + text + out[b:], a
    return out


TIMEOUT = 60                             # seconds per LaTeX run
FONTSPEC = re.compile(r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{[^}]*\bfontspec\b")
ENV_KEEP = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT")     # SYSTEMROOT: Windows needs it


def _env():
    """The environment LaTeX and tlmgr run with: only what they need to find themselves and their packages, never the
    run's secrets (Claude key, GitHub token, site password), since the file being built is someone's upload."""
    env = {k: v for k, v in os.environ.items() if k in ENV_KEEP or k.startswith("TEXMF")}
    return dict(env, openin_any="p", openout_any="p", shell_escape="f")


def _latex_cmd(exe, engine, name, out_dir):
    """-> (command, host time limit) for one LaTeX run. In the cloud (TEAMBID_LATEX_SANDBOX=docker) it runs in a
    throwaway container that sees only TeX (read-only) and out_dir, with no network: openin_any=p doesn't stop
    \\input of an absolute path, so an upload could otherwise put the runner's files (members' data, ~/.ssh) in its PDF."""
    args = ["-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", f"{name}.tex"]
    if os.environ.get("TEAMBID_LATEX_SANDBOX") != "docker":
        return [exe, *args], TIMEOUT
    if not shutil.which("docker"):
        raise ValueError("Docker isn't available here for the LaTeX sandbox")
    bindir = Path(os.path.realpath(exe)).parent       # TinyTeX's own bin dir, past the ~/bin links its installer makes
    return ["docker", "run", "--rm", "--network", "none", "--user", f"{os.getuid()}:{os.getgid()}",
            "-v", f"{bindir.parents[1]}:/opt/tex:ro", "-v", f"{out_dir.absolute()}:/work", "-w", "/work",
            "-e", "HOME=/work", "-e", "TEXMFVAR=/work/.texmf-var", "-e", f"PATH=/opt/tex/bin/{bindir.name}:/usr/bin:/bin",
            "-e", "openin_any=p", "-e", "openout_any=p", "-e", "shell_escape=f",
            os.environ.get("TEAMBID_LATEX_IMAGE", "ubuntu:24.04"), "timeout", "-s", "KILL", str(TIMEOUT),
            # by name: pdflatex is a link to pdftex, and pdftex under its own name starts plain TeX, not LaTeX
            f"/opt/tex/bin/{bindir.name}/{engine}", *args], TIMEOUT + 15      # + container start-up


def available():
    return bool(shutil.which("pdflatex"))


def _latex_error(log, output=""):
    """Extract LaTeX error from log. If log has a "^! ..." line, use that.
    Otherwise use the last 3 non-empty lines of process output."""
    err = re.search(r"^! (.+)$", log, re.M)
    if err:
        return f"LaTeX error: {err.group(1)[:160]}"
    # Fallback: last 3 non-empty lines of stdout + stderr
    if output:
        lines = [line for line in output.split('\n') if line.strip()]
        if lines:
            tail = " / ".join(lines[-3:])[:300]
            return f"LaTeX error: the build failed: {tail}"
    return "LaTeX error: the build failed"


def compile_tex(src, out_dir, name):
    """Build src into out_dir/<name>.pdf. -> (pdf path, pages). Raises ValueError with LaTeX's own error line.
    Safe for a file someone uploaded: no shell commands, no writing outside out_dir (openout_any = paranoid), 60 s per
    run, and in the cloud no reading outside it either (the Docker sandbox, _latex_cmd). A missing package is installed
    once with TinyTeX's tlmgr, on the host: the sandbox sees TeX read-only, so the next run has the package."""
    engine = "xelatex" if FONTSPEC.search(_mask(src)) else "pdflatex"
    exe = shutil.which(engine)
    if not exe:
        raise ValueError(f"{engine} isn't installed here, so a .tex resume can't be built")
    out_dir = Path(out_dir)
    cmd, limit = _latex_cmd(exe, engine, name, out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.tex").write_text(src, encoding="utf-8")
    env = _env()                             # docker itself gets the same short list; the container only its -e values
    tried, log_file = set(), out_dir / f"{name}.log"
    for _ in range(5):
        try:
            r = subprocess.run(cmd, cwd=out_dir, env=env, capture_output=True, text=True, errors="replace", timeout=limit)
        except subprocess.TimeoutExpired:
            raise ValueError(f"LaTeX took longer than {TIMEOUT} s") from None
        log = log_file.read_text(encoding="utf-8", errors="replace") if log_file.exists() else r.stdout
        missing = re.search(r"File `([\w-]+)\.(?:sty|cls)' not found", log)
        if r.returncode and missing and missing.group(1) not in tried and shutil.which("tlmgr"):
            tried.add(missing.group(1))
            try:
                subprocess.run(["tlmgr", "install", missing.group(1)], env=env, capture_output=True, timeout=300)
            except subprocess.TimeoutExpired:
                pass
            continue
        if r.returncode:
            raise ValueError(_latex_error(log, r.stdout + r.stderr))
        if "Rerun to get" in log and "rerun" not in tried:
            tried.add("rerun")
            continue
        break
    if r.returncode:
        raise ValueError(_latex_error(log, r.stdout + r.stderr))
    pdf = out_dir / f"{name}.pdf"
    if not pdf.exists():
        raise ValueError("LaTeX made no PDF")
    import fitz
    with fitz.open(pdf) as d:
        return pdf, d.page_count


def _paper(pdf):
    import fitz
    with fitz.open(pdf) as d:
        return "A4" if abs(d[0].rect.width - 595) < 6 else "Letter"


def find(path, pieces):
    """Locate the pieces in the member's .tex, and build it once as it is: that gives the page count to keep, and a
    file that doesn't build here fails before anything is spent on Claude."""
    src = Path(path).read_text(encoding="utf-8", errors="replace")
    doc = locate(src, pieces)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        doc["pages"] = compile_tex(src, Path(tmp), "original")[1]
    return doc


def build(doc, plan, folder, base):
    """Write the tailored .tex and its PDF into folder. -> {"pdf", "source", "pages", "paper"}."""
    src = render_source(doc, plan)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    pdf, tex = folder / f"{base}.pdf", folder / f"{base}.tex"
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        built, pages = compile_tex(src, Path(tmp), "resume")
        shutil.copy(built, pdf)
    tex.write_text(src, encoding="utf-8")
    return {"pdf": str(pdf), "source": str(tex), "pages": pages, "paper": _paper(pdf)}

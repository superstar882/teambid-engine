"""Tailor a member's own Word resume in place: find the pieces in its paragraphs, put the new text back, build the PDF
with LibreOffice.

Reading (find): every paragraph of the body in reading order, table cells (nested too) included, never the headers,
footers or text boxes. A paragraph's text is its runs' text (a tab or a line break reads as a space), with **bold** on
the runs printed in bold. A bullet is the whole text of one paragraph that is a list item (numbering set on it or by
its style) or starts with a typed sign, which isn't part of its text; the headline, summary and skill lines are matched
whole on their paragraphs too. A piece not found whole isn't in the doc, and stays as written. Safety: a paragraph with
a link, a field, a tracked change, a picture, a text box, a tab or break inside its text, or runs in more than one style
beyond bold is fixed (never reworded), and so is a summary over several paragraphs; a job's bullets, or the skill
lines, move only when none is fixed or holds a section break and their paragraphs stand side by side under one parent,
with nothing between them.
Writing (build): a fresh copy of the file. A reworded paragraph's runs are replaced, in the look of its own first
plain and bold runs, after its typed sign (kept as printed); its w:pPr and everything else in the file stay. Moves
move whole w:p elements. LibreOffice prints the PDF, in a Docker sandbox on GitHub Actions (to_pdf), and the PDF must
read back the new text.
Design: docs/superpowers/specs/2026-11-05-keep-original-style-design.md (.docx)
"""
import os
import re
import shutil
import subprocess
import tempfile
from collections import Counter
from copy import deepcopy
from pathlib import Path

import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from lxml import etree

from .style_pdf import BULLETS, _marked, _skill_parts, _skill_spans, _spot
from .style_tex import ENV_KEEP
from .style_text import key

P, R, TXBX = qn("w:p"), qn("w:r"), qn("w:txbxContent")
# what a paragraph can hold that a rewrite of its runs would lose or break: it may still move, but is never reworded
LOCKED = {qn(t) for t in ("w:hyperlink", "w:fldSimple", "w:fldChar", "w:instrText", "w:ins", "w:del", "w:moveFrom",
                          "w:moveTo", "w:rPrChange", "w:pPrChange", "w:drawing", "w:pict", "w:object", "w:txbxContent",
                          "w:sdt", "w:sym", "w:ruby", "w:footnoteReference", "w:endnoteReference",
                          "w:commentReference", "m:oMath", "m:oMathPara")}
# a run's children that print text: None is the element's own text (w:t). A tracked deletion's w:delText is left out
# on purpose, as python-docx's paragraph.text (the text Claude read, resume_parse.extract_text) leaves it out: its
# paragraph still matches its piece, and is fixed anyway (w:del is LOCKED)
TEXT = {qn("w:t"): None, qn("w:tab"): "\t", qn("w:ptab"): "\t", qn("w:br"): "\n", qn("w:cr"): "\n",
        qn("w:noBreakHyphen"): "-", qn("w:softHyphen"): ""}
TOGGLES = {"b", "i", "caps", "smallCaps", "strike", "dstrike", "vanish", "emboss", "imprint", "outline", "shadow"}
# what makes two runs print differently besides bold: (property, the attributes that count; None for all of them)
LOOKS = [("rFonts", ("ascii", "asciiTheme")), ("rFonts", ("hAnsi", "hAnsiTheme"))] + [(t, None) for t in (
    "i", "sz", "color", "u", "strike", "dstrike", "caps", "smallCaps", "vertAlign", "highlight", "shd", "spacing",
    "position", "w", "vanish", "bdr", "effect", "emboss", "imprint", "outline", "shadow")]
# values that print the same as saying nothing (Word writes them on some runs and not others)
NOTHING = {("u", "none"), ("vertAlign", "baseline"), ("highlight", "none"), ("color", "auto"), ("color", "000000")}
LOOSE_SIGNS = set("-–—*")      # signs that also start ordinary text ("-40%"): one counts only with a space after it
SIGN = re.compile(rf"\s*(?:[{re.escape(''.join(sorted(BULLETS)))}]\s+"
                  rf"|[{re.escape(''.join(sorted(BULLETS - LOOSE_SIGNS)))}]\s*)(?=\S)")


def paragraphs(document):
    """The body's paragraphs in reading order, table cells (nested too) included: not the headers and footers (other
    parts of the file), nor a text box's (they sit inside another paragraph). A piece's "_at" is its place here, so
    build finds the same paragraph in a fresh copy of the file."""
    return [p for p in document.element.body.iter(P) if next(p.iterancestors(TXBX), None) is None]


def _styles(document):
    """The document's styles by id, its default paragraph style and its default run properties."""
    root = document.styles.element
    by_id = {s.get(qn("w:styleId")): s for s in root.findall(qn("w:style"))}
    para = next((i for i, s in by_id.items()
                 if s.get(qn("w:type")) == "paragraph" and s.get(qn("w:default")) in ("1", "true", "on")), None)
    return {"by_id": by_id, "para": para,
            "defaults": root.find(f"{qn('w:docDefaults')}/{qn('w:rPrDefault')}/{qn('w:rPr')}")}


def _chain(st, sid):
    """A style and the styles it's based on, nearest first."""
    out, seen = [], set()
    while sid and sid in st["by_id"] and sid not in seen:
        seen.add(sid)
        out.append(st["by_id"][sid])
        based = out[-1].find(qn("w:basedOn"))
        sid = based.get(qn("w:val")) if based is not None else None
    return out


def _val(el, path):
    """The w:val of el's child at path, or None."""
    found = el.find(path) if el is not None else None
    return found.get(qn("w:val")) if found is not None else None


def _value(rpr, tag, attrs):
    """What one layer of run properties says of a property; None when it says nothing (the next layer decides)."""
    el = rpr.find(qn(f"w:{tag}")) if rpr is not None else None
    if el is None:
        return None
    got = {k.split("}")[-1]: v for k, v in el.attrib.items()}
    if attrs:
        got = {k: v for k, v in got.items() if k in attrs}
        if not got:
            return None
    if tag in TOGGLES:
        return got.get("val", "true") not in ("0", "false", "off")
    if set(got) == {"val"} and (tag, got["val"]) in NOTHING:
        return ""
    return tuple(sorted(got.items()))


def _look(layers, tag, attrs=None):
    """A run's property as printed: from its own properties, its character style, its paragraph's style, then the
    document's defaults."""
    return next((v for v in (_value(l, tag, attrs) for l in layers) if v is not None), False if tag in TOGGLES else "")


def _own_runs(p):
    """p's runs in order, not a text box's (they sit inside p too)."""
    return [r for r in p.iter(R) if next(r.iterancestors(P)) is p]


def _run_text(r):
    """What a run prints, a tab or a break as \\t or \\n."""
    return "".join((c.text or "") if TEXT[c.tag] is None else TEXT[c.tag] for c in r if c.tag in TEXT)


def _pstyles(p, st):
    """p's paragraph style and the styles it's based on."""
    return _chain(st, _val(p.find(qn("w:pPr")), qn("w:pStyle")) or st["para"])


def _layers(r, st, pstyles):
    """The run properties that decide how r prints, nearest first: its own, its character style's, its paragraph
    style's (pstyles), the document's defaults."""
    rpr = r.find(qn("w:rPr"))
    return ([rpr] + [s.find(qn("w:rPr")) for s in _chain(st, _val(rpr, qn("w:rStyle")))]
            + [s.find(qn("w:rPr")) for s in pstyles] + [st["defaults"]])


def _read(p, st):
    """One paragraph -> {"el", "chars": [(character, bold)] with its spaces run together and without a typed sign,
    "plain" (their text), "sign" (the typed sign and the space after it, as written), "list" (a list item), "fixed"
    (it holds what a rewrite would lose: LOCKED, a tab or a break inside its text), "looks" (its runs' styles, bold
    aside), "section" (it ends a section: Word keeps the break in its w:pPr, so moving it would move the break)}."""
    ppr = p.find(qn("w:pPr"))
    pstyles = _pstyles(p, st)
    raw, looks = [], set()
    for r in _own_runs(p):
        layers = _layers(r, st, pstyles)
        text = _run_text(r)
        if text.strip():
            looks.add(tuple(_look(layers, t, a) for t, a in LOOKS))
        bold = _look(layers, "b")
        raw += [(c, bold) for c in text]
    m = SIGN.match("".join(c for c, _ in raw))
    sign = m.group(0) if m else ""
    rest = raw[len(sign):]
    chars = []
    for c, b in rest:
        if not c.isspace():
            chars.append((c, b))
        elif chars and chars[-1][0] != " ":
            chars.append((" ", b))
    while chars and chars[-1][0] == " ":
        chars.pop()
    inner = "".join(c for c, _ in rest).strip()
    num = _val(ppr, f"{qn('w:numPr')}/{qn('w:numId')}")
    for s in pstyles if num is None else []:
        num = _val(s.find(qn("w:pPr")), f"{qn('w:numPr')}/{qn('w:numId')}")
        if num is not None:
            break
    return {"el": p, "chars": chars, "plain": "".join(c for c, _ in chars), "sign": sign,
            "list": num not in (None, "0"),            # numId 0 turns a style's numbering off
            "fixed": any(e.tag in LOCKED for e in p.iter()) or "\t" in inner or "\n" in inner, "looks": looks,
            "section": ppr is not None and ppr.find(qn("w:sectPr")) is not None}


def _group(chars):
    """[(character, bold)] -> [(text, bold)], a run per change of bold."""
    out = []
    for c, b in chars:
        if out and out[-1][1] == b:
            out[-1] = (out[-1][0] + c, b)
        else:
            out.append((c, b))
    return out


def _text(chars):
    return _marked(_group(chars)).strip()


def _side_by_side(els):
    """Whether these paragraphs stand next to each other under one parent (the body or a table cell), in this order,
    with nothing between them: only then can they swap places as whole w:p elements."""
    parent = els[0].getparent()
    if any(e.getparent() is not parent for e in els):
        return False
    first = parent.index(els[0])
    return all(parent.index(e) == first + n for n, e in enumerate(els))


def _claim(keys, used, k, start):
    """The first paragraph from start on whose whole text has key k and that no other piece claimed, else the first
    from the top; -1 if none."""
    for n in [*range(start, len(keys)), *range(min(start, len(keys)))]:
        if n not in used and keys[n] == k:
            return n
    return -1


def locate(document, pieces):
    """Find the confirmed pieces (keep_style.confirm) in a python-docx document. -> the doc's pieces (see find), each
    one's paragraph kept as its place in paragraphs() under "_at". Bullets come first, each job's searched forward
    from where the last one ended, as style_pdf.read does; then the headline, summary and skill lines, on paragraphs
    no bullet holds."""
    st = _styles(document)
    paras = [dict(_read(p, st), at=n) for n, p in enumerate(paragraphs(document))]
    full = [x for x in paras if key(x["plain"])]        # paragraphs with words: a piece can be found only on them
    keys = [key(x["plain"]) for x in full]
    used = set()
    out = {"headline": None, "summary": None, "jobs": [], "skills": [], "skills_move": False}
    at = 0
    for ji, job in enumerate(pieces.get("jobs") or []):
        found = []
        for bi, text in enumerate(job.get("bullets") or []):
            k = key(text)
            n = _claim(keys, used, k, at) if len(k) >= 3 else -1
            if n < 0:
                continue
            used.add(n)
            at, x = n + 1, full[n]
            # without numbering or a typed sign, a paragraph isn't a list item: it may be a sentence of some other part
            found.append({"id": f"r{ji}b{bi}", "text": _text(x["chars"]), "piece": text,
                          "fixed": x["fixed"] or len(x["looks"]) > 1 or not (x["list"] or x["sign"]),
                          "_at": x["at"], "_sign": x["sign"]})
        if found:
            out["jobs"].append({"id": f"r{ji}", **{k: job.get(k, "") for k in ("title", "company", "start", "end")},
                                "reorder": not any(b["fixed"] or paras[b["_at"]]["section"] for b in found)
                                and _side_by_side([paras[b["_at"]]["el"] for b in found]),
                                "bullets": found})
    # headline: the topmost paragraph that reads exactly as it, and never a job's own title line: each job's title it
    # holds must show again below it (a reading can give a job's title as the headline when the header has none)
    k = key(pieces.get("headline"))
    n = _claim(keys, used, k, 0) if len(k) >= 3 else -1
    titles = Counter(key(j.get("title")) for j in pieces.get("jobs") or [])
    below = lambda t: sum(t in keys[m] for m in range(n + 1, len(keys)) if m not in used)
    if n >= 0 and all(below(t) >= c for t, c in titles.items() if len(t) >= 3 and t in k):
        used.add(n)
        x = full[n]
        out["headline"] = {"text": _text(x["chars"]).replace("**", ""), "_at": x["at"],
                           "fixed": x["fixed"] or len(x["looks"]) > 1 or x["list"] or bool(x["sign"])}
    # summary: one paragraph, or several in a row (a list isn't a paragraph); one new text can't go back into several
    # paragraphs without changing how many there are, so a summary over several stays as written
    starts, pos = [], 0
    for kk in keys:
        starts.append(pos)
        pos += len(kk)
    by_start = {s: m for m, s in enumerate(starts)}
    by_end = {s + len(kk): m for m, (s, kk) in enumerate(zip(starts, keys))}
    k = key(pieces.get("summary"))
    i = _spot("".join(keys), by_start, by_end, used, k, 0) if len(k) >= 8 else -1
    if i >= 0:
        span = range(by_start[i], by_end[i + len(k)] + 1)
        used.update(span)
        xs = [full[m] for m in span]
        chars = [c for m, x in enumerate(xs) for c in [(" ", False)] * bool(m) + x["chars"]]
        out["summary"] = {"text": _text(chars), "_at": [x["at"] for x in xs],
                          "fixed": any(x["fixed"] or x["list"] or x["sign"] for x in xs)
                          or len(set().union(*(x["looks"] for x in xs))) > 1 or len(xs) > 1}
    # skill lines: "Label: a, b, c" paragraphs, by their letters alone (key() keeps the ":" and "," between them)
    loose = lambda t: re.sub(r"\W", "", key(t))
    lkeys = [loose(x["plain"]) for x in full]
    lines, at = [], 0
    for line in pieces.get("skills") or []:
        label, items = str(line.get("label") or ""), [str(t) for t in line.get("items") or []]
        k = loose(label + "".join(items))
        n = _claim(lkeys, used, k, at) if label and len(items) >= 2 and len(k) >= 3 else -1
        if n < 0:
            continue
        used.add(n)
        at, x = n + 1, full[n]
        lines.append(_skill_line(x, label, items))
    out["skills"] = [dict(l, id=f"s{m}") for m, l in enumerate(sorted(lines, key=lambda l: l["_at"]))]
    out["skills_move"] = (len(out["skills"]) >= 2
                          and not any(l["fixed"] or paras[l["_at"]]["section"] for l in out["skills"])
                          and _side_by_side([paras[l["_at"]]["el"] for l in out["skills"]]))
    return out


def _skill_line(x, label, items):
    """A skill paragraph -> {"label", "items" (as printed), "fixed", "sep" (what sets the items apart), "_at",
    "_sign", "_head" and "_tail" (what's printed before the first item and after the last, with **bold**), "_bold"
    (the items are bold)}. Fixed when the items aren't all set apart by the same separator, only some of them are
    bold, or the paragraph is (see _read)."""
    at = _skill_spans(x["plain"], label, items)
    base = {"_at": x["at"], "_sign": x["sign"]}
    if not at:
        return {"label": label, "items": list(items), "fixed": True, "sep": "", **base}
    got_label, got_items, seps = _skill_parts(x["plain"], label, items)
    bold = {b for a, z in at[1:] for c, b in x["chars"][a:z] if not c.isspace()}
    return {"label": got_label, "items": got_items, "sep": seps[0],
            "fixed": x["fixed"] or len(x["looks"]) > 1 or len(set(seps)) != 1 or len(bold) > 1,
            "_head": _marked(_group(x["chars"][:at[1][0]])), "_tail": _marked(_group(x["chars"][at[-1][1]:])),
            "_bold": True in bold, **base}


TIMEOUT = 90                     # seconds LibreOffice gets for one PDF
SANDBOX = "TEAMBID_DOCX_SANDBOX"   # "docker" (on GitHub Actions): LibreOffice runs only in a throwaway container
SAFE_XML = etree.XMLParser(resolve_entities=False, no_network=True)     # an upload's own XML: no entities, no fetching


def _soffice():
    return shutil.which("soffice") or shutil.which("libreoffice")


def available():
    """Whether a .docx can be built here: LibreOffice is installed and, on GitHub Actions, its sandbox is on."""
    if not _soffice():
        return False
    if os.environ.get(SANDBOX) == "docker":
        return bool(shutil.which("docker"))
    return os.environ.get("GITHUB_ACTIONS") != "true"


def _env():
    """The environment LibreOffice (or docker, which starts it) runs with: only what it needs to find itself, never
    the run's secrets (Claude key, GitHub token, site password), since the file it opens is someone's upload."""
    return {k: v for k, v in os.environ.items() if k in ENV_KEEP}


def _soffice_cmd(exe, name, out_dir):
    """-> (command, host time limit) for LibreOffice's PDF of out_dir/<name>.docx. In the cloud (TEAMBID_DOCX_SANDBOX=
    docker) it runs in a throwaway container with no network that sees the host's programs and fonts read-only and
    nothing writable but out_dir: a Word file can link other files and pages, and LibreOffice may follow the links.
    timeout inside the container ends LibreOffice there too: the host's limit only stops the docker client."""
    if os.environ.get(SANDBOX) != "docker":
        if os.environ.get("GITHUB_ACTIONS") == "true":
            # doc-tools/action.yml arms the sandbox before anything that can fail; if it's still off here, something
            # upstream broke, and a GitHub Actions runner must never open a member's upload directly
            raise RuntimeError("LibreOffice only runs inside the Docker sandbox on GitHub Actions, and it isn't on")
        work = out_dir.absolute()
        # a profile of its own: a LibreOffice already open on this computer would take the job, or hold its lock
        return [exe, "--headless", "--norestore", f"-env:UserInstallation={(work / '.libreoffice').as_uri()}",
                "--convert-to", "pdf", "--outdir", str(work), str(work / f"{name}.docx")], TIMEOUT
    if not shutil.which("docker"):
        raise RuntimeError("Docker isn't available here for the LibreOffice sandbox")
    return ["docker", "run", "--rm", "--network", "none", "--user", f"{os.getuid()}:{os.getgid()}",
            "-v", "/usr:/usr:ro", "-v", "/etc/fonts:/etc/fonts:ro", "-v", "/usr/share/fonts:/usr/share/fonts:ro",
            # Ubuntu's sofficerc (and the rest of LibreOffice's setup) is a link into /etc/libreoffice
            "-v", "/etc/libreoffice:/etc/libreoffice:ro",
            "-v", f"{out_dir.absolute()}:/work", "-e", "HOME=/tmp", "--tmpfs", "/tmp", "ubuntu:24.04",
            "timeout", "-s", "KILL", str(TIMEOUT),
            "soffice", "--headless", "--norestore", "--convert-to", "pdf", "--outdir", "/work", f"/work/{name}.docx"
            ], TIMEOUT + 15                      # + container start-up


def to_pdf(docx_path, out_dir):
    """LibreOffice's PDF of a .docx -> (pdf path, pages). The file is copied into out_dir (all a sandboxed LibreOffice
    sees) as resume.docx, a name that's safe on any command line. Raises RuntimeError with a plain message when
    LibreOffice isn't installed, its sandbox is off on GitHub Actions or has no Docker, it takes longer than 90 s, or
    it makes no PDF: then the member gets the RenderCV resume."""
    exe = _soffice()
    if not exe:
        raise RuntimeError("LibreOffice isn't installed here, so a Word resume can't be built")
    out_dir, name = Path(out_dir), "resume"
    cmd, limit = _soffice_cmd(exe, name, out_dir)       # fails closed before the upload is even copied
    out_dir.mkdir(parents=True, exist_ok=True)
    src = out_dir / f"{name}.docx"
    if Path(docx_path).absolute() != src.absolute():
        shutil.copyfile(docx_path, src)
    try:
        r = subprocess.run(cmd, cwd=out_dir, env=_env(), capture_output=True, text=True, errors="replace",
                           timeout=limit)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"LibreOffice took longer than {TIMEOUT} s") from None
    except OSError as e:
        raise RuntimeError(f"LibreOffice didn't start: {e}") from None
    pdf = out_dir / f"{name}.pdf"
    if r.returncode or not pdf.exists():
        said = " / ".join([l for l in (r.stdout + r.stderr).splitlines() if l.strip()][-3:])[:300]
        raise RuntimeError("LibreOffice made no PDF of the Word file" + (f": {said}" if said else ""))
    import fitz
    try:
        with fitz.open(pdf) as d:
            return pdf, d.page_count
    except Exception as e:
        raise RuntimeError(f"LibreOffice's PDF doesn't open: {e}") from None


def find(path, pieces):
    """The confirmed pieces found in the member's .docx, as the doc keep_style works with, in the shape
    style_tex.locate gives. "pages" is the page count of LibreOffice's PDF of the file as it is (the count to keep),
    None when LibreOffice can't make it ("_why" says why): then build can't run, keep_style.tailor doesn't ask Claude,
    and the member falls back to RenderCV."""
    doc = locate(docx.Document(str(path)), pieces)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        try:
            pages, why = to_pdf(path, Path(tmp))[1], ""
        except RuntimeError as e:
            pages, why = None, str(e)
    return {"ext": ".docx", "_path": str(path), "_pieces": pieces, "pages": pages, "_why": why, **doc}


def _new_run(rpr, text):
    """A run printing text (a tab or a break as its own element), with a copy of rpr: the properties of a run it
    stands in for."""
    r = OxmlElement("w:r")
    if rpr is not None:
        r.append(deepcopy(rpr))
    for part in re.split(r"([\t\n])", text):
        if part in ("\t", "\n"):
            r.append(OxmlElement("w:tab" if part == "\t" else "w:br"))
        elif part:
            t = OxmlElement("w:t")
            t.set(qn("xml:space"), "preserve")
            t.text = part
            r.append(t)
    return r


def _rewrite(p, st, sign, text):
    """Put text (with **bold**) in place of p's runs, after its typed sign (sign: as _read gives it), which stays as
    printed: the runs that hold only the sign are kept, and the part of the sign at the start of a run comes back in
    a run in that run's look. The plain words get a copy of the first plain run's w:rPr and the bold ones the first
    bold run's; when no run was bold all of it is plain, and when none was plain the bold run's look is the
    paragraph's. Its w:pPr and whatever else it holds (bookmarks) stay."""
    pstyles = _pstyles(p, st)
    keep, gone, lead, left, first = [], [], None, len(sign), {}
    for r in _own_runs(p):
        t = _run_text(r)
        if left and len(t) <= left:                  # all of it is (part of) the sign
            keep.append(r)
            left -= len(t)
            continue
        if left:
            lead, t, left = _new_run(r.find(qn("w:rPr")), t[:left]), t[left:], 0
        gone.append(r)
        if t.strip():
            first.setdefault(_look(_layers(r, st, pstyles), "b"), r)      # bold or not -> the first run so
    if not first:
        raise ValueError("a paragraph to reword in the Word file holds no words")
    rpr = {b: r.find(qn("w:rPr")) for b, r in first.items()}
    plain = rpr[False] if False in rpr else rpr[True]
    parts = text.split("**") if True in rpr and text.count("**") % 2 == 0 else [text.replace("**", "")]
    new = [lead] * (lead is not None) + [_new_run(rpr[True] if i % 2 else plain, s) for i, s in enumerate(parts) if s]
    # the new runs go where the old ones began: before the first one's place in p, or past it when that's a wrapper
    # (a smart tag) that also holds the kept sign
    top = gone[0]
    while top.getparent() is not p:
        top = top.getparent()
    at = p.index(top) + any(top in k.iterancestors() for k in keep)
    for n, r in enumerate(new):
        p.insert(at + n, r)
    for r in gone:
        parent = r.getparent()
        parent.remove(r)
        while parent is not p and all(str(c.tag).endswith("Pr") for c in parent):       # a wrapper left empty
            up = parent.getparent()
            up.remove(parent)
            parent = up


def _changes(doc, plan):
    """The paragraphs build rewords: [(the piece's name, its place in paragraphs(), the text it has, the new text)].
    Only pieces that aren't fixed and get a really new text; a summary only when it's one paragraph (a summary over
    several is fixed), and a skill line's items only in an order of the same items."""
    out = []
    for j in doc["jobs"]:
        for b in j["bullets"]:
            new = (plan.get("text") or {}).get(b["id"])
            if new and not b["fixed"] and new != b["text"]:
                out.append((b["id"], b["_at"], b["text"], new))
    s, h = doc.get("summary"), doc.get("headline")
    if plan.get("summary") and s and not s["fixed"] and len(s["_at"]) == 1 and plan["summary"] != s["text"]:
        out.append(("summary", s["_at"][0], s["text"], plan["summary"]))
    if plan.get("headline") and h and not h["fixed"] and plan["headline"] != h["text"]:
        out.append(("headline", h["_at"], h["text"], plan["headline"]))
    for line in doc["skills"]:
        order = list((plan.get("skills") or {}).get(line["id"]) or [])
        if line.get("fixed") or not order or order == line["items"] \
                or sorted(map(key, order)) != sorted(map(key, line["items"])):
            continue
        printed = {key(t): t for t in line["items"]}
        shown = lambda items: line["_head"] + line["sep"].join(
            f"**{t}**" if line["_bold"] else t for t in items) + line["_tail"]
        out.append((line["id"], line["_at"], shown(line["items"]), shown(printed[key(t)] for t in order)))
    return out


def _moves(doc, plan):
    """The paragraphs build moves: [(the places of paragraphs side by side, the same places in their new order)], for
    each job that may be reordered and the skill lines when they may move, where the plan orders them anew."""
    out = []
    groups = [(j["bullets"], (plan.get("order") or {}).get(j["id"])) for j in doc["jobs"] if j["reorder"]]
    if doc.get("skills_move"):
        groups.append((doc["skills"], plan.get("skill_lines")))
    for pieces, order in groups:
        ids, at = [x["id"] for x in pieces], {x["id"]: x["_at"] for x in pieces}
        order = [str(i) for i in order or []]
        if sorted(order) == sorted(ids) and order != ids:
            out.append(([at[i] for i in ids], [at[i] for i in order]))
    return out


def _on_pages(k, pages):
    """Whether key k reads in the PDF: on one page, or run over onto the next ones (a page's footer and the next
    one's header can come between its parts). pages: each page's key."""
    def longest(rest, page):              # the longest start of rest on the page (a start of a start is there too)
        lo, hi = 0, len(rest)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            lo, hi = (mid, hi) if rest[:mid] in page else (lo, mid - 1)
        return lo
    for start in range(len(pages)):
        rest = k
        for page in pages[start:]:
            if rest in page:
                return True
            cut = longest(rest, page)
            if not cut:
                break
            rest = rest[cut:]
    return False


def _unread(pdf, changes, document):
    """The names of the changes the built PDF doesn't read back: its new text isn't there, or its old text still is,
    where nothing else in the file (the new text included, a page header) holds that text."""
    import fitz
    with fitz.open(pdf) as d:
        pages = [key(p.get_text().replace("\xad", "")) for p in d]          # a soft hyphen at a line's end
    held = []
    for part in document.part.package.iter_parts():
        root = getattr(part, "element", None)              # the parts python-docx reads; the others' XML, if any
        if root is None and part.content_type.endswith("xml"):
            try:
                root = etree.fromstring(part.blob, SAFE_XML)
            except etree.XMLSyntaxError:
                continue
        if root is not None:
            held += [t.text or "" for t in root.iter(qn("w:t"), qn("w:delText"))]
    held, whole = key("".join(held)), "".join(pages)
    return [name for name, _, old, new in changes
            if not _on_pages(key(new), pages) or (key(old) not in held and key(old) in whole)]


def _paper(pdf):
    import fitz
    with fitz.open(pdf) as d:
        return "A4" if abs(d[0].rect.width - 595) < 6 else "Letter"


def build(doc, plan, folder, base):
    """Write the tailored .docx and its PDF into folder. -> {"pdf", "docx" (the member's own file, edited: the
    results page's DOCX download), "pages", "paper"}. The file is opened afresh (find's reading is never written
    back) and each piece's paragraph found again by its place; only the reworded paragraphs' runs change, and the
    paragraphs that move move whole. Raises ValueError when a paragraph isn't the one read, or the PDF doesn't read
    back as written (RuntimeError when LibreOffice fails): then the member gets the RenderCV resume."""
    document = docx.Document(doc["_path"])
    st, ps = _styles(document), paragraphs(document)
    changes = _changes(doc, plan)
    for name, at, old, new in changes:
        x = _read(ps[at], st)
        if key(x["plain"]) != key(old):
            raise ValueError(f"the Word file's paragraph for {name} isn't the one that was read")
        _rewrite(ps[at], st, x["sign"], new)
    for places, order in _moves(doc, plan):
        els = [ps[n] for n in places]
        if not _side_by_side(els):
            raise ValueError("the Word file's paragraphs to reorder aren't side by side")
        parent = els[0].getparent()
        first = parent.index(els[0])
        for e in els:
            parent.remove(e)
        for n, at in enumerate(order):
            parent.insert(first + n, ps[at])
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    out, pdf = folder / f"{base}.docx", folder / f"{base}.pdf"
    document.save(str(out))
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            built, pages = to_pdf(out, Path(tmp))
            bad = _unread(built, changes, document)
            if bad:
                raise ValueError(f"the tailored Word file's PDF didn't read back as written ({', '.join(bad[:4])})")
            shutil.copy(built, pdf)
    except Exception:
        out.unlink(missing_ok=True)              # the RenderCV resume is used instead: no stale tailored file
        raise
    return {"pdf": str(pdf), "docx": str(out), "pages": pages, "paper": _paper(pdf)}

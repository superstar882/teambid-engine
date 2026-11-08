"""Tailor a member's own Word resume in place: find the pieces in its paragraphs, put the new text back, build the PDF
with LibreOffice.

Reading (find): every paragraph of the body in reading order, table cells (nested too) included, never the headers,
footers or text boxes. A paragraph's text is its runs' text (a tab or a line break reads as a space), with **bold** on
the runs printed in bold. A bullet is the whole text of one paragraph that is a list item (numbering set on it or by
its style) or starts with a typed sign, which isn't part of its text; the headline, summary and skill lines are matched
whole on their paragraphs too. A piece not found whole isn't in the doc, and stays as written. Safety: a paragraph with
a link, a field, a tracked change, a picture, a text box, a tab or break inside its text, or runs in more than one style
beyond bold is fixed (never reworded); a job's bullets, or the skill lines, move only when none is fixed and their
paragraphs stand side by side under one parent, with nothing between them.
Design: docs/superpowers/specs/2026-11-05-keep-original-style-design.md (.docx)
"""
import re
import tempfile
from collections import Counter
from pathlib import Path

import docx
from docx.oxml.ns import qn

from .style_pdf import BULLETS, _marked, _skill_parts, _skill_spans, _spot
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


def _read(p, st):
    """One paragraph -> {"el", "chars": [(character, bold)] with its spaces run together and without a typed sign,
    "plain" (their text), "sign" (the typed sign and the space after it, as written), "list" (a list item), "fixed"
    (it holds what a rewrite would lose: LOCKED, a tab or a break inside its text), "looks" (its runs' styles, bold
    aside)}."""
    ppr = p.find(qn("w:pPr"))
    pstyles = _chain(st, _val(ppr, qn("w:pStyle")) or st["para"])
    raw, looks = [], set()
    for r in p.iter(R):
        if next(r.iterancestors(P)) is not p:
            continue                                  # a text box's own run
        rpr = r.find(qn("w:rPr"))
        layers = ([rpr] + [s.find(qn("w:rPr")) for s in _chain(st, _val(rpr, qn("w:rStyle")))]
                  + [s.find(qn("w:rPr")) for s in pstyles] + [st["defaults"]])
        text = "".join((c.text or "") if TEXT[c.tag] is None else TEXT[c.tag] for c in r if c.tag in TEXT)
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
            "fixed": any(e.tag in LOCKED for e in p.iter()) or "\t" in inner or "\n" in inner, "looks": looks}


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
                                "reorder": not any(b["fixed"] for b in found)
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
    # summary: one paragraph, or several in a row (a list isn't a paragraph)
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
                          or len(set().union(*(x["looks"] for x in xs))) > 1
                          or not _side_by_side([x["el"] for x in xs])}
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
    out["skills_move"] = (len(out["skills"]) >= 2 and not any(l["fixed"] for l in out["skills"])
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


def to_pdf(docx_path, out_dir):
    """LibreOffice's PDF of a .docx -> (pdf path, pages). The sandboxed converter comes with build; until then no
    .docx can be built here, and the member gets the RenderCV resume."""
    raise RuntimeError("LibreOffice isn't available here, so a Word resume can't be built")


def find(path, pieces):
    """The confirmed pieces found in the member's .docx, as the doc keep_style works with, in the shape
    style_tex.locate gives. "pages" is the page count of LibreOffice's PDF of the file as it is (the count to keep),
    None when LibreOffice isn't available: then build can't run, and the member falls back to RenderCV."""
    doc = locate(docx.Document(str(path)), pieces)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        try:
            pages = to_pdf(path, Path(tmp))[1]
        except RuntimeError:
            pages = None
    return {"ext": ".docx", "_path": str(path), "_pieces": pieces, "pages": pages, **doc}

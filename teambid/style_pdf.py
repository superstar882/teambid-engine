"""Tailor a member's own resume PDF in place: each job's bullets are reworded and reordered where they stand.

Reading: the text lines (with every letter's position) and the bullet signs (inside the line, a separate one-character
line, or a small drawn dot) give each confirmed bullet its lines. Laying out: a bullet that only moves keeps its own
lines, each word (or letter) at its original x; a reworded one wraps anew in the job's width; each job flows through
its own lines and page breaks. Fonts: the PDF's own font when it measures and reads back the letters as the original
did, else the same family installed online (or a metric-compatible one), else a wide-coverage font. Safety: a job is
reordered only when every bullet was found whole with its own sign and none holds a link; links are put back after
erasing; every redrawn bullet must read back as its text, or the build fails (and the RenderCV resume is used).
Bullets only for now: the headline, summary and skills of a PDF stay as they are.
Design: docs/superpowers/specs/2026-11-05-keep-original-style-design.md (PDF in place).
"""
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path
from statistics import median

from .style_text import key

BULLETS = set("•●▪◦‣∙·-–—*►➤✓✔○■□➢❖")
SANS = re.compile(r"(?i)helvetica|arial|nimbussan|liberationsans|calibri|carlito|roboto|inter|dejavusans|poppins|"
                  r"rubik|opensans|lato|sourcesans|segoe|verdana|tahoma|montserrat|sans")
LIGATURES = re.compile("[ﬀ-ﬆ]")
MIN_SPACE = 0.7          # justified text may squeeze its spaces this far, about as much as LaTeX does
FALLBACK = "DejaVu Sans"  # wide coverage (≈ → € ' ...), on every Ubuntu runner
# a PDF's font family -> the family to look for when the PDF's own copy can't be used (metric-compatible where it exists)
ALIAS = {"calibri": "Carlito", "cambria": "Caladea", "arial": "Liberation Sans", "helvetica": "Liberation Sans",
         "nimbussanl": "Liberation Sans", "nimbussans": "Liberation Sans", "times": "Liberation Serif",
         "timesnewroman": "Liberation Serif", "nimbusromno9l": "Liberation Serif", "couriernew": "Liberation Mono",
         "liberationsans": "Liberation Sans", "liberationserif": "Liberation Serif", "dejavusans": "DejaVu Sans",
         "opensans": "Open Sans", "sourcesanspro": "Source Sans Pro"}


def _fitz():
    import fitz
    return fitz


def _is_sign(text):
    t = text.strip()
    return bool(t) and all(c in BULLETS for c in t)


def _is_bold(span):
    return bool(span["flags"] & 16) or bool(re.search(r"(?i)bold|black|heavy|semi-?bold|demi", span["font"]))


def _plain(text):
    """Ligature characters spelled out (ﬁ -> fi): fonts other than the original may not have them, and ATS read fi."""
    return LIGATURES.sub(lambda m: unicodedata.normalize("NFKC", m.group(0)), text)


def family(name):
    """'ABCDEF+Calibri-Bold' -> 'Calibri', 'Roboto,Bold' -> 'Roboto', 'ArialMT' -> 'Arial'."""
    base = re.split(r"[-,]", (name or "").split("+")[-1])[0]
    return re.sub(r"(MT|PS)$", "", base)


def system_font(name, bold):
    """An installed font file of this family (or its metric-compatible stand-in), via fontconfig; None if none."""
    fam = family(name)
    want = ALIAS.get(fam.replace(" ", "").lower(), fam)
    if not want or not shutil.which("fc-match"):
        return None
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}\n%{family}", f"{want}:weight={200 if bold else 80}"],
                             capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return None
    path, _, families = out.partition("\n")
    return path if path and want.replace(" ", "").lower() in families.replace(" ", "").lower() else None


def _roundtrip(buf, chars):
    """The characters this font draws AND reads back as themselves once re-embedded."""
    fitz = _fitz()
    chars = sorted(chars)
    d = fitz.open()
    p = d.new_page(width=40 * (len(chars) + 2), height=60)
    p.insert_font(fontname="F0", fontbuffer=buf)
    for n, c in enumerate(chars):
        p.insert_text((10 + n * 30, 40), c, fontname="F0", fontsize=12)
    got = [ch["c"] for b in p.get_text("rawdict")["blocks"] for l in b.get("lines", []) for s in l["spans"]
           for ch in s["chars"] if not ch["c"].isspace()]
    return {c for c, g in zip(chars, got) if c == g} if len(got) == len(chars) else set()


class Fonts:
    """Picks the font each piece of text is drawn with, and remembers what it learned."""

    def __init__(self, doc, lines, allow_embedded=True):
        self.doc, self.lines, self.allow = doc, lines, allow_embedded
        self.cache, self.good, self.trust = {}, {}, {}

    def _own(self, page_no, name):
        base = name.split("+")[-1]
        if base not in self.cache:
            self.cache[base] = None
            for f in self.doc[page_no].get_fonts():
                if f[3].split("+")[-1] == base:
                    try:
                        _, ext, _, buf = self.doc.extract_font(f[0])
                        if buf and ext not in ("n/a", ""):
                            self.cache[base] = (_fitz().Font(fontbuffer=buf), buf, f"tb{f[0]}")
                    except Exception:
                        pass
                    break
        return self.cache[base]

    def _trusted(self, name, font):
        """The PDF's own font measures its letters as the PDF placed them (some generators embed fonts whose widths
        disagree with how they were printed: then every redraw would come out unevenly spaced)."""
        base = name.split("+")[-1]
        if base not in self.trust:
            errs = []
            for l in self.lines:
                for s in l["spans"]:
                    if s["font"].split("+")[-1] != base:
                        continue
                    for a, b in zip(s["chars"], s["chars"][1:]):
                        if not a["c"].isspace() and not b["c"].isspace():
                            errs.append(abs(b["origin"][0] - a["origin"][0] - font.text_length(a["c"], fontsize=s["size"])))
                    if len(errs) > 400:
                        break
            self.trust[base] = bool(errs) and sum(e <= 0.35 for e in errs) >= 0.9 * len(errs)
        return self.trust[base]

    def own(self, page_no, name, text):
        """The PDF's own font for text, when it's trusted and draws and reads back every character; else None."""
        if not self.allow or not name or LIGATURES.search(text):
            return None            # a re-embedded font's ligature glyphs read back right but may not draw right
        f = self._own(page_no, name)
        if not f or not self._trusted(name, f[0]):
            return None
        chars = {c for c in text if not c.isspace()}
        good, bad = self.good.setdefault(name.split("+")[-1], (set(), set()))
        todo = chars - good - bad
        if todo:
            ok = _roundtrip(f[1], {c for c in todo if f[0].has_glyph(ord(c))})
            good.update(ok)
            bad.update(todo - ok)
        return f if chars <= good else None

    def installed(self, name, bold, text):
        path = system_font(name, bold)
        if not path:
            return None
        if path not in self.cache:
            buf = Path(path).read_bytes()
            self.cache[path] = (_fitz().Font(fontbuffer=buf), buf, f"tbs{len(self.cache)}")
        f = self.cache[path]
        return f if all(f[0].has_glyph(ord(c)) for c in text if not c.isspace()) else None

    def pick(self, page_no, name, text, bold, own=True):
        """(fitz.Font, font file bytes or None, font name to draw with, is it the PDF's own font) for text."""
        f = self.own(page_no, name, text) if own else None
        if f:
            return f + (True,)
        f = self.installed(name, bold, _plain(text)) or self.installed(FALLBACK, bold, _plain(text))
        if f:
            return f + (False,)
        b14 = ("hebo" if bold else "helv") if SANS.search(name or "") else ("tibo" if bold else "tiro")
        return (_fitz().Font(b14), None, b14, False)


def _lines(doc):
    fitz = _fitz()
    out = []
    for pno, page in enumerate(doc):
        links = [l["from"] for l in page.get_links()]
        for b in page.get_text("rawdict")["blocks"]:
            for l in b.get("lines", []):
                for s in l["spans"]:
                    s["text"] = "".join(c["c"] for c in s["chars"])
                spans = [s for s in l["spans"] if s["text"]]
                if spans:
                    r = fitz.Rect(l["bbox"])
                    out.append({"page": pno, "bbox": r, "spans": spans, "text": "".join(s["text"] for s in spans),
                                "link": any(r.intersects(k) for k in links)})
    return out


def _marks(doc, lines):
    """Bullet signs that aren't part of their text line: separate one-character lines, and small drawn dots."""
    marks = [{"page": l["page"], "rect": l["bbox"], "kind": "text", "span": l["spans"][0]} for l in lines if _is_sign(l["text"])]
    for pno, page in enumerate(doc):
        for dr in page.get_drawings():
            r = dr["rect"]
            if dr.get("fill") and 0.8 < r.width < 8 and 0.8 < r.height < 8 and abs(r.width - r.height) < 1.5:
                marks.append({"page": pno, "rect": r, "fill": dr["fill"],
                              "kind": "circle" if all(i[0] == "c" for i in dr["items"]) else "rect"})
    return marks


def read(doc, pieces):
    """The confirmed bullets (keep_style.confirm) found in the PDF, by job.
    -> [{"id", "reorder", "bullets": [{"id", "text" (with **bold**), "piece", "lines", "mark", "link", "fixed"}], "_lines"}]
    A bullet is found only when it starts and ends exactly on line boundaries; anything else stays as it is."""
    lines = _lines(doc)
    marks = _marks(doc, lines)
    text_lines = [l for l in lines if not _is_sign(l["text"])]
    keys = [key(l["text"]) for l in text_lines]
    starts, pos = [], 0
    for k in keys:
        starts.append(pos)
        pos += len(k)
    by_start = {s: n for n, s in enumerate(starts)}
    by_end = {s + len(k): n for n, (s, k) in enumerate(zip(starts, keys))}
    hay = "".join(keys)
    jobs, at = [], 0
    for ji, job in enumerate(pieces.get("jobs", [])):
        found = []
        for bi, text in enumerate(job.get("bullets", [])):
            k = key(text)
            if len(k) < 8:
                continue
            i = hay.find(k, at)
            if i < 0:
                i = hay.find(k)
            if i < 0 or i not in by_start or i + len(k) not in by_end:
                continue
            ls = text_lines[by_start[i]:by_end[i + len(k)] + 1]
            at = i + len(k)
            mark, sp0 = None, ls[0]["spans"][0]
            if _is_sign(sp0["text"]):
                mark = {"kind": "inline", "span": sp0}
            else:
                lb = ls[0]["bbox"]
                for m in marks:
                    cy = (m["rect"].y0 + m["rect"].y1) / 2
                    if m["page"] == ls[0]["page"] and lb.y0 - 1 <= cy <= lb.y1 + 1 and m["rect"].x1 <= lb.x0 + 1 \
                            and lb.x0 - m["rect"].x1 < 25:
                        mark = m
                        break
            runs, first = [], None
            for l in ls:
                for s in l["spans"]:
                    if mark and mark["kind"] == "inline" and s is mark["span"]:
                        continue
                    first = first or s
                    runs.append((s["text"], _is_bold(s)))
                runs.append((" ", False))
            shown = "".join(f"**{t.strip()}**{' ' if t.endswith(' ') else ''}" if b and t.strip() else t for t, b in runs)
            shown = re.sub(r"\*\*(\s*)\*\*", r"\1", re.sub(r"\s+", " ", shown)).strip()
            spans = [s for l in ls for s in l["spans"] if s["text"].strip() and not _is_sign(s["text"])]
            styled = any(s["flags"] & 2 or abs(s["size"] - first["size"]) > 0.6 or s["color"] != first["color"] for s in spans)
            found.append({"id": f"r{ji}b{bi}", "text": shown, "piece": text, "lines": ls, "mark": mark,
                          "link": any(l["link"] for l in ls), "fixed": styled or any(l["link"] for l in ls)})
        if found:
            reorder = all(b["mark"] for b in found) and not any(b["link"] for b in found)
            jobs.append({"id": f"r{ji}", "bullets": found, "reorder": reorder, "_lines": lines})
    return jobs


def find(path, pieces):
    """The confirmed pieces found in the member's PDF, as the doc keep_style works with (bullets only for now)."""
    fitz = _fitz()
    with fitz.open(path) as d:
        jobs, pages = read(d, pieces), d.page_count
    meta = pieces.get("jobs", [])
    return {"ext": ".pdf", "_path": str(path), "_pieces": pieces, "pages": pages, "headline": None, "summary": None,
            "skills": [], "skills_move": False,
            "jobs": [{"id": j["id"], "reorder": j["reorder"],
                      **{k: meta[int(j["id"][1:])].get(k, "") for k in ("title", "company", "start", "end")},
                      "bullets": [{"id": b["id"], "text": b["text"], "fixed": b["fixed"], "piece": b["piece"]}
                                  for b in j["bullets"]]} for j in jobs]}

# Keep Original Style, Part 3 (bullets inside the member's PDF) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Members who uploaded a PDF, which is most of the team, get every tailored resume built inside their own PDF. Each job's bullets are reworded and reordered where they stand, and everything else in the PDF stays exactly as it was.

**Architecture:** A new handler, `teambid/style_pdf.py`, plugs into Part 1's coordinator (`keep_style.HANDLERS[".pdf"]`) with the same `find(path, pieces) -> doc` / `build(doc, plan, folder, base) -> files` interface as `style_tex`.
- **Reading:** it reads each letter's position and finds each confirmed bullet's lines and its bullet sign: inline, a separate one-character line, or a drawn dot.
- **Drawing:** it erases only those lines and redraws the job's bullets in the new order through the same space. A moved bullet keeps its exact lines. A reworded bullet wraps anew.
- **Checking:** it then reads every bullet back.

Claude's reading, the rewrite and the fact checks are unchanged from Part 1.

**Tech Stack:**
- Python 3.12, unittest
- PyMuPDF (`fitz`) 1.27: rawdict, redaction, `insert_font` and `insert_text` with morph, `subset_fonts`
- fontconfig `fc-match` and Ubuntu font packages in GitHub Actions

**Spec:** `docs/superpowers/specs/2026-11-05-keep-original-style-design.md`. Read the section "PDF in place", which was updated 2026-11-06, and "Build order". Part 1 is merged on `main` (`718c9c7`): `keep_style`, `style_tex`, `llm.read_resume`, `llm.tailor_in_place`, the checks, and `doc-tools`.

**Prototype:** the code below ran on all seven member PDFs. All 7 passed the read-back check with links kept and page counts unchanged, and page images were compared by eye. Re-running it is the last task.

## Global Constraints

- **Where it runs:** online in GitHub Actions (`ubuntu-latest`, Python 3.12). The owner's Windows PC is not a target. Tests needing `fc-match` or the online fonts skip elsewhere.
- **Privacy:** never put a real member's resume in the repo. All fixtures are fictional ("Dana Reyes"), drawn by `tests/pdf_samples.py`.
- **Scope:** bullets only. A PDF's headline, summary and skills are never changed in Part 3 (`find` returns `headline=None`, `summary=None`, `skills=[]`).
- **Outputs:** a PDF member's application gets the edited PDF only. There's no DOCX, and `docs.py` already skips missing files.
- **Every bullet stays exactly once.** A job is reordered only when none of its bullets is fixed.
- **Fixed bullets:** a bullet with a link, italics, mixed sizes or colors, or no sign of its own is never reworded, erased or redrawn.
- **Fitting:** reworded text may squeeze spaces to 70% (`MIN_SPACE = 0.7`), and only in justified jobs. A moved word in a font other than the PDF's own is fitted to its original width (scale at most 1.15, never wider than its space; below 0.6 the job isn't redrawn).
- **Trusting the PDF's own font:** 90% of its letter advances within 0.35 pt of the original, every needed character drawn and read back, and no ligature in the word.
- **Read-back check:**
  - Every redrawn bullet must read back as exactly its text's words from where it was drawn.
  - The link count must be unchanged.
  - Every other word of the PDF must be unchanged (box within 1 pt) and not drawn over.
  - Otherwise render again without the PDF's own fonts.
  - Otherwise raise `ValueError`, so the RenderCV resume is used.
- **Tests:** must never reach the real Claude API. A real key file exists on this PC, and `python tb.py test` loads it.
- **Code style:** match the repo. Flat modules, short docstrings, comments that say why, plain-sentence commit messages ("Keep style: ...").

## File Map

| File | Change | Responsibility |
|---|---|---|
| `teambid/style_pdf.py` | create | PDF handler: read lines, bullet signs and bullets; pick fonts; lay out; erase, draw and check; `find` / `build` |
| `tests/pdf_samples.py` | create | fictional resume PDFs (inline signs, drawn dots, a page break inside a bullet, a linked bullet) and their `PIECES` |
| `tests/test_style_pdf.py` | create | handler tests (Tasks 1-2) |
| `teambid/keep_style.py` | modify | `HANDLERS[".pdf"]`; drop rewordings the PDF couldn't fit from the plan and the note |
| `tests/test_keep_style.py` | modify | end-to-end `service.apply` for a PDF member |
| `.github/actions/doc-tools/action.yml` | modify | install the fonts members' PDFs use, or their metric-compatible stand-ins |

The **doc** that `style_pdf.find` returns has the same shape as Part 1's (see `teambid/keep_style.py`). It also carries the private fields `_path` and `_pieces`, which `build` re-reads:

```python
{"ext": ".pdf", "_path": "<pdf path>", "_pieces": pieces, "pages": 2, "headline": None, "summary": None,
 "skills": [], "skills_move": False,
 "jobs": [{"id": "r0", "title": "...", "company": "...", "start": "", "end": "", "reorder": True,
           "bullets": [{"id": "r0b0", "text": "plain with **bold**", "fixed": False, "piece": "<confirmed text>"}]}]}
```

---

### Task 1: Read the bullets inside a PDF

**Files:**
- Create: `teambid/style_pdf.py` (first part)
- Create: `tests/pdf_samples.py`
- Create: `tests/test_style_pdf.py`

**Interfaces:**
- Consumes: `teambid.style_text.key(text) -> str` (Part 1).
- Produces:
  - `style_pdf.family(name) -> str`
  - `style_pdf.system_font(name, bold) -> str | None`
  - `style_pdf.Fonts(doc, lines, allow_embedded=True)`, whose `.pick(page_no, name, text, bold, own=True)` returns `(fitz.Font, bytes | None, fontname, is_own)` and whose `.own(page_no, name, text)` returns `(fitz.Font, bytes, fontname) | None`
  - `style_pdf.read(doc, pieces) -> jobs`
  - `style_pdf.find(path, pieces) -> doc`
  - `tests.pdf_samples`: `make(path, sign="inline", break_page=False, link_bullet=False) -> path`, `PIECES`

- [ ] **Step 1: Create the fictional samples**

Create `tests/pdf_samples.py`:

```python
"""Fictional resume PDFs for the PDF handler tests (no real people), drawn with PyMuPDF's built-in fonts.

make(path, sign, break_page, link_bullet) draws DANA REYES's resume: a header with a mailto link, an Experience
heading, the jobs in JOBS (each bullet on two lines, **bold** words in Helvetica-Bold) and an Education heading.
PIECES is what keep_style.confirm keeps from Claude's reading of it."""
import fitz

JOBS = [
    ("Senior Backend Engineer", "Northwind Labs", [
        ("Built a payments API in **Python** and FastAPI that handles", "2M requests a day for card and bank transfers."),
        ("Cut p95 latency 40% by moving hot reads to **Redis** and", "adding a write-through cache for the ledger."),
        ("Wrote the public API docs for 12 endpoints and the", "onboarding guide used by partner banks."),
    ]),
    ("Backend Engineer", "Contoso Freight", [
        ("Moved 30 cron jobs to Airflow, ending missed nightly", "runs and cutting manual reruns to zero."),
        ("Added Go unit tests for 6 backend services, raising", "coverage to 85% across the shipping platform."),
    ]),
]
PIECES = {"headline": "", "summary": "", "skills": [],
          "jobs": [{"title": t, "company": c, "location": "", "start": "", "end": "",
                    "bullets": [f"{a} {b}".replace("**", "") for a, b in bullets]} for t, c, bullets in JOBS]}
PITCH, GAP, X_SIGN, X_TEXT = 12.5, 18.0, 52.0, 62.0
BOTTOM = 790.0


def _runs(page, x, y, text, size=10):
    helv, hebo = fitz.Font("helv"), fitz.Font("hebo")
    for n, part in enumerate(text.split("**")):
        if part:
            bold = n % 2 == 1
            page.insert_text((x, y), part, fontname="hebo" if bold else "helv", fontsize=size)
            x += (hebo if bold else helv).text_length(part, fontsize=size)


def make(path, sign="inline", break_page=False, link_bullet=False):
    """sign: 'inline' (a Symbol-font bullet on the line) or 'circle' (a small drawn dot). break_page: the first job
    starts near the bottom of page 1 and its last bullet runs onto page 2. link_bullet: the second job's first bullet
    holds a link."""
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((50, 60), "DANA REYES", fontname="hebo", fontsize=18)
    page.insert_text((50, 80), "dana@example.com", fontname="helv", fontsize=10)
    page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(50, 71, 140, 83), "uri": "mailto:dana@example.com"})
    page.insert_text((50, 110), "Experience", fontname="hebo", fontsize=13)
    y = 708.0 if break_page else 140.0
    for ji, (title, company, bullets) in enumerate(JOBS):
        if y > BOTTOM - 40:
            page, y = doc.new_page(width=595, height=842), 60.0
        page.insert_text((50, y), f"{title}, {company}", fontname="hebo", fontsize=11)
        y += 20
        for bi, lines in enumerate(bullets):
            for n, line in enumerate(lines):
                if y > BOTTOM:
                    page, y = doc.new_page(width=595, height=842), 60.0
                if n == 0:
                    if sign == "circle":
                        page.draw_circle((X_SIGN + 1.6, y - 3.2), 1.6, color=None, fill=(0, 0, 0))
                    else:
                        page.insert_text((X_SIGN, y), "•", fontname="symb", fontsize=10)
                    if link_bullet and ji == 1 and bi == 0:
                        page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(X_TEXT, y - 9, 300, y + 3),
                                          "uri": "https://example.com/airflow"})
                _runs(page, X_TEXT, y, line)
                y += PITCH
            y += GAP - PITCH
        y += 16
    if y > BOTTOM - 20:
        page, y = doc.new_page(width=595, height=842), 60.0
    page.insert_text((50, y + 10), "Education", fontname="hebo", fontsize=13)
    doc.save(path)
    doc.close()
    return path
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_style_pdf.py`:

```python
"""Keep-original-style, PDF handler (stdlib unittest). The fixture PDFs come from tests/pdf_samples.py and use
PyMuPDF's built-in fonts, so these run anywhere; tests that need fontconfig or the online fonts skip elsewhere."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TEAMBID_WORKSPACE", tempfile.mkdtemp(prefix="teambid-test-"))
os.environ.setdefault("TEAMBID_LOCAL_AI", "off")

import fitz  # noqa: E402

from teambid import style_pdf  # noqa: E402
from teambid.style_text import key  # noqa: E402
from tests import pdf_samples as PS  # noqa: E402


def sample(**kw):
    return PS.make(str(Path(tempfile.mkdtemp()) / "dana.pdf"), **kw)


class Read(unittest.TestCase):
    def jobs(self, pieces=PS.PIECES, **kw):
        with fitz.open(sample(**kw)) as d:
            return style_pdf.read(d, pieces)

    def test_finds_every_bullet_with_its_sign(self):
        jobs = self.jobs()
        self.assertEqual([(j["id"], [b["id"] for b in j["bullets"]]) for j in jobs],
                         [("r0", ["r0b0", "r0b1", "r0b2"]), ("r1", ["r1b0", "r1b1"])])
        self.assertTrue(all(b["mark"] for j in jobs for b in j["bullets"]))
        self.assertTrue(all(j["reorder"] for j in jobs))
        self.assertEqual(jobs[0]["bullets"][0]["text"],
                         "Built a payments API in **Python** and FastAPI that handles 2M requests a day for card and bank transfers.")

    def test_drawn_dots_are_bullet_signs_too(self):
        self.assertEqual({b["mark"]["kind"] for j in self.jobs(sign="circle") for b in j["bullets"]}, {"circle"})

    def test_a_linked_bullet_pins_its_job(self):
        jobs = self.jobs(link_bullet=True)
        self.assertTrue(jobs[0]["reorder"])
        self.assertFalse(jobs[1]["reorder"])
        self.assertEqual([b["fixed"] for b in jobs[1]["bullets"]], [True, False])

    def test_only_whole_bullets_are_found(self):
        first = PS.PIECES["jobs"][0]["bullets"][0]
        # a piece that starts mid-line isn't found; one that is only the bullet's second line has no sign
        jobs = self.jobs(pieces={"jobs": [{"bullets": ["payments API in Python and FastAPI that handles"]}]})
        self.assertEqual(jobs, [])
        jobs = self.jobs(pieces={"jobs": [{"bullets": [first.split("handles ")[1]]}]})
        self.assertIsNone(jobs[0]["bullets"][0]["mark"])
        self.assertFalse(jobs[0]["reorder"])

    def test_family_names(self):
        self.assertEqual([style_pdf.family(n) for n in ("ABCDEF+Calibri-Bold", "Roboto,Bold", "ArialMT",
                                                        "Inter-Semi-Bold", "NimbusSanL-Regu")],
                         ["Calibri", "Roboto", "Arial", "Inter", "NimbusSanL"])


class Find(unittest.TestCase):
    def test_doc_shape(self):
        doc = style_pdf.find(sample(), PS.PIECES)
        self.assertEqual((doc["ext"], doc["pages"], doc["headline"], doc["summary"], doc["skills"]), (".pdf", 1, None, None, []))
        self.assertEqual((doc["jobs"][0]["title"], doc["jobs"][0]["company"]), ("Senior Backend Engineer", "Northwind Labs"))
        b = doc["jobs"][0]["bullets"][1]
        self.assertEqual(set(b), {"id", "text", "fixed", "piece"})
        self.assertEqual(b["piece"], PS.PIECES["jobs"][0]["bullets"][1])
        self.assertIn("**Redis**", b["text"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests to see them fail**

Run: `python -m unittest tests.test_style_pdf -v`
Expected: ERROR, `ImportError: cannot import name 'style_pdf' from 'teambid'`

- [ ] **Step 4: Write the first part of `teambid/style_pdf.py`**

```python
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

BULLETS = set("•●▪◦‣∙·-–—*►➤✓✔○■□➢❖")
SANS = re.compile(r"(?i)helvetica|arial|nimbussan|liberationsans|calibri|carlito|roboto|inter|dejavusans|poppins|"
                  r"rubik|opensans|lato|sourcesans|segoe|verdana|tahoma|montserrat|sans")
LIGATURES = re.compile("[ﬀ-ﬆ]")
MIN_SPACE = 0.7          # justified text may squeeze its spaces this far, about as much as LaTeX does
FALLBACK = "DejaVu Sans"  # wide coverage (≈ → € ’ ...), on every Ubuntu runner
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
```

- [ ] **Step 5: Run the tests to see them pass**

Run: `python -m unittest tests.test_style_pdf -v`
Expected: all 6 tests PASS.

- [ ] **Step 6: Commit**

```bash
git add teambid/style_pdf.py tests/pdf_samples.py tests/test_style_pdf.py
git commit -m "Keep style: find each confirmed bullet and its bullet sign inside a member's PDF"
```

---

### Task 2: Lay out, erase, draw and check: `build`

**Files:**
- Modify: `teambid/style_pdf.py` (append)
- Test: `tests/test_style_pdf.py` (append, above `if __name__`)

**Interfaces:**
- Consumes: `read`, `find`, `Fonts`, `_plain`, `_is_bold`, `_is_sign`, `MIN_SPACE` from Task 1.
- Produces: `style_pdf.build(doc, plan, folder: Path, base: str) -> {"pdf": str, "pages": int, "paper": "A4"|"Letter", "kept": [bullet ids]}`. It raises `ValueError` when the result doesn't read back. `plan` has the shape `{"order": {job_id: [ids]}, "text": {bullet_id: "new text with **bold**"}}`.

> **Final review fixes (2026-11-06), which supersede the code below where they differ.** `build` also returns `"order": {job_id: [ids as drawn]}`. A bullet with no sign of its own is fixed too, and any fixed bullet pins its job. Fixed bullets and unchanged jobs are never erased or redrawn. Erasing uses the x-height band of each line, in two passes (dots, then text with no line art). Moved words are fitted at 0.6–1.15 and never wider than their space. Rewordings that don't fit go back one at a time. The check compares word lists and checks that every other word of the PDF is unchanged and not drawn over. Typed signs ("- text") are signs. Reworded text takes the job's most common style. Signs keep their glyph (own font → DejaVu → dot → Symbol). The code is in `teambid/style_pdf.py`, the spec in "PDF in place".

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_style_pdf.py`:

```python
def words(pdf):
    with fitz.open(pdf) as d:
        return [(pg.number, w[1], w[4]) for pg in d for w in pg.get_text("words")]


def first(ws, word):
    return min((pn, y) for pn, y, t in ws if t == word)


def all_text(pdf):
    with fitz.open(pdf) as d:
        return key("".join(pg.get_text() for pg in d))


class Build(unittest.TestCase):
    def build(self, plan, **kw):
        tmp = Path(tempfile.mkdtemp())
        doc = style_pdf.find(PS.make(str(tmp / "in.pdf"), **kw), PS.PIECES)
        return style_pdf.build(doc, plan, tmp, "out")

    def test_no_changes_reads_back_the_same(self):
        f = self.build({"order": {}, "text": {}})
        self.assertEqual((f["pages"], f["paper"], f["kept"]), (1, "A4", []))
        text = all_text(f["pdf"])
        for job in PS.PIECES["jobs"]:
            for b in job["bullets"]:
                self.assertIn(key(b), text)
        with fitz.open(f["pdf"]) as d:
            self.assertEqual(sum(len(pg.get_links()) for pg in d), 1)

    def test_reorder_and_reword(self):
        new = "Moved 30 cron jobs to Airflow, ending missed nightly runs and cutting manual reruns to zero!"
        f = self.build({"order": {"r0": ["r0b2", "r0b0", "r0b1"], "r1": ["r1b1", "r1b0"]}, "text": {"r1b0": new}})
        ws = words(f["pdf"])
        self.assertLess(first(ws, "Wrote"), first(ws, "Built"))
        self.assertLess(first(ws, "Built"), first(ws, "Cut"))
        self.assertLess(first(ws, "Added"), first(ws, "Moved"))
        text = all_text(f["pdf"])
        self.assertIn(key(new), text)
        self.assertNotIn(key(PS.PIECES["jobs"][1]["bullets"][0]), text)
        self.assertEqual(f["kept"], [])

    def test_bold_words_stay_bold(self):
        f = self.build({"order": {}, "text": {
            "r0b1": "Cut p95 latency 40% by moving hot reads to **Redis** and adding a write-through ledger cache."}})
        with fitz.open(f["pdf"]) as d:
            spans = [s for pg in d for b in pg.get_text("dict")["blocks"] for l in b.get("lines", []) for s in l["spans"]]
        redis = [s for s in spans if s["text"].strip() == "Redis"]
        self.assertTrue(redis)
        self.assertTrue(all(style_pdf._is_bold(s) for s in redis))

    def test_a_rewording_that_doesnt_fit_keeps_the_original(self):
        old = PS.PIECES["jobs"][0]["bullets"][1]
        f = self.build({"order": {}, "text": {"r0b1": " ".join([old] * 3)}})
        self.assertEqual(f["kept"], ["r0b1"])
        self.assertIn(key(old), all_text(f["pdf"]))

    def test_a_bullet_split_by_a_page_break_moves_as_one(self):
        f = self.build({"order": {"r0": ["r0b2", "r0b0", "r0b1"]}, "text": {}}, break_page=True)
        self.assertEqual(f["pages"], 2)
        ws = words(f["pdf"])
        self.assertLess(first(ws, "Wrote"), first(ws, "Built"))
        self.assertLess(first(ws, "Built"), first(ws, "Cut"))
        heading = first(ws, "Contoso")               # the next job's heading, on page 2: nothing of job 1 below it
        self.assertTrue(all(w < heading for w in [(pn, y) for pn, y, t in ws if t in ("transfers.", "ledger.", "banks.")]))
        for b in PS.PIECES["jobs"][0]["bullets"]:
            self.assertIn(key(b), all_text(f["pdf"]))

    def test_drawn_dots_move_with_their_bullets(self):
        f = self.build({"order": {"r0": ["r0b2", "r0b0", "r0b1"]}, "text": {}}, sign="circle")
        with fitz.open(f["pdf"]) as d:
            dots = [(pg.number, (dr["rect"].y0 + dr["rect"].y1) / 2) for pg in d for dr in pg.get_drawings()
                    if dr["rect"].width < 8 and dr.get("fill")]
            starts = [(pg.number, (w[1] + w[3]) / 2) for pg in d for w in pg.get_text("words")
                      if w[4] in ("Built", "Cut", "Wrote", "Moved", "Added")]
        self.assertEqual(len(dots), 5)
        for pn, y in starts:
            self.assertTrue(any(dp == pn and abs(dy - y) < 4 for dp, dy in dots), (pn, y))

    def test_a_linked_job_stays_put_and_keeps_its_link(self):
        f = self.build({"order": {"r1": ["r1b1", "r1b0"]},
                        "text": {"r1b0": "Moved 30 cron jobs into Airflow, ending missed nightly runs and cutting reruns to zero."}},
                       link_bullet=True)
        ws = words(f["pdf"])
        self.assertLess(first(ws, "Moved"), first(ws, "Added"))
        self.assertIn(key(PS.PIECES["jobs"][1]["bullets"][0]), all_text(f["pdf"]))
        with fitz.open(f["pdf"]) as d:
            self.assertEqual(sum(len(pg.get_links()) for pg in d), 2)

    def test_a_result_that_doesnt_read_back_fails(self):
        tmp = Path(tempfile.mkdtemp())
        doc = style_pdf.find(PS.make(str(tmp / "in.pdf")), PS.PIECES)
        with mock.patch.object(style_pdf, "_wrong", return_value=["r0b0"]):
            with self.assertRaises(ValueError):
                style_pdf.build(doc, {"order": {}, "text": {}}, tmp, "out")
        self.assertFalse((tmp / "out.pdf").exists())


class OnlineFonts(unittest.TestCase):
    @unittest.skipUnless(style_pdf.system_font("DejaVu Sans", False), "fontconfig and DejaVu Sans aren't installed here")
    def test_reembedded_fonts_read_hyphens_back(self):
        d = fitz.open()
        pg = d.new_page()
        pg.insert_font(fontname="tbs0", fontbuffer=Path(style_pdf.system_font("DejaVu Sans", False)).read_bytes())
        pg.insert_text((50, 100), "end-to-end e-commerce", fontname="tbs0", fontsize=12)
        d.subset_fonts()
        style_pdf._fix_tounicode(d, {"tbs0"})
        with fitz.open("pdf", d.tobytes()) as again:
            self.assertEqual(again[0].get_text().strip(), "end-to-end e-commerce")

    @unittest.skipUnless(os.environ.get("GITHUB_ACTIONS") == "true", "the fonts are installed by the online Tests workflow")
    def test_the_fonts_members_pdfs_use_are_installed(self):
        for name in ("Calibri", "ArialMT", "Helvetica", "Roboto-Regular", "Inter-Regular", "DejaVuSans", "Lato-Regular"):
            self.assertTrue(style_pdf.system_font(name, False), name)
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `python -m unittest tests.test_style_pdf -v`
Expected: the `Build` tests ERROR with `AttributeError: module 'teambid.style_pdf' has no attribute 'build'`. `OnlineFonts` is skipped on this PC.

- [ ] **Step 3: Append the layout, drawing and check to `teambid/style_pdf.py`**

```python
def _style(job):
    """How the job's bullets are set: size, width, justification, line spacing per page, where it may flow."""
    ls = [l for b in job["bullets"] for l in b["lines"]]
    base = lambda l: l["spans"][0]["origin"][1]
    first = job["bullets"][0]["lines"][0]
    t0 = next(s for s in first["spans"] if s["text"].strip() and not _is_sign(s["text"]))
    full = [l for b in job["bullets"] for l in b["lines"][:-1]]
    right = median([l["bbox"].x1 for l in full]) if full else max(l["bbox"].x1 for l in ls)
    justified = len(full) >= 3 and sum(abs(l["bbox"].x1 - right) < 1.5 for l in full) >= 0.8 * len(full)
    regions, gaps, pitches = {}, {}, {}
    for l in ls:
        top, bottom = regions.get(l["page"], (base(l), base(l)))
        regions[l["page"]] = (min(top, base(l)), max(bottom, base(l)))
    for p, n in zip(job["bullets"], job["bullets"][1:]):
        if p["lines"][-1]["page"] == n["lines"][0]["page"]:
            gaps.setdefault(n["lines"][0]["page"], []).append(base(n["lines"][0]) - base(p["lines"][-1]))
    for b in job["bullets"]:
        for a, c in zip(b["lines"], b["lines"][1:]):
            if a["page"] == c["page"]:
                pitches.setdefault(c["page"], []).append(base(c) - base(a))
    allp = [v for vs in pitches.values() for v in vs] or [t0["size"] * 1.25]
    allg = [v for vs in gaps.values() for v in vs] or [median(allp)]
    pitch_at = {pg: median(pitches.get(pg) or allp) for pg in regions}       # LaTeX stretches gaps per page
    between_at = {pg: median(gaps.get(pg) or allg) for pg in regions}
    slack = {}
    for pg, (top, bottom) in regions.items():
        # a page's last line may sit a little lower when nothing is printed below it there (a moved bullet gap can
        # land on the page break); the job's last page never grows, the next heading follows it
        below = any(l["page"] == pg and l["bbox"].y0 > bottom + 2 for l in job["_lines"])
        slack[pg] = 0.5 if pg == max(regions) or below else (between_at[pg] - pitch_at[pg]) + 0.5
    later = [l["spans"][0]["origin"][0] for b in job["bullets"] for l in b["lines"][1:]]
    bold = next((s["font"] for l in ls for s in l["spans"] if _is_bold(s)), None)
    return {"size": t0["size"], "font": t0["font"], "bold_font": bold or t0["font"], "color": t0["color"],
            "right": right, "justified": justified, "regions": regions, "pitch_at": pitch_at, "between_at": between_at,
            "slack": slack, "x_first": t0["origin"][0], "x_next": median(later) if later else t0["origin"][0],
            "page": first["page"]}


def _words(text):
    """'Built **C#** APIs,' -> [[('Built', False)], [('C#', True), (',', False)], ...]"""
    words, cur = [], []
    for n, seg in enumerate(_plain(str(text)).split("**")):
        for m, part in enumerate(seg.split(" ")):
            if m > 0 and cur:
                words.append(cur)
                cur = []
            if part:
                cur.append((part, n % 2 == 1))
    if cur:
        words.append(cur)
    return words


def _new_lines(text, st, fonts):
    """A reworded bullet wrapped into the job's width: lines of (x, text, font, size, color, x-scale)."""
    size, words = st["size"], _words(text)
    letters = {b: "".join(t for w in words for t, bb in w if bb == b) for b in (False, True)}
    fp = {b: fonts.pick(st["page"], st["bold_font"] if b else st["font"], letters[b] + " ", b) for b in (False, True)}
    width = lambda r: fp[r[1]][0].text_length(r[0], fontsize=size)
    space = fp[False][0].text_length(" ", fontsize=size)
    squeeze = MIN_SPACE if st["justified"] else 1.0
    lines, cur, w = [], [], 0.0
    for word in words:
        avail = st["right"] - (st["x_first"] if not lines else st["x_next"])
        ww = sum(width(r) for r in word)
        if cur and w + space * squeeze + ww > avail + 0.01:
            lines.append(cur)
            cur, w = [], 0.0
        w = w + (space * squeeze if cur else 0) + ww
        cur.append(word)
    if cur:
        lines.append(cur)
    out = []
    for n, line in enumerate(lines):
        x0 = st["x_first"] if n == 0 else st["x_next"]
        ws = [sum(width(r) for r in word) for word in line]
        gap = space
        if st["justified"] and n < len(lines) - 1 and len(line) > 1:
            gap = (st["right"] - x0 - sum(ws)) / (len(line) - 1)
        items, x = [], x0
        for word, wwid in zip(line, ws):
            rx = x
            for t, b in word:
                items.append((rx, t, fp[b], size, st["color"], 1.0))
                rx += width((t, b))
            x += wwid + gap
        out.append(items)
    return out


def _old_lines(bullet, fonts):
    """A moved bullet's own lines, each word where it was. In the PDF's own font: as printed (letter by letter where
    a letter advanced differently). In another font: ligatures spelled out and the word fitted to its original width."""
    out = []
    for n, l in enumerate(bullet["lines"]):
        items = []
        for s in l["spans"]:
            if n == 0 and bullet["mark"] and bullet["mark"]["kind"] == "inline" and s is bullet["mark"]["span"]:
                continue
            word = []
            for c in s["chars"] + [None]:
                if c is not None and not c["c"].isspace():
                    word.append(c)
                    continue
                if word:
                    t = "".join(ch["c"] for ch in word)
                    adv = [b["origin"][0] - a["origin"][0] for a, b in zip(word, word[1:])]
                    # two letters at one spot: one glyph (a ligature like fl) read back as several letters; that
                    # word can't be redrawn letter by letter in the PDF's font
                    shared = any(a < 0.5 for a in adv)
                    f = fonts.pick(l["page"], s["font"], t, _is_bold(s), own=not shared)
                    x0, size = word[0]["origin"][0], s["size"]
                    if f[3]:
                        mine = [f[0].text_length(ch["c"], fontsize=size) for ch in word[:-1]]
                        if all(abs(a - m) <= 0.35 for a, m in zip(adv, mine)):
                            items.append((x0, t, f, size, s["color"], 1.0))
                        else:
                            items += [(ch["origin"][0], ch["c"], f, size, s["color"], 1.0) for ch in word]
                    else:
                        t = _plain(t)
                        want = word[-1]["bbox"][2] - x0
                        got = f[0].text_length(t, fontsize=size)
                        sx = want / got if got and 0.85 <= want / got <= 1.15 else 1.0
                        items.append((x0, t, f, size, s["color"], sx))
                word = []
        out.append(items)
    return out


def _flow(job, order, texts, changed, st, fonts):
    """The job's bullets in this order through its own lines and page breaks: [(page, y, items, bullet or None)],
    bullet set on a bullet's first line. None when they don't fit."""
    pages = sorted(st["regions"])
    by_id = {b["id"]: b for b in job["bullets"]}
    pi, y, first, out = 0, st["regions"][pages[0]][0], True, []
    for bid in order:
        b = by_id[bid]
        lines = _new_lines(texts[bid], st, fonts) if bid in changed else _old_lines(b, fonts)
        for n, items in enumerate(lines):
            if not first:
                y += st["between_at"][pages[pi]] if n == 0 else st["pitch_at"][pages[pi]]
            first = False
            if y > st["regions"][pages[pi]][1] + st["slack"][pages[pi]]:
                pi += 1
                if pi >= len(pages):
                    return None
                y = st["regions"][pages[pi]][0]
            out.append((pages[pi], y, items, b if n == 0 else None))
    return out


def _fix_tounicode(doc, names):
    """PyMuPDF writes a re-embedded font's glyph->character table from the font's cmap, where the hyphen glyph also
    stands for the soft hyphen and the space for the no-break space, and it picks those: "end-to-end" would read back
    as "end\\xadto\\xadend". Point them at "-" and " ", in the fonts this edit inserted, and only as the character a glyph
    maps TO (never a glyph number that happens to be AD or A0)."""
    for xref in {f[0] for page in doc for f in page.get_fonts() if f[4] in names}:
        t = doc.xref_get_key(xref, "ToUnicode")
        if t[0] != "xref":
            continue
        n = int(t[1].split()[0])
        s = doc.xref_stream(n)
        new = re.sub(rb"(<[0-9A-Fa-f]+>\s+)<00[Aa][Dd]>(?=\s*[\r\n])", rb"\1<002D>", s)
        new = re.sub(rb"(<[0-9A-Fa-f]+>\s+)<00[Aa]0>(?=\s*[\r\n])", rb"\1<0020>", new)
        if new != s:
            doc.update_stream(n, new)


def _render(path, pieces, plan, allow_embedded):
    """Draw the plan into a fresh copy of the PDF. -> (doc, todo, kept, drawn): todo = [(bullets, flow)] drawn,
    kept = reworded bullet ids that didn't fit, drawn = {bullet id: [(page, rect)] of its drawn lines}."""
    fitz = _fitz()
    doc = fitz.open(path)
    jobs = read(doc, pieces)
    fonts = Fonts(doc, jobs[0]["_lines"] if jobs else [], allow_embedded)
    todo, kept = [], []
    for job in jobs:
        st = _style(job)
        ids = [b["id"] for b in job["bullets"]]
        order = plan.get("order", {}).get(job["id"]) if job["reorder"] else None
        order = order if order and sorted(order) == sorted(ids) else ids
        texts = {b["id"]: b["text"] for b in job["bullets"]}
        changed = {i for i in ids if plan.get("text", {}).get(i)} - {b["id"] for b in job["bullets"] if b["fixed"]}
        texts.update({i: plan["text"][i] for i in changed})
        if any(b["link"] for b in job["bullets"]):
            # a job with a linked bullet stays where it is: a reworded bullet changes only if it keeps its exact lines
            for b in job["bullets"]:
                if b["id"] in changed:
                    new = _new_lines(texts[b["id"]], st, fonts)
                    if len(new) == len(b["lines"]):
                        todo.append(([b], [(l["page"], l["spans"][0]["origin"][1], items, b if n == 0 else None)
                                           for n, (l, items) in enumerate(zip(b["lines"], new))]))
                    else:
                        kept.append(b["id"])
            continue
        for ch, od in ((changed, order), (set(), order), (set(), ids)):
            flow = _flow(job, od, texts, ch, st, fonts)
            if flow:
                kept += sorted(changed - ch)
                todo.append((job["bullets"], flow))
                break
    vector = set()
    for bullets, flow in todo:
        for b in bullets:
            for l in b["lines"]:
                r = l["bbox"]
                doc[l["page"]].add_redact_annot(fitz.Rect(r.x0 - 0.5, r.y0 + 0.8, r.x1 + 0.5, r.y1 - 0.8))
            m = b["mark"]
            if m and m["kind"] != "inline":
                r = m["rect"]
                doc[m["page"]].add_redact_annot(fitz.Rect(r.x0 - 0.3, r.y0 - 0.3, r.x1 + 0.3, r.y1 + 0.3))
                if m["kind"] != "text":
                    vector.add(m["page"])
    for pno, page in enumerate(doc):
        links = page.get_links()                     # erasing text under a link deletes the link: put them back
        page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                              graphics=fitz.PDF_REDACT_LINE_ART_REMOVE_IF_COVERED if pno in vector
                              else fitz.PDF_REDACT_LINE_ART_NONE)
        have = {(round(l["from"].x0), round(l["from"].y0), l.get("uri"), l.get("page")) for l in page.get_links()}
        for l in links:
            if (round(l["from"].x0), round(l["from"].y0), l.get("uri"), l.get("page")) not in have:
                page.insert_link(l)
    inserted, drawn = set(), {}

    def put(page, pno, x, y, t, f, size, color, sx=1.0):
        if f[1] and (pno, f[2]) not in inserted:
            page.insert_font(fontname=f[2], fontbuffer=f[1])
            inserted.add((pno, f[2]))
        morph = (fitz.Point(x, y), fitz.Matrix(sx, 1)) if abs(sx - 1) > 0.002 else None
        page.insert_text((x, y), t, fontname=f[2], fontsize=size, color=fitz.sRGB_to_pdf(color), morph=morph)

    for bullets, flow in todo:
        current = None
        for pno, y, items, b in flow:
            page = doc[pno]
            current = b or current
            if items:
                x0 = min(i[0] for i in items)
                x1 = max(i[0] + i[2][0].text_length(i[1], fontsize=i[3]) * max(1.0, i[5]) for i in items)
                size = items[0][3]
                drawn.setdefault(current["id"], []).append((pno, fitz.Rect(x0 - 0.5, y - 0.75 * size, x1 + 0.5, y + 0.25 * size)))
            if b and b["mark"]:
                m, l0 = b["mark"], b["lines"][0]
                dy = y - l0["spans"][0]["origin"][1]
                if m["kind"] in ("inline", "text"):
                    # the sign in the PDF's own font, else the Symbol font's bullet (a text font's would be a tiny dot)
                    s = m["span"]
                    f = fonts.own(l0["page"], s["font"], s["text"]) or (fitz.Font("symb"), None, "symb")
                    put(page, pno, s["origin"][0], s["origin"][1] + dy, s["text"].strip(), f, s["size"], s["color"])
                elif m["kind"] == "circle":
                    r = fitz.Rect(m["rect"]) + (0, dy, 0, dy)
                    page.draw_circle((r.x0 + r.width / 2, r.y0 + r.height / 2), r.width / 2, color=None, fill=m["fill"])
                else:
                    page.draw_rect(fitz.Rect(m["rect"]) + (0, dy, 0, dy), color=None, fill=m["fill"])
            for x, t, f, size, color, sx in items:
                put(page, pno, x, y, t, f, size, color, sx)
    doc.subset_fonts()
    _fix_tounicode(doc, {name for _, name in inserted})
    return doc, todo, kept, drawn


def _wrong(doc, todo, kept, drawn, plan, links_before):
    """Bullets that don't read back, from where they were drawn, as exactly their text (and "links" if one was lost).
    Clip rects make this independent of reading order, so two-column resumes check right too."""
    bad = []
    for bullets, _ in todo:
        for b in bullets:
            if b["id"] not in drawn:
                continue
            new = plan.get("text", {}).get(b["id"]) if b["id"] not in kept and not b["fixed"] else None
            got = "".join(doc[p].get_text("text", clip=r) for p, r in drawn[b["id"]])
            if key(got) != key(_plain((new or b["text"]).replace("**", ""))):
                bad.append(b["id"])
    if sum(len(p.get_links()) for p in doc) != links_before:
        bad.append("links")
    return bad


def build(doc, plan, folder, base):
    """Write the tailored PDF into folder. -> {"pdf", "pages", "paper", "kept": [bullet ids whose rewording didn't
    fit and kept their text]}. Raises ValueError when the result doesn't read back, even without the PDF's own fonts."""
    fitz = _fitz()
    with fitz.open(doc["_path"]) as d:
        links_before = sum(len(p.get_links()) for p in d)
    bad = []
    for allow in (True, False):
        out, todo, kept, drawn = _render(doc["_path"], doc["_pieces"], plan, allow)
        bad = _wrong(out, todo, kept, drawn, plan, links_before)
        if not bad:
            folder = Path(folder)
            folder.mkdir(parents=True, exist_ok=True)
            pdf = folder / f"{base}.pdf"
            out.save(pdf, garbage=3, deflate=True)
            width, pages = out[0].rect.width, out.page_count
            out.close()
            return {"pdf": str(pdf), "pages": pages, "paper": "A4" if abs(width - 595) < 6 else "Letter", "kept": kept}
        out.close()
    raise ValueError(f"the tailored PDF didn't read back as written ({', '.join(bad[:4])})")
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `python -m unittest tests.test_style_pdf -v`
Expected: 14 tests PASS, and the 2 `OnlineFonts` tests are skipped on this PC.

Run: `python tb.py test`
Expected: the whole suite passes (the last baseline was 126 OK).

- [ ] **Step 5: Commit**

```bash
git add teambid/style_pdf.py tests/test_style_pdf.py
git commit -m "Keep style: redraw a PDF's bullets in place (moved exactly, reworded to fit), links kept, text read back"
```

---

### Task 3: Plug the PDF handler into the coordinator

**Files:**
- Modify: `teambid/keep_style.py` (imports, `HANDLERS` at about line 273, `tailor` at about lines 344-377)
- Test: `tests/test_keep_style.py` (append above `if __name__`)

**Interfaces:**
- Consumes:
  - `style_pdf.find` / `style_pdf.build` (Tasks 1-2)
  - Part 1's `keep_style.tailor(slug, member, profile, jd, jd_text, model, folder, base)`
  - in `tests/test_keep_style.py`: `TempWorkspace`, `JD_TEXT`, and the module imports `service`, `llm`, `config`, `json`, `tempfile`, `mock`, `Path`
- Produces: PDF members get `{"files": {"pdf", "pages", "paper"}, "spec", "note"}` from `keep_style.tailor`. The note says how many rewordings were kept because they didn't fit, and `files` no longer carries `"kept"`.

> **Final review fixes (2026-11-06).** `tailor` also pops `"order"` from a PDF build into the plan, so the note and report give the order really drawn. When nothing in the PDF changed, it deletes the PDF and returns `{"note": "original style skipped: nothing in the file could be tailored safely"}`, and the tailored RenderCV resume is used (owner's decision). Pieces carry `"by"` (`"claude"` from `read`, `"rules"` from `rule_pieces`). For a PDF, pieces not read by Claude (older saved ones without `"by"` too) are only reordered, so Claude isn't called. `service.onboard` and `reparse` save rule-based pieces when Claude's reading is rejected or unavailable, and never over a Claude reading of the same file.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_keep_style.py` (above `if __name__`). Add `from tests import pdf_samples` next to the existing `from tests import tex_samples as S`, and `from teambid.style_text import key` next to the other teambid imports:

```python
class ApplyWithPdf(TempWorkspace):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        src = Path(tempfile.mkdtemp()) / "dana.pdf"
        pdf_samples.make(str(src))
        with mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm, "read_resume", return_value=(json.loads(json.dumps(pdf_samples.PIECES)), "read")):
            cls.slug = service.onboard("Dana Pdf", resume_path=src)["slug"]

    def _apply(self, reply):
        with mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm, "tailor_in_place", return_value=(reply, "ok")), \
             mock.patch.object(llm, "write_letter", side_effect=lambda p, jd, c, t, letter, model: (letter, "kept")), \
             mock.patch.object(llm, "rewrite_resume", side_effect=lambda spec, *a: (spec, "reworded")):
            return service.apply(self.slug, jd_text=JD_TEXT, company="Acme", title="Senior Python Engineer", ai="haiku")

    def test_tailors_inside_the_members_own_pdf(self):
        new = "Moved 30 cron jobs into Airflow, ending missed nightly runs and cutting manual reruns to zero."
        r = self._apply({"order": {"r0": ["r0b2", "r0b0", "r0b1"]}, "bullets": {"r1b0": new}})
        self.assertIn("Resume style: original (.pdf)", r["resume_ai"])
        self.assertEqual(set(r["files"]) - {"letter_pdf", "letter_docx"}, {"pdf", "pages", "paper"})
        import fitz
        with fitz.open(r["files"]["pdf"]) as d:
            text = key("".join(p.get_text() for p in d))
            self.assertEqual(sum(len(p.get_links()) for p in d), 1)
        self.assertIn(key(new), text)
        self.assertEqual(r["problems"], [])

    def test_a_rewording_that_doesnt_fit_is_reported_and_left_out(self):
        long = " ".join([pdf_samples.PIECES["jobs"][0]["bullets"][1]] * 3)
        with mock.patch.object(keep_style, "check", side_effect=lambda doc, reply, profile, jd: dict(
                keep_style.default_plan(doc, jd), text={"r0b1": long})):
            r = self._apply({"bullets": {"r0b1": long}})
        self.assertIn("1 reworded bullet(s) kept their original text to fit", r["resume_ai"])
        self.assertIn("0 of 5 bullets reworded", r["resume_ai"])
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `python -m unittest tests.test_keep_style.ApplyWithPdf -v`
Expected: FAIL. With no `.pdf` handler, `keep_style.tailor` returns `{}` and the RenderCV resume is built, so `resume_ai` lacks "Resume style: original (.pdf)".

- [ ] **Step 3: Wire it in `teambid/keep_style.py`**

Change the import line `from . import config, llm, resume_parse, style_tex` to:

```python
from . import config, llm, resume_parse, style_pdf, style_tex
```

Change `HANDLERS` to:

```python
HANDLERS = {".tex": style_tex, ".pdf": style_pdf}      # .docx comes in part 2 (after PDFs: the team uploads PDFs)
```

In `tailor`, add `kept = []` as the line just above `try:`. Directly under the line `files, reverted = _build(handler, doc, plan, Path(folder), base)`, add:

```python
        kept = files.pop("kept", [])
        for bid in kept:                           # rewordings the file couldn't fit kept their original text
            plan["text"].pop(bid, None)
```

After the `if reverted:` block (before `if why:`), add:

```python
    if kept:
        note += f", {len(kept)} reworded bullet(s) kept their original text to fit"
```

- [ ] **Step 4: Run the tests**

Run: `python -m unittest tests.test_keep_style -v`
Expected: all PASS, including the two new `ApplyWithPdf` tests and the earlier `.tex` tests.

Run: `python tb.py test`
Expected: the whole suite passes.

- [ ] **Step 5: Commit**

```bash
git add teambid/keep_style.py tests/test_keep_style.py
git commit -m "Keep style: members who uploaded a PDF get their own PDF tailored, the template only as the fallback"
```

---

### Task 4: Install the fonts online and run the tests there

**Files:**
- Modify: `.github/actions/doc-tools/action.yml`

**Interfaces:**
- Produces: on the runner, `fc-match` finds Carlito, Caladea, Liberation, Roboto, Inter, Open Sans, Lato and DejaVu, so `style_pdf.system_font` resolves them. The `OnlineFonts` tests run in `tests.yml`.

- [ ] **Step 1: Add the font step**

In `.github/actions/doc-tools/action.yml`, insert this step directly after the first step (the one that writes `TEAMBID_LATEX_SANDBOX=docker` to `$GITHUB_ENV`; it must stay first):

```yaml
    - name: Fonts for members' own PDFs
      shell: bash
      run: |
        # a reworded bullet in a member's PDF is drawn in the PDF's own font when possible, else in this family or its
        # metric-compatible stand-in (Calibri -> Carlito, Arial/Helvetica -> Liberation Sans, ...); DejaVu covers ≈ → €
        sudo apt-get update -qq
        sudo apt-get install -y -qq fonts-crosextra-carlito fonts-crosextra-caladea fonts-liberation fonts-roboto \
          fonts-inter fonts-open-sans fonts-lato fonts-dejavu-core \
          || echo "some fonts didn't install; reworded bullets fall back to DejaVu Sans"
```

- [ ] **Step 2: Check the YAML**

Run: `python -c "import sys, yaml; yaml.safe_load(open(sys.argv[1], encoding='utf-8')); print('ok')" .github/actions/doc-tools/action.yml`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add .github/actions/doc-tools/action.yml
git commit -m "Keep style: install the fonts members' PDFs use (or their stand-ins) where documents are built"
```

- [ ] **Step 4: Ask the owner, then push the branch and watch `Tests`**

Ask the owner first. Once they agree:

```bash
git push -u origin keep-style-pdf
gh run list --branch keep-style-pdf --workflow tests.yml --limit 1
gh run watch <run id> --exit-status
gh run view <run id> --log | grep -E "test_style_pdf|OnlineFonts|Ran [0-9]+ tests|^(OK|FAILED)"
```

Expected:
- The run passes.
- `test_reembedded_fonts_read_hyphens_back` and `test_the_fonts_members_pdfs_use_are_installed` show `ok`, not skipped.
- The `Build` tests pass using the installed fonts: online, Helvetica resolves to Liberation Sans.

If a font package name doesn't exist on the runner, `test_the_fonts_members_pdfs_use_are_installed` names the missing family. Fix the package name; don't drop the check.

---

### Task 5: Prove it on the real PDFs, then ship (owner-gated)

- [ ] **Step 1: Re-run the prototype check on the real PDFs with the final module.** This is local only, and member files never leave this PC.

  ```bash
  python - <<'EOF'
  import glob, os, sys
  sys.path.insert(0, ".")
  os.environ["TEAMBID_LOCAL_AI"] = "off"
  import fitz
  from teambid import keep_style, resume_parse, style_pdf
  for f in sorted(glob.glob("workspace/members/*/resume/*.pdf")):
      pieces = keep_style.pieces_from_profile(resume_parse.parse_file(f))
      doc = style_pdf.find(f, pieces)
      plan = {"order": {j["id"]: [b["id"] for b in reversed(j["bullets"])] for j in doc["jobs"] if j["reorder"]}, "text": {}}
      try:
          out = style_pdf.build(doc, plan, "workspace/.tmp-style-check", os.path.basename(f)[:-4])
          print(os.path.basename(f), "ok", out["pages"], "pages")
      except Exception as e:
          print(os.path.basename(f), "FAILED", e)
  EOF
  ```

  Expected: every member PDF prints `ok`, or `FAILED ... didn't read back`, which is the template fallback; on this PC there's no `fc-match`, so a PDF whose own font can't draw ’ ≈ → can fail here and pass online. The rule-based parse stands in for Claude's reading. Delete `workspace/.tmp-style-check` afterwards.

- [ ] **Step 2: Open a PR** (`gh pr create --base main --head keep-style-pdf`), with the green `Tests` run linked. The owner merges it.

- [ ] **Step 3: After the merge, the owner runs Maintenance → task `reparse-all` once.**
  - It has Claude read every member's PDF and saves `pieces.json` next to each. The task runner has the key since Part 1's final fixes.
  - It replaces each profile's jobs with Claude's reading, and pushes the workspace.
  - Without it, each application re-reads a member's PDF with Sonnet, because `docs.yml` can't save files back.

  Watch: `gh run list --workflow maintain.yml --limit 1` and `gh run view <id> --log | grep -E "reparse|failed"`.

- [ ] **Step 4: The owner adds the LaTeX member** on the results page with their PDF.

- [ ] **Step 5: The owner queues one real job for that member and one for another member, then compares each tailored PDF with the original.**
  - Watch: `gh run view <id> --log | grep -E "Resume style|original style skipped|failed"`.
  - Expected: `Resume style: original (.pdf). N of M bullets reworded, ...`.
  - Confirm by eye:
    - Header, links, fonts, layout, other sections and the page count are unchanged.
    - Every bullet appears once.
    - Reworded bullets read toward the job.

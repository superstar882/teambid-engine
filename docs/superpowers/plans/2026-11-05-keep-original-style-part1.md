# Keep Original Style, Part 1 (core + .tex) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A member who uploads a LaTeX (.tex) resume gets every tailored resume built from their own file. Claude rewrites and reorders only the bullets, summary, headline and skills order, and everything else in the file stays byte-for-byte the same.

**Architecture:**
- **At upload:** Claude reads the resume once (`llm.read_resume`). `keep_style.confirm` keeps only the strings that appear word for word in the resume text and saves them as `pieces.json`.
- **For each job post:**
  - `style_tex.find` locates those pieces in the .tex source.
  - Claude returns new text and a new order for them (`llm.tailor_in_place`).
  - `keep_style.check` accepts only the changes that pass the fact, length and order checks.
  - `style_tex.build` writes the text back and compiles the PDF with TinyTeX.
- **On any failure:** today's RenderCV resume is used, with a note.

**Tech Stack:**
- Python 3.12, unittest
- PyMuPDF (`fitz`)
- TinyTeX (`pdflatex`, `xelatex`) in GitHub Actions
- Claude Messages API, called through the existing `llm._call`

**Spec:** `docs/superpowers/specs/2026-11-05-keep-original-style-design.md` (approved 2026-11-05)

## Global Constraints

- **Where it runs:** everything runs online in GitHub Actions (`ubuntu-latest`, Python 3.12). The owner's Windows machine is not a target. Tests that need `pdflatex` skip when it is missing and run for real in `tests.yml`.
- **Privacy:** never put a real member's resume (Omar's or anyone's) in the repo. All fixtures are fictional ("Dana Reyes").
- **Bullet length:** a reworded bullet may be at most 10% longer and at most 25% shorter than the original (`LENGTH = (0.75, 1.10)`). The same limits apply to the summary.
- **Rejecting Claude's reading:** throw out the whole reading when more than 25% of its bullets are not found word for word (`MAX_MISSED = 0.25`).
- **Page count:** the tailored PDF must have no more pages than the original. Put original text back at most 5 times, then fall back to RenderCV.
- **LaTeX safety:**
  - Run `-no-shell-escape -interaction=nonstopmode -halt-on-error` with the environment variables `openin_any=p` and `openout_any=p`.
  - Run in a temporary folder.
  - Each run has a 60 s limit.
- **Claude calls:**
  - Reading uses `llm.MODELS["sonnet"][0]`, `max_tokens` 16000, timeout 300 s.
  - Tailoring uses the results-page dropdown model, `max_tokens` 8000, timeout 300 s.
- **Fact rules:** existing rules stay on (`llm._bullet_ok`, the banned words, no em dashes or semicolons, no new tools or numbers).
- **Cover letter:** unchanged (`cover.py`, `llm.write_letter`, `render.write_letter`).
- **Code style:** match the repo. Flat modules in `teambid/`, short docstrings, comments that say why, plain-sentence commit messages ("Keep style: ...").

## File Map

| File | Change | Responsibility |
|---|---|---|
| `teambid/style_text.py` | create | `key()`: the matching form of a text, shared by all handlers |
| `teambid/style_tex.py` | create | LaTeX handler: text conversion, find the pieces, write them back, compile safely |
| `teambid/keep_style.py` | create | coordinator: confirm Claude's reading, save/load `pieces.json`, default order, checks, page guard, fallback |
| `teambid/llm.py` | modify | `_call` timeout, `read_resume` (replaces `refine_profile`), `_summary_ok`, `tailor_in_place` |
| `teambid/tailor.py` | modify | `jd_weights()` taken out of `build_resume` so `keep_style` can reuse it |
| `teambid/resume_parse.py` | modify | `.tex` in `extract_text` (reads the PDF it builds) |
| `teambid/service.py` | modify | `onboard` / `reparse` run the Claude reading, and `apply` tries `keep_style` before RenderCV |
| `teambid/docs.py` | modify | ship the `.tex` source, skip files that don't exist |
| `teambid/server.py`, `tb.py` | modify | Claude reading on by default (`--no-llm` to turn it off) |
| `teambid/static/results.html`, `teambid/static/index.html` | modify | accept `.tex`, show the source download, the DOCX link only when it exists |
| `tests/tex_samples.py` | create | fictional .tex resumes (an Omar-like layout and Jake's Resume), their pieces, the PDF-like text |
| `tests/test_style_tex.py` | create | tests for Tasks 1-3 |
| `tests/test_keep_style.py` | create | tests for Tasks 4-6 |
| `.github/actions/doc-tools/action.yml` | create | shared TinyTeX setup (cached) |
| `.github/workflows/tests.yml` | create | `python tb.py test` online, with TinyTeX |
| `.github/workflows/docs.yml`, `maintain.yml`, `scan.yml` | modify | TinyTeX when there is work, plus `ANTHROPIC_API_KEY` for upload reading |

**The doc shape** is shared by every handler. `style_tex.locate` returns it, and `keep_style` and `llm.tailor_in_place` read it:

```python
doc = {
    "ext": ".tex", "_src": "<the .tex source>", "pages": 4,            # pages: set by find()
    "headline": {"text": "SENIOR BACKEND ENGINEER", "fixed": False, "_span": (a, b)} | None,
    "summary":  {"text": "plain text with **bold**", "fixed": False, "_span": (a, b)} | None,
    "jobs": [{"id": "r0", "title": "...", "company": "...", "start": "2022-03", "end": "Present",
              "reorder": True,                                          # every item of the list was matched
              "bullets": [{"id": "r0b0", "text": "plain with **bold**", "fixed": False,
                           "piece": "<the confirmed text from pieces.json>", "_span": (a, b)}]}],
    "skills": [{"id": "s0", "label": "Languages", "items": ["Python", "Go"], "_span": (a, b), "_items": [...], "_frame": (...)}],
    "skills_move": True,                                                # all skill lines share one markup frame
}
```

**The plan shape.** `keep_style.default_plan` and `keep_style.check` build it, and `style_tex.render_source` reads it:

```python
plan = {"headline": "new" | None, "summary": "new" | None, "text": {"r0b0": "new text with **bold**"},
        "order": {"r0": ["r0b1", "r0b0"]}, "skills": {"s0": ["Go", "Python"]}, "skill_lines": ["s1", "s0"]}
```

---

### Task 1: Matching key and LaTeX text conversion

**Files:**
- Create: `teambid/style_text.py`
- Create: `teambid/style_tex.py` (first part)
- Create: `tests/tex_samples.py`
- Test: `tests/test_style_tex.py`

**Interfaces:**
- Produces:
  - `style_text.key(text) -> str`
  - `style_tex.to_plain(src: str) -> (str, bool)`: the plain text with `**bold**`, and whether the piece is simple
  - `style_tex.to_tex(text: str) -> str`
  - `style_tex._mask(src) -> str`
  - `style_tex._close(s, i) -> int`
  - `tests.tex_samples`: `SAMPLE`, `PIECES`, `SAMPLE_TEXT`, `JAKE`, `JAKE_PIECES`

- [ ] **Step 1: Create the fictional samples**

Create `tests/tex_samples.py`:

```python
"""Fictional LaTeX resumes for the keep-original-style tests (no real people).

SAMPLE uses the layout of a common hand-made resume (\\section*, \\subsection*, itemize, \\textbf keywords);
JAKE uses Jake's Resume template (\\resumeItem macros). PIECES / JAKE_PIECES are what keep_style.confirm keeps from
Claude's reading; SAMPLE_TEXT is what the PDF of SAMPLE reads like (with a word split across lines)."""

SAMPLE = r"""\documentclass[a4paper,10pt]{article}
\usepackage[left=0.5in,right=0.5in,top=0.6in,bottom=0.5in]{geometry}
\usepackage{hyperref}
\usepackage{enumitem}
\pagestyle{empty}
% a comment with \item in it must be ignored
\begin{document}

\begin{center}
{\Huge\bfseries DANA REYES}\\[1em]
{\LARGE SENIOR BACKEND ENGINEER}
\end{center}

\begin{center}
Austin, USA \hspace{2em} \href{mailto:dana@example.com}{dana@example.com} \hspace{2em} \href{https://github.com/dana-example}{GitHub}
\end{center}

\section*{Profile}
Backend engineer with \textbf{7+ years} building \textbf{Python} and \textbf{Go} services for payments and logistics.

\section*{Employment History}

\subsection*{Senior Backend Engineer at Northwind Labs, Austin}
\textbf{March 2022 -- Present}
\begin{itemize}[leftmargin=0.5cm]

\item Built a payments API in \textbf{Python} and FastAPI that handles 2M requests a day.

\item Cut p95 latency 40\% by moving hot reads to \textbf{Redis}.

\item Wrote the \href{https://example.com/docs}{public API docs} for 12 endpoints.

\end{itemize}

\subsection*{Backend Engineer at Contoso Freight, Remote}
\textbf{June 2019 -- February 2022}
\begin{itemize}[leftmargin=0.5cm]

\item Moved 30 cron jobs to Airflow, ending missed nightly runs.

\item Added Go unit tests for 6 backend services, raising coverage to 85\%.

\end{itemize}

\section*{Skills}
\begin{itemize}
\item {Languages:} Python, Go, SQL, C\#.

\item{Cloud \& Data:} AWS, Docker, PostgreSQL, Redis, Airflow.
\end{itemize}

\section*{Education}
\textbf{B.S. Computer Science, University of Texas} (2015 -- 2019)

\end{document}
"""

PIECES = {
    "headline": "SENIOR BACKEND ENGINEER",
    "summary": "Backend engineer with 7+ years building Python and Go services for payments and logistics.",
    "jobs": [
        {"title": "Senior Backend Engineer", "company": "Northwind Labs", "location": "Austin", "start": "2022-03", "end": "Present",
         "bullets": ["Built a payments API in Python and FastAPI that handles 2M requests a day.",
                     "Cut p95 latency 40% by moving hot reads to Redis.",
                     "Wrote the public API docs for 12 endpoints."]},
        {"title": "Backend Engineer", "company": "Contoso Freight", "location": "Remote", "start": "2019-06", "end": "2022-02",
         "bullets": ["Moved 30 cron jobs to Airflow, ending missed nightly runs.",
                     "Added Go unit tests for 6 backend services, raising coverage to 85%."]},
    ],
    "skills": [{"label": "Languages", "items": ["Python", "Go", "SQL", "C#"]},
               {"label": "Cloud & Data", "items": ["AWS", "Docker", "PostgreSQL", "Redis", "Airflow"]}],
}

SAMPLE_TEXT = """DANA REYES
SENIOR BACKEND ENGINEER
Austin, USA    dana@example.com    GitHub
Profile
Backend engineer with 7+ years building Python and Go services for payments and logistics.
Employment History
Senior Backend Engineer at Northwind Labs, Austin
March 2022 – Present
• Built a payments API in Python and FastAPI that handles 2M re-
quests a day.
• Cut p95 latency 40% by moving hot reads to Redis.
• Wrote the public API docs for 12 endpoints.
Backend Engineer at Contoso Freight, Remote
June 2019 – February 2022
• Moved 30 cron jobs to Airflow, ending missed nightly runs.
• Added Go unit tests for 6 backend services, raising coverage to 85%.
Skills
• Languages: Python, Go, SQL, C#.
• Cloud & Data: AWS, Docker, PostgreSQL, Redis, Airflow.
Education
B.S. Computer Science, University of Texas (2015 – 2019)
"""

JAKE = r"""\documentclass[letterpaper,11pt]{article}
\usepackage{titlesec}
\newcommand{\resumeItem}[1]{
  \item\small{
    {#1 \vspace{-2pt}}
  }
}
\newcommand{\resumeSubheading}[4]{
  \vspace{-2pt}\item
    \begin{tabular*}{0.97\textwidth}[t]{l@{\extracolsep{\fill}}r}
      \textbf{#1} & #2 \\
      \textit{\small#3} & \textit{\small #4} \\
    \end{tabular*}\vspace{-7pt}
}
\newcommand{\resumeSubItem}[1]{\resumeItem{#1}\vspace{-4pt}}
\newcommand{\resumeSubHeadingListStart}{\begin{itemize}[leftmargin=0.15in, label={}]}
\newcommand{\resumeSubHeadingListEnd}{\end{itemize}}
\newcommand{\resumeItemListStart}{\begin{itemize}}
\newcommand{\resumeItemListEnd}{\end{itemize}\vspace{-5pt}}
\begin{document}
\begin{center}
    \textbf{\Huge \scshape Dana Reyes} \\ \vspace{1pt}
    \small 555-0100 $|$ \href{mailto:dana@example.com}{\underline{dana@example.com}}
\end{center}
\section{Experience}
  \resumeSubHeadingListStart
    \resumeSubheading
      {Backend Engineer}{June 2022 -- Present}
      {Northwind Labs}{Austin, TX}
      \resumeItemListStart
        \resumeItem{Built a REST API in \textbf{Python} and FastAPI serving 2M requests a day} % comment, here
        \resumeItem{Cut p95 latency 40\% by moving hot reads to Redis}
        \resumeItem{Wrote the \href{https://example.com/docs}{public docs} for 12 endpoints}
      \resumeItemListEnd
    \resumeSubheading
      {Software Engineer Intern}{May 2021 -- Aug 2021}
      {Contoso}{Remote}
      \resumeItemListStart
        \resumeItem{Added Go unit tests that raised coverage to 85\%}
        \resumeItem{Automated releases with GitHub Actions}
      \resumeItemListEnd
  \resumeSubHeadingListEnd
\section{Technical Skills}
 \begin{itemize}[leftmargin=0.15in, label={}]
    \small{\item{
     \textbf{Languages}{: Java, Python, C/C++, SQL (Postgres), JavaScript} \\
     \textbf{Frameworks}{: React, Node.js, Flask, FastAPI}
    }}
 \end{itemize}
\end{document}
"""

JAKE_PIECES = {
    "headline": "", "summary": "",
    "jobs": [
        {"title": "Backend Engineer", "company": "Northwind Labs", "location": "Austin, TX", "start": "2022-06", "end": "Present",
         "bullets": ["Built a REST API in Python and FastAPI serving 2M requests a day",
                     "Cut p95 latency 40% by moving hot reads to Redis",
                     "Wrote the public docs for 12 endpoints"]},
        {"title": "Software Engineer Intern", "company": "Contoso", "location": "Remote", "start": "2021-05", "end": "2021-08",
         "bullets": ["Added Go unit tests that raised coverage to 85%", "Automated releases with GitHub Actions"]},
    ],
    "skills": [{"label": "Languages", "items": ["Java", "Python", "C/C++", "SQL (Postgres)", "JavaScript"]},
               {"label": "Frameworks", "items": ["React", "Node.js", "Flask", "FastAPI"]}],
}
```

- [ ] **Step 2: Write the failing tests**

Create `tests/test_style_tex.py`:

```python
"""Keep-original-style, LaTeX handler (stdlib unittest). Tests that build PDFs skip without pdflatex;
the online "Tests" workflow installs TinyTeX so they run there."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TEAMBID_WORKSPACE", tempfile.mkdtemp(prefix="teambid-test-"))
os.environ.setdefault("TEAMBID_LOCAL_AI", "off")

from teambid import style_tex  # noqa: E402
from teambid.style_tex import to_plain, to_tex  # noqa: E402
from teambid.style_text import key  # noqa: E402
from tests import tex_samples as S  # noqa: E402


class Key(unittest.TestCase):
    def test_ignores_what_a_pdf_changes(self):
        self.assertEqual(key("snake_case – end-to-\nend"), key("snake case-end to end"))
        self.assertEqual(key("ﬁle “x” **Bold**"), key('file "x" Bold'))
        self.assertEqual(key(S.SAMPLE_TEXT.split("• ")[1]), key(S.PIECES["jobs"][0]["bullets"][0] + "\n"))

    def test_keeps_the_words_and_numbers(self):
        self.assertNotEqual(key("Built 2M"), key("Built 3M"))
        self.assertNotEqual(key("Built APIs"), key("Built API"))


class PlainText(unittest.TestCase):
    def test_bold_and_escapes(self):
        self.assertEqual(to_plain(r"Cut latency 40\% with \textbf{Redis} and C\#."),
                         ("Cut latency 40% with **Redis** and C#.", True))

    def test_dashes_quotes_and_comments(self):
        self.assertEqual(to_plain("2019 -- 2022, ``ok'' % note\nnext"), ('2019 – 2022, "ok" next', True))

    def test_links_italics_and_line_breaks_make_a_piece_move_only(self):
        self.assertEqual(to_plain(r"Wrote the \href{https://x.io}{public docs} for 12"), ("Wrote the public docs for 12", False))
        self.assertFalse(to_plain(r"\textit{Remote}")[1])
        self.assertFalse(to_plain("one \\\\ two")[1])

    def test_to_tex_escapes_everything(self):
        self.assertEqual(to_tex("Saved 40% & **C#** <x>"), r"Saved 40\% \& \textbf{C\#} \textless{}x\textgreater{}")
        self.assertEqual(to_tex("snake_case – done"), r"snake\_case -- done")
        self.assertEqual(to_tex("odd ** mark"), "odd  mark")

    def test_round_trip(self):
        for s in ("Built **.NET 9** APIs, 50% faster & safer", 'C# and F# – "quoted"'):
            self.assertEqual(to_plain(to_tex(s))[0], s)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests to see them fail**

Run: `python -m unittest tests.test_style_tex -v`
Expected: ERROR, `ModuleNotFoundError: No module named 'teambid.style_tex'`

- [ ] **Step 4: Write `teambid/style_text.py`**

```python
"""Text matching shared by the keep-original-style file handlers (style_tex.py now; .docx and PDF later).

key() is the form of a text that survives the trip through a PDF: line breaks, words split with a hyphen at a line
end, dash and quote styles, ligatures (ﬁ), an underscore pdfTeX draws as a line (it reads back as a space) and
**bold** marks are all ignored. Two texts with the same key are the same words.
"""
import re
import unicodedata

_QUOTES = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"'})
_IGNORED = re.compile(r"[\s\-‐‑‒–—|•·_]+")


def key(text):
    s = unicodedata.normalize("NFKC", str(text or "")).translate(_QUOTES).replace("**", "")
    return _IGNORED.sub("", s).casefold()
```

- [ ] **Step 5: Write the first part of `teambid/style_tex.py`**

```python
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
```

- [ ] **Step 6: Run the tests to see them pass**

Run: `python -m unittest tests.test_style_tex -v`
Expected: all 7 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add teambid/style_text.py teambid/style_tex.py tests/tex_samples.py tests/test_style_tex.py
git commit -m "Keep style: matching key and LaTeX text conversion"
```

---

### Task 2: Find the pieces in a .tex file and write them back

**Files:**
- Modify: `teambid/style_tex.py` (append)
- Test: `tests/test_style_tex.py` (append the classes below, above `if __name__`)

**Interfaces:**
- Consumes: `key`, `to_plain`, `to_tex`, `_mask`, `_close` from Task 1.
- Produces:
  - `style_tex.locate(src: str, pieces: dict) -> doc` (the doc shape in the File Map)
  - `style_tex.render_source(doc, plan: dict) -> str`

  `pieces` has the shape of `tex_samples.PIECES`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_style_tex.py`:

```python
class Locate(unittest.TestCase):
    def setUp(self):
        self.doc = style_tex.locate(S.SAMPLE, S.PIECES)

    def test_finds_every_piece(self):
        d = self.doc
        self.assertEqual(d["headline"]["text"], "SENIOR BACKEND ENGINEER")
        self.assertIn("**7+ years**", d["summary"]["text"])
        self.assertFalse(d["summary"]["fixed"])
        self.assertEqual([j["id"] for j in d["jobs"]], ["r0", "r1"])
        self.assertEqual([b["id"] for b in d["jobs"][0]["bullets"]], ["r0b0", "r0b1", "r0b2"])
        self.assertEqual([b["fixed"] for b in d["jobs"][0]["bullets"]], [False, False, True])      # r0b2 has a link
        self.assertTrue(all(j["reorder"] for j in d["jobs"]))
        self.assertEqual([(l["label"], l["items"]) for l in d["skills"]],
                         [("Languages", ["Python", "Go", "SQL", "C#"]),
                          ("Cloud & Data", ["AWS", "Docker", "PostgreSQL", "Redis", "Airflow"])])
        self.assertTrue(d["skills_move"])

    def test_no_plan_gives_back_the_same_file(self):
        self.assertEqual(style_tex.render_source(self.doc, {}), S.SAMPLE)

    def test_reorder_keeps_every_bullet_exactly_once(self):
        out = style_tex.render_source(self.doc, {"order": {"r0": ["r0b2", "r0b0", "r0b1"]}})
        for b in self.doc["jobs"][0]["bullets"]:
            a, z = b["_span"]
            self.assertEqual(out.count(S.SAMPLE[a:z]), 1)
        self.assertLess(out.index("public API docs"), out.index("payments API"))
        self.assertEqual(len(out), len(S.SAMPLE))

    def test_rewording_changes_only_that_bullet(self):
        new = "Cut p95 latency 40% with **Redis** caching & fewer reads."
        out = style_tex.render_source(self.doc, {"text": {"r0b1": new}})
        tex = r"Cut p95 latency 40\% with \textbf{Redis} caching \& fewer reads."
        self.assertIn(tex, out)
        a, z = self.doc["jobs"][0]["bullets"][1]["_span"]
        self.assertEqual(out.replace(tex, S.SAMPLE[a:z]), S.SAMPLE)

    def test_fixed_bullet_keeps_its_text(self):
        self.assertEqual(style_tex.render_source(self.doc, {"text": {"r0b2": "Wrote docs for 12 endpoints."}}), S.SAMPLE)

    def test_skills_reorder_inside_and_between_lines(self):
        out = style_tex.render_source(self.doc, {"skills": {"s0": ["C#", "SQL", "Go", "Python"]}, "skill_lines": ["s1", "s0"]})
        self.assertIn(r"{Languages:} C\#, SQL, Go, Python.", out)
        self.assertLess(out.index(r"Cloud \& Data"), out.index("{Languages:}"))

    def test_bad_orders_are_ignored(self):
        out = style_tex.render_source(self.doc, {"order": {"r0": ["r0b0", "r0b0", "r0b1"]}, "skill_lines": ["s0"],
                                                 "skills": {"s0": ["Python", "Rust", "SQL", "C#"]}})
        self.assertEqual(out, S.SAMPLE)

    def test_headline_and_summary(self):
        out = style_tex.render_source(self.doc, {"headline": "SENIOR PYTHON ENGINEER",
                                                 "summary": "Python engineer with **7+ years** on payments."})
        self.assertIn(r"{\LARGE SENIOR PYTHON ENGINEER}", out)
        self.assertIn(r"Python engineer with \textbf{7+ years} on payments.", out)


class JakeTemplate(unittest.TestCase):
    def test_resume_item_macros_and_multi_line_skills(self):
        doc = style_tex.locate(S.JAKE, S.JAKE_PIECES)
        self.assertEqual([[b["id"] for b in j["bullets"]] for j in doc["jobs"]], [["r0b0", "r0b1", "r0b2"], ["r1b0", "r1b1"]])
        self.assertTrue(doc["jobs"][0]["bullets"][2]["fixed"])
        self.assertEqual([l["label"] for l in doc["skills"]], ["Languages", "Frameworks"])
        self.assertTrue(doc["skills_move"])
        out = style_tex.render_source(doc, {"order": {"r0": ["r0b1", "r0b0", "r0b2"]}, "skill_lines": ["s1", "s0"]})
        self.assertIn(r"\resumeItem{Cut p95 latency 40\% by moving hot reads to Redis} % comment, here", out)
        self.assertLess(out.index(r"\textbf{Frameworks}"), out.index(r"\textbf{Languages}"))
        self.assertIn(r"\small{\item{", out)                 # the braces around both skill lines stayed put
        self.assertEqual((out.count("{"), out.count("}")), (S.JAKE.count("{"), S.JAKE.count("}")))
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `python -m unittest tests.test_style_tex -v`
Expected: the new tests ERROR with `AttributeError: module 'teambid.style_tex' has no attribute 'locate'`.

- [ ] **Step 3: Append the locator and writer to `teambid/style_tex.py`**

```python
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
```

- [ ] **Step 4: Run the tests to see them pass**

Run: `python -m unittest tests.test_style_tex -v`
Expected: all tests PASS (16).

- [ ] **Step 5: Commit**

```bash
git add teambid/style_tex.py tests/test_style_tex.py
git commit -m "Keep style: find a .tex resume's bullets, summary, headline and skills, and write them back"
```

---

### Task 3: Build PDFs from LaTeX safely, and read .tex uploads

**Files:**
- Modify: `teambid/style_tex.py` (append)
- Modify: `teambid/resume_parse.py:87-135` (`extract_text`) and the docstring at line 8
- Test: `tests/test_style_tex.py` (append)

**Interfaces:**
- Consumes: `locate`, `render_source`, `_mask` from Tasks 1-2.
- Produces:
  - `style_tex.available() -> bool`
  - `style_tex.compile_tex(src: str, out_dir: Path, name: str) -> (Path, int)`, raises `ValueError`
  - `style_tex.find(path, pieces) -> doc` (with `doc["pages"]`)
  - `style_tex.build(doc, plan, folder: Path, base: str) -> {"pdf": str, "source": str, "pages": int, "paper": "A4"|"Letter"}`
  - `resume_parse.extract_text(path)` accepts `.tex`, with `meta["source"] == "tex"`

- [ ] **Step 1: Write the failing tests**

Add `import fitz`, `from teambid import resume_parse`, `import subprocess`, and `from unittest import mock` to the imports in `tests/test_style_tex.py`. Then append:

```python
@unittest.skipUnless(style_tex.available(), "pdflatex isn't installed here (the online Tests workflow has it)")
class Build(unittest.TestCase):
    def test_builds_the_sample(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            pdf, pages = style_tex.compile_tex(S.SAMPLE, Path(tmp), "resume")
            self.assertTrue(pdf.exists())
            self.assertEqual(pages, 1)

    def test_latex_errors_are_reported(self):
        with self.assertRaises(ValueError):
            style_tex.compile_tex(S.SAMPLE.replace("\\end{itemize}", "", 1), Path(tempfile.mkdtemp()), "broken")

    def test_no_shell_commands_and_no_reading_outside_the_folder(self):
        tmp = Path(tempfile.mkdtemp())
        evil = S.SAMPLE.replace("\\begin{document}", "\\begin{document}\\immediate\\write18{touch pwned}", 1)
        try:
            style_tex.compile_tex(evil, tmp, "evil")
        except ValueError:
            pass
        self.assertFalse((tmp / "pwned").exists())
        with self.assertRaises(ValueError):
            style_tex.compile_tex(S.SAMPLE.replace("\\begin{document}", "\\begin{document}\\input{/etc/hostname}", 1), tmp, "read")

    def test_find_then_build(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            src = Path(tmp) / "dana.tex"
            src.write_text(S.SAMPLE, encoding="utf-8")
            doc = style_tex.find(src, S.PIECES)
            self.assertEqual(doc["pages"], 1)
            files = style_tex.build(doc, {"order": {"r1": ["r1b1", "r1b0"]}}, Path(tmp), "out")
            self.assertEqual((files["pages"], files["paper"]), (1, "A4"))
            with fitz.open(files["pdf"]) as d:
                text = d[0].get_text()
            self.assertLess(text.index("Go unit tests"), text.index("cron jobs"))
            self.assertTrue(Path(files["source"]).read_text(encoding="utf-8").startswith("\\documentclass"))

    def test_extract_text_reads_a_tex_upload(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            src = Path(tmp) / "dana.tex"
            src.write_text(S.SAMPLE, encoding="utf-8")
            text, meta = resume_parse.extract_text(src)
        self.assertEqual((meta["source"], meta["file"]), ("tex", "dana.tex"))
        for b in [b for j in S.PIECES["jobs"] for b in j["bullets"]]:
            self.assertIn(key(b), key(text))        # what Claude copies from this text is found in the .tex


class BuildErrors(unittest.TestCase):
    def test_timeout(self):
        with mock.patch("teambid.style_tex.shutil.which", return_value="pdflatex"):
            with mock.patch("teambid.style_tex.subprocess.run", side_effect=subprocess.TimeoutExpired("pdflatex", 60)):
                with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                    with self.assertRaises(ValueError) as ctx:
                        style_tex.compile_tex(S.SAMPLE, Path(tmp), "x")
                    self.assertIn("longer than 60 s", str(ctx.exception))

    def test_retries_run_out(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            with mock.patch("teambid.style_tex.shutil.which", return_value="pdflatex"):
                call_count = [0]
                def mock_run(*args, **kwargs):
                    if "pdflatex" in args[0]:
                        call_count[0] += 1
                        log_file = Path(kwargs["cwd"]) / "x.log"
                        log_file.write_text(f"! LaTeX Error: File `pkg{call_count[0]}.sty' not found.", encoding="utf-8")
                        return subprocess.CompletedProcess(args[0], 1, "", "")
                    else:
                        return subprocess.CompletedProcess(args[0], 0, "", "")
                with mock.patch("teambid.style_tex.subprocess.run", side_effect=mock_run):
                    with self.assertRaises(ValueError) as ctx:
                        style_tex.compile_tex(S.SAMPLE, Path(tmp), "x")
                    self.assertTrue(str(ctx.exception).startswith("LaTeX error:"))
                    self.assertIn("not found", str(ctx.exception))
                    self.assertNotIn("made no PDF", str(ctx.exception))

    def test_relabel(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            src = Path(tmp) / "test.tex"
            src.write_text(S.SAMPLE, encoding="utf-8")
            with mock.patch("teambid.style_tex.compile_tex", side_effect=ValueError("LaTeX error: boom")):
                with self.assertRaises(ValueError) as ctx:
                    resume_parse.extract_text(src)
                self.assertIn("upload its PDF instead", str(ctx.exception))
```

- [ ] **Step 2: Run the tests to see them fail (or skip)**

Run: `python -m unittest tests.test_style_tex -v`
Expected: `AttributeError: module 'teambid.style_tex' has no attribute 'available'` (an error at import of the class decorator).

- [ ] **Step 3: Append the build functions to `teambid/style_tex.py`**

```python
TIMEOUT = 60                             # seconds per LaTeX run
FONTSPEC = re.compile(r"\\(?:usepackage|RequirePackage)\s*(?:\[[^\]]*\])?\s*\{[^}]*\bfontspec\b")


def available():
    return bool(shutil.which("pdflatex"))


def _latex_error(log):
    """Extract LaTeX error from log."""
    err = re.search(r"^! (.+)$", log, re.M)
    return f"LaTeX error: {err.group(1)[:160] if err else 'the build failed'}"


def compile_tex(src, out_dir, name):
    """Build src into out_dir/<name>.pdf. -> (pdf path, pages). Raises ValueError with LaTeX's own error line.
    Safe for a file someone uploaded: no shell commands, no reading or writing outside out_dir (openin_any/openout_any
    = paranoid), 60 s per run. A missing package is installed once with TinyTeX's tlmgr."""
    engine = "xelatex" if FONTSPEC.search(_mask(src)) else "pdflatex"
    exe = shutil.which(engine)
    if not exe:
        raise ValueError(f"{engine} isn't installed here, so a .tex resume can't be built")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{name}.tex").write_text(src, encoding="utf-8")
    env = dict(os.environ, openin_any="p", openout_any="p", shell_escape="f")
    cmd = [exe, "-no-shell-escape", "-interaction=nonstopmode", "-halt-on-error", f"{name}.tex"]
    tried, log_file = set(), out_dir / f"{name}.log"
    for _ in range(5):
        try:
            r = subprocess.run(cmd, cwd=out_dir, env=env, capture_output=True, text=True, errors="replace", timeout=TIMEOUT)
        except subprocess.TimeoutExpired:
            raise ValueError(f"LaTeX took longer than {TIMEOUT} s") from None
        log = log_file.read_text(encoding="utf-8", errors="replace") if log_file.exists() else r.stdout
        missing = re.search(r"File `([\w-]+)\.(?:sty|cls)' not found", log)
        if r.returncode and missing and missing.group(1) not in tried and shutil.which("tlmgr"):
            tried.add(missing.group(1))
            try:
                subprocess.run(["tlmgr", "install", missing.group(1)], capture_output=True, timeout=300)
            except subprocess.TimeoutExpired:
                pass
            continue
        if r.returncode:
            if "rerun" not in tried and "Rerun to get" in log:
                tried.add("rerun")
                continue
            raise ValueError(_latex_error(log))
        if "Rerun to get" in log and "rerun" not in tried:
            tried.add("rerun")
            continue
        break
    if r.returncode:
        raise ValueError(_latex_error(log))
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
```

- [ ] **Step 4: Read .tex uploads in `teambid/resume_parse.py`**

In `extract_text`, insert this just before the last line, `return p.read_text(encoding="utf-8", errors="replace"), meta`:

```python
    if ext == ".tex":                    # a LaTeX resume: read the text of the PDF it builds
        import tempfile
        from . import style_tex
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            try:
                pdf, _ = style_tex.compile_tex(p.read_text(encoding="utf-8", errors="replace"), Path(tmp), "resume")
            except ValueError as e:          # e.g. it needs a .cls or image that wasn't uploaded with it
                raise ValueError(f"couldn't build this .tex file ({e}); upload its PDF instead") from e
            text, meta = extract_text(pdf)
        meta.update(file=p.name, source="tex")
        return text, meta
```

Also change the docstring: replace `llm.refine_profile() can clean it further (it may only restructure what is in the text).` (line 8) with `keep_style.read() has Claude read it too (only strings found word for word in the text are kept).`

- [ ] **Step 5: Run the tests**

Run: `python -m unittest tests.test_style_tex -v`
Expected on this Windows machine: the Task 1-2 tests PASS, and `Build` shows `skipped 'pdflatex isn't installed here...'`. The `Build` tests run for real in the online `tests.yml` workflow (Task 7).

- [ ] **Step 6: Commit**

```bash
git add teambid/style_tex.py teambid/resume_parse.py tests/test_style_tex.py
git commit -m "Keep style: build LaTeX resumes safely and read .tex uploads"
```

---

### Task 4: Claude reads the resume once at upload

**Files:**
- Create: `teambid/keep_style.py` (first part)
- Modify:
  - `teambid/llm.py`: `_call` at lines 33-39, and replace `refine_profile` at lines 121-137
  - `teambid/service.py`: imports at line 10, `onboard` at lines 15-39, `reparse` at lines 301-317
  - `teambid/server.py:106`
  - `tb.py`: lines 4, 92 and 145
  - `teambid/static/index.html`: lines 246-250
  - `teambid/static/results.html:917`
- Test: `tests/test_keep_style.py`

**Interfaces:**
- Consumes: `style_text.key`; `tests.tex_samples.PIECES` and `SAMPLE_TEXT`.
- Produces:
  - `llm._call(system, user, max_tokens=1500, model=None, timeout=120)`
  - `llm.READ_RULES`
  - `llm.read_resume(text, model=None) -> (dict | None, note)`
  - `keep_style.confirm(reading, text) -> (pieces | None, note)`
  - `keep_style.read(text) -> (pieces | None, note)`
  - `keep_style.pieces_from_profile(profile) -> pieces`
  - `keep_style.apply_to_profile(profile, pieces) -> profile`
  - `keep_style.save_pieces(slug, src, pieces)`
  - `keep_style.load_pieces(slug, src) -> pieces | None`
  - `service.onboard(..., use_llm=True)`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_keep_style.py`:

```python
"""Keep-original-style: Claude's reading, the checks, the coordinator (stdlib unittest; Claude and LaTeX are faked)."""
import json
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

from teambid import config, keep_style, llm, local_ai, resume_parse, service, style_tex, tailor  # noqa: E402
from tests import tex_samples as S  # noqa: E402

local_ai.DISABLED = True


class TempWorkspace(unittest.TestCase):
    """Each class gets its own empty workspace (database, members), put back afterwards."""
    @classmethod
    def setUpClass(cls):
        cls._saved = (config.WORKSPACE, config.DB_PATH, config.MEMBERS, config.CACHE, config.REPORTS)
        tmp = Path(tempfile.mkdtemp(prefix="teambid-style-"))
        config.WORKSPACE, config.DB_PATH = tmp, tmp / "teambid.db"
        config.MEMBERS, config.CACHE, config.REPORTS = tmp / "members", tmp / "cache", tmp / "reports"

    @classmethod
    def tearDownClass(cls):
        config.WORKSPACE, config.DB_PATH, config.MEMBERS, config.CACHE, config.REPORTS = cls._saved


def reading(extra_bullet=None):
    r = json.loads(json.dumps(S.PIECES))
    if extra_bullet:
        r["jobs"][0]["bullets"].append(extra_bullet)
    return r


class Confirm(unittest.TestCase):
    def test_keeps_exact_copies_and_drops_inventions(self):
        r = reading("Led a team of 12 engineers.")
        r["skills"][0]["items"].append("Rust")
        pieces, note = keep_style.confirm(r, S.SAMPLE_TEXT)
        self.assertEqual(pieces["jobs"][0]["bullets"], S.PIECES["jobs"][0]["bullets"])
        self.assertEqual([l["label"] for l in pieces["skills"]], ["Cloud & Data"])       # the line with Rust is dropped
        self.assertEqual(pieces["headline"], "SENIOR BACKEND ENGINEER")
        self.assertIn("5 of 6 bullets", note)

    def test_bullets_must_come_in_reading_order(self):
        r = reading()
        r["jobs"] = r["jobs"][::-1]
        self.assertIsNone(keep_style.confirm(r, S.SAMPLE_TEXT)[0])

    def test_too_many_misses_rejects_the_reading(self):
        r = {"jobs": [{"title": "x", "bullets": ["Invented one.", "Invented two.", S.PIECES["jobs"][0]["bullets"][0]]}]}
        pieces, note = keep_style.confirm(r, S.SAMPLE_TEXT)
        self.assertIsNone(pieces)
        self.assertIn("2 of 3", note)

    def test_headline_not_in_the_text_is_dropped(self):
        r = reading()
        r["headline"] = "STAFF ENGINEER"
        self.assertEqual(keep_style.confirm(r, S.SAMPLE_TEXT)[0]["headline"], "")


class ApplyToProfile(unittest.TestCase):
    def test_replaces_jobs_and_works_out_years_again(self):
        profile = resume_parse.parse(S.SAMPLE_TEXT)
        profile["raw_text"] = S.SAMPLE_TEXT
        keep_style.apply_to_profile(profile, S.PIECES)
        self.assertEqual([r["company"] for r in profile["roles"]], ["Northwind Labs", "Contoso Freight"])
        self.assertEqual((profile["roles"][0]["end"], profile["roles"][1]["end"]), ("Present", "2022-02"))
        self.assertTrue(profile["roles"][0]["current"])
        self.assertTrue(any("40" in m for m in profile["metrics"]))
        self.assertGreater(profile["years_experience"], 5)
        self.assertEqual(profile["headline"], "SENIOR BACKEND ENGINEER")


class Onboard(TempWorkspace):
    def _src(self):
        src = Path(tempfile.mkdtemp()) / "dana.txt"
        src.write_text(S.SAMPLE_TEXT, encoding="utf-8")
        return src

    def test_claude_reading_replaces_the_parse_and_is_saved(self):
        with mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm, "read_resume", return_value=(reading("Led a team of 12 engineers."), "read")):
            r = service.onboard("Dana Reyes", resume_path=self._src())
        self.assertEqual([len(x["bullets"]) for x in r["profile"]["roles"]], [3, 2])
        folder = config.member_dir(r["slug"]) / "resume"
        self.assertEqual(json.loads((folder / "pieces.json").read_text(encoding="utf-8"))["source"], "dana.txt")
        self.assertEqual(keep_style.load_pieces(r["slug"], folder / "dana.txt")["jobs"][1]["company"], "Contoso Freight")

    def test_saved_pieces_belong_to_one_exact_file(self):
        with mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm, "read_resume", return_value=(reading(), "read")):
            r = service.onboard("Dana Two", resume_path=self._src())
        f = config.member_dir(r["slug"]) / "resume" / "dana.txt"
        f.write_text(S.SAMPLE_TEXT + "\nchanged", encoding="utf-8")
        self.assertIsNone(keep_style.load_pieces(r["slug"], f))

    def test_without_claude_the_rule_based_parse_stays(self):
        with mock.patch.object(llm, "available", return_value=False):
            r = service.onboard("Dana Three", resume_path=self._src())
        self.assertFalse((config.member_dir(r["slug"]) / "resume" / "pieces.json").exists())


class ReadPrompt(unittest.TestCase):
    def test_reads_the_whole_text_with_sonnet(self):
        with mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm, "_call", return_value='Here: {"jobs": []}') as call:
            data, _ = llm.read_resume("x" * 20000)
        self.assertEqual(data, {"jobs": []})
        system, user, max_tokens, model = call.call_args[0]
        self.assertEqual((system, max_tokens, model), (llm.READ_RULES, 16000, llm.MODELS["sonnet"][0]))
        self.assertIn("x" * 20000, user)
        self.assertEqual(call.call_args[1]["timeout"], 300)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `python -m unittest tests.test_keep_style -v`
Expected: ERROR, `ImportError: cannot import name 'keep_style' from 'teambid'`

- [ ] **Step 3: Add the timeout to `llm._call` and replace `refine_profile` with `read_resume`**

In `teambid/llm.py`, change `_call` (lines 33-39) to:

```python
def _call(system, user, max_tokens=1500, model=None, timeout=120):
    r = requests.post(API, timeout=timeout, headers={"x-api-key": config.ANTHROPIC_KEY, "anthropic-version": "2023-06-01",
                                                     "content-type": "application/json"},
                      json={"model": model or config.MODEL, "max_tokens": max_tokens, "system": system,
                            "messages": [{"role": "user", "content": user}]})
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
```

Delete the whole `refine_profile` function (lines 121-137). Put this in its place:

```python
READ_RULES = (
    "You read one resume and return its structure as JSON. Copy every string EXACTLY as it appears in the resume text: "
    "same words, punctuation, capitals and numbers. Join words that a line break split, but never reword, shorten, merge, "
    "split, add or drop anything.\n"
    "headline: the title line under the name (\"\" if there is none). summary: the whole profile or summary paragraph "
    "(\"\" if none). jobs: every work-experience entry (full-time, part-time, contract, consulting), in the order they "
    "appear, each with title, company, location (\"\" if none), start and end as YYYY-MM (end \"Present\" for a current "
    "job, YYYY-01 when only the year is given) and bullets: every bullet under that job, in order. skills: each labeled "
    "line of the skills section as {label, items} with the items split at the commas ([] when the skills aren't labeled "
    "lines).\n"
    "Return ONLY JSON: {\"headline\": \"...\", \"summary\": \"...\", \"jobs\": [{\"title\": \"...\", \"company\": \"...\", "
    "\"location\": \"...\", \"start\": \"YYYY-MM\", \"end\": \"YYYY-MM or Present\", \"bullets\": [\"...\"]}], "
    "\"skills\": [{\"label\": \"...\", \"items\": [\"...\"]}]}")


def read_resume(text, model=None):
    """Claude reads the whole resume once (at upload) and returns its structure. -> (dict or None, note).
    keep_style.confirm() then keeps only the strings that really are in the text."""
    if not available():
        return None, "no Claude API key"
    try:
        out = _call(READ_RULES, f"RESUME TEXT:\n{text[:60000]}", 16000, model or MODELS["sonnet"][0], timeout=300)
        return json.loads(re.search(r"\{.*\}", out, re.S).group(0)), "read by Claude"
    except Exception as e:
        return None, f"Claude reading skipped: {e}"
```

- [ ] **Step 4: Create `teambid/keep_style.py`**

```python
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
        if label and len(items) >= 2 and at(label, shortest=2) >= 0 and all(at(x, shortest=1) >= 0 for x in items):
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
```

- [ ] **Step 5: Run Claude's reading in `service.onboard` and `service.reparse`**

In `teambid/service.py` line 10, add `keep_style` to the import:

```python
from . import analyze, config, cover, keep_style, llm, render, resume_parse, storage, tailor, vault, writing
```

In `onboard`:
- Change the signature default to `use_llm=True`.
- Replace lines 29-39 (the block from `note = ""` through `resume_parse.derive(profile)`) with:

```python
    note = ""
    if use_llm and llm.available():      # Claude reads jobs, bullets, summary and skills; code keeps only exact copies
        pieces, note = keep_style.read(profile["raw_text"])
        if pieces:
            keep_style.apply_to_profile(profile, pieces)
            keep_style.save_pieces(slug, dst, pieces)
```

In `reparse`, replace these two lines:

```python
    files = sorted(f for f in (config.member_dir(slug) / "resume").iterdir() if f.suffix.lower() in (".pdf", ".docx", ".txt", ".md"))
```
```python
    profile = resume_parse.parse_file(files[0])
```

with:

```python
    files = sorted((f for f in (config.member_dir(slug) / "resume").iterdir()
                    if f.suffix.lower() in (".tex", ".pdf", ".docx", ".txt", ".md")),
                   key=lambda f: (f.suffix.lower() != ".tex", f.name))          # a .tex source wins over its PDF
```
```python
    profile = resume_parse.parse_file(files[0])
    if llm.available():
        pieces, _ = keep_style.read(profile["raw_text"])
        if pieces:
            keep_style.apply_to_profile(profile, pieces)
            keep_style.save_pieces(slug, files[0], pieces)
```

- [ ] **Step 6: Make the reading the default in the local app and CLI, and accept .tex uploads**

`teambid/server.py:106`: change `use_llm=bool(b.get("use_llm")))` to `use_llm=bool(b.get("use_llm", True)))`.

`tb.py`:
- Line 4: change `[--llm]` to `[--no-llm]`.
- Line 92: change `s.add_argument("--llm", action="store_true")` to `s.add_argument("--no-llm", action="store_true")`.
- Line 145: change `use_llm=a.llm` to `use_llm=not a.no_llm`.

`teambid/static/index.html`:
- Line 246: change `Upload a resume (PDF, DOCX or TXT).` to `Upload a resume (PDF, DOCX, TXT or a LaTeX .tex file).`
- Line 248: change `accept=".pdf,.docx,.txt,.md"` to `accept=".pdf,.docx,.txt,.md,.tex"`.
- Line 250: change `<label>Use Claude API to clean the parse</label><label><input id="n_llm" type="checkbox"> only if ANTHROPIC_API_KEY is set</label>` to `<label>Read the resume with Claude</label><label><input id="n_llm" type="checkbox" checked> when ANTHROPIC_API_KEY is set</label>`.

`teambid/static/results.html:917`: change `Resume (PDF, DOCX or TXT, up to 1.5 MB)<input id="a_file" type="file" accept=".pdf,.docx,.txt,.md">` to `Resume (PDF, DOCX, TXT or LaTeX .tex, up to 1.5 MB)<input id="a_file" type="file" accept=".pdf,.docx,.txt,.md,.tex">`.

- [ ] **Step 7: Run the tests**

Run: `python -m unittest tests.test_keep_style -v`
Expected: all tests PASS (9).

Run: `python tb.py test`
Expected: the whole suite passes. Nothing else used `refine_profile`. Check with `grep -rn refine_profile teambid tests tb.py`, which should find nothing.

- [ ] **Step 8: Commit**

```bash
git add teambid/keep_style.py teambid/llm.py teambid/service.py teambid/server.py tb.py teambid/static/index.html teambid/static/results.html tests/test_keep_style.py
git commit -m "Keep style: Claude reads each resume once at upload; only exact copies are kept"
```

---

### Task 5: Claude rewrites the pieces, code checks every change

**Files:**
- Modify:
  - `teambid/tailor.py`: `build_resume` at lines 125-133
  - `teambid/llm.py`: `rewrite_resume` at lines 283-290, plus new `_summary_ok`, `TAILOR_RULES` and `tailor_in_place`
  - `teambid/keep_style.py` (append, and update the imports)
- Test: `tests/test_keep_style.py` (append)

**Interfaces:**
- Consumes:
  - `style_tex.locate` (Task 2), which builds the doc in tests
  - `llm._bullet_ok(new, old, have)` (existing)
  - `tailor._bullet_score(text, weights, sem=None)` (existing)
- Produces:
  - `tailor.jd_weights(jd) -> Counter`
  - `llm._summary_ok(new, old, profile, lo=0.6, hi=1.4) -> bool`
  - `llm.TAILOR_RULES`
  - `llm.tailor_in_place(doc, jd_text, model=None) -> (dict | None, note)`
  - `keep_style.LENGTH`
  - `keep_style.clean_bold(new, old) -> str`
  - `keep_style.headline_ok(new, old, profile, job_title) -> str | None`
  - `keep_style.default_plan(doc, jd) -> plan`
  - `keep_style.check(doc, reply, profile, jd) -> plan`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_keep_style.py` (above `if __name__`):

```python
JD_TEXT = """Senior Python Engineer
Acme builds backend services for freight.
Requirements
- Go backend services and Redis caching
- PostgreSQL
Benefits
- Health insurance
"""
PROFILE = {"raw_text": S.SAMPLE_TEXT, "level": "senior",
           "skills": {"all": ["Python", "Go", "SQL", "C#", "AWS", "Docker", "PostgreSQL", "Redis", "Airflow", "FastAPI",
                              "Unit testing"]},
           "roles": [{"title": "Senior Backend Engineer", "company": "Northwind Labs"},
                     {"title": "Backend Engineer", "company": "Contoso Freight"}]}


class Checks(unittest.TestCase):
    def setUp(self):
        self.doc = style_tex.locate(S.SAMPLE, S.PIECES)
        self.jd = tailor.analyze_jd(JD_TEXT, "Senior Python Engineer", "Acme")

    def plan(self, **reply):
        return keep_style.check(self.doc, reply, PROFILE, self.jd)

    def test_default_order_puts_what_the_job_needs_first(self):
        p = keep_style.default_plan(self.doc, self.jd)
        self.assertEqual(p["order"]["r0"], ["r0b1", "r0b0", "r0b2"])          # the Redis bullet first
        self.assertEqual(p["order"]["r1"], ["r1b1", "r1b0"])                  # the Go bullet first
        self.assertEqual(p["skills"]["s0"], ["Go", "Python", "SQL", "C#"])
        self.assertEqual(p["skills"]["s1"], ["PostgreSQL", "Redis", "AWS", "Docker", "Airflow"])
        self.assertEqual(p["skill_lines"], ["s1", "s0"])
        self.assertEqual((p["text"], p["headline"], p["summary"]), ({}, None, None))

    def test_an_order_must_hold_every_bullet_once(self):
        default = keep_style.default_plan(self.doc, self.jd)["order"]["r0"]
        for bad in (["r0b0", "r0b1"], ["r0b0", "r0b0", "r0b1"], ["r0b0", "r0b1", "r0b9"]):
            self.assertEqual(self.plan(order={"r0": bad})["order"]["r0"], default, bad)
        self.assertEqual(self.plan(order={"r0": ["r0b2", "r0b0", "r0b1"]})["order"]["r0"], ["r0b2", "r0b0", "r0b1"])

    def test_bullet_rewording_rules(self):
        ok = "Built a payments API in **Python** and **FastAPI** handling 2M requests a day."
        self.assertEqual(self.plan(bullets={"r0b0": ok})["text"]["r0b0"], ok)
        for bad in ("Built a high-throughput payments API in Python and FastAPI that reliably handles 2M requests every day.",
                    "Built a payments API in Python and FastAPI that handles 3M requests a day.",
                    "Built a payments API in Python, FastAPI and Kafka that handles 2M requests a day."):
            self.assertNotIn("r0b0", self.plan(bullets={"r0b0": bad})["text"], bad)
        self.assertNotIn("r0b2", self.plan(bullets={"r0b2": "Wrote the public API docs for all 12 endpoints."})["text"])

    def test_bold_only_on_tools_and_only_where_the_original_had_bold(self):
        got = self.plan(bullets={"r0b0": "Built a **payments** API in **Python** and FastAPI handling 2M requests a day."})
        self.assertEqual(got["text"]["r0b0"], "Built a payments API in **Python** and FastAPI handling 2M requests a day.")
        got = self.plan(bullets={"r1b0": "Moved 30 cron jobs into **Airflow**, ending missed nightly runs."})
        self.assertEqual(got["text"]["r1b0"], "Moved 30 cron jobs into Airflow, ending missed nightly runs.")

    def test_headline_rules(self):
        self.assertEqual(self.plan(headline="Senior Python Engineer")["headline"], "SENIOR PYTHON ENGINEER")
        for bad in ("Staff Python Engineer", "Senior Rust Engineer", "Principal Engineer"):
            self.assertIsNone(self.plan(headline=bad)["headline"], bad)

    def test_skills_can_only_be_reordered(self):
        p = self.plan(skills={"s0": ["SQL", "C#", "Python", "Go"], "s1": ["AWS", "Docker", "Kubernetes", "Redis", "Airflow"]},
                      skill_lines=["s0", "s1"])
        self.assertEqual(p["skills"]["s0"], ["SQL", "C#", "Python", "Go"])
        self.assertEqual(p["skills"]["s1"], keep_style.default_plan(self.doc, self.jd)["skills"]["s1"])
        self.assertEqual(p["skill_lines"], ["s0", "s1"])

    def test_summary_keeps_its_facts_and_length(self):
        ok = "Backend engineer with **7+ years** building Go and Python services for logistics and payments."
        self.assertEqual(self.plan(summary=ok)["summary"], ok)
        self.assertIsNone(self.plan(summary="Backend engineer with 11+ years building Go and Python services for payments.")["summary"])


class TailorPrompt(unittest.TestCase):
    def test_sends_every_piece_with_its_id(self):
        doc = style_tex.locate(S.SAMPLE, S.PIECES)
        with mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm, "_call", return_value='Sure: {"bullets": {}}') as call:
            reply, _ = llm.tailor_in_place(doc, "We need Go.", "claude-haiku-5-5")
        self.assertEqual(reply, {"bullets": {}})
        system, user, max_tokens, model = call.call_args[0]
        self.assertEqual((system, max_tokens, model), (llm.TAILOR_RULES, 8000, "claude-haiku-5-5"))
        for needle in ("HEADLINE: SENIOR BACKEND ENGINEER", "r0: Senior Backend Engineer at Northwind Labs",
                       "r0b0: Built a payments API in **Python**", "r0b2 (fixed): Wrote the public API docs",
                       "s1 - Cloud & Data: AWS, Docker"):
            self.assertIn(needle, user)
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `python -m unittest tests.test_keep_style -v`
Expected: the new tests ERROR, `AttributeError: module 'teambid.keep_style' has no attribute 'check'` (and `default_plan`, `tailor_in_place`).

- [ ] **Step 3: Take `jd_weights` out of `tailor.build_resume`**

In `teambid/tailor.py`, add above `def build_resume`:

```python
def jd_weights(jd):
    """How much each skill matters to this job: must-haves 3, nice-to-haves 1.5, plus 0.5 per mention (3 at most)."""
    weights = Counter()
    for s in jd["required"]:
        weights[s] += 3
    for s in jd["preferred"]:
        weights[s] += 1.5
    for s, n in jd["all"].items():
        weights[s] += min(n, 3) * 0.5
    return weights
```

In `build_resume`, replace the first 7 lines of the body (`weights = Counter()` through `weights[s] += min(n, 3) * 0.5`) with `weights = jd_weights(jd)`.

- [ ] **Step 4: Add `_summary_ok` and `tailor_in_place` to `teambid/llm.py`**

Add above `def rewrite_resume`:

```python
def _summary_ok(new, old, profile, lo=0.6, hi=1.4):
    """A reworded summary keeps to the resume's numbers and tools, avoids the banned words and stays about as long."""
    have = set(profile.get("skills", {}).get("all", []))
    raw = profile.get("raw_text", "") + " " + old
    return bool(new and new != old and all(n in raw for n in _numbers(new))
                and not [s for s in SK.find(new) if s not in have]
                and not any(re.search(rf"\b{re.escape(w)}\b", new.lower()) for w in writing.BANNED)
                and lo <= len(new) / max(1, len(old)) <= hi)
```

In `rewrite_resume`, replace lines 283-290 (from `s_new, s_old = ...` through the `took += 1` under the summary `if`) with:

```python
    s_new, s_old = str(data.get("summary", "")).strip(), spec.get("summary", "")
    if _summary_ok(s_new, s_old, profile):
        spec["summary"] = s_new
        took += 1
```

Append at the end of `teambid/llm.py`:

```python
TAILOR_RULES = (
    "You are a senior engineering recruiter tailoring one candidate's resume to one job post. You edit the text inside "
    "their own resume file, so the layout stays theirs. You get their headline, summary, every bullet of every job "
    "(each with an ID) and their skills lines. Make a hiring manager for THIS job see the match in a 6-second skim.\n"
    "Bullets: past-tense action verb first, then what was built or changed, then the result. Use the job post's own "
    "term when the bullet truly shows it. Lead with the part that matters most to this job. One or two job terms per "
    "bullet at most, never stuff keywords. Each bullet stays within 10% longer or 25% shorter than its original. Words "
    "wrapped in ** are bold in the file: you may bold tool or skill names the same way, only in bullets that already "
    "use **. Bullets marked (fixed) can move but keep their text. If a bullet is already strong for this job, return "
    "it unchanged.\n"
    "order: for every job, list ALL of its bullet IDs exactly once, the most relevant to this job first.\n"
    "headline: the job post's title when the candidate has held that kind of role at that level, else their own "
    "headline, in the same capital-letter style as the original. Never a higher level (lead, staff, principal, "
    "manager, architect, head) than a title they have held.\n"
    "summary: the same facts, aimed at this job's main need, about the same length.\n"
    "skills: every line with exactly the same items, the ones this job asks for first. skill_lines: every line ID "
    "once, the lines this job cares about first.\n"
    "Hard rules: keep every number exactly as written. Keep the same facts, scope and seniority (no 'led' if they "
    "'helped'). Never add a tool, skill, company, metric or result that isn't in the original. No em dashes, no "
    "semicolons, no first person.\n"
    "Never use these words: " + ", ".join(sorted(writing.BANNED)) + ".\n"
    "Return ONLY JSON: {\"headline\": \"...\", \"summary\": \"...\", \"bullets\": {\"<id>\": \"...\"}, "
    "\"order\": {\"<job id>\": [\"<bullet id>\", ...]}, \"skills\": {\"<line id>\": [\"...\"]}, "
    "\"skill_lines\": [\"<line id>\", ...]}")


def tailor_in_place(doc, jd_text, model=None):
    """Claude rewrites and reorders the pieces of the member's own file (keep_style doc) for one job post.
    -> (reply dict or None, note). keep_style.check() decides what of it is used."""
    if not available():
        return None, "no Claude API key"
    lines = [f"JOB POST:\n{jd_text[:12000]}", ""]
    if doc.get("headline"):
        lines.append(f"HEADLINE: {doc['headline']['text']}")
    if doc.get("summary"):
        lines.append(f"SUMMARY{' (fixed)' if doc['summary']['fixed'] else ''}: {doc['summary']['text']}")
    lines.append("\nJOBS:")
    for j in doc["jobs"]:
        lines.append(f"{j['id']}: {j['title']} at {j['company']} ({j['start']} - {j['end']})")
        lines += [f"  {b['id']}{' (fixed)' if b['fixed'] else ''}: {b['text']}" for b in j["bullets"]]
    if doc.get("skills"):
        lines.append("\nSKILLS:")
        lines += [f"{l['id']} - {l['label']}: {', '.join(l['items'])}" for l in doc["skills"]]
    try:
        out = _call(TAILOR_RULES, "\n".join(lines), 8000, model, timeout=300)
        return json.loads(re.search(r"\{.*\}", out, re.S).group(0)), "ok"
    except Exception as e:
        return None, f"Claude resume step skipped: {e}"
```

- [ ] **Step 5: Append the checks to `teambid/keep_style.py`**

Change the imports to:

```python
from . import config, llm, resume_parse, tailor
from . import skills as SK
from .style_text import key
```

Append:

```python
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


def _bullet_new(new, old, have):
    """Claude's rewording of one bullet if it passes the fact checks and the length limits, else None."""
    new = clean_bold(new, old)
    n, o = new.replace("**", ""), old.replace("**", "")
    ok = llm._bullet_ok(n, o, have) and LENGTH[0] <= len(n) / max(1, len(o)) <= LENGTH[1]
    return new if ok else None


def headline_ok(new, old, profile, job_title):
    """The new headline in the original's capital-letter style, or None. Its words must come from titles the member
    held or the job's title, with no level above one they held and no tool they don't list."""
    new = re.sub(r"\s+", " ", re.sub(r"[\\`<>{}*]", "", str(new or ""))).strip()
    if not new or key(new) == key(old) or len(new) > max(60, 1.5 * len(old)):
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
    w = tailor.jd_weights(jd)
    weight = lambda item: sum(w.get(s, 0) for s in SK.find(item, trusted=True))
    plan = {"headline": None, "summary": None, "text": {}, "order": {}, "skills": {}, "skill_lines": []}
    for j in doc["jobs"]:
        if j["reorder"]:
            ranked = sorted(j["bullets"], key=lambda b: -tailor._bullet_score(b["text"].replace("**", ""), w))
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
        got = [str(x) for x in orders.get(j["id"]) or []]
        if j["reorder"] and sorted(got) == sorted(b["id"] for b in j["bullets"]):
            plan["order"][j["id"]] = got
        for b in j["bullets"]:
            new = _bullet_new(texts.get(b["id"]), b["text"], have)
            if new and not b["fixed"]:
                plan["text"][b["id"]] = new
    s = doc.get("summary")
    if s and not s["fixed"]:
        new = clean_bold(reply.get("summary"), s["text"])
        if llm._summary_ok(new.replace("**", ""), s["text"].replace("**", ""), profile, *LENGTH):
            plan["summary"] = new
    h = doc.get("headline")
    if h and not h["fixed"]:
        plan["headline"] = headline_ok(reply.get("headline"), h["text"], profile, jd.get("title", ""))
    lines = reply.get("skills") if isinstance(reply.get("skills"), dict) else {}
    for line in doc["skills"]:
        got = [str(x).strip() for x in lines.get(line["id"]) or []]
        if got and sorted(map(key, got)) == sorted(map(key, line["items"])):
            plan["skills"][line["id"]] = got
    got = [str(x) for x in reply.get("skill_lines") or []]
    if doc.get("skills_move") and got and sorted(got) == sorted(l["id"] for l in doc["skills"]):
        plan["skill_lines"] = got
    return plan
```

- [ ] **Step 6: Run the tests**

Run: `python -m unittest tests.test_keep_style -v`
Expected: all tests PASS (17).

Run: `python -m unittest tests.test_docs tests.test_teambid -v`
Expected: PASS. The existing `rewrite_resume` summary check and `build_resume` behave exactly as before.

- [ ] **Step 7: Commit**

```bash
git add teambid/tailor.py teambid/llm.py teambid/keep_style.py tests/test_keep_style.py
git commit -m "Keep style: Claude rewrites and reorders the pieces; code checks facts, length, order and bold"
```

---

### Task 6: The coordinator, `service.apply`, and the downloads

**Files:**
- Modify:
  - `teambid/keep_style.py` (append, and update the imports)
  - `teambid/service.py:144-182` (in `apply`)
  - `teambid/docs.py:18` and `117-121`
  - `teambid/static/results.html:477`
  - `teambid/static/index.html:357`
- Test: `tests/test_keep_style.py` (append)

**Interfaces:**
- Consumes:
  - `style_tex.find` and `build` (Task 3)
  - `keep_style.read`, `confirm`, `pieces_from_profile`, `load_pieces` and `save_pieces` (Task 4)
  - `keep_style.default_plan` and `check`, and `llm.tailor_in_place` (Task 5)
- Produces:
  - `keep_style.HANDLERS`
  - `keep_style.source_file(slug, member) -> Path | None`
  - `keep_style.pieces_for(slug, profile, src) -> pieces | None`
  - `keep_style._build(handler, doc, plan, folder, base) -> (files, reverted: int)`
  - `keep_style.report_spec(doc, plan) -> spec`
  - `keep_style.tailor(slug, member, profile, jd, jd_text, model, folder, base) -> dict`

  `tailor()` returns `{"files", "spec", "note"}` on success, `{"note"}` when it fell back, and `{}` when the member has no editable file.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_keep_style.py` (above `if __name__`):

```python
def fake_compile(src, out_dir, name):
    """Stands in for pdflatex: a one-page A4 PDF holding the text of the source, line by line."""
    lines = []
    for line in src.split("\\begin{document}")[-1].splitlines():
        try:
            lines.append(style_tex.to_plain(line)[0].replace("**", ""))
        except ValueError:
            pass
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(36, 36, 560, 806), "\n".join(l for l in lines if l), fontsize=6)
    pdf = Path(out_dir) / f"{name}.pdf"
    doc.save(pdf)
    return pdf, 1


class PageGuard(unittest.TestCase):
    def test_puts_back_the_bullet_that_grew_most(self):
        doc = {"pages": 1, "summary": None,
               "jobs": [{"id": "r0", "bullets": [{"id": "r0b0", "text": "short"}, {"id": "r0b1", "text": "also short"}]}]}
        plan = {"text": {"r0b0": "a much much longer bullet", "r0b1": "also short!"}, "summary": None}
        handler = mock.Mock()
        handler.build.side_effect = lambda d, p, f, b: {"pages": 2 if "r0b0" in p["text"] else 1}
        files, reverted = keep_style._build(handler, doc, plan, Path("."), "x")
        self.assertEqual((files["pages"], reverted, list(plan["text"])), (1, 1, ["r0b1"]))

    def test_gives_up_when_nothing_grew(self):
        handler = mock.Mock()
        handler.build.return_value = {"pages": 2}
        with self.assertRaises(ValueError):
            keep_style._build(handler, {"pages": 1, "jobs": [], "summary": None}, {"text": {}, "summary": None}, Path("."), "x")


class ApplyWithTex(TempWorkspace):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        src = Path(tempfile.mkdtemp()) / "dana.tex"
        src.write_text(S.SAMPLE, encoding="utf-8")
        with mock.patch.object(style_tex, "compile_tex", fake_compile), \
             mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm, "read_resume", return_value=(reading(), "read")):
            cls.slug = service.onboard("Dana Reyes", resume_path=src)["slug"]

    def _apply(self, reply, compile_fn=fake_compile):
        with mock.patch.object(style_tex, "compile_tex", compile_fn), \
             mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm, "tailor_in_place", return_value=(reply, "ok")), \
             mock.patch.object(llm, "write_letter", side_effect=lambda p, jd, c, t, letter, model: (letter, "kept")), \
             mock.patch.object(llm, "rewrite_resume", side_effect=lambda spec, *a: (spec, "reworded")):
            return service.apply(self.slug, jd_text=JD_TEXT, company="Acme", title="Senior Python Engineer", ai="haiku")

    def test_tailors_inside_the_members_own_file(self):
        r = self._apply({"order": {"r1": ["r1b1", "r1b0"]},
                         "bullets": {"r0b0": "Built a payments API in **Python** and **FastAPI** handling 2M requests a day."}})
        tex = Path(r["files"]["source"]).read_text(encoding="utf-8")
        self.assertIn(r"Built a payments API in \textbf{Python} and \textbf{FastAPI} handling 2M requests a day.", tex)
        self.assertLess(tex.index("Go unit tests"), tex.index("cron jobs"))
        self.assertTrue(tex.startswith(S.SAMPLE[:S.SAMPLE.index("\\section*{Profile}")]))      # header untouched
        self.assertTrue(Path(r["files"]["pdf"]).exists())
        self.assertNotIn("docx", r["files"])
        self.assertTrue(Path(r["files"]["letter_pdf"]).exists())                              # the letter as before
        self.assertIn("Resume style: original (.tex)", r["resume_ai"])
        self.assertEqual(r["problems"], [])
        report = (Path(r["folder"]) / "report.md").read_text(encoding="utf-8")
        self.assertIn("Resume style: original (.tex)", report)

    def test_falls_back_to_rendercv_when_latex_fails(self):
        def broken(src, out_dir, name):
            raise ValueError("LaTeX error: Undefined control sequence.")
        r = self._apply({}, broken)
        self.assertTrue(Path(r["files"]["docx"]).exists())
        self.assertIn("original style skipped: LaTeX error", r["resume_ai"])

    def test_members_without_a_tex_file_are_untouched(self):
        self.assertEqual(keep_style.tailor("nobody-here", {"resume_file": "x.pdf"}, {}, {}, "", None, ".", "b"), {})
```

- [ ] **Step 2: Run the tests to see them fail**

Run: `python -m unittest tests.test_keep_style -v`
Expected: the new tests ERROR, `AttributeError: module 'teambid.keep_style' has no attribute '_build'` (and `tailor`). `test_tailors_inside_the_members_own_file` fails because `r["files"]` has no `"source"`.

- [ ] **Step 3: Append the coordinator to `teambid/keep_style.py`**

Change the imports to:

```python
from . import config, llm, resume_parse, style_tex, tailor
from . import skills as SK
from .style_text import key
```

Append:

```python
HANDLERS = {".tex": style_tex}        # .docx and PDF handlers come in parts 2 and 3


def source_file(slug, member):
    """The member's own resume file a handler can edit, or None (today's RenderCV resume is used then)."""
    folder = config.member_dir(slug) / "resume"
    stored = Path((member or {}).get("resume_file") or "")
    if stored.suffix.lower() in HANDLERS and (folder / stored.name).exists():    # the stored path may be another PC's
        return folder / stored.name
    found = sorted(f for f in folder.iterdir() if f.suffix.lower() in HANDLERS)
    return found[0] if found else None


def pieces_for(slug, profile, src):
    """The confirmed pieces of the member's file: the saved ones while the file is unchanged, else read again (Claude
    when a key is set, the rule-based parse if not) and saved."""
    saved = load_pieces(slug, src)
    if saved:
        return saved
    text, _ = resume_parse.extract_text(src)
    pieces = read(text)[0] if llm.available() else None
    if not pieces:
        pieces = confirm(pieces_from_profile(profile), text)[0]
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
    try:
        pieces = pieces_for(slug, profile, src)
        if not pieces:
            return {"note": "original style skipped: couldn't read the resume's parts"}
        doc = handler.find(src, pieces)
        if not doc["jobs"]:
            return {"note": "original style skipped: couldn't find the job bullets in the file"}
        plan, why, reply = default_plan(doc, jd), "no Claude: reordered only", None
        if model:
            reply, why = llm.tailor_in_place(doc, jd_text, model)
            if reply:
                plan, why = check(doc, reply, profile, jd), ""
        files, reverted = _build(handler, doc, plan, Path(folder), base)
    except Exception as e:                       # any failure: today's RenderCV resume is used instead
        return {"note": f"original style skipped: {str(e)[:160]}"}
    total = sum(len(j["bullets"]) for j in doc["jobs"])
    moved = sum(1 for j in doc["jobs"] if plan["order"].get(j["id"], [b["id"] for b in j["bullets"]]) != [b["id"] for b in j["bullets"]])
    note = (f"Resume style: original ({doc['ext']}). {len(plan['text'])} of {total} bullets reworded, "
            f"{total - len(plan['text'])} kept as written, order changed in {moved} jobs, "
            f"{files['pages']} page(s) (original {doc['pages']})")
    if reverted:
        note += f", put back {reverted} longer piece(s) to keep the page count"
    if why:
        note += f" ({why})"
    spec = report_spec(doc, plan)
    spec["style"]["claude_reply"] = reply        # spec.json shows what Claude sent next to what passed the checks
    return {"files": files, "spec": spec, "note": note}
```

- [ ] **Step 4: Wire it into `service.apply`**

In `teambid/service.py` `apply`, replace:

```python
    if use_claude:                    # reword the chosen bullets toward the post (numbers, facts and tools kept)
        spec, resume_note = llm.rewrite_resume(spec, p, jd_text, model)
    problems = tailor.validate(spec, p)
    kw = tailor.keyword_report(spec, jd)
    letter, letter_check = cover.draft_letter(p, jd, fit)
```

with:

```python
    letter, letter_check = cover.draft_letter(p, jd, fit)
```

Replace:

```python
    files = render.write_resume(spec, folder, base, p.get("years_experience", 0), reg)
```

with:

```python
    # the member's own file (their look: icons, links, layout) when a handler can edit it; else today's RenderCV resume
    style = keep_style.tailor(slug, m, p, jd, jd_text, model if use_claude else None, folder, base)
    if style.get("files"):
        files, spec, resume_note = style["files"], style["spec"], style["note"]
    else:
        if use_claude:                # reword the chosen bullets toward the post (numbers, facts and tools kept)
            spec, resume_note = llm.rewrite_resume(spec, p, jd_text, model)
        files = render.write_resume(spec, folder, base, p.get("years_experience", 0), reg)
        resume_note = "; ".join(n for n in (style.get("note"), resume_note) if n)
    problems = tailor.validate(spec, p)
    kw = tailor.keyword_report(spec, jd)
```

In the `report = [...]` list, replace `f"Resume pages: {files['pages']}", ` with `f"Resume pages: {files['pages']}", f"Resume: {resume_note or 'built from the template'}", `.

- [ ] **Step 5: Ship the .tex source from the cloud, and show it on the pages**

`teambid/docs.py:18`: change `MIME = {...}` to:

```python
MIME = {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "tex": "text/x-tex"}
```

`teambid/docs.py:117-121`: replace the loop with:

```python
            for key, path in (("resume_pdf", r["files"]["pdf"]), ("resume_docx", r["files"].get("docx")),
                              ("resume_src", r["files"].get("source")),
                              ("letter_pdf", r["files"]["letter_pdf"]), ("letter_docx", r["files"]["letter_docx"])):
                if not path:             # a member's own .tex has no DOCX; RenderCV resumes have no source file
                    continue
                (out_dir / f"{key}.enc").write_bytes(_encrypt_file(aes, path))
                ext = Path(path).suffix.lstrip(".")
                files[key] = {"name": Path(path).name, "type": MIME[ext]}
```

`teambid/static/results.html:477`: change `DOC_FILES` to:

```js
const DOC_FILES = [["resume_pdf", "Resume PDF"], ["resume_docx", "Resume DOCX"], ["resume_src", "Resume source (.tex)"], ["letter_pdf", "Cover letter PDF"], ["letter_docx", "Cover letter DOCX"]];
```

`teambid/static/index.html:357`: change `${fileLink(r.files.pdf,"Resume PDF")} · ${fileLink(r.files.docx,"DOCX")}` to `${fileLink(r.files.pdf,"Resume PDF")}${r.files.docx ? " · " + fileLink(r.files.docx,"DOCX") : ""}${r.files.source ? " · " + fileLink(r.files.source,"Source (.tex)") : ""}`.

- [ ] **Step 6: Run all the tests**

Run: `python -m unittest tests.test_keep_style -v`
Expected: all tests PASS (22).

Run: `python tb.py test`
Expected: the whole suite PASSES. Members without a .tex file go through exactly the old path, because `keep_style.tailor` returns `{}` for them.

- [ ] **Step 7: Commit**

```bash
git add teambid/keep_style.py teambid/service.py teambid/docs.py teambid/static/results.html teambid/static/index.html tests/test_keep_style.py
git commit -m "Keep style: tailored resumes are built inside the member's own .tex file, RenderCV as the fallback"
```

---

### Task 7: Run it online (GitHub Actions)

**Files:**
- Create: `.github/actions/doc-tools/action.yml`
- Create: `.github/workflows/tests.yml`
- Modify: `.github/workflows/docs.yml`, `.github/workflows/maintain.yml`, `.github/workflows/scan.yml`

**Interfaces:**
- Consumes: `python tb.py test`, `python tb.py admin check` (writes `admin=N` to `GITHUB_OUTPUT`), `python tb.py docs --check` (writes `pending=N`).
- Produces: `pdflatex` / `xelatex` / `tlmgr` on the `PATH` in the workflows that read or build resumes.

- [ ] **Step 1: Create the shared tool setup**

Create `.github/actions/doc-tools/action.yml`:

```yaml
# TinyTeX (a small, real TeX Live: the same pdfLaTeX engine Overleaf uses) so members' own LaTeX resumes can be read
# at upload and rebuilt for each job. The install is cached between runs; a package a resume needs that isn't in the
# list below is installed by style_tex.compile_tex on first use.
name: Document tools
description: TinyTeX for building members' own LaTeX resumes
runs:
  using: composite
  steps:
    - name: Restore TinyTeX
      id: cache
      uses: actions/cache@v4
      with:
        path: ~/.TinyTeX
        key: tinytex-${{ runner.os }}-v1

    - name: Install TinyTeX
      if: steps.cache.outputs.cache-hit != 'true'
      shell: bash
      run: |
        curl -fsSL "https://yihui.org/tinytex/install-bin-unix.sh" | sh
        "$HOME/.TinyTeX/bin/x86_64-linux/tlmgr" install fontawesome fontawesome5 sectsty enumitem helvetic titlesec \
          marvosym preprint babel-english fancyhdr || echo "some packages weren't found; builds install what they need"

    - name: Put LaTeX on the PATH
      shell: bash
      run: echo "$HOME/.TinyTeX/bin/x86_64-linux" >> "$GITHUB_PATH"
```

- [ ] **Step 2: Create the online test workflow**

Create `.github/workflows/tests.yml`:

```yaml
# The full test suite with LaTeX installed, so the .tex build tests run for real (they skip on a PC without it).
name: Tests

on:
  push:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    timeout-minutes: 30
    env:
      PYTHONUNBUFFERED: "1"
    steps:
      - uses: actions/checkout@v7

      - uses: actions/setup-python@v7
        with:
          python-version: "3.12"
          cache: pip

      - run: pip install -r requirements.txt

      - uses: ./.github/actions/doc-tools

      - run: python tb.py test
```

Note: the spec says "on every push to main". `push:` with no branch filter also runs it on `keep-original-style`, so the branch is tested before it is merged. A workflow file that exists only on a branch can't be started by hand until it reaches `main`.

- [ ] **Step 3: Use the tools in the existing workflows**

`.github/workflows/docs.yml`: insert between the steps `Pull workspace (read only)` and `Build documents`:

```yaml
      - name: Document tools (LaTeX for members' own resume files)
        if: steps.q.outputs.pending != '0'
        continue-on-error: true          # without LaTeX, .tex members get the RenderCV resume and a note
        uses: ./.github/actions/doc-tools
```

`.github/workflows/maintain.yml`:
- In the `env:` block of the `maintain` job, add `ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}` under `TEAMBID_SITE_PASSWORD: ${{ secrets.TEAMBID_SITE_PASSWORD }}`.
- Insert just above the step `Team changes from the results page`:

```yaml
      - name: Document tools (to read uploaded .tex resumes)
        continue-on-error: true
        uses: ./.github/actions/doc-tools
```

`.github/workflows/scan.yml`:
- In the `env:` block of the `scan` job (the one with `timeout-minutes: 330`), add `ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}` under `TEAMBID_SITE_PASSWORD: ${{ secrets.TEAMBID_SITE_PASSWORD }}`.
- Insert just above the step `Team changes from the results page`:

```yaml
      - name: Team changes waiting?
        id: adm
        run: python tb.py admin check

      - name: Document tools (to read uploaded .tex resumes)
        if: steps.adm.outputs.admin != '0'
        continue-on-error: true
        uses: ./.github/actions/doc-tools
```

Why the key is added: `maintain.yml` and `scan.yml` run `tb.py admin apply` ("+ Add member"). Without `ANTHROPIC_API_KEY` there, Claude's reading at upload could never run online.

- [ ] **Step 4: Check the YAML**

Run: `python -c "import sys, yaml; [yaml.safe_load(open(f, encoding='utf-8')) for f in sys.argv[1:]]; print('ok')" .github/actions/doc-tools/action.yml .github/workflows/tests.yml .github/workflows/docs.yml .github/workflows/maintain.yml .github/workflows/scan.yml`
Expected: `ok`

Run: `git diff .github/workflows/` and read it. Only the lines above changed.

- [ ] **Step 5: Commit**

```bash
git add .github/actions/doc-tools/action.yml .github/workflows/tests.yml .github/workflows/docs.yml .github/workflows/maintain.yml .github/workflows/scan.yml
git commit -m "Keep style: LaTeX in the cloud workflows, Claude key for upload reading, tests run online"
```

- [ ] **Step 6: Ask the owner, then push the branch and watch the tests**

Ask the owner before pushing, because it is outward-facing. Once they agree:

```bash
git push -u origin keep-original-style
gh run list --workflow tests.yml --branch keep-original-style --limit 1
gh run watch <run id> --exit-status
```

Also note how long the `doc-tools` step takes with no cache (the first run) and with the cache (the second run, started by hand from the Actions page once it is on `main`), and tell the owner. The spec asked for this cost check.

Expected: the `Tests` run passes, and the `Build` tests from Task 3 show as run, not skipped:
- Check with `gh run view <run id> --log | grep -E "test_builds_the_sample|test_no_shell|skipped"`.
- If a test that existed before this work fails only in the cloud (for example `test_page`, which needs Node), report it to the owner with the log lines. Don't change unrelated tests to make it pass.

---

### Task 8: Merge and check it end to end with Omar (owner-gated)

Omar can't be added before this is on `main`. The live `maintain.yml`, `scan.yml` and `docs.yml` run from `main`, and today's code reads a `.tex` upload as plain text.

- [ ] **Step 1: Ask the owner to approve the merge.** Show them `git log --oneline main..keep-original-style` and the green `Tests` run. Merging changes the live workflows.

- [ ] **Step 2: Merge** (only after a yes):

```bash
git checkout main
git merge --ff-only keep-original-style
git push origin main
```

- [ ] **Step 3: The owner adds Omar** on the results page with "+ Add member". They upload the `.tex` that built his current PDF; the copy pasted in chat is older, with the email link going to the hotmail address.

  Then watch the Maintenance run:

  ```bash
  gh run list --workflow maintain.yml --limit 1
  gh run view <run id> --log | grep -E "add |pieces|LaTeX|error"
  ```

  Expected: the log shows `add Omar Tamimi: added Omar Tamimi: 5 jobs read from the resume, ...`.

- [ ] **Step 4: The owner queues one real job for Omar** (Documents tab, a Claude model chosen). Watch `docs.yml`:

  ```bash
  gh run list --workflow docs.yml --limit 1
  gh run view <run id> --log | grep -E "Resume style|original style skipped|failed"
  ```

  Expected: `Resume style: original (.tex). N of 45 bullets reworded, ..., 4 page(s) (original 4)`.

- [ ] **Step 5: The owner downloads the PDF and the .tex** and compares the PDF side by side with the original. Things to confirm:
  - The header, icons, the 5 links, fonts and spacing are identical.
  - Every one of the 45 bullets is there once.
  - The bullets read toward the job.
  - Education and certifications are unchanged.
  - The cover letter is as before.

  Record anything that differs as a follow-up, and don't patch it in place without the owner.

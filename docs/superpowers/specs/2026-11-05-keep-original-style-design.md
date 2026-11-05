# Keep the original resume style when tailoring

Date: 2026-11-05
Status: approved 2026-11-05

## Goal

Today a tailored resume is a new document. The original is parsed into data, bullets are picked and reworded, and
RenderCV lays out a fresh page in the `engineeringclassic` theme (`teambid/cv_pdf.py:12`). The member's own look is lost:
their icons, links, fonts and layout.

The new mode keeps the member's own file and changes only the words inside it, so the tailored resume looks exactly
like the one they gave us.

Example member: a member. His resume is a pdfLaTeX file. It has FontAwesome icons, five links, Helvetica (phv), a
custom `\section*` / `\subsection*` / `itemize` layout, and runs to 4 pages.

## Rules (what may change and what may not)

1. **Bullets** in each job are reworded toward the job post. The facts stay the same: same numbers, no tool the person
   doesn't list, no higher seniority.
2. **Bullets are reordered within each job**, most relevant to the job post first. Every bullet stays, and none are
   added. The jobs themselves keep their order.
3. **The summary paragraph** is reworded toward the job post, with the same fact rules.
4. **The headline** may change to fit the job's title. It may only use titles the person has held or the job's own
   title, it may not claim a higher level than the person has held, and it keeps the original's capital-letter style.
5. **Skills** are reorder only. Within each line, the job's skills move first. Lines the job cares about move up. No
   skill is added or removed.
6. **Everything else is untouched**: header, contact details, icons, links, fonts, margins, spacing, section headings,
   education, certifications and other sections.
7. **The cover letter does not change** (`cover.py`, `llm.write_letter`, `render.write_letter`).
8. **The mode is always on, for every member.** It uses the member's source file if they uploaded one and their PDF if
   not. RenderCV is used only if editing the original fails.
9. **Without Claude** (the "free" model or no API key), the mode still keeps the original style. It reorders bullets by
   relevance and reorders skills, and leaves the wording as written.
10. **Everything runs online in GitHub Actions.** The owner's Windows machine is not a target.

"Matched to the job post" means using the post's own terms and putting the most relevant work first. A skill the person
hasn't listed is never added. The existing `report.md` keyword report keeps listing what the post asks for that the
resume doesn't show.

## Which file gets edited

| Member uploads | Edited file | PDF built by | Match to original | Outputs per application |
|---|---|---|---|---|
| `.tex` | the .tex | TinyTeX (`pdflatex`, or `xelatex` when the file uses `fontspec`) | exact (same engine as Overleaf) | PDF + edited .tex |
| `.docx` | the .docx | LibreOffice, with Carlito and Liberation fonts | .docx exact, PDF very close to Word's export | PDF + edited .docx |
| `.pdf` only | the PDF, in place | PyMuPDF | near-identical; line endings may differ | edited PDF + today's plain DOCX |

`.tex` joins `.pdf/.docx/.txt/.md` in both upload forms (`static/index.html:248`, `static/results.html:917`).
`.txt/.md` uploads keep today's RenderCV output, since there is no style to keep. Only a single `.tex` file is
supported. If the file needs other files (images, a `.cls`), it fails to build, and the upload says to send the PDF
instead.

## Architecture

```
job post -> analyze_jd / fit            (unchanged)
         -> build_resume                (still run: relevance scores + report)
         -> member's original file?
              |- .tex / .docx / .pdf -> load pieces.json -> Claude rewrites + reorders -> checks -> write back -> PDF
              '- any step fails      -> today's RenderCV resume, with a note in report.md
         -> cover letter                (unchanged)
```

### New and changed units

| Unit | Job | Depends on |
|---|---|---|
| `teambid/keep_style.py` | Coordinator: picks the handler, loads or builds `pieces.json`, plans the default order, runs Claude and the checks, writes the files, falls back to RenderCV. | handlers, `llm`, `tailor`, `render` |
| `teambid/style_tex.py` | Find pieces in a .tex, write the new text back, build the PDF with TinyTeX. | `pdflatex` / `xelatex` |
| `teambid/style_docx.py` | Find pieces in a .docx, write the new text back, build the PDF with LibreOffice. | python-docx, `soffice` |
| `teambid/style_pdf.py` | Find pieces in a PDF, erase them, draw the new text in place. | PyMuPDF |
| `llm.read_resume` | Claude reads the whole resume once and returns its structure (replaces `refine_profile`). | Anthropic API |
| `llm.tailor_in_place` | Claude rewrites and reorders the pieces for one job post. | Anthropic API |
| `service.onboard`, `admin._add` | Accept `.tex`, compile it once to get text, run `read_resume`, save `pieces.json`. | `style_tex`, `llm` |
| `service.apply` | Call `keep_style` before RenderCV (`service.py:138-171`). | `keep_style` |
| `.github/actions/doc-tools` | Shared setup step: TinyTeX (cached), `libreoffice-writer-nogui`, fonts. | apt, TinyTeX installer |
| `.github/workflows/tests.yml` | Runs `python tb.py test` online, with the tools installed. | `doc-tools` |

Every handler has the same three functions:

```python
find(path, pieces) -> Doc        # map each confirmed piece to its spot in the file; flag pieces that can't be reworded
write(doc, plan, folder, base)   # put new text / new order back; returns the edited source file
build(edited, folder, base)      # -> {"pdf": path, "pages": n, "source": path}
```

The database doesn't change. `members.resume_file` already points to the uploaded original in
`members/<slug>/resume/`, and `pieces.json` is saved next to it.

## Step 1: Claude reads the resume (once per upload)

**When:** at upload or replacement, in every upload path: the local app, `tb.py add`, and "+ Add member" on the
results page (`admin._add`). The result is saved to `members/<slug>/resume/pieces.json` and reused by every
application. Members uploaded before this change get it built on their next application, and it is saved then.

**Input:** the full resume text. For .tex, that's the text of the PDF built from it. For .docx and PDF, it's the text
`resume_parse.extract_text` already gets. Nothing is cut; today's `refine_profile` cuts at 15,000 characters, and
one member's resume is longer than that.

**Model:** Sonnet. It runs once per member, so accuracy matters more than cost. `max_tokens` is 16000, so a 4-page
resume can be returned in full. one member's is about 5,000 tokens.

**Output:**

```json
{"headline": "SENIOR FULL STACK .NET DEVELOPER",
 "summary": "Senior Full Stack Software Engineer with 8+ years...",
 "jobs": [{"title": "...", "company": "...", "location": "...", "start": "2026-02", "end": "Present",
           "bullets": ["exact text of bullet 1", "..."]}],
 "skills": [{"label": "Programming Languages", "items": ["C#", "JavaScript", "..."]}]}
```

**Claude decides what each piece is. Code decides where it is.**
- Every string must appear word for word in the resume text, in reading order, with no overlaps. Only whitespace, line
  breaks, words split with a hyphen at a line end, and dash and quote styles (`--` vs `–`, `'` vs `’`) are ignored.
  Handlers use the same rule when they match pieces to their file.
- A string that doesn't match is dropped, and that piece stays in the file as written.
- If more than 25% of the bullets fail to match, the whole result is rejected and today's rule-based parser
  (`resume_parse.parse`) is used.
- Claude's `jobs` replace the rule-based `roles` in the member's profile (as `refine_profile` does today), so the fact
  checks compare against a cleaner list. The old opt-in checkbox is no longer needed. The step runs whenever an API key
  is set.

**IDs:** job `i`, bullet `j` is `r{i}b{j}`. Skills line `k` is `s{k}`. Plus `headline` and `summary`.

## Step 2: Claude rewrites the pieces (once per application)

**Input:** the job post (first 12,000 characters, as today) plus the pieces with their IDs, grouped by job, with each
job's title, company and dates. A bullet is sent as plain text, with `**x**` marking words that were bold in the original.

**Model:** the results-page dropdown, as today (`docs.py:107-110`). `max_tokens` is about 8000, since every bullet comes
back.

**Output:**

```json
{"headline": "...", "summary": "...",
 "bullets": {"r0b0": "new text", "...": "..."},
 "order":   {"r0": ["r0b3", "r0b0", "r0b1"]},
 "skills":  {"s0": ["C#", "SQL", "TypeScript"]},
 "skill_lines": ["s1", "s0", "s3"]}
```

**The prompt** builds on `RESUME_RULES` (`llm.py:225-242`): the recruiter voice, strong bullets, the job's own terms,
the hard fact rules and the banned words. It adds the reorder task, the length limits, the headline rule and the
skills-reorder rule.

## Step 3: checks

Each piece is checked on its own. A piece that fails keeps its original text or order, and the other pieces still go
through.

| Piece | Accepted only if | If not |
|---|---|---|
| Job order | It holds exactly that job's IDs, each once. | Order by `tailor` relevance scores |
| Bullet | It passes `llm._bullet_ok` (same numbers, no unlisted tool, no banned words, no new result words), is at most 10% longer and at most 25% shorter, and has only `**bold**` formatting on tool/skill names, and only where the original used bold. | Original text |
| Summary | It passes today's summary check (`llm.py:283-290`) and the same length limits. | Original text |
| Headline | Its words come from titles the person has held or the job's title, its level is no higher than any they've held, and it keeps the original's capitalization. | Original text |
| Skills line | It holds the same items. | Original order |
| Skill line order | It holds the same lines. | Original order |

**Pieces that can move but can't be reworded:** a piece containing a link or any formatting other than bold. Its
original text is kept exactly. In a PDF, a bullet with a link can't move either.

**Order without Claude:** bullets are ordered by the same relevance score `tailor.build_resume` uses, computed for every
bullet (not only the ones `max_bullets` keeps). Skills are ordered by job weight, the same way `tailor` builds
`SKILL_LINES` today.

**Page count:** the built PDF must have no more pages than the original. If it has more, original text is put back for
the bullets that grew the most, one at a time, and the PDF is rebuilt (at most 5 rebuilds). If it still has more pages,
the run falls back to RenderCV. In this mode `render._shrink` and the region page budget aren't used, because no bullet
may be dropped.

`tailor.validate` and `tailor.keyword_report` still run on the final text, for `report.md`.

## File handlers

### .tex (`style_tex.py`)

- **Find:**
  - Sections are found by `\section` / `\section*` title (Experience, Employment, Work History, Profile, Summary,
    About, Skills).
  - In the experience section, each list environment is one job, and its bullets are the `\item` blocks. Commands
    defined with `\newcommand` whose body uses `\item`, such as Jake's Resume `\resumeItem{...}`, count as bullets
    too, with the text in their argument.
  - Each block is converted to plain text: `\textbf{x}` becomes `**x**`; `\%`, `\&`, `\#`, `\_` and `--` become plain
    characters; comments are removed. The plain text is matched to the confirmed pieces.
  - The headline is the span in the header (before the first section) that matches the confirmed headline.
  - The summary is the paragraph in the profile/summary section.
  - Skills lines are the `\item`s in the skills section. The label stays and the comma-separated items are reordered,
    keeping the ending punctuation.
  - A block with any command other than `\textbf` (for example `\href`, `\textit`, math) is flagged as move-only.
- **Write:**
  - Special characters are escaped, and `**x**` becomes `\textbf{x}`.
  - Only the text of each piece is replaced, working from the end of the file backwards so earlier positions stay valid.
  - Reordering moves whole `\item` blocks within their own list, keeping the original whitespace between them.
  - The preamble, header and everything else stay byte-for-byte the same.
- **Build:**
  - `pdflatex` (or `xelatex` when the file loads `fontspec`) runs in a temporary folder, with
    `-no-shell-escape -interaction=nonstopmode -halt-on-error`.
  - `openin_any=p` and `openout_any=p` keep it from reading or writing files outside that folder.
  - The time limit is 60 s. It runs a second time if the log asks for it.
  - TinyTeX installs a missing package and retries once (`tlmgr install`).

### .docx (`style_docx.py`)

- **Find:** bullets are the paragraphs under the experience heading that are list items (`w:numPr`, set directly or by
  the style) or start with a bullet character. Each group is tied to the job heading above it. Headline, summary and
  skills paragraphs are matched by text to the confirmed pieces. A paragraph with a hyperlink is move-only.
- **Write:**
  - The paragraph's own formatting is reused: the first plain run's `rPr` for plain text and the first bold run's
    `rPr` for `**bold**`. The other runs are removed.
  - Reordering moves whole `w:p` elements. This happens only when a job's bullets sit next to each other under the
    same parent (body or table cell); if they don't, that job keeps its order.
- **Build:** `soffice --headless --convert-to pdf`, with a 90 s time limit. Fonts come from the shared setup:
  Carlito (Calibri), Caladea (Cambria), Liberation (Arial, Times), Roboto, Inter.

### PDF in place (`style_pdf.py`)

- **Find:**
  - Each confirmed bullet is matched to its lines with `get_text("dict")`, joining words split across lines.
  - Each bullet becomes a list of line boxes with font, size, color and left edge, plus its bullet symbol box.
  - A job's lines can run across a page break.
  - Bullets with link annotations are locked: they can't be reworded or moved.
- **Erase:** a redaction over each line box, applied with `images=PDF_REDACT_IMAGE_NONE` and
  `graphics=PDF_REDACT_LINE_ART_NONE`, so only text is removed. Nothing outside the boxes is touched.
- **Draw:**
  - **Font:**
    - The embedded font is used when it has every glyph the new text needs. Embedded fonts are usually partial: in
      one member's PDF, NimbusSanL has no `Y`, `Z`, `;` or quotes.
    - Otherwise a matching open font is used for that whole job: NimbusSanL/Helvetica/Arial → Liberation Sans,
      Calibri → Carlito, Times → Liberation Serif, and Roboto, Inter and Poppins use the real fonts.
    - Base-14 Helvetica is the last resort.
    - Bold uses the bold face of the same family.
  - Size, color, left edge, line spacing and the gap between bullets are copied from the original. The bullet symbol is
    redrawn at the start of each bullet.
  - If the original lines were justified, the new lines are too, by spreading the word spacing. There is no
    hyphenation.
  - Bullets are laid out in their new order through the job's original line space, continuing to the next page where
    the original did. Nothing may go below the job's original last line. If a job doesn't fit, original text is put back
    for the bullets that grew the most until it fits.
  - `doc.subset_fonts()` keeps the file small. The text stays real, searchable text, so applicant tracking systems can
    read it.
- **Known limit:** a line may break at a different word than LaTeX or Word chose. The page reads as the same document,
  but line endings won't match the original exactly.

## Running online (GitHub Actions)

| Workflow | Job | Needs |
|---|---|---|
| `maintain.yml`, `scan.yml` (`tb.py admin apply`) | Upload: compile .tex, `read_resume`, save `pieces.json` | TinyTeX |
| `docs.yml` (`tb.py docs`) | Tailored resumes | TinyTeX, LibreOffice, fonts |
| `tests.yml` (new) | `python tb.py test` on push to `main` and by hand | TinyTeX, LibreOffice, fonts |

- **Shared setup:** `.github/actions/doc-tools` installs TinyTeX (install folder cached with `actions/cache`),
  `libreoffice-writer-nogui`, `fonts-crosextra-carlito`, `fonts-crosextra-caladea`, `fonts-liberation`, `fonts-roboto`
  and `fonts-inter`.
- **When the setup runs:** in `docs.yml`, `maintain.yml` and `scan.yml`, only after the queue check finds work, so empty
  15-minute `docs.yml` runs stay as fast as now.
- **Missing tools:** a missing tool counts as a failed step, so that resume falls back to RenderCV.

## Errors and reporting

Any failure falls back to today's RenderCV resume for that application. Failures include: no confirmed pieces, a
handler that can't place pieces, a build error, a timeout, and too many pages after the put-back step. The reason is
added to `report.md` and to the `resume_ai` note shown on the results page.

On success, `report.md` gets a line like:
> Resume style: original (.tex). 41 of 45 bullets reworded, 4 kept as written (failed checks), order changed in 5 jobs,
> 4 pages like the original.

`spec.json` records the pieces, the plan Claude sent, and which pieces were accepted.

## Testing

`tests/test_keep_style.py` runs offline, with `llm._call` faked (as in `tests/test_docs.py`). The tests that need a tool
are skipped when the tool is missing, like the Ollama tests. They run for real in `tests.yml`.

- **Checks:** an order with a missing, extra or repeated ID falls back; the length limits; a headline claiming a higher
  level is rejected; skills can only be reordered; non-bold formatting is stripped; bold is only accepted where the
  original used it.
- **Step 1:** a string not in the text is dropped; more than 25% failures rejects the whole result; the profile's roles
  are replaced.
- **.tex:**
  - It runs on a small made-up resume in two styles, member-like (`\section*` + `itemize`) and Jake's Resume
    (`\resumeItem`).
  - Outside the edited spans, the output is byte-for-byte the input.
  - Every bullet ID appears exactly once.
  - Escaping round-trips.
  - The file builds, and the page count is kept.
- **.docx:** the fixture is made with python-docx and has a header link, bold runs, bullets inside a table cell, and
  bullets that aren't next to each other. Links and the header stay the same, the paragraph count stays the same, the
  bold `rPr` is reused, and jobs whose bullets aren't next to each other keep their order.
- **PDF:** the fixture PDF is drawn in the test, with header links and bullets across a page break. The link list is
  identical, text outside the bullet boxes is identical, every new bullet's text is present, nothing is drawn below a
  job's original last line, and the fallback font is used when a glyph is missing.
- **`service.apply`:** a .tex member whose build fails gets the RenderCV resume and a note in the report. The cover
  letter output is unchanged.
- **Existing tests:** `python tb.py test` keeps passing.
- **End-to-end, online:** add a member through "+ Add member" with his .tex, queue one real job, and compare the PDF with his
  original side by side. This adds a real member, so the owner confirms first. His file never goes into the repo.

## Build order

Each part can ship on its own.

1. **Core and .tex:** `read_resume`, `pieces.json`, `tailor_in_place` and the checks, `keep_style`, `style_tex`, `.tex`
   upload, `doc-tools` with TinyTeX, `tests.yml`. a member works end to end.
2. **.docx:** `style_docx` and LibreOffice in `doc-tools`.
3. **PDF in place:** `style_pdf`. This covers the current members, who uploaded PDFs only.

The first implementation plan covers part 1.

## To check during planning

- **Cost:** check the TinyTeX cache size and how long the first package installs take on the runner.
- **one member's .tex:** upload the version that built his current PDF. The copy pasted in chat is older: its email link
  still points to `an old address`.

The model IDs in `llm.MODELS` (`claude-sonnet-5-5`, `claude-haiku-5-5`) are confirmed correct by the owner.

## Out of scope

- Multi-file LaTeX projects (images, `.cls` files) and Overleaf zip uploads.
- Changing the jobs' order, adding or removing sections, or changing education or certifications.
- Restyling or "improving" layouts.
- Any change to the cover letter.

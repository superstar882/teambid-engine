# Keep Original Style, Part 2: Word (.docx) Uploads Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A member who uploaded a Word resume gets every tailored resume built from their own .docx: bullets reworded and reordered, the summary reworded, the headline set where allowed, and skills reordered. Everything else in the file stays the same. The PDF is built by LibreOffice online.

**Architecture:** a new handler `teambid/style_docx.py`, registered as `keep_style.HANDLERS[".docx"]`, with the same interface as `style_tex` and `style_pdf`:
- `find(path, pieces) -> doc`: the same doc shape, with internal `_` keys.
- `build(doc, plan, folder, base) -> files`.

It edits the .docx XML with python-docx (already a dependency) and converts it to PDF with LibreOffice, inside the same kind of Docker sandbox as LaTeX. `keep_style` drives it unchanged, through `check`, `_build` (the page-count put-back) and `tailor`.

**Tech stack:** Python 3.12, python-docx, LibreOffice (`soffice --headless --convert-to pdf`), Docker on the GitHub runner, stdlib unittest.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-11-05-keep-original-style-design.md`, the sections "Rules", "Which file gets edited", ".docx (`style_docx.py`)", "Running online" and "Testing". Owner decisions carried from parts 1, 3 and 4:
  - **Headline:** it never steps down (`keep_style.headline_ok` already enforces this).
  - **Bold:** it stays on the phrases that were bold in the original (`clean_bold`).
  - **Fallback:** a file that can't be tailored safely falls back to the tailored RenderCV resume, with a note.
- **Only the pieces change.** Everything else in the .docx stays byte-for-byte the same in its XML: the header, links, tables, images, styles, sections and other paragraphs. A paragraph with a hyperlink, a field, a tracked change, an image or a text box is fixed: never reworded, though it may move as a whole paragraph where moving is allowed.
- **Reordering moves whole `w:p` elements,** only within a run of sibling list paragraphs under the same parent (the body or a table cell) with nothing between them. Otherwise that job keeps its order.
- **Rewriting a paragraph reuses its own formatting.** The text goes in with the first plain run's `w:rPr`, and `**bold**` with the first bold run's `w:rPr`. The paragraph's `w:pPr` (numbering, indent, spacing) is never touched.
- **Page count:** the built PDF must have no more pages than LibreOffice's PDF of the original file. `keep_style._build` already puts back the longest pieces, one at a time, until it fits.
- **Security:**
  - LibreOffice opens a member's upload only inside a Docker container with `--network none`. The container sees the host's `/usr` and `/etc/fonts` read-only, and nothing writable except one work folder; its HOME is a tmpfs in the container.
  - It gets an allow-listed environment (no secrets), and its time limit is 90 s.
  - It fails closed: on GitHub Actions (`GITHUB_ACTIONS=true`) LibreOffice never runs outside the sandbox (`TEAMBID_DOCX_SANDBOX=docker`).
  - Follow `style_tex._latex_cmd` and `_env`.
- **Tests:**
  - Tests never call the real Claude API.
  - Fixtures are fictional and built with python-docx in the test.
  - Tests that need LibreOffice skip when `soffice` (or the sandbox) is missing. They run online.
- **Everything runs online.** This PC has no LibreOffice. `python tb.py test` stays green (baseline 274 OK, 12 skipped).
- **Style:** match the surrounding code: flat functions, short docstrings that say why, plain-English notes. Use the Edit/Write tools for code.

---

### Task 1: Find the pieces in a .docx

**Files:** create `teambid/style_docx.py`, `tests/docx_samples.py` (a fictional fixture builder) and `tests/test_style_docx.py`.

**Produces:** `style_docx.find(path, pieces) -> doc`, in the shape `style_tex.locate` gives:
- `{"ext": ".docx", "_path", "_pieces", "pages": int|None, "headline": {"text", "fixed"}|None, "summary": {...}|None, "jobs": [{"id": "r<n>", "reorder", "title", "company", "start", "end", "bullets": [{"id": "r<n>b<m>", "text" (with **bold**), "fixed", "piece"}]}], "skills": [{"id": "s<n>", "label", "items", "fixed"}], "skills_move": bool}`
- Internal `_`-prefixed keys may hold paragraph references. Keep them out of anything JSON-serialised (`report_spec` uses only public keys).
- `pages` is the page count of LibreOffice's PDF of the original, from Task 2's converter. It is None when LibreOffice isn't available: then `build` can't run, and the member falls back to RenderCV.

**Rules:**
- **Paragraphs:** walk all of them in document order, in the body and in table cells (nested too), skipping headers and footers. Each paragraph's text is the concatenation of its runs' `w:t`, with `w:tab` as a space.
- **Bullets** are paragraphs that are list items (`w:numPr` set directly or by the paragraph's style) or whose text starts with a bullet character (`style_pdf.BULLETS`). A typed sign isn't part of the bullet's text.
- **Matching** is by `key()` of the confirmed text: a bullet is the whole text of exactly one paragraph. A piece not found is absent, never guessed.
- **Jobs** take the bullets of each confirmed job in reading order, as `style_pdf.read` does: search forward and claim each paragraph once.
- **Fixed** pieces:
  - a hyperlink (`w:hyperlink`), a field (`w:fldSimple` or `w:fldChar`), tracked changes (`w:ins`/`w:del`), a drawing or picture, or a text box in the paragraph;
  - runs in more than one style apart from bold (italic, a different size, colour or font);
  - (bullets only) no list numbering and no typed sign, because a piece cut out of a longer paragraph never matches whole.
- **Reorder:** a job may be reordered only when none of its bullets is fixed and its paragraphs are consecutive siblings under one parent, with nothing between them.
- **Headline, summary and skills** each match the confirmed text on one paragraph, or the summary on consecutive paragraphs.
  - A skills paragraph is "Label: items", the label first, with the items separated by one separator (`sep`).
  - `skills_move` is true when the skills paragraphs are consecutive siblings, none of them fixed.

**Tests** (fixture with python-docx: a name and headline, a header with a hyperlink, a summary with a bold phrase, two jobs with list bullets where one bullet holds a bold tool, skills paragraphs "Languages: Python, Go, SQL", and options for each case):
- Every piece is found with the right ids, and `**bold**` appears in the text.
- A bullet with a hyperlink is fixed, and its job is not reordered.
- Bullets inside a table cell are found, and their reorder is allowed.
- Bullets that aren't next to each other (a paragraph between them) give `reorder` False.
- A typed "• " bullet is found without its sign in the text.
- Skills paragraphs are found, and `skills_move` is true.
- Pieces that aren't in the file are absent.

Steps: failing tests → implement → `python -m unittest tests.test_style_docx -v` → commit "Keep style: find a Word resume's bullets, summary, headline and skills".

---

### Task 2: Write the pieces back, build the PDF, wire it in

**Files:** `teambid/style_docx.py`, `teambid/keep_style.py` (HANDLERS and any docx-specific wiring), `tests/test_style_docx.py`, `tests/test_keep_style.py`.

**Produces:**
- `style_docx.build(doc, plan, folder, base) -> {"pdf", "docx", "pages", "paper"}`. `"docx"` is the edited member file, which the results page offers as the DOCX download (`docs.py` uploads `files["docx"]`).
- `style_docx.to_pdf(docx_path, out_dir) -> (pdf_path, pages)`: the sandboxed LibreOffice converter. It raises `RuntimeError` with a plain message when LibreOffice is missing, times out or fails.
- `keep_style.HANDLERS[".docx"] = style_docx`. `keep_style.source_file` must return a member's stored .docx. Check how it picks files, and make sure a .docx upload counts as the source file.

**Rules:**
- **Writing:**
  - Edit the XML of a fresh copy: open `doc["_path"]` again in `build`, never the parsed object from `find`.
  - Bullet text (`plan["text"]`), the summary, the headline and skills items (with `sep`) replace the runs of their paragraph. Plain text goes in with the first plain run's `rPr`, and `**bold**` spans with the first bold run's `rPr`; if there was no bold run, write all of it plain.
  - A typed sign stays at the start of its paragraph as it was printed.
  - `w:pPr` is untouched.
- **Order:** move the `w:p` elements of a reorderable job into the planned order inside their parent. Do the same for `skill_lines` when `skills_move` is true.
- **Building:**
  - Save to `folder/base.docx`, convert with `to_pdf`, and return the page count and paper size (A4 or Letter from the PDF's first page).
  - `keep_style._build` compares the page count with `doc["pages"]` and puts back the longest grown pieces when it's over.
- **Sandbox** (copy the `style_tex._latex_cmd` pattern):
  - With `TEAMBID_DOCX_SANDBOX=docker`, run `docker run --rm --network none --user <uid>:<gid> -v /usr:/usr:ro -v /etc/fonts:/etc/fonts:ro -v /usr/share/fonts:/usr/share/fonts:ro -v <work>:/work -e HOME=/tmp --tmpfs /tmp ubuntu:24.04 soffice --headless --norestore --convert-to pdf --outdir /work /work/<name>.docx`.
  - Off GitHub Actions without the sandbox, run `soffice` directly with an allow-listed env. On GitHub Actions without the sandbox, raise.
  - Time limit: 90 s.
- **Verify:** the reworded paragraphs read back from the built PDF. Use PyMuPDF text: `key()` of each new text appears in the PDF text, and the old text of a reworded paragraph doesn't. If not, raise, and the member falls back to RenderCV.

**Tests:**
- **XML only (always run, no LibreOffice needed):**
  - Writing a new bullet, summary, headline and skills order produces a .docx whose other paragraphs are byte-identical in their XML, with the same paragraph count.
  - The reused `rPr` keeps the run's font and size, and bold stays only on `**bold**`.
  - A reorder moves whole paragraphs.
  - A fixed paragraph is untouched.
  - A table-cell job reorders inside its cell.
- **Converter:**
  - The command uses `--network none` and the allow-listed env: test `_soffice_cmd` the way the LaTeX sandbox tests do.
  - It raises on GitHub Actions without the sandbox.
- **LibreOffice (skip when missing):**
  - The build produces a PDF that reads back the new text with the page count kept.
  - An over-long rewording that would add a page is put back by `keep_style._build`.
- **keep_style:** an ApplyWithDocx test (Claude mocked):
  - A .docx member gets their own style: the note says "Resume style: original (.docx)", and files have "pdf" and "docx".
  - When LibreOffice is missing, the member falls back to RenderCV with a note.

Steps: failing tests → implement → `python -m unittest tests.test_style_docx tests.test_keep_style -v` → `python tb.py test` → commit "Keep style: a Word member's own .docx is tailored and built with LibreOffice in a sandbox".

---

### Task 3: LibreOffice online, then ship (controller, owner-gated)

- **Install:** `.github/actions/doc-tools/action.yml` gets one best-effort step: `sudo apt-get install -y -qq libreoffice-writer-nogui`.
  - Arm `TEAMBID_DOCX_SANDBOX=docker` first, as is done for LaTeX.
  - On failure, echo and carry on: Word members then fall back to RenderCV.
  - Keep it after the fonts step.
- **Check online:** push, run Tests online, and confirm the LibreOffice tests ran (not skipped) and passed.
- **Ship:** open a PR and merge it on the owner's OK. No member uses .docx yet, so there is nothing to rebuild.

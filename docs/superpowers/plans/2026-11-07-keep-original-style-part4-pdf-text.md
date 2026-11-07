# Keep Original Style, Part 4: PDF Headline, Summary and Skills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A member's own PDF gets its summary reworded, its headline set to the job's title where allowed, and its skills reordered, all in place, with the same safety as bullets.

**Architecture:** `style_pdf.read` also finds the confirmed headline, summary and skill lines on whole lines. `find` returns them in the doc shape `keep_style` already uses for `.tex`. `build` turns each into a pseudo-job made of pseudo-bullets, so the existing layout, erase, draw, read-back, whole-page check and retry ladder handle them unchanged. Only these are new:
- in-place layout for one line or a paragraph;
- centred headlines;
- skill-line text;
- mapping what was applied back to the plan.

**Tech stack:** Python 3.12, PyMuPDF (fitz), stdlib unittest. Fixtures are fictional PDFs drawn in `tests/pdf_samples.py`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-11-05-keep-original-style-design.md`, section "PDF headline, summary and skills (part 4)". Its rules are binding.
- Owner decisions (2026-11-07):
  - Summary bold stays on the phrases that were bold in the original (`keep_style.clean_bold`, unchanged).
  - Skills reorder within lines, and whole lines move when they form a run.
  - Chips (skills in drawn boxes) are fixed.
- Safety rule: a garbled PDF must never pass. Every redrawn piece must read back word for word, and every other word on the page must stay where it was. Anything unclear keeps the original. Pinning or keeping is always the safe direction.
- Fixed pieces are never erased or redrawn: a link, italics, mixed sizes or colors other than bold, a drawing in its lines, or a headline that is right-aligned or in mixed styles.
- Nothing may grow: a summary or skill line keeps at most its own line count, and a headline must fit the room it has.
- Tests never call the real Claude API (mock `llm.*`), and fixtures stay fictional.
- Close fitz docs with `with`. Edit with the Edit tool; heredocs mangle backslashes on this PC.
- `python tb.py test` must stay green. The baseline is 213 OK, 12 skipped.
- Everything runs online. The local PC has no fc-match: tests that need installed fonts skip here.
- Match the surrounding code style: flat functions, short docstrings that say why, plain English in notes.

## File Structure

- Modify `teambid/style_pdf.py`:
  - `read()` / `find()`: locate the headline, summary and skill lines.
  - `_lay_out` / `_render` / `build`: pseudo-jobs.
  - `_wrong` / `_disturbed` / ladder: id patterns.
- Modify `teambid/keep_style.py` (`tailor`): map the handler's report of what it didn't apply back to the plan, plus the note.
- Modify `tests/pdf_samples.py`: add a header headline line (left or centred), a summary paragraph and a Skills section (label and items, optionally chips) to the DANA REYES fixture, behind options so existing tests are unchanged. Extend `PIECES` through a helper (for example `pieces(headline=..., summary=..., skills=...)`), not by changing the default.
- Modify `tests/test_style_pdf.py` and `tests/test_keep_style.py`.

---

### Task 1: Find the headline, summary and skill lines in a PDF

**Files:** `teambid/style_pdf.py`, `tests/pdf_samples.py`, `tests/test_style_pdf.py`

**Produces:**
- `style_pdf.read(doc, pieces)` keeps returning the jobs list it returns today, unchanged.
- A new `style_pdf.read_text_parts(doc, pieces, lines, marks)`, or an equivalent private function called from `find`, returns `{"headline": part|None, "summary": part|None, "skills": [line,...], "skills_move": bool}`:
  - A `part` is `{"text": shown text with **bold**, "fixed": bool, "lines": [line dicts], "align": "left"|"center"}`. `align` is used for the headline only.
  - A skills `line` is `{"id": "s0"..., "label": str, "items": [str], "fixed": bool, "lines": [...], "sep": str}`.
- `find()` puts these in the doc:
  - `"headline": {"text", "fixed"}`, `"summary": {"text", "fixed"}`, `"skills": [{"id", "label", "items", "fixed"}]`, and `"skills_move"`. This is the same shape `style_tex` gives, so `keep_style.check` and `llm.tailor_in_place` work unchanged.
  - Keep the internal `lines` out of the doc, or under `_`-prefixed keys.

**Rules:**
- **Matching:** a piece is found only on whole lines, by `key()` of the confirmed text, over lines no bullet claimed. Use the same `hay`/`spot` approach `read()` uses for bullets, and keep page furniture out. Not found means the piece is absent (`None` or skipped), never guessed.
- **Headline:** the confirmed `pieces["headline"]`, on exactly one line.
  - `align` is `"center"` when the line's centre is within 3 pt of the page's text centre: the centre between the smallest x0 and the largest x1 of all text lines on that page. It is `"left"` when the line starts within 2 pt of the page's text left edge or of its column's left edge.
  - Fixed when the alignment is anything else, the line holds more than one style (font, size, color, bold), it holds a link, or `_art_in` finds a drawing in it.
- **Summary:** the confirmed `pieces["summary"]`, on one or more consecutive lines. Fixed for a link, italics, sizes differing by more than 0.6 pt, colors other than one text color (bold may differ), or a drawing in its lines.
- **Skill lines:**
  - Each confirmed `pieces["skills"][n]` (`{"label", "items"}`) is found on whole consecutive lines whose key equals `key(label + items joined)`, with the label first.
  - `sep` is the separator text between the first two items as printed (", " / " · " / " | "). If the items aren't all separated by that same separator, the line is fixed.
  - Fixed for chips (`_art_in` true on any of its lines, which is how boxed items show), a link, italics, or mixed sizes or colors beyond a bold label.
  - `skills_move` is true when at least two skill lines are found, none is fixed, they sit in one column, and `_runs`-style checks find nothing between consecutive ones except other skill lines. Simplest: build a pseudo-job from them and require `len(_runs(pseudo)) == 1`.

**Tests** (fixture options, no real people):
- A left headline and a centred headline are found, with the right `align`. A two-style headline is fixed.
- A two-line summary is found, with `**bold**` marks where the fixture has bold. A summary with an italic word is fixed.
- Three skill lines with a bold label and ", " separators are found, with the items in printed order and `skills_move` true. With chips (small drawn boxes around items) they're fixed and `skills_move` is false.
- Pieces not in the PDF are absent, and nothing else changes: the existing Read tests pass unchanged.
- `find()` gives exactly the shape above. Add a doc-shape test like `Find.test_doc_shape`.

Steps: write the failing tests → implement → run `python -m unittest tests.test_style_pdf -v` → commit "Keep style: find a PDF's headline, summary and skill lines".

---

### Task 2: Redraw them in place

**Files:** `teambid/style_pdf.py`, `tests/test_style_pdf.py`

**Consumes:** Task 1's parts. The plan dict from `keep_style.check` has these keys:
- `"headline"` (str or None)
- `"summary"` (str with **bold** or None)
- `"skills"`: {sid: [items in new order]}
- `"skill_lines"`: [sid in new order] or []
- `"text"` and `"order"`: bullets, as today

**Produces:**
- `build(doc, plan, folder, base)` also draws these, and returns one more key: `"parts_kept": {"headline": bool, "summary": bool, "skills": [sid whose new order was NOT drawn], "skill_lines": bool}`. Here `True` means the planned change was not applied, and the original stays.
- Existing keys keep their meaning. `"order"` stays about jobs only.

**How:**
- **Pseudo-jobs.** In `_render`/`_lay_out`, each found, non-fixed part with a planned change becomes a pseudo-job:
  - ids `"xh"`, `"xs"` and `"xk"`;
  - pseudo-bullet ids `"xhb0"`, `"xsb0"` and `"xkb<n>"`, where n is the skill line's index (`s<n>`);
  - `mark: None`, but they must not be fixed by the "no sign" rule. Build them after `read()` or flag them, without touching the bullet rules.
- **Generalise the id patterns:**
  - the ladder's `job_of`: bullet id → job id, for example `bid.rsplit("b", 1)[0]`;
  - the culprit regex in `build`: `r"\b(?:r\d+|x[hsk])b\d+\b"`;
  - anything else that assumes `r\d+b\d+`.
  - A part whose redraw fails is "spared" like a job: left exactly as it was, and reported in `parts_kept`.
- **Summary and skill lines (in-place text):**
  - Use `_new_lines` with the part's own text start x (first line) and continuation x, the right edge = max x1 of its lines, and the justification rule of `_style` (computed on the part).
  - Use the part's main style, with bold as the shown text marks it.
  - Draw on the part's own baselines. It is used only if it needs no more lines than the part has. If it doesn't fit, it's kept and reported.
  - A skill line's new text is `**label** + rest`, styled as printed (bold label if the label was bold), followed by the items joined by `sep`.
- **Headline:**
  - The new text is laid out on one line.
  - `"left"`: start at the line's x0; the room runs to the page's text right edge, or to 4 pt before any other text on the same baseline to its right.
  - `"center"`: centred on the same centre, with the room = the page's text width.
  - Same font, size and color. If it doesn't fit, keep and report it. Centred layout is new: extend `_new_lines` with an optional `center` argument, or position the single line yourself.
- **Skill line order:**
  - When `plan["skill_lines"]` differs from the printed order and `skills_move` is true, the `"xk"` pseudo-job is reordered through `_flow`, like a job's bullets.
  - Lines whose items were also reordered are "changed" (new text) in the same flow.
  - If no flow fits, the order is kept and `parts_kept["skill_lines"] = True`.
- **Read-back:**
  - `_wrong` checks pseudo-bullets like bullets. The expected words for `xhb0` are the new headline, for `xsb0` the new summary, and for `xkb<n>` the skill line's new text.
  - Put the expected texts in the plan copy `_render` uses (for example under `plan["text"]` with the pseudo ids). `keep_style`'s `plan["text"]` must not keep them.
  - The whole-page check (`_disturbed`) and `_signs_hit` stay as they are.

**Tests:**
- **Summary:**
  - A shorter summary rewording reads back, and the lines outside it are untouched.
  - One that needs an extra line is kept (`parts_kept["summary"]`), and the PDF is byte-identical in text to the original.
  - Bold on an originally bold phrase stays bold.
- **Headline:**
  - A left headline replaced by a shorter title reads back at the same x.
  - A centred one is centred: its new centre is within 1 pt of the old centre.
  - One that doesn't fit is kept.
- **Skills:**
  - Reordered items read back in the new order with the same separators, and the label stays bold.
  - Moving whole lines (`skill_lines` reversed) reads back in the new order.
  - Chips are left alone even if the plan asks for a change (`parts_kept`).
- **Safety:**
  - A mocked `_wrong` that flags `xsb0` leaves the summary as it was, and the bullets still change.
  - A failure that names no part still raises.
- **No change:** an empty plan for the parts draws nothing for them (count `add_redact_annot` calls, as `test_an_unchanged_job_isnt_erased` does).
- **Existing:** all existing Build tests pass unchanged.

Steps: failing tests → implement → `python -m unittest tests.test_style_pdf -v` → `python tb.py test` → commit "Keep style: redraw a PDF's summary, headline and skills in place".

---

### Task 3: keep_style uses what the PDF handler really drew

**Files:** `teambid/keep_style.py`, `teambid/style_pdf.py` (module docstring, the `find` docstring), `tests/test_keep_style.py`

**Consumes:** `build`'s `"parts_kept"`.

**Produces:** in `keep_style.tailor`, after `_build`, for the PDF handler:
- pop `"parts_kept"`;
- set `plan["headline"] = None` or `plan["summary"] = None` where kept;
- set `plan["skills"][sid]` back to the doc's printed items for each kept sid;
- set `plan["skill_lines"] = []` when kept.

Then `report_spec` and the note tell only what was drawn.
- **The note:** add the parts drawn, for example ", summary reworded, headline set to the job's title, skills reordered (3 lines)". Mention parts kept only when Claude proposed a change that didn't fit, for example ", the summary kept its text to fit".
- **"Nothing changed" rule:** extend it so a PDF where only the summary, headline or skills changed is not sent to the template.
- **Rule-based pieces** (`by != "claude"`): already reorder-only. Confirm summary and headline stay, and that skills are still reordered by job weight (`default_plan`).
- **Docstrings:** update the module docstring ("Bullets only for now") and the `find` docstring.

**Tests** (ApplyWithPdf style, Claude mocked):
- A reply with a new summary, headline and skill order tailors all three inside the PDF. The note says so, and the PDF reads back with the new summary.
- A summary too long to fit is reported as kept, and the report's summary is the original.
- A PDF where only the skills change still gets its own style, not the template.

Steps: failing tests → implement → `python -m unittest tests.test_keep_style -v` → `python tb.py test` → commit "Keep style: the note and report say which PDF parts were tailored".

---

### Task 4: Prove it on the real PDFs, then ship (controller, owner-gated)

- **Real plans:** rerun the real-PDF check (`scratchpad/run_wave2.py`, Arial standing in for the online fonts) with Claude's real plans for Karol and Leandro (`diag_plan.py --new`, one Sonnet call each) and the saved readings of all 7.
  - Every member still builds.
  - Count the summaries, headlines and skill lines drawn.
  - Look at before and after pages by eye.
- **Ship:** push the branch, run online Tests, open a PR, merge on the owner's OK, then rebuild documents on request.

"""Fictional resume PDFs for the PDF handler tests (no real people), drawn with PyMuPDF's built-in fonts.

make(path, ...) draws DANA REYES's resume: a header with a mailto link, an Experience heading, the jobs in JOBS (each
bullet on two lines, **bold** words in Helvetica-Bold) and an Education heading. Its options draw the variations the
tests need (see make), a headline, a summary and skill lines among them. PIECES is what keep_style.confirm keeps from
Claude's reading of it; pieces() adds the headline, summary and skill lines to it."""
import re

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
HEADLINE = "Backend Engineer for Payment Platforms"
SUMMARY = ("Backend engineer with eight years of **Python** and Go, building",
           "payment systems that banks and card networks rely on daily.")
SKILLS = [("Languages", ["Python", "Go", "SQL", "TypeScript"]),
          ("Data", ["PostgreSQL", "Redis", "Kafka", "Airflow"]),
          ("Cloud", ["AWS", "Docker", "Kubernetes", "Terraform"])]
PITCH, GAP, X_SIGN, X_TEXT = 12.5, 18.0, 52.0, 62.0
BOTTOM = 790.0
BLUE = (0.1, 0.3, 0.8)
GRAY = (0.37, 0.39, 0.41)


def pieces(headline=False, summary=False, skills=False):
    """PIECES with the confirmed headline (HEADLINE, or a text given), summary and skill lines that make()'s options of
    the same names draw. A fresh copy: a test may change it."""
    out = {**PIECES, "jobs": [dict(j, bullets=list(j["bullets"])) for j in PIECES["jobs"]]}
    if headline:
        out["headline"] = HEADLINE if headline is True else headline
    if summary:
        out["summary"] = " ".join(SUMMARY).replace("**", "")
    if skills:
        out["skills"] = [{"label": label, "items": list(items)} for label, items in SKILLS]
    return out


def _runs(page, x, y, text, faces, size=10):
    """Draw text from (x, y): **bold**, //italic//, ##bold blue## and %%letter-spaced%% runs (each letter 1.2 pt
    apart: more than a tenth of the size, less than the gap MuPDF reads as a space); a run without marks is ONE
    insert_text."""
    bold = italic = blue = tracked = False
    for part in re.split(r"(\*\*|//|##|%%)", text):
        if part in ("**", "//", "##", "%%"):
            bold, italic, blue = bold ^ (part == "**"), italic ^ (part == "//"), blue ^ (part == "##")
            tracked ^= part == "%%"
            continue
        if part:
            name, font = faces["bold" if bold or blue else "italic" if italic else "body"]
            for t in part if tracked else [part]:
                page.insert_text((x, y), t, fontname=name, fontsize=size, color=BLUE if blue else (0, 0, 0))
                x += font.text_length(t, fontsize=size) + (1.2 if tracked else 0)
            x -= 1.2 if tracked else 0


def _one_name(doc):
    """PyMuPDF names an inserted font "Arial Regular" in two places and "ArialMT" (its program's name) in a third; a
    real PDF uses one name throughout, so the text's font name finds its font."""
    for xref in {f[0] for pg in doc for f in pg.get_fonts() if f[4] in ("F0", "F1")}:
        desc = int(doc.xref_get_key(xref, "DescendantFonts")[1].strip("[]").split()[0])
        name = doc.xref_get_key(desc, "BaseFont")[1]
        doc.xref_set_key(xref, "BaseFont", name)
        doc.xref_set_key(int(doc.xref_get_key(desc, "FontDescriptor")[1].split()[0]), "FontName", name)


def make(path, sign="inline", break_page=False, link_bullet=False, tight=False, pitches=None, italic=False,
         lead_in=False, font_file=None, rule=False, intro=False, space_in_bold=False, underline=False, tracked=False,
         blank=False, subhead=False, mailto="mailto:dana@example.com", subhead_page=False, labels=False, sidebar=False,
         bold_start=False, footer=False, header=False, headline=None, summary=None, skills=None, topline=None,
         beside=None):
    """sign: 'inline' (a Symbol-font bullet on the line), 'circle' (a small drawn dot), 'typed' ("- " typed into the
    line's text, as Word's typed bullets and HTML-to-PDF write it), 'dash' or 'dot' (an en dash or a bullet in another
    font than the text's: Times, or the bold font of font_file), 'gray' (the inline sign and a space after it in gray,
    as some resume builders draw them).
    break_page: the first job starts near the bottom of page 1 and its last bullet runs onto page 2.
    link_bullet: the second job's first bullet holds a link.
    tight: lines 11.5 pt apart with no extra gap between bullets, the job headings right above and below.
    pitches: the line spacing inside each of the first job's bullets (the gaps between bullets stay).
    italic: "public" in the first job's third bullet is in italics.
    lead_in: the first bullet starts with a bold blue word.
    font_file: (regular, bold) TrueType files embedded whole for the bullets, with a correct text layer (as Word
    writes it).
    rule: a thin line through the middle of the second job's first bullet line (a strike-through or a table rule).
    intro: the first job's first bullet is a paragraph without a sign, set at x=50 (left of the signs at 52).
    space_in_bold: the space before a bold word is drawn in the bold run (" Python"), as some exporters write it.
    underline: a line 3 pt under the baseline of the second job's first bullet's last line (below that line's box).
    tracked: "public" in the first job's third bullet is letter-spaced (each letter set on its own).
    blank: a lone space at the foot of the page, written right after the first job's last line (no letters, no place).
    subhead: a project heading inside the first job, between its first and second bullets.
    mailto: where the header's email link goes (an old address, say: the text still shows dana@example.com).
    subhead_page: the first job's second bullet starts a new page under a project heading at the top of it, larger
    than the bullets' text ("same": the same size; "indent": the same size where the bullets' wrapped lines start).
    labels: project labels in the left margin beside the first job's first and third bullets' first lines; "two"
    puts each label's dates on a line under it.
    sidebar: a column of text in the left margin all along the first job, in its own line spacing (not labels).
    bold_start: the second line of the first job's first bullet starts with a bold word ("most": is mostly bold).
    footer: "Page n of N" at each page's foot, just above its bottom 5%, as Word sets it.
    header: a gray header line on page 2 at half an inch, as Word sets it.
    headline: HEADLINE on a line of its own under the name (what's below moves down): 'left' (where the name starts),
    'center' (centred over the page's text), 'right' (ending where the page's text does), 'mixed' (left, one word in
    bold), 'title' (left, the first job's title).
    summary: a Summary heading and SUMMARY's two lines (one word in bold) above Experience; 'italic': one word of it in
    italics.
    skills: a Skills heading and SKILLS as "**Label:** a, b, c" lines under Education; 'chips': each item in a small
    drawn box; 'gap': two spaces after each label.
    topline: a line of small text at the top of page 1, above the name (a sentence that holds the headline's words).
    beside: a word on the headline's line, at x=290 in 10 pt (other text on its line, to its right)."""
    pitch, gap, above, after = (11.5, 11.5, 11.5, 0.0) if tight else (PITCH, GAP, 20.0, 16.0)
    if font_file:
        faces = {"body": ("F0", fitz.Font(fontfile=font_file[0])), "bold": ("F1", fitz.Font(fontfile=font_file[1]))}
    else:
        faces = {"body": ("helv", fitz.Font("helv")), "bold": ("hebo", fitz.Font("hebo"))}
    faces["italic"] = ("heit", fitz.Font("heit"))
    doc = fitz.open()

    def new_page():
        p = doc.new_page(width=595, height=842)
        if header and doc.page_count == 2:
            p.insert_text((50, 45), "Dana Reyes - Resume", fontname="helv", fontsize=8, color=GRAY)
        if font_file:
            p.insert_font(fontname="F0", fontfile=font_file[0])
            p.insert_font(fontname="F1", fontfile=font_file[1])
        return p

    page, side = new_page(), []
    top = 14.0 if headline else 0.0              # room for the headline under the name
    if topline:
        page.insert_text((50, 34), topline, fontname="helv", fontsize=8)
    page.insert_text((50, 60), "DANA REYES", fontname="hebo", fontsize=18)
    page.insert_text((50, 80 + top), "dana@example.com", fontname="helv", fontsize=10)
    page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(50, 71 + top, 140, 83 + top), "uri": mailto})
    y = 110 + top
    if summary:
        page.insert_text((50, y), "Summary", fontname="hebo", fontsize=13)
        for n, line in enumerate(SUMMARY):
            if summary == "italic" and n == 1:
                line = line.replace("daily", "//daily//")
            _runs(page, 50, y + 20 + n * PITCH, line, faces)
        y += 20 + len(SUMMARY) * PITCH + 30 - PITCH
    page.insert_text((50, y), "Experience", fontname="hebo", fontsize=13)
    y = 708.0 if break_page else y + 30
    for ji, (title, company, bullets) in enumerate(JOBS):
        if y > BOTTOM - 40:
            page, y = new_page(), 60.0
        page.insert_text((50, y), f"{title}, {company}", fontname="hebo", fontsize=11)
        y += above
        for bi, lines in enumerate(bullets):
            p = pitches[bi] if pitches and ji == 0 else pitch
            if subhead and (ji, bi) == (0, 1):
                page.insert_text((50, y), "Payments platform", fontname="hebo", fontsize=10)
                y += gap
            if subhead_page and (ji, bi) == (0, 1):
                page, y = new_page(), 60.0
                page.insert_text((X_TEXT if subhead_page == "indent" else 50, y), "Payments platform", fontname="hebo",
                                 fontsize=11.5 if subhead_page is True else 10)
                y += gap
            for n, line in enumerate(lines):
                if y > BOTTOM:
                    page, y = new_page(), 60.0
                if italic and (ji, bi, n) == (0, 2, 0):
                    line = line.replace("public", "//public//")
                if lead_in and (ji, bi, n) == (0, 0, 0):
                    line = line.replace("Built", "##Built##", 1)
                if tracked and (ji, bi, n) == (0, 2, 0):
                    line = line.replace("public", "%%public%%")
                if bold_start and (ji, bi, n) == (0, 0, 1):
                    line = "**2M requests a day for card and bank** transfers." if bold_start == "most" else                         line.replace("2M", "**2M**", 1)
                if space_in_bold:
                    line = line.replace(" **", "** ")      # "in **Python** and" -> "in", " Python", " and"
                x = X_TEXT
                if intro and (ji, bi) == (0, 0):
                    x = 50.0
                elif n == 0:
                    if sign == "circle":
                        page.draw_circle((X_SIGN + 1.6, y - 3.2), 1.6, color=None, fill=(0, 0, 0))
                    elif sign == "typed":
                        line = "- " + line
                        x -= faces["body"][1].text_length("- ", fontsize=10)
                    elif sign in ("dash", "dot"):
                        page.insert_text((X_SIGN, y), "–" if sign == "dash" else "•",
                                         fontname=faces["bold"][0] if font_file else "tiro", fontsize=10)
                    elif sign == "gray":                  # the sign and the space after it in gray, the text black
                        page.insert_text((X_SIGN, y), "•", fontname="symb", fontsize=10, color=GRAY)
                        page.insert_text((X_SIGN + 4.6, y), " ", fontname="helv", fontsize=10, color=GRAY)
                    else:
                        page.insert_text((X_SIGN, y), "•", fontname="symb", fontsize=10)
                    if link_bullet and ji == 1 and bi == 0:
                        page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(X_TEXT, y - 9, 300, y + 3),
                                          "uri": "https://example.com/airflow"})
                    if rule and (ji, bi) == (1, 0):
                        page.draw_line((X_TEXT, y - 3), (X_TEXT + 60, y - 3), color=(0, 0, 0), width=0.5)
                if underline and (ji, bi, n) == (1, 0, 1):
                    page.draw_line((X_TEXT, y + 3), (X_TEXT + 30, y + 3), color=(0, 0, 0), width=0.5)
                if labels and ji == 0 and bi in (0, 2) and n == 0:
                    page.insert_text((14, y), "Ledger" if bi == 0 else "Docs", fontname="hebo", fontsize=8)
                    if labels == "two":
                        page.insert_text((14, y + 9), "2021-23" if bi == 0 else "2023-24", fontname="helv", fontsize=8)
                if sidebar and ji == 0:
                    side.append((page, y))
                _runs(page, x, y, line, faces)
                y += p
            if blank and (ji, bi) == (0, len(bullets) - 1):
                page.insert_text((300, 830), " ", fontname="helv", fontsize=10)
            y += gap - p
        y += after
    if side:                                  # after the bullets, as a sidebar is drawn: its own lines, every 9.5 pt
        pg, top, bottom = side[0][0], side[0][1] - 20, side[-1][1] + 10
        for n in range(int((bottom - top) / 9.5) + 1):
            pg.insert_text((14, top + 9.5 * n), "Skill", fontname="helv", fontsize=8)
    if y > BOTTOM - 20:
        page, y = new_page(), 60.0
    page.insert_text((50, y + 10), "Education", fontname="hebo", fontsize=13)
    if skills:
        if y > BOTTOM - 100:
            page, y = new_page(), 20.0
        page.insert_text((50, y + 50), "Skills", fontname="hebo", fontsize=13)
        body, bold = faces["body"][1], faces["bold"][1]
        for n, (label, items) in enumerate(SKILLS):
            sy = y + 70 + 14 * n
            _runs(page, 50, sy, f"**{label}:**{'  ' if skills == 'gap' else ' '}" + ", ".join(items), faces)
            x = 50 + bold.text_length(f"{label}:", fontsize=10) + body.text_length(" ", fontsize=10)
            for item in items:
                w = body.text_length(item, fontsize=10)
                if skills == "chips":
                    page.draw_rect(fitz.Rect(x - 1.5, sy - 8, x + w + 1.5, sy + 2.5), color=GRAY, width=0.5)
                x += w + body.text_length(", ", fontsize=10)
    if headline:                              # last: a centred one is centred over all the text on its page
        hp = page if page.number == 0 else doc[0]
        text = PIECES["jobs"][0]["title"] if headline == "title" else HEADLINE
        x, ws, width = 50.0, hp.get_text("words"), fitz.Font("helv").text_length(text, fontsize=12)
        if headline == "center":
            x = (min(w[0] for w in ws) + max(w[2] for w in ws) - width) / 2
        elif headline == "right":
            x = max(w[2] for w in ws) - width
        heads = {"body": ("helv", fitz.Font("helv")), "bold": ("hebo", fitz.Font("hebo")), "italic": faces["italic"]}
        _runs(hp, x, 78, text.replace("Payment", "**Payment**") if headline == "mixed" else text, heads, size=12)
        if beside:
            hp.insert_text((290, 78), beside, fontname="helv", fontsize=10)
    if font_file:
        from teambid import style_pdf
        style_pdf._fix_tounicode(doc, {"F0", "F1"})        # hyphens and spaces read back as "-" and " "
        _one_name(doc)
    if footer:
        for n, pg in enumerate(doc):
            pg.insert_text((270, 804), f"Page {n + 1} of {doc.page_count}", fontname="helv", fontsize=10)
    doc.save(path)
    doc.close()
    return path

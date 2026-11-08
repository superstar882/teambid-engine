"""Fictional Word resumes for the .docx handler tests (no real people), built with python-docx.

make(path, ...) writes LENA BRANDT's resume: her name and HEADLINE, a contact line with a link, a Summary heading and
SUMMARY (one phrase in bold), an Experience heading with the jobs in JOBS (a heading line, then each bullet as a list
item: the first job's by the "List Bullet" style, the second's by numbering set on the paragraph itself; **bold**
words in bold runs), and a Skills heading with SKILLS as "**Label:** a, b, c" paragraphs. Its options build the
variations the tests need (see make). PIECES is what keep_style.confirm keeps from Claude's reading of it."""
import re

import docx
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

NAME = "Lena Brandt"
HEADLINE = "Data Platform Engineer"
CONTACT = ("lena.brandt@example.com | Hamburg | ", "github.com/lenabrandt-example")      # the second part is a link
SUMMARY = ("Data engineer with seven years of **Python** and SQL, building the pipelines that analysts and finance "
           "teams trust every morning.")
JOBS = [
    ("Senior Data Engineer", "Fabrikam Analytics", "2021-03", "Present", [
        "Built a streaming pipeline on **Kafka** that loads 40M events a day into the warehouse.",
        "Cut the nightly batch from 6 hours to 90 minutes by partitioning the largest tables.",
        "Wrote the data contracts and on-call runbook used by four product teams.",
    ]),
    ("Data Engineer", "Tailspin Retail", "2018-06", "2021-02", [
        "Moved 25 cron jobs to Airflow, ending missed nightly runs and manual reruns.",
        "Added dbt tests to 60 models, catching schema drift before it reached the reports.",
    ]),
]
SKILLS = [("Languages", ["Python", "Go", "SQL"]),
          ("Data", ["PostgreSQL", "Kafka", "Airflow"]),
          ("Cloud", ["AWS", "Docker", "Terraform"])]
PIECES = {"headline": HEADLINE, "summary": SUMMARY.replace("**", ""), "by": "claude",
          "jobs": [{"title": t, "company": c, "location": "", "start": s, "end": e,
                    "bullets": [b.replace("**", "") for b in bullets]} for t, c, s, e, bullets in JOBS],
          "skills": [{"label": label, "items": items} for label, items in SKILLS]}


def pieces():
    """A fresh copy of PIECES: a test may change it."""
    return {**PIECES, "jobs": [dict(j, bullets=list(j["bullets"])) for j in PIECES["jobs"]],
            "skills": [dict(l, items=list(l["items"])) for l in PIECES["skills"]]}


def _runs(par, text):
    """Add text to par: **bold** and //italic// runs, each stretch without marks one plain run."""
    bold = italic = False
    for part in re.split(r"(\*\*|//)", text):
        if part in ("**", "//"):
            bold, italic = bold ^ (part == "**"), italic ^ (part == "//")
            continue
        if part:
            run = par.add_run(part)
            run.bold = bold or None
            run.italic = italic or None


def _link(par, text, url):
    """A w:hyperlink to url holding one blue, underlined run of text."""
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), par.part.relate_to(url, RT.HYPERLINK, is_external=True))
    run = OxmlElement("w:r")
    rpr = OxmlElement("w:rPr")
    for tag, val in (("w:color", "0563C1"), ("w:u", "single")):
        el = OxmlElement(tag)
        el.set(qn("w:val"), val)
        rpr.append(el)
    t = OxmlElement("w:t")
    t.text = text
    t.set(qn("xml:space"), "preserve")
    run.append(rpr)
    run.append(t)
    link.append(run)
    par._p.append(link)


def _numbered(par):
    """Make par a list item by numbering set on the paragraph itself (w:numPr), not by its style."""
    num = par._p.get_or_add_pPr().get_or_add_numPr()
    num.get_or_add_ilvl().val = 0
    num.get_or_add_numId().val = 1


def _bullet(where, text, how, link=None):
    """One bullet paragraph added to where (the document or a table cell): how is 'style' (List Bullet), 'numpr' (its
    own numbering) or 'typed' ("• " typed into its text). link: (word, url) makes that word of it a link."""
    par = where.add_paragraph(style="List Bullet" if how == "style" else None)
    if how == "numpr":
        _numbered(par)
    if how == "typed":
        text = "• " + text
    if link:
        before, after = text.split(link[0], 1)
        _runs(par, before)
        _link(par, *link)
        _runs(par, after)
    else:
        _runs(par, text)
    return par


def make(path, link_bullet=False, table=False, nested=False, gap=False, typed=False, italic=False, header_text=None):
    """link_bullet: "Airflow" in the second job's first bullet is a link.
    table: the first job's bullets are in the right cell of a one-row table (its dates in the left cell); nested: in
    a table inside that cell.
    gap: a plain paragraph ("Team of six engineers.") between the first job's first and second bullets.
    typed: the first job's bullets are plain paragraphs that start with a typed "• " (no list numbering).
    italic: "on-call runbook" in the first job's third bullet is in italics.
    header_text: a paragraph of this text in the page header (Word's header part, not the body)."""
    d = docx.Document()
    if header_text:
        d.sections[0].header.paragraphs[0].text = header_text
    name = d.add_paragraph()
    _runs(name, f"**{NAME}**")
    d.add_paragraph(HEADLINE)
    contact = d.add_paragraph()
    _runs(contact, CONTACT[0])
    _link(contact, CONTACT[1], "https://github.com/lenabrandt-example")
    d.add_heading("Summary", level=1)
    _runs(d.add_paragraph(), SUMMARY)
    d.add_heading("Experience", level=1)
    for n, (title, company, start, end, bullets) in enumerate(JOBS):
        _runs(d.add_paragraph(), f"**{title}** | {company} | {start} - {end}")
        where = d
        if n == 0 and table:
            t = d.add_table(rows=1, cols=2)
            t.cell(0, 0).text = f"{start} - {end}"
            where = t.cell(0, 1)
            if nested:
                where = where.add_table(rows=1, cols=1).cell(0, 0)
        for m, text in enumerate(bullets):
            if n == 0 and m == 1 and gap:
                where.add_paragraph("Team of six engineers.")
            if n == 0 and m == 2 and italic:
                text = text.replace("on-call runbook", "//on-call runbook//")
            how = "typed" if n == 0 and typed else "style" if n == 0 else "numpr"
            _bullet(where, text, how,
                    ("Airflow", "https://airflow.apache.org") if n == 1 and m == 0 and link_bullet else None)
            if where is not d and where.paragraphs[0].text == "" and len(where.paragraphs) > 1:
                where.paragraphs[0]._p.getparent().remove(where.paragraphs[0]._p)   # a new cell's empty paragraph
    d.add_heading("Skills", level=1)
    for label, items in SKILLS:
        _runs(d.add_paragraph(), f"**{label}:** {', '.join(items)}")
    d.add_heading("Education", level=1)
    d.add_paragraph("B.Sc. Computer Science, University of Bremen, 2018")
    d.save(path)
    return path

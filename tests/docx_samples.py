"""Fictional Word resumes for the .docx handler tests (no real people), built with python-docx.

make(path, ...) writes LENA BRANDT's resume: her name and HEADLINE, a contact line with a link, a Summary heading and
SUMMARY (one phrase in bold), an Experience heading with the jobs in JOBS (a heading line, then each bullet as a list
item: the first job's by the "List Bullet" style, the second's by numbering set on the paragraph itself; **bold**
words in bold runs), and a Skills heading with SKILLS as "**Label:** a, b, c" paragraphs. Its options build the
variations the tests need (see make). PIECES is what keep_style.confirm keeps from Claude's reading of it."""
import io
import re
import struct
import zlib

import docx
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

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


def _png():
    """A 1x1 white PNG, for a picture in a paragraph."""
    chunk = lambda kind, data: (struct.pack(">I", len(data)) + kind + data
                                + struct.pack(">I", zlib.crc32(kind + data)))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff")) + chunk(b"IEND", b""))


def _xml(xml):
    """The elements of a piece of WordprocessingML text (the w: namespace declared; VML's v: where it's used)."""
    return list(parse_xml(f'<w:wrap {nsdecls("w")} xmlns:v="urn:schemas-microsoft-com:vml">{xml}</w:wrap>'))


def _r(text, tag="w:t"):
    return f'<w:r><{tag} xml:space="preserve">{text}</{tag}></w:r>'


TRACK = 'w:author="A. Reviewer" w:date="2026-11-01T09:00:00Z"'
# odd: how the first job's first bullet holds it -> (its text before, the XML in the middle, its text after)
ODD = {
    "fldSimple": ("Built a streaming pipeline on **Kafka** that loads ",
                  f'<w:fldSimple w:instr=" DOCPROPERTY Events ">{_r("40M")}</w:fldSimple>',
                  " events a day into the warehouse."),
    "fldChar": ("Built a streaming pipeline on **Kafka** that loads ",
                '<w:r><w:fldChar w:fldCharType="begin"/></w:r>' + _r(" DOCPROPERTY Events ", "w:instrText")
                + '<w:r><w:fldChar w:fldCharType="separate"/></w:r>' + _r("40M")
                + '<w:r><w:fldChar w:fldCharType="end"/></w:r>',
                " events a day into the warehouse."),
    "ins": ("Built a streaming pipeline on **Kafka** that loads 40M events a day into ",
            f'<w:ins w:id="1" {TRACK}>{_r("the warehouse")}</w:ins>', "."),
    "del": ("Built a streaming pipeline on **Kafka** that loads 40M ",
            f'<w:del w:id="2" {TRACK}>{_r("nightly ", "w:delText")}</w:del>', "events a day into the warehouse."),
    "pict": ("Built a streaming pipeline on **Kafka** that loads 40M events a day into the warehouse.",
             '<w:r><w:pict><v:rect style="width:6pt;height:6pt" fillcolor="#0563C1"/></w:pict></w:r>', ""),
    "textbox": ("Built a streaming pipeline on **Kafka** that loads 40M events a day into the warehouse.",
                '<w:r><w:pict><v:shape style="width:220pt;height:30pt"><v:textbox><w:txbxContent>'
                '<w:p><w:pPr><w:pStyle w:val="ListBullet"/></w:pPr>{inner}</w:p>'
                '</w:txbxContent></v:textbox></v:shape></w:pict></w:r>', ""),
}


def _odd_bullet(where, odd, inner):
    """The first job's first bullet (a "List Bullet" paragraph) holding odd (ODD, or 'drawing': a picture after its
    text). inner: the text a text box in it holds (the first job's third bullet, then not in the body)."""
    par = where.add_paragraph(style="List Bullet")
    if odd == "drawing":
        _runs(par, JOBS[0][4][0])
        par.add_run().add_picture(io.BytesIO(_png()))
        return
    before, middle, after = ODD[odd]
    _runs(par, before)
    for el in _xml(middle.replace("{inner}", _r(inner))):
        par._p.append(el)
    _runs(par, after)


def make(path, link_bullet=False, table=False, nested=False, gap=False, typed=False, italic=False, header_text=None,
         odd=None):
    """link_bullet: "Airflow" in the second job's first bullet is a link.
    table: the first job's bullets are in the right cell of a one-row table (its dates in the left cell); nested: in
    a table inside that cell.
    gap: a plain paragraph ("Team of six engineers.") between the first job's first and second bullets.
    typed: the first job's bullets are plain paragraphs that start with a typed "• " (no list numbering).
    italic: "on-call runbook" in the first job's third bullet is in italics.
    header_text: a paragraph of this text in the page header (Word's header part, not the body).
    odd: the first job's first bullet holds a simple field ('fldSimple') or a complex one ('fldChar') giving its
    "40M", a tracked insertion of "the warehouse" ('ins'), a tracked deletion of "nightly " before "events" ('del'), a
    picture after its text ('drawing': DrawingML; 'pict': a VML shape), or a text box after its text holding the
    first job's third bullet ('textbox'; that bullet is then nowhere else)."""
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
            if n == 0 and m == 0 and odd:
                _odd_bullet(where, odd, bullets[2])
                continue
            if n == 0 and m == 2 and odd == "textbox":
                continue                      # it's in the first bullet's text box
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

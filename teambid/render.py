"""Render a resume spec / cover letter to DOCX (python-docx) and PDF (PyMuPDF Story: HTML+CSS layout, no Word needed).

Layout follows ATS research: one column, standard section names, real text (no tables, images or text boxes),
dates on the role line, 10-11 pt body. fit_one_page() drops the least relevant bullets of the oldest roles until the
PDF is one page (two for 8+ years of experience).
"""
import html
from pathlib import Path

import docx
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, Inches, RGBColor

CSS = """
* { font-family: sans-serif; }
body { font-size: 9.6pt; line-height: 1.22; color: #111; }
h1 { font-size: 18pt; margin: 0 0 1pt 0; }
.head { font-size: 10pt; color: #333; margin: 0 0 1pt 0; }
.contact { font-size: 8.8pt; color: #333; margin: 0 0 4pt 0; }
h2 { font-size: 10pt; text-transform: uppercase; letter-spacing: 0.5pt; border-bottom: 0.6pt solid #888; margin: 6pt 0 2pt 0; color: #222; }
.role { margin: 3pt 0 0 0; }
.rt { font-weight: bold; }
.dates { color: #333; }
.stack { font-size: 8.5pt; color: #444; margin: 0; }
ul { margin: 1pt 0 0 12pt; padding: 0; }
li { margin: 0 0 1pt 0; }
p { margin: 0 0 2pt 0; }
.sk { margin: 0 0 1pt 0; }
"""


def _date(s):
    if not s:
        return ""
    if s == "Present":
        return "Present"
    import calendar
    try:
        y, m = s.split("-")
        return f"{calendar.month_abbr[int(m)]} {y}"
    except ValueError:
        return s


def _contact_line(c):
    return "  |  ".join(x for x in [c.get("location"), c.get("email"), c.get("phone"), c.get("linkedin"), c.get("github"), c.get("website")] if x)


def resume_html(spec):
    e = html.escape
    out = [f"<h1>{e(spec['name'])}</h1>"]
    if spec.get("headline"):
        out.append(f"<p class='head'>{e(spec['headline'])}</p>")
    out.append(f"<p class='contact'>{e(_contact_line(spec.get('contact', {})))}</p>")
    if spec.get("summary"):
        out += ["<h2>Summary</h2>", f"<p>{e(spec['summary'])}</p>"]
    if spec.get("skills"):
        out.append("<h2>Skills</h2>")
        out += [f"<p class='sk'><b>{e(g)}:</b> {e(', '.join(items))}</p>" for g, items in spec["skills"] if items]
    if spec.get("roles"):
        out.append("<h2>Experience</h2>")
        for r in spec["roles"]:
            dates = f"{_date(r['start'])} - {_date(r['end'])}" if r.get("start") else ""
            loc = f" | {e(r['location'])}" if r.get("location") else ""
            out.append(f"<p class='role'><span class='rt'>{e(r['title'])}</span>, {e(r['company'])}{loc} &nbsp; <span class='dates'>{e(dates)}</span></p>")
            if r.get("stack"):
                out.append(f"<p class='stack'>{e(' | '.join(r['stack']))}</p>")
            if r["bullets"]:
                out.append("<ul>" + "".join(f"<li>{e(b)}</li>" for b in r["bullets"]) + "</ul>")
    if spec.get("projects"):
        out.append("<h2>Projects</h2>")
        for p in spec["projects"]:
            link = f" ({e(p['link'])})" if p.get("link") else ""
            out.append(f"<p class='role'><span class='rt'>{e(p['name'])}</span>{link}</p>")
            if p.get("stack"):
                out.append(f"<p class='stack'>{e(' | '.join(p['stack']))}</p>")
            out.append("<ul>" + "".join(f"<li>{e(b)}</li>" for b in p["bullets"]) + "</ul>")
    if spec.get("education"):
        out.append("<h2>Education</h2>")
        for ed in spec["education"]:
            deg = ", ".join(x for x in [ed.get("degree"), ed.get("field")] if x)
            gpa = f" | GPA {ed['gpa']}" if ed.get("gpa") else ""
            yrs = " - ".join(x for x in [ed.get("start"), ed.get("end")] if x)
            out.append(f"<p><b>{e(ed.get('school', ''))}</b>{', ' + e(deg) if deg else ''}{e(gpa)} &nbsp; <span class='dates'>{e(yrs)}</span></p>")
    extra = [*spec.get("certifications", []), *spec.get("awards", [])]
    if extra:
        title = "Certifications and awards" if spec.get("awards") and spec.get("certifications") else \
            ("Awards" if spec.get("awards") else "Certifications")
        out += [f"<h2>{title}</h2>", "<p>" + " &nbsp;·&nbsp; ".join(e(x) for x in extra) + "</p>"]
    return "<body>" + "\n".join(out) + "</body>"


def html_to_pdf(body_html, path, css=CSS, paper="letter"):
    import fitz
    story = fitz.Story(html=body_html, user_css=css)
    writer = fitz.DocumentWriter(str(path))
    mediabox = fitz.paper_rect(paper)
    where = mediabox + (40, 34, -40, -34)
    pages, more = 0, 1
    while more:
        dev = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
        pages += 1
        if pages > 6:
            break
    writer.close()
    return pages


def resume_pdf(spec, path, paper="letter"):
    """Resume PDF -> pages. RenderCV's typeset layout when installed (cv_pdf.py); the HTML layout above otherwise."""
    from . import cv_pdf
    if cv_pdf.available():
        try:
            return cv_pdf.write_pdf(spec, path, paper)
        except Exception as e:                   # odd data RenderCV won't take: still give the member a resume
            print(f"RenderCV failed, using the basic layout: {str(e)[:200]}")
    return html_to_pdf(resume_html(spec), path, paper=paper)


def _paper_docx(d, paper):
    from docx.shared import Mm
    for s in d.sections:
        if paper == "a4":
            s.page_width, s.page_height = Mm(210), Mm(297)
        else:
            s.page_width, s.page_height = Inches(8.5), Inches(11)


def resume_docx(spec, path, paper="letter"):
    d = docx.Document()
    _paper_docx(d, paper)
    for s in d.sections:
        s.top_margin = s.bottom_margin = Inches(0.5)
        s.left_margin = s.right_margin = Inches(0.6)
    st = d.styles["Normal"]
    st.font.name, st.font.size = "Calibri", Pt(10)
    st.paragraph_format.space_after = Pt(1)

    def para(text="", bold=False, size=None, color=None, after=1):
        p = d.add_paragraph()
        r = p.add_run(text)
        r.bold = bold
        if size:
            r.font.size = Pt(size)
        if color:
            r.font.color.rgb = RGBColor.from_string(color)
        p.paragraph_format.space_after = Pt(after)
        return p

    def heading(t):
        p = para(t.upper(), bold=True, size=10.5, color="222222", after=1)
        p.paragraph_format.space_before = Pt(6)

    para(spec["name"], bold=True, size=18, after=0)
    if spec.get("headline"):
        para(spec["headline"], size=10.5, color="333333", after=0)
    para(_contact_line(spec.get("contact", {})), size=9, color="333333", after=4)
    if spec.get("summary"):
        heading("Summary")
        para(spec["summary"])
    if spec.get("skills"):
        heading("Skills")
        for g, items in spec["skills"]:
            p = d.add_paragraph()
            p.add_run(f"{g}: ").bold = True
            p.add_run(", ".join(items))
            p.paragraph_format.space_after = Pt(0)
    if spec.get("roles"):
        heading("Experience")
        for r in spec["roles"]:
            p = d.add_paragraph()
            p.add_run(r["title"]).bold = True
            p.add_run(f", {r['company']}" + (f" | {r['location']}" if r.get("location") else ""))
            if r.get("start"):
                p.add_run(f"    {_date(r['start'])} - {_date(r['end'])}")
            p.paragraph_format.space_before = Pt(3)
            p.paragraph_format.space_after = Pt(0)
            if r.get("stack"):
                para(" | ".join(r["stack"]), size=8.5, color="444444", after=0)
            for b in r["bullets"]:
                bp = d.add_paragraph(b, style="List Bullet")
                bp.paragraph_format.space_after = Pt(0)
    if spec.get("projects"):
        heading("Projects")
        for pj in spec["projects"]:
            para(pj["name"] + (f" ({pj['link']})" if pj.get("link") else ""), bold=True, after=0)
            for b in pj["bullets"]:
                d.add_paragraph(b, style="List Bullet").paragraph_format.space_after = Pt(0)
    if spec.get("education"):
        heading("Education")
        for ed in spec["education"]:
            deg = ", ".join(x for x in [ed.get("degree"), ed.get("field")] if x)
            p = d.add_paragraph()
            p.add_run(ed.get("school", "")).bold = True
            p.add_run((", " + deg if deg else "") + (f" | GPA {ed['gpa']}" if ed.get("gpa") else "") +
                      ("    " + " - ".join(x for x in [ed.get("start"), ed.get("end")] if x)))
    extra = [*spec.get("certifications", []), *spec.get("awards", [])]
    if extra:
        heading("Certifications and awards" if spec.get("awards") and spec.get("certifications") else
                ("Awards" if spec.get("awards") else "Certifications"))
        d.add_paragraph("  ·  ".join(extra)).paragraph_format.space_after = Pt(0)
    d.save(path)


def _shrink(spec):
    """Take one thing out to save space, least useful first. -> False when nothing is left to take.
    A 4th bullet goes before a 5th skill line, a 3rd before a 4th, and every job keeps 2 bullets while anything else can go:
    a resume with one line per job reads as if the member did little."""
    roles, skills = spec["roles"], spec.get("skills") or []

    def drop_bullet(keep):
        """From the jobs with more than `keep` bullets, drop the least relevant last bullet (older job on ties)."""
        cands = [i for i, r in enumerate(roles) if len(r["bullets"]) > keep]
        if not cands:
            return False
        last = lambda i: (roles[i].get("scores") or [0] * len(roles[i]["bullets"]))[len(roles[i]["bullets"]) - 1]
        r = roles[min(cands, key=lambda i: (last(i), -i))]
        r["bullets"].pop()
        if r.get("scores"):
            r["scores"] = r["scores"][:len(r["bullets"])]
        return True

    if spec.get("projects"):
        spec["projects"].pop()
    elif drop_bullet(3):
        pass
    elif len(skills) > 4:
        skills.pop()
    elif drop_bullet(2):
        pass
    elif len(skills) > 3:
        skills.pop()
    elif any(r.get("stack") for r in roles):
        next(r for r in reversed(roles) if r.get("stack"))["stack"] = []     # oldest job's tech line first
    elif drop_bullet(1):
        pass
    else:
        return False
    return True


def fit_one_page(spec, years=0, pdf_path=None, log=None, paper="letter", budget=None):
    """Take things out (see _shrink) until the PDF fits the page budget. Returns pages."""
    import tempfile
    budget = budget or (2 if years >= 8 else 1)
    tmp = Path(pdf_path) if pdf_path else Path(tempfile.mkstemp(suffix=".pdf")[1])
    for _ in range(60):
        pages = resume_pdf(spec, tmp, paper)
        if pages <= budget or not _shrink(spec):
            return pages
    return resume_pdf(spec, tmp, paper)


def _last_page_fill(pdf_path):
    """How much of the last page is used (0-1): a 2-line spill onto page 2 looks like a mistake."""
    import fitz
    with fitz.open(pdf_path) as doc:
        pg = doc[-1]
        ys = [b[3] for b in pg.get_text("blocks") if b[4].strip()]
        return (max(ys) - pg.rect.y0) / pg.rect.height if ys else 0.0


def fit_pages(spec, years, pdf_path, paper, budget):
    """fit_one_page, then: if the last page is under a quarter full, drop up to 3 of the least relevant old bullets to
    save that page. Keeps the longer version when 3 bullets aren't enough."""
    import copy
    pages = fit_one_page(spec, years, pdf_path, paper=paper, budget=budget)
    if pages < 2 or _last_page_fill(pdf_path) > 0.25:
        return pages
    trial = copy.deepcopy(spec)
    for _ in range(3):
        if not _shrink(trial):
            break
        if resume_pdf(trial, pdf_path, paper) < pages:
            spec.clear()
            spec.update(trial)
            return pages - 1
    return resume_pdf(spec, pdf_path, paper)


def write_resume(spec, folder, base, years=0, region="US"):
    from . import region as RG
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    pdf = folder / f"{base}.pdf"
    paper = RG.paper(region)
    pages = fit_pages(spec, years, pdf, paper, RG.page_budget(region, years))
    resume_docx(spec, folder / f"{base}.docx", paper)
    return {"pdf": str(pdf), "docx": str(folder / f"{base}.docx"), "pages": pages, "paper": paper.upper() if paper == "a4" else "Letter"}


def letter_html(name, contact, body, date_str):
    e = html.escape
    paras = "".join(f"<p>{e(p)}</p>" for p in body.strip().split("\n\n"))
    return (f"<body><h1>{e(name)}</h1><p class='contact'>{e(_contact_line(contact))}</p><p>{e(date_str)}</p>{paras}</body>")


LETTER_CSS = CSS.replace("font-size: 9.6pt", "font-size: 11pt").replace("line-height: 1.22", "line-height: 1.4") + " p { margin: 0 0 9pt 0; }"


def write_letter(name, contact, body, folder, base, date_str, paper="letter"):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    pdf = folder / f"{base}.pdf"
    html_to_pdf(letter_html(name, contact, body, date_str), pdf, LETTER_CSS, paper=paper)
    d = docx.Document()
    _paper_docx(d, paper)
    for s in d.sections:
        s.left_margin = s.right_margin = Inches(0.9)
    d.styles["Normal"].font.name, d.styles["Normal"].font.size = "Calibri", Pt(11)
    p = d.add_paragraph()
    r = p.add_run(name)
    r.bold, r.font.size = True, Pt(16)
    d.add_paragraph(_contact_line(contact))
    d.add_paragraph(date_str)
    for chunk in body.strip().split("\n\n"):
        d.add_paragraph(chunk)
    d.save(folder / f"{base}.docx")
    return {"pdf": str(pdf), "docx": str(folder / f"{base}.docx")}

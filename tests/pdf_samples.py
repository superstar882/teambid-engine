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

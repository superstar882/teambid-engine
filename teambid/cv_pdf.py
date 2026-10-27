"""Resume PDF with RenderCV (free, MIT, Typst typesetting): https://github.com/rendercv/rendercv

The same resume spec as render.resume_html, mapped onto RenderCV's YAML model and compiled in-process (no LaTeX, no
network). One column, standard section names, real text: ATS-safe. render.html_to_pdf stays as the fallback when
RenderCV isn't installed or a member's data trips its validation.
"""
import re
import shutil
import tempfile
from pathlib import Path

THEME = "engineeringresumes"


def available():
    try:
        import rendercv  # noqa: F401
        return True
    except ImportError:
        return False


def _md(text):
    """Escape the Markdown RenderCV would otherwise read in resume text (a lone * or _ turns a line italic)."""
    return re.sub(r"([\\*_`\[\]#])", r"\\\1", str(text or "")).strip()


def _url(u):
    u = (u or "").strip()
    return u if not u or re.match(r"https?://", u) else "https://" + u


def _date(s):
    from .render import _date as fmt
    return fmt(s)


def _span(start, end):
    a, b = _date(start), _date(end)
    return f"{a} – {b}" if a and b else (a or b)


def _connections(c):
    """Contact items as RenderCV custom connections (text + optional https link). Email and phone are plain text, so
    RenderCV's strict email/phone validation can never reject a member's resume."""
    out = []
    for key, icon in (("location", "location-dot"), ("email", "envelope"), ("phone", "phone")):
        if c.get(key):
            out.append({"placeholder": _md(c[key]), "url": None, "fontawesome_icon": icon})
    for key, icon in (("linkedin", "linkedin"), ("github", "github"), ("website", "link")):
        if c.get(key):
            shown = re.sub(r"^https?://(www\.)?", "", c[key].strip()).rstrip("/")
            out.append({"placeholder": _md(shown), "url": _url(c[key]), "fontawesome_icon": icon})
    return out


def to_rendercv(spec, paper="letter"):
    sections = {}
    if spec.get("summary"):
        sections["Summary"] = [_md(spec["summary"])]
    if spec.get("skills"):
        sections["Skills"] = [{"label": _md(g), "details": _md(", ".join(items))} for g, items in spec["skills"] if items]
    if spec.get("roles"):
        sections["Experience"] = [{
            "company": _md(r["company"]), "position": _md(r["title"]),
            "location": _md(r.get("location")) or None,
            "date": _span(r.get("start"), r.get("end")) or None,
            "summary": _md(" | ".join(r["stack"])) if r.get("stack") else None,
            "highlights": [_md(b) for b in r["bullets"]] or None,
        } for r in spec["roles"]]
    if spec.get("projects"):
        sections["Projects"] = [{
            "name": f"[{_md(p['name'])}]({_url(p['link'])})" if p.get("link") else _md(p["name"]),
            "summary": _md(" | ".join(p["stack"])) if p.get("stack") else None,
            "highlights": [_md(b) for b in p["bullets"]] or None,
        } for p in spec["projects"]]
    if spec.get("education"):
        sections["Education"] = [{
            "institution": _md(ed.get("school")) or "Education",
            "area": _md(ed.get("field") or ed.get("degree")) or None,
            "degree": _md(ed.get("degree")) if ed.get("field") and ed.get("degree") else None,
            "date": " – ".join(x for x in [ed.get("start"), ed.get("end")] if x) or None,
            "highlights": [f"GPA {_md(ed['gpa'])}"] if ed.get("gpa") else None,
        } for ed in spec["education"]]
    extra = [*spec.get("certifications", []), *spec.get("awards", [])]
    if extra:
        title = "Certifications and Awards" if spec.get("awards") and spec.get("certifications") else \
            ("Awards" if spec.get("awards") else "Certifications")
        sections[title] = [" · ".join(_md(x) for x in extra)]
    clean = lambda d: {k: v for k, v in d.items() if v not in (None, "", [])}
    sections = {k: [clean(x) if isinstance(x, dict) else x for x in v] for k, v in sections.items()}
    cv = clean({"name": spec["name"], "headline": _md(spec.get("headline")),
                "custom_connections": _connections(spec.get("contact", {})), "sections": sections})
    return {"cv": cv,
            "design": {"theme": THEME,
                       "page": {"size": "a4" if paper == "a4" else "us-letter", "show_footer": False, "show_top_note": False,
                                "top_margin": "0.5in", "bottom_margin": "0.5in", "left_margin": "0.6in", "right_margin": "0.6in"},
                       # the theme's gaps are made for long CVs: tighter (still easy to read) so a 1-page resume keeps
                       # 2-4 bullets per job instead of losing them to whitespace
                       "typography": {"line_spacing": "0.5em", "font_size": {"name": "22pt", "section_titles": "1.15em"}},
                       "header": {"space_below_name": "0.25cm", "space_below_headline": "0.2cm", "space_below_connections": "0.3cm"},
                       "section_titles": {"space_above": "0.3cm", "space_below": "0.18cm"},
                       "sections": {"space_between_regular_entries": "0.22cm", "space_between_text_based_entries": "0.08cm"},
                       "entries": {"summary": {"space_above": "0.04cm"},
                                   "highlights": {"space_above": "0.05cm", "space_between_items": "0.04cm"}}}}


def write_pdf(spec, pdf_path, paper="letter"):
    """Build the PDF at pdf_path. -> page count. Raises if RenderCV rejects the data (the caller falls back)."""
    import fitz
    import yaml
    from rendercv.renderer.pdf_png import generate_pdf
    from rendercv.renderer.typst import generate_typst
    from rendercv.schema.rendercv_model_builder import build_rendercv_dictionary_and_model
    work = Path(tempfile.mkdtemp(prefix="rcv-"))
    try:
        data = to_rendercv(spec, paper)
        data["settings"] = {"render_command": {
            "output_folder": str(work), "typst_path": str(work / "cv.typ"), "pdf_path": str(work / "cv.pdf"),
            "dont_generate_markdown": True, "dont_generate_html": True, "dont_generate_png": True}}
        src = work / "cv.yaml"
        text = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        src.write_text(text, encoding="utf-8")
        _, model = build_rendercv_dictionary_and_model(text, input_file_path=src)
        pdf = generate_pdf(model, generate_typst(model))
        shutil.copyfile(pdf, pdf_path)
        with fitz.open(pdf_path) as doc:
            return doc.page_count
    finally:
        shutil.rmtree(work, ignore_errors=True)

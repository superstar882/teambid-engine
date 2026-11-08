"""Keep-original-style, Word (.docx) handler (stdlib unittest). The fixture files come from tests/docx_samples.py and
are built with python-docx. Only the WithLibreOffice tests need LibreOffice (they run online); everywhere else the
converter is mocked, or faked by DS.fake_pdf, which prints the file's text into a PDF."""
import io
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from copy import deepcopy
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TEAMBID_WORKSPACE", tempfile.mkdtemp(prefix="teambid-test-"))
os.environ.setdefault("TEAMBID_LOCAL_AI", "off")

import docx  # noqa: E402
import fitz  # noqa: E402
from docx.oxml import OxmlElement  # noqa: E402
from docx.oxml.ns import qn  # noqa: E402
from docx.shared import Pt  # noqa: E402
from lxml import etree  # noqa: E402

from teambid import keep_style, style_docx, tailor  # noqa: E402
from teambid.style_text import key  # noqa: E402
from tests import docx_samples as DS  # noqa: E402

NO_OFFICE = RuntimeError("LibreOffice isn't available here, so a Word resume can't be built")
PLAN = {"headline": None, "summary": None, "text": {}, "order": {}, "skills": {}, "skill_lines": []}
NEW_BULLET = "Cut the nightly batch from 6 hours to 90 minutes by partitioning the biggest warehouse tables."
NEW_SUMMARY = ("Data engineer with seven years of **Python** and SQL, building the streaming pipelines analysts and "
               "finance teams trust daily.")
NEW_HEADLINE = "Senior Data Engineer"


def made(**kw):
    """A fresh fixture file (DS.make's options) -> its path."""
    return DS.make(str(Path(tempfile.mkdtemp()) / "lena.docx"), **kw)


def edit(path, change):
    """The fixture at path, changed by change(its python-docx document) and saved -> path."""
    d = docx.Document(path)
    change(d)
    d.save(path)
    return path


def starting(d, text):
    """The body paragraph of python-docx document d that starts with text."""
    return next(p for p in d.paragraphs if p.text.startswith(text))


def find(pieces=None, convert=NO_OFFICE, path=None, **kw):
    """style_docx.find on path, else a fresh fixture; convert: what the PDF converter does (raises it, or returns
    it)."""
    path = path or made(**kw)
    how = {"side_effect": convert} if isinstance(convert, Exception) else {"return_value": convert}
    with mock.patch.object(style_docx, "to_pdf", **how):
        return style_docx.find(path, pieces or DS.pieces())


def build(path, plan, convert=DS.fake_pdf, folder=None):
    """find, then build PLAN updated with plan into folder (a fresh one if None), LibreOffice faked by convert.
    -> (doc, files)."""
    with mock.patch.object(style_docx, "to_pdf", side_effect=convert):
        doc = style_docx.find(path, DS.pieces())
        return doc, style_docx.build(doc, dict(PLAN, **plan), folder or Path(tempfile.mkdtemp()), "out")


def xml(path):
    """The body's paragraphs in reading order, each as its XML."""
    return [etree.tostring(p) for p in style_docx.paragraphs(docx.Document(str(path)))]


def para(path, at):
    return style_docx.paragraphs(docx.Document(str(path)))[at]


def text(path, at):
    """What the paragraph at place `at` prints."""
    return "".join(t.text or "" for t in para(path, at).iter(qn("w:t")))


def runs(path, at):
    """[(text, bold, its w:rPr as XML)] for each run of the paragraph at place `at`."""
    out = []
    for r in para(path, at).iter(qn("w:r")):
        rpr = r.find(qn("w:rPr"))
        out.append(("".join(t.text or "" for t in r.iter(qn("w:t"))),
                    rpr is not None and rpr.find(qn("w:b")) is not None,
                    None if rpr is None else etree.tostring(rpr)))
    return out


def parts(path):
    """Every part of the file but the body (word/document.xml): {name: its XML in canonical form, or its bytes}."""
    out = {}
    with zipfile.ZipFile(path) as z:
        for name in z.namelist():
            data = z.read(name)
            if name != "word/document.xml":
                out[name] = (etree.tostring(etree.parse(io.BytesIO(data)), method="c14n")
                             if name.endswith((".xml", ".rels")) else data)
    return out


def one_page(path):
    d = fitz.open()
    d.new_page()
    d.save(path)
    d.close()


def ids(doc):
    return [(j["id"], [b["id"] for b in j["bullets"]]) for j in doc["jobs"]]


def bullet(doc, bid):
    return next(b for j in doc["jobs"] for b in j["bullets"] if b["id"] == bid)


def job(doc, jid):
    return next(j for j in doc["jobs"] if j["id"] == jid)


class Find(unittest.TestCase):
    def test_finds_every_piece_with_its_id_and_bold(self):
        doc = find()
        self.assertEqual(doc["ext"], ".docx")
        self.assertEqual(ids(doc), [("r0", ["r0b0", "r0b1", "r0b2"]), ("r1", ["r1b0", "r1b1"])])
        self.assertEqual(bullet(doc, "r0b0")["text"],
                         "Built a streaming pipeline on **Kafka** that loads 40M events a day into the warehouse.")
        self.assertEqual(bullet(doc, "r0b0")["piece"], DS.PIECES["jobs"][0]["bullets"][0])
        self.assertFalse(any(b["fixed"] for j in doc["jobs"] for b in j["bullets"]))
        self.assertTrue(all(j["reorder"] for j in doc["jobs"]))
        r0 = job(doc, "r0")
        self.assertEqual((r0["title"], r0["company"], r0["start"], r0["end"]),
                         ("Senior Data Engineer", "Fabrikam Analytics", "2021-03", "Present"))
        self.assertEqual(doc["headline"]["text"], DS.HEADLINE)
        self.assertFalse(doc["headline"]["fixed"])
        self.assertEqual(doc["summary"]["text"], DS.SUMMARY)
        self.assertIn("**Python**", doc["summary"]["text"])
        self.assertFalse(doc["summary"]["fixed"])
        self.assertIsNone(doc["pages"])                       # no LibreOffice: build can't run, RenderCV is used
        self.assertEqual(doc["_why"], str(NO_OFFICE))         # the note says why
        self.assertEqual(doc["_pieces"]["headline"], DS.HEADLINE)
        self.assertTrue(doc["_path"].endswith("lena.docx"))

    def test_bullets_numbered_by_their_style_or_by_themselves_are_list_items(self):
        doc = find()                                          # r0: "List Bullet" style; r1: w:numPr on the paragraph
        self.assertEqual(bullet(doc, "r1b0")["text"], DS.PIECES["jobs"][1]["bullets"][0])
        self.assertFalse(bullet(doc, "r1b0")["fixed"])

    def test_the_doc_works_with_keep_style(self):
        doc = find()
        jd = tailor.analyze_jd("Requirements:\n- Kafka and Python streaming pipelines\n- Airflow", "Data Engineer", "Contoso")
        plan = keep_style.default_plan(doc, jd)
        self.assertEqual(sorted(plan["order"]["r0"]), ["r0b0", "r0b1", "r0b2"])
        spec = keep_style.report_spec(doc, plan)
        self.assertEqual(len(spec["roles"]), 2)
        self.assertEqual([s[0] for s in spec["skills"]], ["Data", "Languages", "Cloud"])     # the job's skills first

    def test_pages_is_the_converters_page_count(self):
        self.assertEqual(find(convert=("original.pdf", 2))["pages"], 2)

    def test_a_bullet_with_a_link_is_fixed_and_its_job_keeps_its_order(self):
        doc = find(link_bullet=True)
        b = bullet(doc, "r1b0")
        self.assertTrue(b["fixed"])
        self.assertIn("Airflow", b["text"])
        self.assertFalse(job(doc, "r1")["reorder"])
        self.assertTrue(job(doc, "r0")["reorder"])

    def test_a_bullet_with_italics_is_fixed_but_bold_alone_is_not(self):
        doc = find(italic=True)
        self.assertTrue(bullet(doc, "r0b2")["fixed"])
        self.assertFalse(bullet(doc, "r0b0")["fixed"])        # holds **Kafka**
        self.assertFalse(job(doc, "r0")["reorder"])

    def test_a_field_makes_its_bullet_fixed(self):
        for odd in ("fldSimple", "fldChar"):
            with self.subTest(odd=odd):
                doc = find(odd=odd)
                b = bullet(doc, "r0b0")
                self.assertEqual(b["text"],              # the field's result reads as text, its code doesn't
                                 "Built a streaming pipeline on **Kafka** that loads 40M events a day into the warehouse.")
                self.assertTrue(b["fixed"])
                self.assertFalse(job(doc, "r0")["reorder"])
                self.assertFalse(bullet(doc, "r0b1")["fixed"])

    def test_a_tracked_insertion_makes_its_bullet_fixed(self):
        doc = find(odd="ins")
        b = bullet(doc, "r0b0")
        self.assertTrue(b["text"].endswith("into the warehouse."))
        self.assertTrue(b["fixed"])
        self.assertFalse(job(doc, "r0")["reorder"])

    def test_a_tracked_deletion_is_left_out_of_the_text_and_fixed(self):
        doc = find(odd="del")                    # the file holds "40M nightly events", "nightly " deleted
        b = bullet(doc, "r0b0")
        self.assertEqual(b["piece"], DS.PIECES["jobs"][0]["bullets"][0])
        self.assertNotIn("nightly", b["text"])
        self.assertTrue(b["fixed"])
        self.assertFalse(job(doc, "r0")["reorder"])

    def test_a_drawing_or_picture_makes_its_bullet_fixed(self):
        for odd in ("drawing", "pict"):
            with self.subTest(odd=odd):
                doc = find(odd=odd)
                self.assertEqual(bullet(doc, "r0b0")["piece"], DS.PIECES["jobs"][0]["bullets"][0])
                self.assertTrue(bullet(doc, "r0b0")["fixed"])
                self.assertFalse(job(doc, "r0")["reorder"])

    def test_a_text_box_holds_no_pieces_and_fixes_its_paragraph(self):
        doc = find(odd="textbox")               # r0b2 is only in a text box in r0b0's paragraph
        self.assertEqual(ids(doc), [("r0", ["r0b0", "r0b1"]), ("r1", ["r1b0", "r1b1"])])
        self.assertTrue(bullet(doc, "r0b0")["fixed"])
        self.assertFalse(job(doc, "r0")["reorder"])

    def test_bullets_in_a_table_cell_are_found_and_may_move(self):
        for nested in (False, True):
            with self.subTest(nested=nested):
                doc = find(table=True, nested=nested)
                self.assertEqual(ids(doc), [("r0", ["r0b0", "r0b1", "r0b2"]), ("r1", ["r1b0", "r1b1"])])
                self.assertTrue(job(doc, "r0")["reorder"])
                self.assertIn("**Kafka**", bullet(doc, "r0b0")["text"])

    def test_bullets_not_side_by_side_keep_their_order(self):
        doc = find(gap=True)
        self.assertEqual(ids(doc)[0], ("r0", ["r0b0", "r0b1", "r0b2"]))
        self.assertFalse(job(doc, "r0")["reorder"])
        self.assertFalse(any(b["fixed"] for b in job(doc, "r0")["bullets"]))
        self.assertTrue(job(doc, "r1")["reorder"])

    def test_a_typed_sign_isnt_part_of_the_bullets_text(self):
        doc = find(typed=True)
        b = bullet(doc, "r0b0")
        self.assertEqual(b["text"], "Built a streaming pipeline on **Kafka** that loads 40M events a day into the warehouse.")
        self.assertFalse(b["fixed"])
        self.assertTrue(job(doc, "r0")["reorder"])

    def test_a_bullet_paragraph_without_a_sign_or_numbering_is_fixed(self):
        p = DS.pieces()
        p["jobs"][0]["bullets"].insert(1, "Team of six engineers.")
        doc = find(p, gap=True)
        self.assertEqual(ids(doc)[0], ("r0", ["r0b0", "r0b1", "r0b2", "r0b3"]))
        self.assertTrue(bullet(doc, "r0b1")["fixed"])
        self.assertFalse(job(doc, "r0")["reorder"])

    def test_skill_paragraphs_are_found_and_may_move(self):
        doc = find()
        self.assertEqual([(l["id"], l["label"], l["items"], l["fixed"]) for l in doc["skills"]],
                         [("s0", "Languages", ["Python", "Go", "SQL"], False),
                          ("s1", "Data", ["PostgreSQL", "Kafka", "Airflow"], False),
                          ("s2", "Cloud", ["AWS", "Docker", "Terraform"], False)])
        self.assertEqual(doc["skills"][0]["sep"], ", ")
        self.assertTrue(doc["skills_move"])

    def test_pieces_not_in_the_file_are_absent(self):
        p = DS.pieces()
        p["headline"] = "Principal Data Architect"
        p["summary"] = "Platform lead who has run data teams across three continents for a decade."
        p["jobs"][0]["bullets"].insert(1, "Led the warehouse move from Redshift to Snowflake for all teams.")
        p["jobs"].append({"title": "Analyst", "company": "Contoso", "location": "", "start": "2016-01", "end": "2018-05",
                          "bullets": ["Built weekly sales dashboards in Tableau for the regional managers."]})
        p["skills"].append({"label": "Tools", "items": ["Git", "Make", "Jira"]})
        # a piece in the page header isn't in the body: it isn't found there either
        doc = find(p, header_text="Led the warehouse move from Redshift to Snowflake for all teams.")
        self.assertIsNone(doc["headline"])
        self.assertIsNone(doc["summary"])
        self.assertEqual(ids(doc), [("r0", ["r0b0", "r0b2", "r0b3"]), ("r1", ["r1b0", "r1b1"])])
        self.assertTrue(job(doc, "r0")["reorder"])
        self.assertEqual([l["label"] for l in doc["skills"]], ["Languages", "Data", "Cloud"])

    def test_a_headline_that_is_a_jobs_own_title_line_isnt_the_headline(self):
        p = DS.pieces()
        p["headline"] = "Senior Data Engineer | Fabrikam Analytics | 2021-03 - Present"
        self.assertIsNone(find(p)["headline"])

    def test_a_summary_over_two_paragraphs_is_fixed(self):
        doc = find(split_summary=True)          # one new text can't go back into two paragraphs
        self.assertEqual(doc["summary"]["text"], DS.SUMMARY)
        self.assertEqual(len(doc["summary"]["_at"]), 2)
        self.assertTrue(doc["summary"]["fixed"])

    def test_a_paragraph_holding_a_section_break_never_moves(self):
        path = made()
        d = docx.Document(path)               # Word keeps a section break in its last paragraph's w:pPr
        last = next(p for p in d.paragraphs if p.text.startswith("Wrote the data contracts"))
        last._p.get_or_add_pPr().append(OxmlElement("w:sectPr"))
        d.save(path)
        doc = find(path=path)
        self.assertFalse(job(doc, "r0")["reorder"])
        self.assertFalse(bullet(doc, "r0b2")["fixed"])          # its text may still change
        self.assertTrue(job(doc, "r1")["reorder"])

    def test_a_break_or_tab_at_a_paragraphs_edge_fixes_it(self):
        # a gap made with Shift+Enter, a page break or a tab is in no text: a rewrite would drop it, and nothing tells
        cases = [("a Shift+Enter after a bullet", "Cut the nightly", "end", "w:br", None, "r0b1"),
                 ("a page break after the summary", "Data engineer", "end", "w:br", "page", "summary"),
                 ("a page break before a bullet", "Moved 25 cron", "start", "w:br", "page", "r1b0"),
                 ("a column break after a bullet", "Added dbt", "end", "w:br", "column", "r1b1"),
                 ("a carriage return after a bullet", "Added dbt", "end", "w:cr", None, "r1b1"),
                 ("a tab before the headline", DS.HEADLINE, "start", "w:tab", None, "headline"),
                 ("a tab after a bullet", "Cut the nightly", "end", "w:tab", None, "r0b1"),
                 ("a tab after a skill line", "Cloud:", "end", "w:tab", None, "s2")]
        for name, start, where, tag, kind, piece in cases:
            with self.subTest(name):
                def change(d):
                    p, r, el = starting(d, start)._p, OxmlElement("w:r"), OxmlElement(tag)
                    if kind:
                        el.set(qn("w:type"), kind)
                    r.append(el)
                    p.insert(len(p) if where == "end" else int(p.find(qn("w:pPr")) is not None), r)
                path = edit(made(), change)
                doc, files = build(path, {"text": {piece: NEW_BULLET}, "summary": NEW_SUMMARY,
                                          "headline": NEW_HEADLINE, "skills": {"s2": ["Terraform", "AWS", "Docker"]}})
                got = doc[piece] if piece in ("headline", "summary") else \
                    next((l for l in doc["skills"] if l["id"] == piece), None) or bullet(doc, piece)
                self.assertTrue(got["fixed"])
                others = [b for j in doc["jobs"] for b in j["bullets"] if b["id"] != piece]
                self.assertFalse(any(b["fixed"] for b in others))
                at = got["_at"][0] if piece == "summary" else got["_at"]
                self.assertEqual(xml(files["docx"])[at], xml(path)[at])          # kept as it is, break and all

    def test_bullets_formatted_apart_keep_their_order(self):
        def sub_style(d):
            starting(d, "Cut the nightly").style = d.styles["List Bullet 2"]

        def sub_level(d):           # job 2's bullets are numbered on the paragraph itself
            starting(d, "Added dbt tests")._p.pPr.find(f"{qn('w:numPr')}/{qn('w:ilvl')}").set(qn("w:val"), "1")

        def space_after(d):
            starting(d, "Wrote the data contracts").paragraph_format.space_after = Pt(12)

        def bookmark(d):            # from the first bullet into the second
            start, end = DS._xml('<w:bookmarkStart w:id="7" w:name="jobOne"/><w:bookmarkEnd w:id="7"/>')
            starting(d, "Built a streaming")._p.append(start)
            starting(d, "Cut the nightly")._p.append(end)
        for name, change, jid, other in [("a sub-bullet by its style", sub_style, "r0", "r1"),
                                         ("a sub-bullet by its list level", sub_level, "r1", "r0"),
                                         ("more space after a job's last bullet", space_after, "r0", "r1"),
                                         ("a bookmark from one bullet into the next", bookmark, "r0", "r1")]:
            with self.subTest(name):
                doc = find(path=edit(made(), change))
                self.assertFalse(job(doc, jid)["reorder"])
                self.assertTrue(job(doc, other)["reorder"])
                self.assertFalse(any(b["fixed"] for j in doc["jobs"] for b in j["bullets"]))   # words may change

    def test_what_doesnt_change_how_a_bullet_prints_still_lets_it_move(self):
        def own_bookmark(d):        # Word's _GoBack: a bookmark that starts and ends inside one paragraph
            for el in DS._xml('<w:bookmarkStart w:id="0" w:name="_GoBack"/><w:bookmarkEnd w:id="0"/>'):
                starting(d, "Cut the nightly")._p.append(el)

        def mark_and_rsid(d):       # the paragraph mark's own look (w:pPr/w:rPr), and Word's revision ids
            p = starting(d, "Wrote the data contracts")._p
            p.set(qn("w:rsidR"), "00AB12CD")
            p.get_or_add_pPr().append(DS._xml("<w:rPr><w:b/></w:rPr>")[0])
        for name, change in [("a bookmark inside one bullet", own_bookmark),
                             ("the paragraph mark's look and an rsid", mark_and_rsid)]:
            with self.subTest(name):
                self.assertTrue(job(find(path=edit(made(), change)), "r0")["reorder"])

    def test_skill_lines_formatted_apart_stay_where_they_are(self):
        def space_after(d):
            starting(d, "Cloud:").paragraph_format.space_after = Pt(12)

        def bookmark(d):
            start, end = DS._xml('<w:bookmarkStart w:id="8" w:name="langs"/><w:bookmarkEnd w:id="8"/>')
            starting(d, "Languages:")._p.append(start)
            starting(d, "Data:")._p.append(end)
        self.assertTrue(find()["skills_move"])
        for name, change in [("more space after the last line", space_after), ("a bookmark over two lines", bookmark)]:
            with self.subTest(name):
                doc = find(path=edit(made(), change))
                self.assertFalse(doc["skills_move"])
                self.assertFalse(any(l["fixed"] for l in doc["skills"]))        # their items may still reorder


class Write(unittest.TestCase):
    """build puts the plan into a fresh copy of the file; LibreOffice is faked (DS.fake_pdf)."""

    def test_only_the_reworded_paragraphs_change(self):
        path = made()
        before, others = xml(path), parts(path)
        doc, files = build(path, {"text": {"r0b1": NEW_BULLET}, "summary": NEW_SUMMARY, "headline": NEW_HEADLINE,
                                  "skills": {"s0": ["SQL", "Python", "Go"]}})
        after = xml(files["docx"])
        at = {"r0b1": bullet(doc, "r0b1")["_at"], "summary": doc["summary"]["_at"][0],
              "headline": doc["headline"]["_at"], "s0": doc["skills"][0]["_at"]}
        self.assertEqual(len(after), len(before))
        self.assertEqual([n for n in range(len(before)) if before[n] != after[n]], sorted(at.values()))
        self.assertEqual(text(files["docx"], at["r0b1"]), NEW_BULLET)
        self.assertEqual(text(files["docx"], at["summary"]), NEW_SUMMARY.replace("**", ""))
        self.assertEqual(text(files["docx"], at["headline"]), NEW_HEADLINE)
        self.assertEqual(text(files["docx"], at["s0"]), "Languages: SQL, Python, Go")
        ppr = lambda p: etree.tostring(p.find(qn("w:pPr"))) if p.find(qn("w:pPr")) is not None else None
        for n in at.values():
            self.assertEqual(ppr(para(files["docx"], n)), ppr(para(path, n)))      # w:pPr untouched
        self.assertEqual(parts(files["docx"]), others)          # header, styles, numbering, links' targets
        self.assertEqual(set(files), {"pdf", "docx", "pages", "paper"})
        self.assertEqual((files["pages"], files["paper"], Path(files["docx"]).name), (1, "Letter", "out.docx"))
        self.assertTrue(Path(files["pdf"]).is_file())

    def test_a_rewording_keeps_its_runs_look_and_bold_only_on_bold(self):
        path = made()
        d = docx.Document(path)
        for p in d.paragraphs:
            if p.text.startswith(("Built a streaming", "Cut the nightly", "Data engineer")):
                for r in p.runs:
                    r.font.name, r.font.size = "Carlito", Pt(10.5)
        d.save(path)
        new0 = "Built a **Kafka** streaming pipeline that loads 40M events a day into the warehouse for analysts."
        new1 = "Cut the nightly batch from 6 hours to 90 minutes with **Spark** partitions on the largest tables."
        doc, files = build(path, {"text": {"r0b0": new0, "r0b1": new1}, "summary": NEW_SUMMARY})
        old = runs(path, bullet(doc, "r0b0")["_at"])
        plain, bold = (next(x for _, b, x in old if b is want) for want in (False, True))
        self.assertIn(b'w:ascii="Carlito"', plain)
        self.assertIn(b'w:val="21"', plain)                    # 10.5 pt
        self.assertIn(b'w:ascii="Carlito"', bold)
        self.assertEqual(runs(files["docx"], bullet(doc, "r0b0")["_at"]),
                         [("Built a ", False, plain), ("Kafka", True, bold),
                          (" streaming pipeline that loads 40M events a day into the warehouse for analysts.", False,
                           plain)])
        # no bold run in the paragraph: all of it plain, in its first run's look
        first = runs(path, bullet(doc, "r0b1")["_at"])[0][2]
        self.assertEqual(runs(files["docx"], bullet(doc, "r0b1")["_at"]), [(new1.replace("**", ""), False, first)])
        old = runs(path, doc["summary"]["_at"][0])
        plain, bold = (next(x for _, b, x in old if b is want) for want in (False, True))
        self.assertEqual(runs(files["docx"], doc["summary"]["_at"][0]),
                         [("Data engineer with seven years of ", False, plain), ("Python", True, bold),
                          (" and SQL, building the streaming pipelines analysts and finance teams trust daily.", False,
                           plain)])

    def test_a_reorder_moves_whole_paragraphs(self):
        path = made()
        before = xml(path)
        doc, files = build(path, {"order": {"r0": ["r0b2", "r0b0", "r0b1"]}, "skill_lines": ["s2", "s0", "s1"]})
        r0, sk = [b["_at"] for b in job(doc, "r0")["bullets"]], [l["_at"] for l in doc["skills"]]
        moved = {**dict(zip(r0, [r0[2], r0[0], r0[1]])), **dict(zip(sk, [sk[2], sk[0], sk[1]]))}
        self.assertEqual(xml(files["docx"]), [before[moved.get(n, n)] for n in range(len(before))])

    def test_a_fixed_paragraph_is_untouched(self):
        path = made(link_bullet=True)
        before = xml(path)
        doc, files = build(path, {"text": {"r1b0": "Moved 25 cron jobs into Airflow, ending missed nightly runs and "
                                                    "every manual rerun."},
                                  "order": {"r1": ["r1b1", "r1b0"]}})
        self.assertTrue(bullet(doc, "r1b0")["fixed"])
        self.assertEqual(xml(files["docx"]), before)

    def test_a_summary_over_two_paragraphs_stays_as_written(self):
        path = made(split_summary=True)
        before = xml(path)
        with mock.patch.object(style_docx, "to_pdf", side_effect=DS.fake_pdf):
            doc = style_docx.find(path, DS.pieces())
            doc["summary"]["fixed"] = False                  # build keeps it as written even then
            files = style_docx.build(doc, dict(PLAN, summary=NEW_SUMMARY), Path(tempfile.mkdtemp()), "out")
        self.assertEqual(xml(files["docx"]), before)

    def test_a_table_cell_job_reorders_inside_its_cell(self):
        for nested in (False, True):
            with self.subTest(nested=nested):
                path = made(table=True, nested=nested)
                before = xml(path)
                doc, files = build(path, {"order": {"r0": ["r0b1", "r0b2", "r0b0"]}})
                r0 = [b["_at"] for b in job(doc, "r0")["bullets"]]
                moved = dict(zip(r0, [r0[1], r0[2], r0[0]]))
                self.assertEqual(xml(files["docx"]), [before[moved.get(n, n)] for n in range(len(before))])
                cells = {para(files["docx"], n).getparent().tag for n in r0}
                self.assertEqual(cells, {qn("w:tc")})

    def test_a_typed_sign_stays_at_the_start_as_printed(self):
        path = made(typed=True)
        d = docx.Document(path)                      # the third bullet's sign in a run of its own (Word's rsid on it)
        p = next(p for p in d.paragraphs if p.text.startswith("• Wrote"))
        sign = deepcopy(p.runs[0]._r)
        p._p.insert(p._p.index(p.runs[0]._r), sign)
        sign.set(qn("w:rsidR"), "00A1B2C3")
        sign.find(qn("w:t")).text = "• "
        sign.find(qn("w:t")).set(qn("xml:space"), "preserve")
        p.runs[1].text = p.runs[1].text[2:]
        d.save(path)
        new2 = "Wrote the data contracts and on-call runbook that four product teams now use daily."
        doc, files = build(path, {"text": {"r0b1": NEW_BULLET, "r0b2": new2}})
        self.assertEqual(text(files["docx"], bullet(doc, "r0b1")["_at"]), "• " + NEW_BULLET)
        self.assertEqual(text(files["docx"], bullet(doc, "r0b2")["_at"]), "• " + new2)
        own = lambda path: etree.tostring(para(path, bullet(doc, "r0b2")["_at"]).find(qn("w:r")))
        self.assertEqual(own(files["docx"]), own(path))         # that run is kept as it is

    def test_a_sign_sharing_a_run_with_the_words_and_spaces_before_the_words_stay_exactly_as_written(self):
        def change(d):
            r = starting(d, "• Cut the nightly").runs[0]._r     # one run: "•", a positioned tab, then the words
            r.set(qn("w:rsidR"), "00C0FFEE")
            t = r.find(qn("w:t"))
            words, t.text = t.text[2:], "•"
            for el in DS._xml('<w:ptab w:relativeTo="margin" w:alignment="left" w:leader="none"/>'
                              f'<w:t xml:space="preserve">{words}</w:t>'):
                r.append(el)
            starting(d, DS.HEADLINE).runs[0].text = "   " + DS.HEADLINE          # centred by hand
        path = edit(made(typed=True), change)
        doc, files = build(path, {"text": {"r0b1": NEW_BULLET}, "headline": NEW_HEADLINE})
        at = bullet(doc, "r0b1")["_at"]
        self.assertEqual(bullet(doc, "r0b1")["_sign"], "•\t")
        sign = deepcopy(para(path, at).find(qn("w:r")))
        sign.remove(sign[-1])                                   # the run as it was, without its words
        self.assertEqual(etree.tostring(deepcopy(para(files["docx"], at).find(qn("w:r")))), etree.tostring(sign))
        self.assertEqual(text(files["docx"], at), "•" + NEW_BULLET)
        self.assertEqual(text(files["docx"], doc["headline"]["_at"]), "   " + NEW_HEADLINE)

    def test_a_file_without_its_own_styles_stays_so(self):
        path = DS.without_styles(made())
        names = lambda p: sorted(zipfile.ZipFile(p).namelist())
        self.assertNotIn("word/styles.xml", names(path))
        before = parts(path)
        new = "Moved 25 cron jobs into Airflow, ending missed nightly runs and every manual rerun."
        doc, files = build(path, {"text": {"r1b0": new}})
        self.assertFalse(bullet(doc, "r1b0")["fixed"])          # numbered on the paragraph itself: still a bullet
        self.assertEqual(text(files["docx"], bullet(doc, "r1b0")["_at"]), new)
        self.assertEqual(names(files["docx"]), names(path))     # no styles part of python-docx's own added
        self.assertEqual(parts(files["docx"]), before)          # its relationships and content types as they were

    def test_a_headline_partly_in_bold_stays_as_printed(self):
        def change(d):
            h = starting(d, DS.HEADLINE)
            h.runs[0].text, h.runs[0].bold = "Data Platform", True
            h.add_run(" Engineer")
        path = edit(made(), change)
        before = xml(path)
        doc, files = build(path, {"headline": "Senior Data Platform Engineer"})
        self.assertEqual(doc["headline"]["text"], DS.HEADLINE)
        self.assertTrue(doc["headline"]["fixed"])
        self.assertEqual(xml(files["docx"]), before)
        whole = find(path=edit(made(), lambda d: setattr(starting(d, DS.HEADLINE).runs[0], "bold", True)))
        self.assertFalse(whole["headline"]["fixed"])            # all of it bold: one look, may be reworded

    def test_a_sub_bullet_never_moves_away_from_its_bullet(self):
        path = edit(made(), lambda d: setattr(starting(d, "Cut the nightly"), "style", d.styles["List Bullet 2"]))
        before = xml(path)
        doc, files = build(path, {"order": {"r0": ["r0b1", "r0b0", "r0b2"]}})
        self.assertFalse(job(doc, "r0")["reorder"])
        self.assertEqual(xml(files["docx"]), before)

    def test_the_pdf_must_read_back_the_new_text(self):
        path = made()

        def blank(docx_path, out_dir):
            one_page(Path(out_dir) / "resume.pdf")
            return Path(out_dir) / "resume.pdf", 1
        stale = lambda docx_path, out_dir: DS.fake_pdf(path, out_dir)    # as if LibreOffice printed the original
        for name, convert in (("the old text", stale), ("nothing", blank)):
            with self.subTest(printed=name):
                folder = Path(tempfile.mkdtemp())
                with self.assertRaises(ValueError) as ctx:
                    build(path, {"text": {"r0b1": NEW_BULLET}, "headline": NEW_HEADLINE}, convert, folder)
                self.assertIn("didn't read back as written (r0b1, headline)", str(ctx.exception))
                self.assertEqual(list(folder.iterdir()), [])            # no tailored file left behind

    def test_a_paragraph_that_isnt_the_one_read_is_never_rewritten(self):
        path = made()
        with mock.patch.object(style_docx, "to_pdf", side_effect=DS.fake_pdf):
            doc = style_docx.find(path, DS.pieces())
            bullet(doc, "r0b1")["_at"] = bullet(doc, "r0b2")["_at"]          # as if the walk had changed
            with self.assertRaises(ValueError) as ctx:
                style_docx.build(doc, dict(PLAN, text={"r0b1": NEW_BULLET}), Path(tempfile.mkdtemp()), "out")
        self.assertIn("isn't the one that was read", str(ctx.exception))

    def test_an_old_text_the_file_also_holds_elsewhere_may_still_read(self):
        path = made(header_text=DS.HEADLINE)                   # the old headline is in the page header too
        doc, files = build(path, {"headline": NEW_HEADLINE})
        self.assertEqual(text(files["docx"], doc["headline"]["_at"]), NEW_HEADLINE)
        with fitz.open(files["pdf"]) as d:
            self.assertIn(key(DS.HEADLINE), key(d[0].get_text()))

    def test_a_long_paragraph_may_run_over_onto_the_next_pages(self):
        long = " ".join([NEW_BULLET] * 180)
        doc, files = build(made(), {"text": {"r0b1": long}})
        self.assertGreaterEqual(files["pages"], 3)
        self.assertEqual(text(files["docx"], bullet(doc, "r0b1")["_at"]), long)


class Converter(unittest.TestCase):
    """to_pdf, LibreOffice mocked: the sandbox, the allow-listed env, failing closed."""

    def setUp(self):
        # these fake a direct run unless they say otherwise: the online Tests job may turn the sandbox on and sets
        # GITHUB_ACTIONS=true, and both must be undone for these mocked tests
        direct = mock.patch.dict(os.environ, {"TEAMBID_DOCX_SANDBOX": ""})
        direct.start()
        self.addCleanup(direct.stop)
        os.environ.pop("GITHUB_ACTIONS", None)
        self.src, self.tmp, self.calls = made(), Path(tempfile.mkdtemp()), []

    def run_ok(self, cmd, **kw):
        """Stands in for LibreOffice: a one-page PDF in the work folder."""
        self.calls.append((cmd, kw))
        one_page(self.tmp / "resume.pdf")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def os_release(self, text):
        """The host's /etc/os-release, as a file holding text (None: there is none)."""
        path = Path(tempfile.mkdtemp()) / "os-release"
        if text is not None:
            path.write_text(text, encoding="utf-8")
        return mock.patch.object(style_docx, "OS_RELEASE", path)

    def test_the_sandbox_has_no_network_and_sees_only_the_work_folder(self):
        tools = {"soffice": "/usr/bin/soffice", "docker": "/usr/bin/docker"}
        fake = {"TEAMBID_DOCX_SANDBOX": "docker", "ANTHROPIC_API_KEY": "sk-secret", "GH_TOKEN": "gh-secret",
                "TEAMBID_SITE_PASSWORD": "pw-secret"}
        with mock.patch.dict(os.environ, fake), \
             mock.patch("teambid.style_docx.shutil.which", side_effect=tools.get), \
             mock.patch("teambid.style_docx.os.getuid", create=True, return_value=1001), \
             mock.patch("teambid.style_docx.os.getgid", create=True, return_value=118), \
             self.os_release('NAME="Ubuntu"\nVERSION_ID="26.04"\nID=ubuntu\n'), \
             mock.patch("teambid.style_docx.subprocess.run", side_effect=self.run_ok):
            pdf, pages = style_docx.to_pdf(self.src, self.tmp)
        want = ["docker", "run", "--rm", "--network", "none",
                "--security-opt", "no-new-privileges", "--cap-drop", "ALL", "--memory", "1g", "--pids-limit", "256",
                "--user", "1001:118",
                "-v", "/usr:/usr:ro", "-v", "/etc/fonts:/etc/fonts:ro", "-v", "/usr/share/fonts:/usr/share/fonts:ro",
                "-v", "/etc/libreoffice:/etc/libreoffice:ro",
                "-v", f"{self.tmp.absolute()}:/work", "-e", "HOME=/tmp", "--tmpfs", "/tmp", "ubuntu:26.04",
                "timeout", "-s", "KILL", "90",
                "soffice", "--headless", "--norestore", "-env:UserInstallation=file:///work/.libreoffice",
                "--convert-to", "pdf", "--outdir", "/work", "/work/resume.docx"]
        self.assertEqual([c for c, _ in self.calls], [want])
        self.assertEqual(self.calls[0][1]["timeout"], 105)                  # + container start-up
        self.assertEqual((Path(pdf), pages), (self.tmp / "resume.pdf", 1))
        self.assertEqual((self.tmp / "resume.docx").read_bytes(), Path(self.src).read_bytes())   # its own copy
        for cmd, kw in self.calls:                # on failure, print only what leaked, never the whole env
            self.assertEqual([a for a in cmd if "secret" in a], [])
            self.assertEqual([k for k, v in kw["env"].items() if "secret" in v], [])
            self.assertEqual(kw["env"]["PATH"], os.environ["PATH"])

    def test_a_direct_run_gets_only_the_allow_listed_env_and_a_profile_of_its_own(self):
        fake = {"ANTHROPIC_API_KEY": "sk-secret", "GH_TOKEN": "gh-secret", "TEAMBID_SITE_PASSWORD": "pw-secret"}
        with mock.patch.dict(os.environ, fake), \
             mock.patch("teambid.style_docx.shutil.which", side_effect={"soffice": "/opt/lo/soffice"}.get), \
             mock.patch("teambid.style_docx.subprocess.run", side_effect=self.run_ok):
            self.assertEqual(style_docx.to_pdf(self.src, self.tmp)[1], 1)
        work = self.tmp.absolute()
        (cmd, kw), = self.calls
        self.assertEqual(cmd, ["/opt/lo/soffice", "--headless", "--norestore",
                               f"-env:UserInstallation={(work / '.libreoffice').as_uri()}", "--convert-to", "pdf",
                               "--outdir", str(work), str(work / "resume.docx")])
        self.assertEqual(kw["timeout"], 90)
        self.assertEqual(sorted(set(kw["env"]) & set(fake)), [])
        self.assertEqual(kw["env"]["PATH"], os.environ["PATH"])

    def test_github_actions_refuses_to_run_libreoffice_outside_the_sandbox(self):
        with mock.patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}), \
             mock.patch("teambid.style_docx.shutil.which", return_value="/usr/bin/soffice"), \
             mock.patch("teambid.style_docx.subprocess.run") as run:
            with self.assertRaises(RuntimeError) as ctx:
                style_docx.to_pdf(self.src, self.tmp)
            self.assertFalse(style_docx.available())
        self.assertIn("sandbox", str(ctx.exception))
        run.assert_not_called()
        self.assertEqual(list(self.tmp.iterdir()), [])             # not even a copy of the upload

    def test_no_docker_no_build(self):
        with mock.patch.dict(os.environ, {"TEAMBID_DOCX_SANDBOX": "docker"}), \
             mock.patch("teambid.style_docx.shutil.which", side_effect={"soffice": "/usr/bin/soffice"}.get), \
             mock.patch("teambid.style_docx.subprocess.run") as run:
            with self.assertRaises(RuntimeError) as ctx:
                style_docx.to_pdf(self.src, self.tmp)
        self.assertEqual(str(ctx.exception), "Docker isn't available here for the LibreOffice sandbox")
        run.assert_not_called()                  # never falls back to opening the upload outside the sandbox

    def test_without_libreoffice_nothing_runs(self):
        with mock.patch("teambid.style_docx.shutil.which", return_value=None), \
             mock.patch("teambid.style_docx.subprocess.run") as run:
            with self.assertRaises(RuntimeError) as ctx:
                style_docx.to_pdf(self.src, self.tmp)
            self.assertFalse(style_docx.available())
        self.assertIn("LibreOffice isn't installed", str(ctx.exception))
        run.assert_not_called()

    def test_a_run_over_the_time_limit_fails(self):
        with mock.patch("teambid.style_docx.shutil.which", return_value="/usr/bin/soffice"), \
             mock.patch("teambid.style_docx.subprocess.run", side_effect=subprocess.TimeoutExpired("soffice", 90)):
            with self.assertRaises(RuntimeError) as ctx:
                style_docx.to_pdf(self.src, self.tmp)
        self.assertIn("longer than 90 s", str(ctx.exception))

    def test_no_pdf_fails_with_libreoffices_own_words(self):
        said = subprocess.CompletedProcess([], 0, "", "Error: source file could not be loaded\n")
        with mock.patch("teambid.style_docx.shutil.which", return_value="/usr/bin/soffice"), \
             mock.patch("teambid.style_docx.subprocess.run", return_value=said):
            with self.assertRaises(RuntimeError) as ctx:
                style_docx.to_pdf(self.src, self.tmp)
        self.assertIn("source file could not be loaded", str(ctx.exception))

    def test_the_sandbox_runs_the_hosts_own_ubuntu(self):
        # the container runs the host's /usr: its /etc must be the same Ubuntu, and 24.04 is the guess when it's unknown
        cases = {'NAME="Ubuntu"\nVERSION_ID="26.04"\nID=ubuntu\nID_LIKE=debian\n': "ubuntu:26.04",
                 "ID=ubuntu\nVERSION_ID=24.10\n": "ubuntu:24.10",
                 'ID=debian\nVERSION_ID="12"\n': "ubuntu:24.04",
                 'ID=linuxmint\nVERSION_ID="22.1"\nID_LIKE="ubuntu debian"\n': "ubuntu:24.04",    # no Ubuntu 22.1
                 'ID=ubuntu\nVERSION_ID="noble; rm -rf /"\n': "ubuntu:24.04",
                 "ID=ubuntu\n": "ubuntu:24.04",
                 None: "ubuntu:24.04"}
        for text, want in cases.items():
            with self.subTest(os_release=text), self.os_release(text):
                self.assertEqual(style_docx._image(), want)

    def produces(self, make):
        """to_pdf where LibreOffice leaves make(path of its PDF) in the work folder -> the RuntimeError it raises."""
        def run(cmd, **kw):
            make(self.tmp / "resume.pdf")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        with mock.patch("teambid.style_docx.shutil.which", return_value="/usr/bin/soffice"), \
             mock.patch("teambid.style_docx.subprocess.run", side_effect=run):
            with self.assertRaises(RuntimeError) as ctx:
                style_docx.to_pdf(self.src, self.tmp)
        return ctx.exception

    def test_a_pdf_that_is_a_folder_is_refused(self):
        e = self.produces(lambda path: path.mkdir())
        self.assertEqual(str(e), "LibreOffice's PDF isn't a plain file in its work folder, so it isn't used")

    def test_a_pdf_that_is_a_link_to_a_host_file_is_refused(self):
        # a LibreOffice taken over by a hostile file could leave a link to another member's resume as its PDF
        other = Path(tempfile.mkdtemp()) / "someone-else.pdf"
        one_page(other)
        try:
            os.symlink(Path(tempfile.mkdtemp()) / "probe", Path(tempfile.mkdtemp()) / "link")
        except OSError:
            self.skipTest("this computer can't make symbolic links (Windows without the privilege); runs online")
        e = self.produces(lambda path: os.symlink(other, path))
        self.assertEqual(str(e), "LibreOffice's PDF isn't a plain file in its work folder, so it isn't used")


@unittest.skipUnless(style_docx.available(), "LibreOffice (on GitHub Actions, in its sandbox) runs in the online Tests")
class WithLibreOffice(unittest.TestCase):
    def test_the_pdf_reads_back_the_new_text_with_the_page_count_kept(self):
        doc = style_docx.find(made(), DS.pieces())
        self.assertEqual(doc["pages"], 1)
        plan = dict(PLAN, text={"r0b1": NEW_BULLET}, summary=NEW_SUMMARY, headline=NEW_HEADLINE,
                    order={"r0": ["r0b2", "r0b0", "r0b1"]}, skills={"s0": ["SQL", "Python", "Go"]},
                    skill_lines=["s1", "s0", "s2"])
        files = style_docx.build(doc, plan, Path(tempfile.mkdtemp()), "out")
        self.assertEqual((files["pages"], files["paper"]), (1, "Letter"))
        with fitz.open(files["pdf"]) as d:
            got = key("".join(p.get_text() for p in d))
        for t in (NEW_BULLET, NEW_SUMMARY, NEW_HEADLINE, "Languages: SQL, Python, Go", DS.CONTACT[1]):
            self.assertIn(key(t), got)
        self.assertNotIn(key(DS.JOBS[0][4][1]), got)
        self.assertLess(got.index(key(DS.JOBS[0][4][2])), got.index(key(DS.JOBS[0][4][0])))
        self.assertLess(got.index(key("Data: PostgreSQL")), got.index(key("Languages: SQL")))

    def test_an_over_long_rewording_is_put_back_to_keep_the_page_count(self):
        doc = style_docx.find(made(), DS.pieces())
        short = "Added dbt tests to 60 models, catching schema drift long before it reached the reports."
        plan = dict(PLAN, text={"r0b1": " ".join([NEW_BULLET] * 40), "r1b1": short})
        files, reverted = keep_style._build(style_docx, doc, plan, Path(tempfile.mkdtemp()), "out")
        self.assertEqual((files["pages"], reverted, list(plan["text"])), (1, 1, ["r1b1"]))
        with fitz.open(files["pdf"]) as d:
            self.assertIn(key(short), key("".join(p.get_text() for p in d)))


if __name__ == "__main__":
    unittest.main()

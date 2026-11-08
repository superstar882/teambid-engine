"""Keep-original-style, Word (.docx) handler (stdlib unittest). The fixture files come from tests/docx_samples.py and
are built with python-docx; LibreOffice is never needed here (the converter is mocked where find calls it)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TEAMBID_WORKSPACE", tempfile.mkdtemp(prefix="teambid-test-"))
os.environ.setdefault("TEAMBID_LOCAL_AI", "off")

from teambid import keep_style, style_docx, tailor  # noqa: E402
from tests import docx_samples as DS  # noqa: E402

NO_OFFICE = RuntimeError("LibreOffice isn't available here, so a Word resume can't be built")


def find(pieces=None, convert=NO_OFFICE, **kw):
    """style_docx.find on a fresh fixture; convert: what the PDF converter does (raises it, or returns it)."""
    path = DS.make(str(Path(tempfile.mkdtemp()) / "lena.docx"), **kw)
    how = {"side_effect": convert} if isinstance(convert, Exception) else {"return_value": convert}
    with mock.patch.object(style_docx, "to_pdf", **how):
        return style_docx.find(path, pieces or DS.pieces())


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


if __name__ == "__main__":
    unittest.main()

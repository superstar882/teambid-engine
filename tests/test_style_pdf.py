"""Keep-original-style, PDF handler (stdlib unittest). The fixture PDFs come from tests/pdf_samples.py and use
PyMuPDF's built-in fonts, so these run anywhere; tests that need fontconfig or the online fonts skip elsewhere."""
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

import fitz  # noqa: E402

from teambid import style_pdf  # noqa: E402
from teambid.style_text import key  # noqa: E402
from tests import pdf_samples as PS  # noqa: E402


def sample(**kw):
    return PS.make(str(Path(tempfile.mkdtemp()) / "dana.pdf"), **kw)


class Read(unittest.TestCase):
    def jobs(self, pieces=PS.PIECES, **kw):
        with fitz.open(sample(**kw)) as d:
            return style_pdf.read(d, pieces)

    def test_finds_every_bullet_with_its_sign(self):
        jobs = self.jobs()
        self.assertEqual([(j["id"], [b["id"] for b in j["bullets"]]) for j in jobs],
                         [("r0", ["r0b0", "r0b1", "r0b2"]), ("r1", ["r1b0", "r1b1"])])
        self.assertTrue(all(b["mark"] for j in jobs for b in j["bullets"]))
        self.assertTrue(all(j["reorder"] for j in jobs))
        self.assertEqual(jobs[0]["bullets"][0]["text"],
                         "Built a payments API in **Python** and FastAPI that handles 2M requests a day for card and bank transfers.")

    def test_drawn_dots_are_bullet_signs_too(self):
        self.assertEqual({b["mark"]["kind"] for j in self.jobs(sign="circle") for b in j["bullets"]}, {"circle"})

    def test_a_linked_bullet_pins_its_job(self):
        jobs = self.jobs(link_bullet=True)
        self.assertTrue(jobs[0]["reorder"])
        self.assertFalse(jobs[1]["reorder"])
        self.assertEqual([b["fixed"] for b in jobs[1]["bullets"]], [True, False])

    def test_only_whole_bullets_are_found(self):
        first = PS.PIECES["jobs"][0]["bullets"][0]
        # a piece that starts mid-line isn't found; one that is only the bullet's second line has no sign
        jobs = self.jobs(pieces={"jobs": [{"bullets": ["payments API in Python and FastAPI that handles"]}]})
        self.assertEqual(jobs, [])
        jobs = self.jobs(pieces={"jobs": [{"bullets": [first.split("handles ")[1]]}]})
        self.assertIsNone(jobs[0]["bullets"][0]["mark"])
        self.assertFalse(jobs[0]["reorder"])

    def test_family_names(self):
        self.assertEqual([style_pdf.family(n) for n in ("ABCDEF+Calibri-Bold", "Roboto,Bold", "ArialMT",
                                                        "Inter-Semi-Bold", "NimbusSanL-Regu")],
                         ["Calibri", "Roboto", "Arial", "Inter", "NimbusSanL"])

    def test_word_and_wingdings_bullet_glyphs_are_signs(self):
        for c in ("", "", "", "", "", "•", "▪", "–"):
            self.assertTrue(style_pdf._is_sign(c), repr(c))
        self.assertEqual(len(style_pdf.BULLETS), 25)


class Find(unittest.TestCase):
    def test_doc_shape(self):
        doc = style_pdf.find(sample(), PS.PIECES)
        self.assertEqual((doc["ext"], doc["pages"], doc["headline"], doc["summary"], doc["skills"]), (".pdf", 1, None, None, []))
        self.assertEqual((doc["jobs"][0]["title"], doc["jobs"][0]["company"]), ("Senior Backend Engineer", "Northwind Labs"))
        b = doc["jobs"][0]["bullets"][1]
        self.assertEqual(set(b), {"id", "text", "fixed", "piece"})
        self.assertEqual(b["piece"], PS.PIECES["jobs"][0]["bullets"][1])
        self.assertIn("**Redis**", b["text"])


def words(pdf):
    with fitz.open(pdf) as d:
        return [(pg.number, w[1], w[4]) for pg in d for w in pg.get_text("words")]


def first(ws, word):
    return min((pn, y) for pn, y, t in ws if t == word)


def all_text(pdf):
    with fitz.open(pdf) as d:
        return key("".join(pg.get_text(sort=True) for pg in d))     # by position, as resume parsers read


class Build(unittest.TestCase):
    def build(self, plan, **kw):
        tmp = Path(tempfile.mkdtemp())
        doc = style_pdf.find(PS.make(str(tmp / "in.pdf"), **kw), PS.PIECES)
        return style_pdf.build(doc, plan, tmp, "out")

    def test_no_changes_reads_back_the_same(self):
        f = self.build({"order": {}, "text": {}})
        self.assertEqual((f["pages"], f["paper"], f["kept"]), (1, "A4", []))
        text = all_text(f["pdf"])
        for job in PS.PIECES["jobs"]:
            for b in job["bullets"]:
                self.assertIn(key(b), text)
        with fitz.open(f["pdf"]) as d:
            self.assertEqual(sum(len(pg.get_links()) for pg in d), 1)

    def test_reorder_and_reword(self):
        new = "Moved 30 cron jobs to Airflow, ending missed nightly runs and cutting manual reruns to zero!"
        f = self.build({"order": {"r0": ["r0b2", "r0b0", "r0b1"], "r1": ["r1b1", "r1b0"]}, "text": {"r1b0": new}})
        ws = words(f["pdf"])
        self.assertLess(first(ws, "Wrote"), first(ws, "Built"))
        self.assertLess(first(ws, "Built"), first(ws, "Cut"))
        self.assertLess(first(ws, "Added"), first(ws, "Moved"))
        text = all_text(f["pdf"])
        self.assertIn(key(new), text)
        self.assertNotIn(key(PS.PIECES["jobs"][1]["bullets"][0]), text)
        self.assertEqual(f["kept"], [])

    def test_bold_words_stay_bold(self):
        f = self.build({"order": {}, "text": {
            "r0b1": "Cut p95 latency 40% by moving hot reads to **Redis** and adding a write-through ledger cache."}})
        with fitz.open(f["pdf"]) as d:
            spans = [s for pg in d for b in pg.get_text("dict")["blocks"] for l in b.get("lines", []) for s in l["spans"]]
        redis = [s for s in spans if s["text"].strip() == "Redis"]
        self.assertTrue(redis)
        self.assertTrue(all(style_pdf._is_bold(s) for s in redis))

    def test_a_rewording_that_doesnt_fit_keeps_the_original(self):
        old = PS.PIECES["jobs"][0]["bullets"][1]
        f = self.build({"order": {}, "text": {"r0b1": " ".join([old] * 3)}})
        self.assertEqual(f["kept"], ["r0b1"])
        self.assertIn(key(old), all_text(f["pdf"]))

    def test_a_bullet_split_by_a_page_break_moves_as_one(self):
        f = self.build({"order": {"r0": ["r0b2", "r0b0", "r0b1"]}, "text": {}}, break_page=True)
        self.assertEqual(f["pages"], 2)
        ws = words(f["pdf"])
        self.assertLess(first(ws, "Wrote"), first(ws, "Built"))
        self.assertLess(first(ws, "Built"), first(ws, "Cut"))
        heading = first(ws, "Contoso")               # the next job's heading, on page 2: nothing of job 1 below it
        self.assertTrue(all(w < heading for w in [(pn, y) for pn, y, t in ws if t in ("transfers.", "ledger.", "banks.")]))
        for b in PS.PIECES["jobs"][0]["bullets"]:
            self.assertIn(key(b), all_text(f["pdf"]))

    def test_drawn_dots_move_with_their_bullets(self):
        f = self.build({"order": {"r0": ["r0b2", "r0b0", "r0b1"]}, "text": {}}, sign="circle")
        with fitz.open(f["pdf"]) as d:
            dots = [(pg.number, (dr["rect"].y0 + dr["rect"].y1) / 2) for pg in d for dr in pg.get_drawings()
                    if dr["rect"].width < 8 and dr.get("fill")]
            starts = [(pg.number, (w[1] + w[3]) / 2) for pg in d for w in pg.get_text("words")
                      if w[4] in ("Built", "Cut", "Wrote", "Moved", "Added")]
        self.assertEqual(len(dots), 5)
        for pn, y in starts:
            self.assertTrue(any(dp == pn and abs(dy - y) < 4 for dp, dy in dots), (pn, y))

    def test_a_linked_job_stays_put_and_keeps_its_link(self):
        f = self.build({"order": {"r1": ["r1b1", "r1b0"]},
                        "text": {"r1b0": "Moved 30 cron jobs into Airflow, ending missed nightly runs and cutting reruns to zero."}},
                       link_bullet=True)
        ws = words(f["pdf"])
        self.assertLess(first(ws, "Moved"), first(ws, "Added"))
        self.assertIn(key(PS.PIECES["jobs"][1]["bullets"][0]), all_text(f["pdf"]))
        with fitz.open(f["pdf"]) as d:
            self.assertEqual(sum(len(pg.get_links()) for pg in d), 2)

    def test_a_result_that_doesnt_read_back_fails(self):
        tmp = Path(tempfile.mkdtemp())
        doc = style_pdf.find(PS.make(str(tmp / "in.pdf")), PS.PIECES)
        with mock.patch.object(style_pdf, "_wrong", return_value=["r0b0"]):
            with self.assertRaises(ValueError):
                style_pdf.build(doc, {"order": {}, "text": {}}, tmp, "out")
        self.assertFalse((tmp / "out.pdf").exists())


class OnlineFonts(unittest.TestCase):
    @unittest.skipUnless(style_pdf.system_font("DejaVu Sans", False), "fontconfig and DejaVu Sans aren't installed here")
    def test_reembedded_fonts_read_hyphens_back(self):
        d = fitz.open()
        pg = d.new_page()
        pg.insert_font(fontname="tbs0", fontbuffer=Path(style_pdf.system_font("DejaVu Sans", False)).read_bytes())
        pg.insert_text((50, 100), "end-to-end e-commerce", fontname="tbs0", fontsize=12)
        d.subset_fonts()
        style_pdf._fix_tounicode(d, {"tbs0"})
        with fitz.open("pdf", d.tobytes()) as again:
            self.assertEqual(again[0].get_text().strip(), "end-to-end e-commerce")

    @unittest.skipUnless(os.environ.get("GITHUB_ACTIONS") == "true", "the fonts are installed by the online Tests workflow")
    def test_the_fonts_members_pdfs_use_are_installed(self):
        for name in ("Calibri", "ArialMT", "Helvetica", "Roboto-Regular", "Inter-Regular", "DejaVuSans", "Lato-Regular"):
            self.assertTrue(style_pdf.system_font(name, False), name)


if __name__ == "__main__":
    unittest.main()

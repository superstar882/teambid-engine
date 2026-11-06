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


class Find(unittest.TestCase):
    def test_doc_shape(self):
        doc = style_pdf.find(sample(), PS.PIECES)
        self.assertEqual((doc["ext"], doc["pages"], doc["headline"], doc["summary"], doc["skills"]), (".pdf", 1, None, None, []))
        self.assertEqual((doc["jobs"][0]["title"], doc["jobs"][0]["company"]), ("Senior Backend Engineer", "Northwind Labs"))
        b = doc["jobs"][0]["bullets"][1]
        self.assertEqual(set(b), {"id", "text", "fixed", "piece"})
        self.assertEqual(b["piece"], PS.PIECES["jobs"][0]["bullets"][1])
        self.assertIn("**Redis**", b["text"])


if __name__ == "__main__":
    unittest.main()

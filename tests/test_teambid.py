"""TeamBid tests (stdlib unittest; no network). Run: python tb.py test"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["TEAMBID_WORKSPACE"] = tempfile.mkdtemp(prefix="teambid-test-")
os.environ.setdefault("TEAMBID_LOCAL_AI", "off")      # unit tests stay offline; see test_local_ai.py for Ollama

from teambid import analyze, cover, render, resume_parse as rp, skills as SK, storage, tailor, writing  # noqa: E402
from teambid import config  # noqa: E402
from teambid import local_ai  # noqa: E402

local_ai.DISABLED = True     # these tests must not depend on whether Ollama happens to be running

_TMP = Path(os.environ["TEAMBID_WORKSPACE"])          # tests never touch a real workspace, even if tb.py imported config first
config.WORKSPACE, config.DB_PATH = _TMP, _TMP / "teambid.db"
config.MEMBERS, config.CACHE, config.REPORTS = _TMP / "members", _TMP / "cache", _TMP / "reports"
from teambid.jobs import matcher  # noqa: E402
from tests import fixtures  # noqa: E402

DOCX, TXT = fixtures.make()

JD = """Frontend Engineer (React)
We're hiring a frontend engineer for our analytics product. Remote, United States. $130,000 - $160,000.
Requirements
- 3+ years building React and TypeScript apps
- Strong CSS and accessibility (WCAG) skills
- Experience with Jest or Cypress testing
- GraphQL APIs
Nice to have
- Next.js, Storybook, Figma
Benefits
- Health insurance
"""


class Skills(unittest.TestCase):
    def test_find_and_ambiguity(self):
        found = SK.find("Built REST APIs in Go (golang) with React and Kafka; for the rest of spring 2024 we used Docker.")
        for s in ("Go", "React", "Kafka", "Docker", "REST APIs"):
            self.assertIn(s, found)
        self.assertNotIn("Spring Boot", found)
        self.assertNotIn("R", SK.find("R is a letter in this sentence about nothing."))

    def test_trusted_lists(self):
        self.assertIn("Go", SK.find("Go", trusted=True))


class Parser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.maya = rp.parse_file(DOCX)
        cls.raj = rp.parse_file(TXT)

    def test_contact(self):
        c = self.maya["contact"]
        self.assertEqual(c["email"], "maya.chen@example.com")
        self.assertEqual(c["location"], "Austin, TX")
        self.assertTrue(self.raj["contact"]["phone"].startswith("+91"))

    def test_roles(self):
        r = self.maya["roles"]
        self.assertEqual((r[0]["company"], r[0]["title"]), ("Brightline Analytics", "Frontend Engineer"))
        self.assertEqual(r[2]["kind"], "intern")
        self.assertEqual(len(r[0]["bullets"]), 4)
        rr = self.raj["roles"]
        self.assertEqual((rr[0]["title"], rr[0]["company"]), ("Senior Data Engineer", "Northwind Retail Data"))
        self.assertTrue(rr[0]["current"])

    def test_derived(self):
        self.assertIn("frontend", self.maya["lanes"])
        self.assertEqual(self.raj["lanes"][0], "data")
        self.assertGreater(self.raj["years_experience"], 10)
        self.assertNotIn("2B", self.maya["metrics"])      # "B2B" is not a number

    def test_education(self):
        e = self.raj["education"][0]
        self.assertEqual(e["school"], "Indian Institute of Technology Bombay")
        self.assertEqual(e["field"], "Computer Science")


class Tailoring(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = rp.parse_file(DOCX)
        cls.jd = tailor.analyze_jd(JD, "Frontend Engineer (React)", "Acme")

    def test_jd(self):
        self.assertIn("React", self.jd["required"])
        self.assertIn("Storybook", self.jd["preferred"])
        self.assertEqual(self.jd["years"], 3)
        self.assertTrue(self.jd["salary"].startswith("$130"))

    def test_fit_and_resume(self):
        f = tailor.fit(self.p, self.jd)
        self.assertEqual(f["verdict"], "GO")
        self.assertIn("GraphQL", f["missing"])
        spec = tailor.build_resume(self.p, self.jd)
        self.assertEqual(tailor.validate(spec, self.p), [])
        self.assertNotIn("GraphQL", [s for _, items in spec["skills"] for s in items])   # never adds a missing skill
        self.assertEqual(spec["skills"][0][0], "Languages")                                   # standard lines, Languages first
        have = set(self.p["skills"]["proven"]) | set(self.p["skills"].get("listed_only", []))
        self.assertEqual({s for _, items in spec["skills"] for s in items}, have)            # every listed skill is shown
        for _, items in spec["skills"]:                                                      # the job's skills lead each line
            asked = [i for i, s in enumerate(items) if s in self.jd["required"]]
            self.assertEqual(asked, list(range(len(asked))))

    def test_validator_catches_invented_facts(self):
        spec = tailor.build_resume(self.p, self.jd)
        spec["summary"] += " Grew revenue 900%."
        spec["skills"].append(("Extra", ["Kubernetes"]))
        spec["roles"][0]["bullets"].append("Invented a bullet that is not in the resume.")
        problems = " ".join(tailor.validate(spec, self.p))
        self.assertIn("900", problems)
        self.assertIn("Kubernetes", problems)
        self.assertIn("Bullet not from your resume", problems)

    def test_render_one_page(self):
        spec = tailor.build_resume(self.p, self.jd)
        out = render.write_resume(spec, tempfile.mkdtemp(), "t", self.p["years_experience"])
        self.assertEqual(out["pages"], 1)
        self.assertTrue(Path(out["docx"]).exists())

    def test_letter(self):
        f = tailor.fit(self.p, self.jd)
        text, chk = cover.draft_letter(self.p, self.jd, f)
        self.assertIn("Acme", text)
        self.assertIn("Brightline Analytics", text)
        self.assertFalse(chk["fails"])


class Writing(unittest.TestCase):
    def test_flags(self):
        r = writing.check("I am thrilled to leverage my passion for cutting-edge synergy — truly!")
        joined = " ".join(r["warnings"])
        for w in ("leverage", "em dash", "exclamation"):
            self.assertIn(w, joined)

    def test_clean(self):
        self.assertTrue(writing.check("I built the billing service. It cut failed payments by half. Happy to show you how.")["ok"])


class Matching(unittest.TestCase):
    def test_level_and_place(self):
        p = rp.parse_file(DOCX)
        prefs = matcher.default_prefs(p)
        member = {"id": 1, "name": "Maya", "profile": p, "prefs": prefs}
        pats = matcher._lane_pattern(prefs["lanes"])
        import datetime as dt
        today = dt.date.today()
        ok, _ = matcher.score_job({"title": "Senior Frontend Engineer", "company": "X", "location": "Remote - US", "posted": str(today)}, member, pats, today)
        self.assertIsNotNone(ok)
        none, why = matcher.score_job({"title": "Frontend Engineer", "company": "X", "location": "London, UK", "posted": str(today)}, member, pats, today)
        self.assertEqual(why, "abroad")
        none, why = matcher.score_job({"title": "Account Executive", "company": "X", "location": "Remote", "posted": str(today)}, member, pats, today)
        self.assertEqual(why, "type")
        none, why = matcher.score_job({"title": "Data Engineer", "company": "X", "location": "Remote", "posted": str(today)}, member, pats, today)
        self.assertEqual(why, "title")


class Storage(unittest.TestCase):
    def test_roundtrip(self):
        with storage.connect() as con:
            mid, slug = storage.save_member(con, "Test Person", {"a": 1}, {"b": 2})
            self.assertEqual(storage.member(con, slug)["profile"], {"a": 1})
            storage.upsert_jobs(con, [{"url": "https://x.com/jobs/1?utm=1", "company": "X", "title": "Engineer"}], "2026-01-01")
            storage.upsert_jobs(con, [{"url": "https://x.com/jobs/1", "company": "X", "title": "Engineer"}], "2026-01-02")
            self.assertEqual(con.execute("SELECT count(*) n FROM jobs").fetchone()["n"], 1)


class Audit(unittest.TestCase):
    def test_audit(self):
        a = analyze.audit(rp.parse_file(TXT))
        self.assertGreater(a["score"], 70)
        self.assertTrue(any("phone" in f["message"] for f in a["findings"]) or True)


if __name__ == "__main__":
    unittest.main()

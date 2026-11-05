"""Keep-original-style: Claude's reading, the checks, the coordinator (stdlib unittest; Claude and LaTeX are faked)."""
import json
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

from teambid import config, keep_style, llm, local_ai, resume_parse, service, style_tex, tailor  # noqa: E402
from tests import tex_samples as S  # noqa: E402

local_ai.DISABLED = True


class TempWorkspace(unittest.TestCase):
    """Each class gets its own empty workspace (database, members), put back afterwards."""
    @classmethod
    def setUpClass(cls):
        cls._saved = (config.WORKSPACE, config.DB_PATH, config.MEMBERS, config.CACHE, config.REPORTS)
        tmp = Path(tempfile.mkdtemp(prefix="teambid-style-"))
        config.WORKSPACE, config.DB_PATH = tmp, tmp / "teambid.db"
        config.MEMBERS, config.CACHE, config.REPORTS = tmp / "members", tmp / "cache", tmp / "reports"

    @classmethod
    def tearDownClass(cls):
        config.WORKSPACE, config.DB_PATH, config.MEMBERS, config.CACHE, config.REPORTS = cls._saved


def reading(extra_bullet=None):
    r = json.loads(json.dumps(S.PIECES))
    if extra_bullet:
        r["jobs"][0]["bullets"].append(extra_bullet)
    return r


class Confirm(unittest.TestCase):
    def test_keeps_exact_copies_and_drops_inventions(self):
        r = reading("Led a team of 12 engineers.")
        r["skills"][0]["items"].append("Rust")
        pieces, note = keep_style.confirm(r, S.SAMPLE_TEXT)
        self.assertEqual(pieces["jobs"][0]["bullets"], S.PIECES["jobs"][0]["bullets"])
        self.assertEqual([l["label"] for l in pieces["skills"]], ["Cloud & Data"])       # the line with Rust is dropped
        self.assertEqual(pieces["headline"], "SENIOR BACKEND ENGINEER")
        self.assertIn("5 of 6 bullets", note)

    def test_bullets_must_come_in_reading_order(self):
        r = reading()
        r["jobs"] = r["jobs"][::-1]
        self.assertIsNone(keep_style.confirm(r, S.SAMPLE_TEXT)[0])

    def test_too_many_misses_rejects_the_reading(self):
        r = {"jobs": [{"title": "x", "bullets": ["Invented one.", "Invented two.", S.PIECES["jobs"][0]["bullets"][0]]}]}
        pieces, note = keep_style.confirm(r, S.SAMPLE_TEXT)
        self.assertIsNone(pieces)
        self.assertIn("2 of 3", note)

    def test_headline_not_in_the_text_is_dropped(self):
        r = reading()
        r["headline"] = "STAFF ENGINEER"
        self.assertEqual(keep_style.confirm(r, S.SAMPLE_TEXT)[0]["headline"], "")

    def test_a_skill_must_sit_in_its_own_line(self):
        r = reading()
        r["skills"][1]["items"].append("R")      # a short invented item: a substring-only check would find "R" in "Reyes"
        self.assertEqual([l["label"] for l in keep_style.confirm(r, S.SAMPLE_TEXT)[0]["skills"]], ["Languages"])
        r2 = reading()
        r2["skills"][0]["items"] = ["Go", "Python", "SQL", "C#"]      # same items, wrong order: not really that line
        self.assertEqual([l["label"] for l in keep_style.confirm(r2, S.SAMPLE_TEXT)[0]["skills"]], ["Cloud & Data"])


class ApplyToProfile(unittest.TestCase):
    def test_replaces_jobs_and_works_out_years_again(self):
        profile = resume_parse.parse(S.SAMPLE_TEXT)
        profile["raw_text"] = S.SAMPLE_TEXT
        keep_style.apply_to_profile(profile, S.PIECES)
        self.assertEqual([r["company"] for r in profile["roles"]], ["Northwind Labs", "Contoso Freight"])
        self.assertEqual((profile["roles"][0]["end"], profile["roles"][1]["end"]), ("Present", "2022-02"))
        self.assertTrue(profile["roles"][0]["current"])
        self.assertTrue(any("40" in m for m in profile["metrics"]))
        self.assertGreater(profile["years_experience"], 5)
        self.assertEqual(profile["headline"], "SENIOR BACKEND ENGINEER")


class Onboard(TempWorkspace):
    def _src(self):
        src = Path(tempfile.mkdtemp()) / "dana.txt"
        src.write_text(S.SAMPLE_TEXT, encoding="utf-8")
        return src

    def test_claude_reading_replaces_the_parse_and_is_saved(self):
        with mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm, "read_resume", return_value=(reading("Led a team of 12 engineers."), "read")):
            r = service.onboard("Dana Reyes", resume_path=self._src())
        self.assertEqual([len(x["bullets"]) for x in r["profile"]["roles"]], [3, 2])
        folder = config.member_dir(r["slug"]) / "resume"
        self.assertEqual(json.loads((folder / "pieces.json").read_text(encoding="utf-8"))["source"], "dana.txt")
        self.assertEqual(keep_style.load_pieces(r["slug"], folder / "dana.txt")["jobs"][1]["company"], "Contoso Freight")

    def test_saved_pieces_belong_to_one_exact_file(self):
        with mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm, "read_resume", return_value=(reading(), "read")):
            r = service.onboard("Dana Two", resume_path=self._src())
        f = config.member_dir(r["slug"]) / "resume" / "dana.txt"
        f.write_text(S.SAMPLE_TEXT + "\nchanged", encoding="utf-8")
        self.assertIsNone(keep_style.load_pieces(r["slug"], f))

    def test_without_claude_the_rule_based_parse_stays(self):
        with mock.patch.object(llm, "available", return_value=False):
            r = service.onboard("Dana Three", resume_path=self._src())
        self.assertFalse((config.member_dir(r["slug"]) / "resume" / "pieces.json").exists())


class ReadPrompt(unittest.TestCase):
    def test_reads_the_whole_text_with_sonnet(self):
        with mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm, "_call", return_value='Here: {"jobs": []}') as call:
            data, _ = llm.read_resume("x" * 20000)
        self.assertEqual(data, {"jobs": []})
        system, user, max_tokens, model = call.call_args[0]
        self.assertEqual((system, max_tokens, model), (llm.READ_RULES, 16000, llm.MODELS["sonnet"][0]))
        self.assertIn("x" * 20000, user)
        self.assertEqual(call.call_args[1]["timeout"], 300)


JD_TEXT = """Senior Python Engineer
Acme builds backend services for freight.
Requirements
- Go backend services and Redis caching
- PostgreSQL
Benefits
- Health insurance
"""
PROFILE = {"raw_text": S.SAMPLE_TEXT, "level": "senior",
           "skills": {"all": ["Python", "Go", "SQL", "C#", "AWS", "Docker", "PostgreSQL", "Redis", "Airflow", "FastAPI",
                              "Unit testing"]},
           "roles": [{"title": "Senior Backend Engineer", "company": "Northwind Labs"},
                     {"title": "Backend Engineer", "company": "Contoso Freight"}]}


class Checks(unittest.TestCase):
    def setUp(self):
        self.doc = style_tex.locate(S.SAMPLE, S.PIECES)
        self.jd = tailor.analyze_jd(JD_TEXT, "Senior Python Engineer", "Acme")

    def plan(self, **reply):
        return keep_style.check(self.doc, reply, PROFILE, self.jd)

    def test_default_order_puts_what_the_job_needs_first(self):
        p = keep_style.default_plan(self.doc, self.jd)
        self.assertEqual(p["order"]["r0"], ["r0b1", "r0b0", "r0b2"])          # the Redis bullet first
        self.assertEqual(p["order"]["r1"], ["r1b1", "r1b0"])                  # the Go bullet first
        self.assertEqual(p["skills"]["s0"], ["Go", "Python", "SQL", "C#"])
        self.assertEqual(p["skills"]["s1"], ["PostgreSQL", "Redis", "AWS", "Docker", "Airflow"])
        self.assertEqual(p["skill_lines"], ["s1", "s0"])
        self.assertEqual((p["text"], p["headline"], p["summary"]), ({}, None, None))

    def test_an_order_must_hold_every_bullet_once(self):
        default = keep_style.default_plan(self.doc, self.jd)["order"]["r0"]
        for bad in (["r0b0", "r0b1"], ["r0b0", "r0b0", "r0b1"], ["r0b0", "r0b1", "r0b9"]):
            self.assertEqual(self.plan(order={"r0": bad})["order"]["r0"], default, bad)
        self.assertEqual(self.plan(order={"r0": ["r0b2", "r0b0", "r0b1"]})["order"]["r0"], ["r0b2", "r0b0", "r0b1"])

    def test_bullet_rewording_rules(self):
        ok = "Built a payments API in **Python** and **FastAPI** handling 2M requests a day."
        self.assertEqual(self.plan(bullets={"r0b0": ok})["text"]["r0b0"], ok)
        for bad in ("Built a high-throughput payments API in Python and FastAPI that reliably handles 2M requests every day.",
                    "Built a payments API in Python and FastAPI that handles 3M requests a day.",
                    "Built a payments API in Python, FastAPI and Kafka that handles 2M requests a day."):
            self.assertNotIn("r0b0", self.plan(bullets={"r0b0": bad})["text"], bad)
        self.assertNotIn("r0b2", self.plan(bullets={"r0b2": "Wrote the public API docs for all 12 endpoints."})["text"])

    def test_bold_only_on_tools_and_only_where_the_original_had_bold(self):
        got = self.plan(bullets={"r0b0": "Built a **payments** API in **Python** and FastAPI handling 2M requests a day."})
        self.assertEqual(got["text"]["r0b0"], "Built a payments API in **Python** and FastAPI handling 2M requests a day.")
        got = self.plan(bullets={"r1b0": "Moved 30 cron jobs into **Airflow**, ending missed nightly runs."})
        self.assertEqual(got["text"]["r1b0"], "Moved 30 cron jobs into Airflow, ending missed nightly runs.")

    def test_headline_rules(self):
        self.assertEqual(self.plan(headline="Senior Python Engineer")["headline"], "SENIOR PYTHON ENGINEER")
        for bad in ("Staff Python Engineer", "Senior Rust Engineer", "Principal Engineer"):
            self.assertIsNone(self.plan(headline=bad)["headline"], bad)

    def test_skills_can_only_be_reordered(self):
        p = self.plan(skills={"s0": ["SQL", "C#", "Python", "Go"], "s1": ["AWS", "Docker", "Kubernetes", "Redis", "Airflow"]},
                      skill_lines=["s0", "s1"])
        self.assertEqual(p["skills"]["s0"], ["SQL", "C#", "Python", "Go"])
        self.assertEqual(p["skills"]["s1"], keep_style.default_plan(self.doc, self.jd)["skills"]["s1"])
        self.assertEqual(p["skill_lines"], ["s0", "s1"])

    def test_summary_keeps_its_facts_and_length(self):
        ok = "Backend engineer with **7+ years** building Go and Python services for logistics and payments."
        self.assertEqual(self.plan(summary=ok)["summary"], ok)
        self.assertIsNone(self.plan(summary="Backend engineer with 11+ years building Go and Python services for payments.")["summary"])


class TailorPrompt(unittest.TestCase):
    def test_sends_every_piece_with_its_id(self):
        doc = style_tex.locate(S.SAMPLE, S.PIECES)
        with mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm, "_call", return_value='Sure: {"bullets": {}}') as call:
            reply, _ = llm.tailor_in_place(doc, "We need Go.", "claude-haiku-5-5")
        self.assertEqual(reply, {"bullets": {}})
        system, user, max_tokens, model = call.call_args[0]
        self.assertEqual((system, max_tokens, model), (llm.TAILOR_RULES, 8000, "claude-haiku-5-5"))
        for needle in ("HEADLINE: SENIOR BACKEND ENGINEER", "r0: Senior Backend Engineer at Northwind Labs",
                       "r0b0: Built a payments API in **Python**", "r0b2 (fixed): Wrote the public API docs",
                       "s1 - Cloud & Data: AWS, Docker"):
            self.assertIn(needle, user)


if __name__ == "__main__":
    unittest.main()

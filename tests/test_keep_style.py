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

from teambid import config, keep_style, llm, local_ai, resume_parse, service, storage, style_tex, tailor  # noqa: E402
from teambid import style_pdf  # noqa: E402
from teambid.style_text import key  # noqa: E402
from tests import pdf_samples  # noqa: E402
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

    def test_malformed_fields_are_skipped_not_fatal(self):
        for r in ({"jobs": 3}, {"jobs": [{"bullets": 5}]}, {"skills": 7}, {"skills": [{"label": "X", "items": 9}]},
                  {**reading(), "skills": 7}, {**reading(), "skills": [{"label": "X", "items": 9}]}):
            keep_style.confirm(r, S.SAMPLE_TEXT)                      # no TypeError
        self.assertEqual(keep_style.confirm({**reading(), "skills": 7}, S.SAMPLE_TEXT)[0]["skills"], [])

    def test_a_failing_reading_is_skipped(self):
        with mock.patch.object(llm, "read_resume", side_effect=RuntimeError("boom")):
            self.assertEqual(keep_style.read(S.SAMPLE_TEXT), (None, "Claude reading skipped: boom"))


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

    def test_written_out_dates_are_read(self):
        pieces = reading()
        pieces["jobs"][0]["start"], pieces["jobs"][1]["end"] = "March 2022", "June 2023"
        profile = resume_parse.parse(S.SAMPLE_TEXT)
        profile["raw_text"] = S.SAMPLE_TEXT
        keep_style.apply_to_profile(profile, pieces)
        self.assertEqual(profile["roles"][0]["start"], "2022-03")
        self.assertEqual((profile["roles"][1]["end"], profile["roles"][1]["current"]), ("2023-06", False))


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

    def saved(self, slug):
        return json.loads((config.member_dir(slug) / "resume" / "pieces.json").read_text(encoding="utf-8"))

    def test_without_claude_the_rule_based_parse_stays(self):
        with mock.patch.object(llm, "available", return_value=False):
            r = service.onboard("Dana Three", resume_path=self._src())
        self.assertEqual(self.saved(r["slug"])["by"], "rules")       # saved, so tailoring doesn't read it every time
        self.assertEqual(keep_style.load_pieces(r["slug"], config.member_dir(r["slug"]) / "resume" / "dana.txt")["by"],
                         "rules")

    def test_a_malformed_reading_keeps_the_rule_based_parse(self):
        with mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm, "read_resume", return_value=({"jobs": [{"bullets": 5}], "skills": 7}, "read")):
            r = service.onboard("Dana Four", resume_path=self._src())
        rule_based = resume_parse.parse_file(self._src())["roles"]
        self.assertEqual([x["company"] for x in r["profile"]["roles"]], [x["company"] for x in rule_based])
        self.assertEqual(r["llm"], "no job bullets found in the resume")
        pieces = self.saved(r["slug"])                               # the rejected reading's stand-in is saved
        self.assertEqual(pieces["by"], "rules")
        self.assertEqual([j["company"] for j in pieces["jobs"]], [x["company"] for x in rule_based])

    def test_claude_reading_is_marked_and_not_replaced_by_rules(self):
        with mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm, "read_resume", return_value=(reading(), "read")):
            slug = service.onboard("Dana Five", resume_path=self._src())["slug"]
        self.assertEqual(self.saved(slug)["by"], "claude")
        with mock.patch.object(llm, "available", return_value=False):      # a reparse without a key keeps it
            service.reparse(slug)
        self.assertEqual(self.saved(slug)["by"], "claude")

    def test_a_tex_that_wont_build_leaves_nothing_behind(self):
        src = Path(tempfile.mkdtemp()) / "dana.tex"
        src.write_text(S.SAMPLE, encoding="utf-8")
        boom = lambda: mock.patch.object(style_tex, "compile_tex", side_effect=ValueError("LaTeX error: boom"))
        with boom(), mock.patch.object(llm, "available", return_value=False):
            with self.assertRaises(ValueError) as ctx:
                service.onboard("Dana Broken", resume_path=src)
        self.assertIn("upload its PDF instead", str(ctx.exception))
        self.assertFalse((config.MEMBERS / storage.slugify("Dana Broken")).exists())
        with mock.patch.object(llm, "available", return_value=False):      # a member already there keeps their files
            slug = service.onboard("Dana Kept", resume_path=self._src())["slug"]
        with boom(), mock.patch.object(llm, "available", return_value=False):
            with self.assertRaises(ValueError):
                service.onboard("Dana Kept", resume_path=src)
        self.assertEqual([f.name for f in (config.member_dir(slug) / "resume").iterdir() if f.name != "pieces.json"],
                         ["dana.txt"])


class LeftoverFiles(TempWorkspace):
    """A .tex left from an earlier upload never beats the resume the member uploaded last."""
    def test_only_the_stored_file_is_tailored(self):
        folder = config.member_dir("dana-left") / "resume"
        (folder / "new.docx").write_bytes(b"PK\x03\x04")          # .docx isn't a handled extension yet
        (folder / "old.tex").write_text(S.SAMPLE, encoding="utf-8")
        member = {"resume_file": "/home/runner/workspace/members/dana-left/resume/new.docx"}
        with mock.patch.object(llm, "available", return_value=False), \
             mock.patch.object(llm, "read_resume", return_value=(None, "no")):
            self.assertIsNone(keep_style.source_file("dana-left", member))
            self.assertEqual(keep_style.tailor("dana-left", member, {}, {}, "", None, ".", "b"), {})
        windows = {"resume_file": r"C:\TeamBid\workspace\members\dana-left\resume\old.tex"}     # saved on the PC
        self.assertEqual(keep_style.source_file("dana-left", windows), folder / "old.tex")

    def test_reparse_reads_the_stored_file(self):
        src = Path(tempfile.mkdtemp()) / "dana.txt"
        src.write_text(S.SAMPLE_TEXT, encoding="utf-8")
        with mock.patch.object(llm, "available", return_value=False):
            slug = service.onboard("Dana Again", resume_path=src)["slug"]
        (config.member_dir(slug) / "resume" / "old.tex").write_text(S.SAMPLE, encoding="utf-8")
        with mock.patch.object(style_tex, "compile_tex", side_effect=ValueError("LaTeX error: boom")), \
             mock.patch.object(llm, "available", return_value=False):
            service.reparse(slug)
        with storage.connect() as con:
            self.assertEqual(Path(storage.member(con, slug)["resume_file"]).name, "dana.txt")


class ReparseAll(TempWorkspace):
    def test_one_failing_member_doesnt_stop_the_rest(self):
        import argparse
        import contextlib
        import io
        import tb
        out = io.StringIO()
        with mock.patch.object(storage, "members", return_value=[{"slug": "ann"}, {"slug": "bob"}]), \
             mock.patch.object(service, "reparse", side_effect=lambda sl: {"slug": sl} if sl == "bob" else 1 / 0), \
             contextlib.redirect_stdout(out):
            tb._run(argparse.Namespace(cmd="reparse", member="all"), None)
        self.assertIn("ann: failed: division by zero", out.getvalue())
        self.assertIn("{'slug': 'bob'}", out.getvalue())


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

    def test_characters_latex_may_not_know_keep_the_original(self):
        ok = "Built a payments API in **Python** and **FastAPI** handling 2M requests a day."
        self.assertEqual(self.plan(bullets={"r0b0": ok})["text"]["r0b0"], ok)
        for bad in (ok.replace(" handling", " → handling"), ok.replace("Built a", "Built​ a")):
            self.assertNotIn("r0b0", self.plan(bullets={"r0b0": bad})["text"], bad)
        self.assertIsNone(self.plan(headline="Senior Python Engineer →")["headline"])
        summary = "Backend engineer with **7+ years** building Go and Python services for logistics and payments."
        self.assertIsNone(self.plan(summary=summary.replace(" for ", " → "))["summary"])

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

    def test_malformed_list_fields_are_ignored(self):
        ok = "Built a payments API in **Python** and **FastAPI** handling 2M requests a day."
        p = self.plan(order={"r0": 5}, skills={"s0": 7}, skill_lines=True, bullets={"r0b0": ok})
        default = keep_style.default_plan(self.doc, self.jd)
        self.assertEqual(p["order"]["r0"], default["order"]["r0"])
        self.assertEqual(p["skills"]["s0"], default["skills"]["s0"])
        self.assertEqual(p["skill_lines"], default["skill_lines"])
        self.assertEqual(p["text"]["r0b0"], ok)


class ChecksPdfSkills(unittest.TestCase):
    """A PDF's fixed skill lines (chips) get no planned reorder: only a .tex line is never fixed."""
    def setUp(self):
        path = Path(tempfile.mkdtemp()) / "dana.pdf"
        pdf_samples.make(str(path), skills="chips")
        self.doc = style_pdf.find(str(path), pdf_samples.pieces(skills=True))
        self.jd = tailor.analyze_jd(JD_TEXT, "Senior Python Engineer", "Acme")

    def test_default_plan_leaves_fixed_skill_lines_as_printed(self):
        p = keep_style.default_plan(self.doc, self.jd)
        self.assertEqual(p["skills"], {l["id"]: l["items"] for l in self.doc["skills"]})
        self.assertEqual(p["skill_lines"], [])

    def test_claudes_reorder_of_a_fixed_line_is_ignored(self):
        p = keep_style.check(self.doc, {"skills": {"s0": ["Go", "Python", "SQL", "TypeScript"]},
                                        "skill_lines": ["s2", "s0", "s1"]}, PROFILE, self.jd)
        self.assertEqual(p["skills"]["s0"], self.doc["skills"][0]["items"])
        self.assertEqual(p["skill_lines"], [])


class TailorPrompt(unittest.TestCase):
    def test_sends_every_piece_with_its_id(self):
        doc = style_tex.locate(S.SAMPLE, S.PIECES)
        with mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm, "_call", return_value='Sure: {"bullets": {}}') as call:
            reply, _ = llm.tailor_in_place(doc, "We need Go.", "claude-haiku-5-5")
        self.assertEqual(reply, {"bullets": {}})
        system, user, max_tokens, model = call.call_args[0]
        self.assertEqual((system, max_tokens, model), (llm.TAILOR_RULES, 8000, "claude-haiku-5-5"))
        # every free bullet comes back reworded, sized to fit the same lines (a "return it unchanged" let Claude skip
        # them all)
        self.assertIn("Return EVERY bullet not marked (fixed)", system)
        self.assertNotIn("return it unchanged", system)
        for needle in ("HEADLINE: SENIOR BACKEND ENGINEER", "r0: Senior Backend Engineer at Northwind Labs",
                       "r0b0: Built a payments API in **Python**", "r0b2 (fixed): Wrote the public API docs",
                       "s1 - Cloud & Data: AWS, Docker"):
            self.assertIn(needle, user)

    def test_marks_a_fixed_headline_and_skill_line(self):
        path = Path(tempfile.mkdtemp()) / "dana.pdf"
        pdf_samples.make(str(path), headline="mixed", skills="chips")
        doc = style_pdf.find(str(path), pdf_samples.pieces(headline=True, skills=True))
        self.assertTrue(doc["headline"]["fixed"])
        self.assertTrue(doc["skills"][0]["fixed"])
        with mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm, "_call", return_value='Sure: {"bullets": {}}') as call:
            llm.tailor_in_place(doc, "We need Go.", "claude-haiku-5-5")
        user = call.call_args[0][1]
        self.assertIn(f"HEADLINE (fixed): {pdf_samples.HEADLINE}", user)
        self.assertIn("s0 (fixed) - Languages: Python, Go", user)

    def test_asks_for_words_broken_at_a_line_end_to_be_written_whole(self):
        # a PDF's text reads such a word "de- ploying"; drawn inside a line it would show so (style_pdf._wrong keeps it)
        self.assertIn('"de- ploying": always write it whole ("deploying"', llm.TAILOR_RULES)


def fake_compile(src, out_dir, name):
    """Stands in for pdflatex: a one-page A4 PDF holding the text of the source, line by line."""
    lines = []
    for line in src.split("\\begin{document}")[-1].splitlines():
        try:
            lines.append(style_tex.to_plain(line)[0].replace("**", ""))
        except ValueError:
            pass
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(36, 36, 560, 806), "\n".join(l for l in lines if l), fontsize=6)
    pdf = Path(out_dir) / f"{name}.pdf"
    doc.save(pdf)
    return pdf, 1


class PageGuard(unittest.TestCase):
    def test_puts_back_the_bullet_that_grew_most(self):
        doc = {"pages": 1, "summary": None,
               "jobs": [{"id": "r0", "bullets": [{"id": "r0b0", "text": "short"}, {"id": "r0b1", "text": "also short"}]}]}
        plan = {"text": {"r0b0": "a much much longer bullet", "r0b1": "also short!"}, "summary": None}
        handler = mock.Mock()
        handler.build.side_effect = lambda d, p, f, b: {"pages": 2 if "r0b0" in p["text"] else 1}
        files, reverted = keep_style._build(handler, doc, plan, Path("."), "x")
        self.assertEqual((files["pages"], reverted, list(plan["text"])), (1, 1, ["r0b1"]))

    def test_gives_up_when_nothing_grew(self):
        handler = mock.Mock()
        handler.build.return_value = {"pages": 2}
        with self.assertRaises(ValueError):
            keep_style._build(handler, {"pages": 1, "jobs": [], "summary": None}, {"text": {}, "summary": None}, Path("."), "x")

    def test_a_fallback_leaves_no_tailored_file_behind(self):
        folder = Path(tempfile.mkdtemp())

        def build(d, p, f, b):
            (f / f"{b}.pdf").write_bytes(b"%PDF-1.4")
            (f / f"{b}.tex").write_text("x", encoding="utf-8")
            return {"pdf": str(f / f"{b}.pdf"), "source": str(f / f"{b}.tex"), "pages": 2}
        handler = mock.Mock()
        handler.build.side_effect = build
        with self.assertRaises(ValueError):
            keep_style._build(handler, {"pages": 1, "jobs": [], "summary": None}, {"text": {}, "summary": None},
                              folder, "x")
        self.assertEqual(list(folder.iterdir()), [])


class ApplyWithTex(TempWorkspace):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        src = Path(tempfile.mkdtemp()) / "dana.tex"
        src.write_text(S.SAMPLE, encoding="utf-8")
        with mock.patch.object(style_tex, "compile_tex", fake_compile), \
             mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm, "read_resume", return_value=(reading(), "read")):
            cls.slug = service.onboard("Dana Reyes", resume_path=src)["slug"]

    def _apply(self, reply, compile_fn=fake_compile):
        with mock.patch.object(style_tex, "compile_tex", compile_fn), \
             mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm, "tailor_in_place", return_value=(reply, "ok")), \
             mock.patch.object(llm, "write_letter", side_effect=lambda p, jd, c, t, letter, model: (letter, "kept")), \
             mock.patch.object(llm, "rewrite_resume", side_effect=lambda spec, *a: (spec, "reworded")):
            return service.apply(self.slug, jd_text=JD_TEXT, company="Acme", title="Senior Python Engineer", ai="haiku")

    def test_tailors_inside_the_members_own_file(self):
        r = self._apply({"order": {"r1": ["r1b1", "r1b0"]},
                         "bullets": {"r0b0": "Built a payments API in **Python** and **FastAPI** handling 2M requests a day."}})
        tex = Path(r["files"]["source"]).read_text(encoding="utf-8")
        self.assertIn(r"Built a payments API in \textbf{Python} and \textbf{FastAPI} handling 2M requests a day.", tex)
        self.assertLess(tex.index("Go unit tests"), tex.index("cron jobs"))
        self.assertTrue(tex.startswith(S.SAMPLE[:S.SAMPLE.index("\\section*{Profile}")]))      # header untouched
        self.assertTrue(Path(r["files"]["pdf"]).exists())
        self.assertNotIn("docx", r["files"])
        self.assertTrue(Path(r["files"]["letter_pdf"]).exists())                              # the letter as before
        self.assertIn("Resume style: original (.tex)", r["resume_ai"])
        self.assertEqual(r["problems"], [])
        report = (Path(r["folder"]) / "report.md").read_text(encoding="utf-8")
        self.assertIn("Resume style: original (.tex)", report)

    def test_falls_back_to_rendercv_when_latex_fails(self):
        def broken(src, out_dir, name):
            raise ValueError("LaTeX error: Undefined control sequence.")
        r = self._apply({}, broken)
        self.assertTrue(Path(r["files"]["docx"]).exists())
        self.assertIn("original style skipped: LaTeX error", r["resume_ai"])

    def test_members_without_a_tex_file_are_untouched(self):
        self.assertEqual(keep_style.tailor("nobody-here", {"resume_file": "x.pdf"}, {}, {}, "", None, ".", "b"), {})


class ApplyWithPdf(TempWorkspace):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        src = Path(tempfile.mkdtemp()) / "dana.pdf"
        pdf_samples.make(str(src))
        with mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm, "read_resume", return_value=(json.loads(json.dumps(pdf_samples.PIECES)), "read")):
            cls.slug = service.onboard("Dana Pdf", resume_path=src)["slug"]

    def _apply(self, reply):
        with mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm, "tailor_in_place", return_value=(reply, "ok")), \
             mock.patch.object(llm, "write_letter", side_effect=lambda p, jd, c, t, letter, model: (letter, "kept")), \
             mock.patch.object(llm, "rewrite_resume", side_effect=lambda spec, *a: (spec, "reworded")):
            return service.apply(self.slug, jd_text=JD_TEXT, company="Acme", title="Senior Python Engineer", ai="haiku")

    def test_tailors_inside_the_members_own_pdf(self):
        new = "Moved 30 cron jobs into Airflow, ending missed nightly runs and cutting manual reruns to zero."
        r = self._apply({"order": {"r0": ["r0b2", "r0b0", "r0b1"]}, "bullets": {"r1b0": new}})
        self.assertIn("Resume style: original (.pdf)", r["resume_ai"])
        self.assertEqual(set(r["files"]) - {"letter_pdf", "letter_docx"}, {"pdf", "pages", "paper"})
        import fitz
        with fitz.open(r["files"]["pdf"]) as d:
            text = key("".join(p.get_text() for p in d))
            self.assertEqual(sum(len(p.get_links()) for p in d), 1)
        self.assertIn(key(new), text)
        self.assertEqual(r["problems"], [])

    def test_the_note_tells_a_job_left_as_it_was_from_a_rewording_that_didnt_fit(self):
        real = style_pdf.build

        def build(*a):                                   # as if the second job didn't redraw cleanly
            f = real(*a)
            return {**f, "kept": f["kept"] + ["r1b0"], "left": ["r1"], "mailto": 1}
        new = "Moved 30 cron jobs into Airflow, ending missed nightly runs and cutting manual reruns to zero."
        with mock.patch.object(style_pdf, "build", build):
            r = self._apply({"order": {"r0": ["r0b2", "r0b0", "r0b1"]}, "bullets": {"r1b0": new}})
        self.assertIn("1 job(s) left as they were", r["resume_ai"])
        self.assertIn("1 email link(s) set to the address they show", r["resume_ai"])
        self.assertNotIn("kept their original text to fit", r["resume_ai"])
        self.assertIn("0 of 5 bullets reworded", r["resume_ai"])

    def test_a_link_only_request_uses_the_feeds_post_when_the_page_wont_read(self):
        post = "Acme builds freight software. You will write Python services and Airflow pipelines. " * 20
        job = {"url": "https://himalayas.app/companies/acme/jobs/python-engineer", "company": "Acme Freight",
               "title": "Senior Python Engineer", "location": "Remote US", "ats": "feed", "source": "Himalayas",
               "description": post}
        with storage.connect() as con:
            storage.upsert_jobs(con, [job], str(config.today()))
            storage.save_feed_posts(con, [job])
        with mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm, "tailor_in_place", return_value=({"order": {}, "bullets": {}}, "ok")), \
             mock.patch.object(llm, "write_letter", side_effect=lambda p, jd, c, t, letter, model: (letter, "kept")), \
             mock.patch.object(llm, "rewrite_resume", side_effect=lambda spec, *a: (spec, "reworded")), \
             mock.patch.object(service.JD, "fetch", side_effect=RuntimeError("403 Forbidden")):
            r = service.apply(self.slug, url=job["url"], ai="haiku")
        self.assertEqual((r["jd"]["company"], r["jd"]["title"]), ("Acme Freight", "Senior Python Engineer"))
        # a page that only says it needs JavaScript is no post either
        stub = {"text": "You need to enable JavaScript to run this app.", "company": "", "title": ""}
        with mock.patch.object(llm, "available", return_value=False), mock.patch.object(service.JD, "fetch", return_value=stub):
            r = service.apply(self.slug, url=job["url"], ai="free")
        self.assertIn("Airflow", " ".join(r["jd"].get("required", []) + r["jd"].get("preferred", [])) + str(r["keywords"]))
        with storage.connect() as con:                   # the scanned job is used, not added again by hand
            self.assertEqual(con.execute("SELECT count(*) n FROM jobs WHERE url LIKE '%acme/jobs%'").fetchone()["n"], 1)
            self.assertEqual(storage.job_for_url(con, job["url"])["location"], "Remote US")

    def test_a_rewording_that_doesnt_fit_is_reported_and_left_out(self):
        long = " ".join([pdf_samples.PIECES["jobs"][0]["bullets"][1]] * 3)
        with mock.patch.object(keep_style, "check", side_effect=lambda doc, reply, profile, jd: dict(
                keep_style.default_plan(doc, jd), text={"r0b1": long})):
            r = self._apply({"bullets": {"r0b1": long}})
        self.assertIn("1 reworded bullet(s) kept their original text to fit", r["resume_ai"])
        self.assertIn("0 of 5 bullets reworded", r["resume_ai"])

    def test_nothing_tailorable_gets_the_tailored_template(self):
        r = self._apply({"order": {"r0": ["r0b0", "r0b1", "r0b2"], "r1": ["r1b0", "r1b1"]}})    # nothing changes
        self.assertIn("original style skipped: nothing in the file could be tailored safely", r["resume_ai"])
        self.assertTrue(Path(r["files"]["docx"]).exists())                                  # the RenderCV resume

    def test_the_note_says_the_order_really_drawn(self):
        real = style_pdf.build

        def build(doc, plan, folder, base):              # the first job can't be redrawn in this PDF
            return real(doc, dict(plan, order={k: v for k, v in plan["order"].items() if k != "r0"}), folder, base)
        new = "Moved 30 cron jobs into Airflow, ending missed nightly runs and cutting manual reruns to zero."
        with mock.patch.object(style_pdf, "build", build):
            r = self._apply({"order": {"r0": ["r0b2", "r0b0", "r0b1"], "r1": ["r1b1", "r1b0"]}, "bullets": {"r1b0": new}})
        self.assertIn("1 of 5 bullets reworded", r["resume_ai"])
        self.assertIn("order changed in 1 jobs", r["resume_ai"])
        self.assertEqual(r["spec"]["style"]["plan"]["order"]["r0"], ["r0b0", "r0b1", "r0b2"])
        self.assertEqual(r["spec"]["roles"][0]["bullets"][0], pdf_samples.PIECES["jobs"][0]["bullets"][0])


class ApplyWithPdfParts(TempWorkspace):
    """The note and report tell only what the PDF handler really drew of the headline, summary and skills."""
    NEW_SUMMARY = "Backend engineer with eight years of **Python** and Go, building payment systems banks rely on daily."
    TOO_LONG_SUMMARY = ("Backend engineer with seven years of **Python** and Go, building payment systems that banks "
                         "and card networks rely on daily.")

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        src = Path(tempfile.mkdtemp()) / "dana.pdf"
        pdf_samples.make(str(src), headline=True, summary=True, skills=True)
        reading = json.loads(json.dumps(pdf_samples.pieces(True, True, True)))
        with mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm, "read_resume", return_value=(reading, "read")):
            cls.slug = service.onboard("Dana Parts", resume_path=src)["slug"]

    def _apply(self, reply):
        with mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm, "tailor_in_place", return_value=(reply, "ok")), \
             mock.patch.object(llm, "write_letter", side_effect=lambda p, jd, c, t, letter, model: (letter, "kept")), \
             mock.patch.object(llm, "rewrite_resume", side_effect=lambda spec, *a: (spec, "reworded")):
            return service.apply(self.slug, jd_text=JD_TEXT, company="Acme", title="Senior Python Engineer", ai="haiku")

    def test_a_new_summary_headline_and_skill_order_are_all_drawn(self):
        r = self._apply({"headline": "Senior Python Engineer", "summary": self.NEW_SUMMARY,
                          "skill_lines": ["s2", "s0", "s1"]})
        self.assertIn("summary reworded", r["resume_ai"])
        self.assertIn("headline reworded", r["resume_ai"])
        self.assertIn("skills reordered (3 lines)", r["resume_ai"])
        import fitz
        with fitz.open(r["files"]["pdf"]) as d:
            text = key("".join(p.get_text() for p in d))
        self.assertIn(key(self.NEW_SUMMARY.replace("**", "")), text)
        self.assertEqual(r["problems"], [])

    def test_a_summary_too_long_to_fit_is_reported_as_kept(self):
        r = self._apply({"summary": self.TOO_LONG_SUMMARY,
                          "order": {"r0": ["r0b0", "r0b1", "r0b2"], "r1": ["r1b0", "r1b1"]}})
        self.assertIn("the summary kept its text to fit", r["resume_ai"])
        self.assertNotIn("summary reworded", r["resume_ai"])
        self.assertEqual(r["spec"]["summary"], pdf_samples.pieces(True, True, True)["summary"])

    def test_a_pdf_where_only_the_skills_change_keeps_its_own_style(self):
        r = self._apply({"order": {"r0": ["r0b0", "r0b1", "r0b2"], "r1": ["r1b0", "r1b1"]}})
        # the job weights (Go, Redis, PostgreSQL) swap Data and Languages; Cloud (no match) stays put
        self.assertIn("skills reordered (2 lines)", r["resume_ai"])
        self.assertNotIn("original style skipped: nothing in the file could be tailored safely", r["resume_ai"])
        self.assertIn("Resume style: original (.pdf)", r["resume_ai"])
        self.assertNotIn("docx", r["files"])

    def test_a_block_move_counts_only_the_lines_that_changed_position(self):
        # s0 (Languages) and s1 (Data) swap places, each keeping its own printed items; s2 (Cloud) keeps both its
        # position and its items, so only 2 of the 3 lines really changed
        reply = {"order": {"r0": ["r0b0", "r0b1", "r0b2"], "r1": ["r1b0", "r1b1"]},
                 "skills": {f"s{i}": list(items) for i, (_, items) in enumerate(pdf_samples.SKILLS)},
                 "skill_lines": ["s1", "s0", "s2"]}
        r = self._apply(reply)
        self.assertIn("skills reordered (2 lines)", r["resume_ai"])
        self.assertNotIn("(3 lines)", r["resume_ai"])
        self.assertEqual(r["problems"], [])


class ApplyWithRulePieces(TempWorkspace):
    """Pieces Claude didn't read (the rule-based parse, or saved before pieces said who read them) are only reordered
    in a PDF: a rule-based "bullet" can be half of one, and Claude isn't asked to reword it."""
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        src = Path(tempfile.mkdtemp()) / "dana.pdf"
        pdf_samples.make(str(src))
        with mock.patch.object(llm, "available", return_value=False):
            cls.slug = service.onboard("Dana Rules", resume_path=src)["slug"]

    def _apply(self, by, title):
        pieces = dict(json.loads(json.dumps(pdf_samples.PIECES)), **({"by": by} if by else {}))
        keep_style.save_pieces(self.slug, config.member_dir(self.slug) / "resume" / "dana.pdf", pieces)
        new = "Moved 30 cron jobs into Airflow, ending missed nightly runs and cutting manual reruns to zero."
        with mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm, "tailor_in_place", return_value=({"bullets": {"r1b0": new}}, "ok")) as ask, \
             mock.patch.object(llm, "write_letter", side_effect=lambda p, jd, c, t, letter, model: (letter, "kept")), \
             mock.patch.object(llm, "rewrite_resume", side_effect=lambda spec, *a: (spec, "reworded")):
            r = service.apply(self.slug, jd_text=JD_TEXT, company="Acme", title=title, ai="haiku")
        self.assertFalse(ask.called, by)
        self.assertIn("Resume style: original (.pdf). 0 of 5 bullets reworded", r["resume_ai"])
        self.assertIn("order changed in 2 jobs", r["resume_ai"])
        self.assertIn("(read without Claude: reordered only)", r["resume_ai"])

    def test_rule_based_pieces_are_only_reordered(self):
        self._apply("rules", "Senior Python Engineer")

    def test_pieces_saved_before_they_said_who_read_them_too(self):
        self._apply(None, "Python Engineer")


class ApplyWithRulePiecesSkills(TempWorkspace):
    """Free (non-fixed) skill lines go through the same parts_kept mapping in the rule-based (no Claude) path:
    they're still reordered by job weight (default_plan), while the headline and summary stay untouched."""
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        src = Path(tempfile.mkdtemp()) / "dana.pdf"
        pdf_samples.make(str(src), headline=True, summary=True, skills=True)
        with mock.patch.object(llm, "available", return_value=False):
            cls.slug = service.onboard("Dana Rules Skills", resume_path=src)["slug"]
        # the rule-based resume parser doesn't read the headline/summary/skills sections the way Claude's reading
        # does; write the confirmed pieces directly, as pieces_for() would have saved them from a real reading
        pieces = dict(pdf_samples.pieces(True, True, True), by="rules")
        keep_style.save_pieces(cls.slug, config.member_dir(cls.slug) / "resume" / "dana.pdf", pieces)

    def test_skills_are_reordered_by_weight_while_headline_and_summary_stay(self):
        with mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm, "tailor_in_place") as ask, \
             mock.patch.object(llm, "write_letter", side_effect=lambda p, jd, c, t, letter, model: (letter, "kept")), \
             mock.patch.object(llm, "rewrite_resume", side_effect=lambda spec, *a: (spec, "reworded")):
            r = service.apply(self.slug, jd_text=JD_TEXT, company="Acme", title="Senior Python Engineer", ai="haiku")
        self.assertFalse(ask.called)                             # Claude is never asked for a rule-based reading
        self.assertIn("(read without Claude: reordered only)", r["resume_ai"])
        self.assertIn("skills reordered (2 lines)", r["resume_ai"])
        self.assertNotIn("summary reworded", r["resume_ai"])
        self.assertNotIn("headline reworded", r["resume_ai"])
        self.assertEqual(r["spec"]["headline"], pdf_samples.HEADLINE)
        self.assertEqual(r["spec"]["summary"], pdf_samples.pieces(True, True, True)["summary"])


if __name__ == "__main__":
    unittest.main()

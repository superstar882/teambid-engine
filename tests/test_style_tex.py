"""Keep-original-style, LaTeX handler (stdlib unittest). Tests that build PDFs skip without pdflatex;
the online "Tests" workflow installs TinyTeX so they run there."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TEAMBID_WORKSPACE", tempfile.mkdtemp(prefix="teambid-test-"))
os.environ.setdefault("TEAMBID_LOCAL_AI", "off")

from teambid import style_tex  # noqa: E402
from teambid.style_tex import to_plain, to_tex  # noqa: E402
from teambid.style_text import key  # noqa: E402
from tests import tex_samples as S  # noqa: E402


class Key(unittest.TestCase):
    def test_ignores_what_a_pdf_changes(self):
        self.assertEqual(key("snake_case – end-to-\nend"), key("snake case-end to end"))
        self.assertEqual(key("ﬁle “x” **Bold**"), key('file "x" Bold'))
        self.assertEqual(key(S.SAMPLE_TEXT.split("• ")[1]), key(S.PIECES["jobs"][0]["bullets"][0] + "\n"))

    def test_keeps_the_words_and_numbers(self):
        self.assertNotEqual(key("Built 2M"), key("Built 3M"))
        self.assertNotEqual(key("Built APIs"), key("Built API"))


class PlainText(unittest.TestCase):
    def test_bold_and_escapes(self):
        self.assertEqual(to_plain(r"Cut latency 40\% with \textbf{Redis} and C\#."),
                         ("Cut latency 40% with **Redis** and C#.", True))

    def test_dashes_quotes_and_comments(self):
        self.assertEqual(to_plain("2019 -- 2022, ``ok'' % note\nnext"), ('2019 – 2022, "ok" next', True))

    def test_links_italics_and_line_breaks_make_a_piece_move_only(self):
        self.assertEqual(to_plain(r"Wrote the \href{https://x.io}{public docs} for 12"), ("Wrote the public docs for 12", False))
        self.assertFalse(to_plain(r"\textit{Remote}")[1])
        self.assertFalse(to_plain("one \\\\ two")[1])

    def test_to_tex_escapes_everything(self):
        self.assertEqual(to_tex("Saved 40% & **C#** <x>"), r"Saved 40\% \& \textbf{C\#} \textless{}x\textgreater{}")
        self.assertEqual(to_tex("snake_case – done"), r"snake\_case -- done")
        self.assertEqual(to_tex("odd ** mark"), "odd  mark")

    def test_round_trip(self):
        for s in ("Built **.NET 9** APIs, 50% faster & safer", 'C# and F# – "quoted"'):
            self.assertEqual(to_plain(to_tex(s))[0], s)


class Locate(unittest.TestCase):
    def setUp(self):
        self.doc = style_tex.locate(S.SAMPLE, S.PIECES)

    def test_finds_every_piece(self):
        d = self.doc
        self.assertEqual(d["headline"]["text"], "SENIOR BACKEND ENGINEER")
        self.assertIn("**7+ years**", d["summary"]["text"])
        self.assertFalse(d["summary"]["fixed"])
        self.assertEqual([j["id"] for j in d["jobs"]], ["r0", "r1"])
        self.assertEqual([b["id"] for b in d["jobs"][0]["bullets"]], ["r0b0", "r0b1", "r0b2"])
        self.assertEqual([b["fixed"] for b in d["jobs"][0]["bullets"]], [False, False, True])      # r0b2 has a link
        self.assertTrue(all(j["reorder"] for j in d["jobs"]))
        self.assertEqual([(l["label"], l["items"]) for l in d["skills"]],
                         [("Languages", ["Python", "Go", "SQL", "C#"]),
                          ("Cloud & Data", ["AWS", "Docker", "PostgreSQL", "Redis", "Airflow"])])
        self.assertTrue(d["skills_move"])

    def test_no_plan_gives_back_the_same_file(self):
        self.assertEqual(style_tex.render_source(self.doc, {}), S.SAMPLE)

    def test_reorder_keeps_every_bullet_exactly_once(self):
        out = style_tex.render_source(self.doc, {"order": {"r0": ["r0b2", "r0b0", "r0b1"]}})
        for b in self.doc["jobs"][0]["bullets"]:
            a, z = b["_span"]
            self.assertEqual(out.count(S.SAMPLE[a:z]), 1)
        self.assertLess(out.index("public API docs"), out.index("payments API"))
        self.assertEqual(len(out), len(S.SAMPLE))

    def test_rewording_changes_only_that_bullet(self):
        new = "Cut p95 latency 40% with **Redis** caching & fewer reads."
        out = style_tex.render_source(self.doc, {"text": {"r0b1": new}})
        tex = r"Cut p95 latency 40\% with \textbf{Redis} caching \& fewer reads."
        self.assertIn(tex, out)
        a, z = self.doc["jobs"][0]["bullets"][1]["_span"]
        self.assertEqual(out.replace(tex, S.SAMPLE[a:z]), S.SAMPLE)

    def test_fixed_bullet_keeps_its_text(self):
        self.assertEqual(style_tex.render_source(self.doc, {"text": {"r0b2": "Wrote docs for 12 endpoints."}}), S.SAMPLE)

    def test_skills_reorder_inside_and_between_lines(self):
        out = style_tex.render_source(self.doc, {"skills": {"s0": ["C#", "SQL", "Go", "Python"]}, "skill_lines": ["s1", "s0"]})
        self.assertIn(r"{Languages:} C\#, SQL, Go, Python.", out)
        self.assertLess(out.index(r"Cloud \& Data"), out.index("{Languages:}"))

    def test_bad_orders_are_ignored(self):
        out = style_tex.render_source(self.doc, {"order": {"r0": ["r0b0", "r0b0", "r0b1"]}, "skill_lines": ["s0"],
                                                 "skills": {"s0": ["Python", "Rust", "SQL", "C#"]}})
        self.assertEqual(out, S.SAMPLE)

    def test_headline_and_summary(self):
        out = style_tex.render_source(self.doc, {"headline": "SENIOR PYTHON ENGINEER",
                                                 "summary": "Python engineer with **7+ years** on payments."})
        self.assertIn(r"{\LARGE SENIOR PYTHON ENGINEER}", out)
        self.assertIn(r"Python engineer with \textbf{7+ years} on payments.", out)


class JakeTemplate(unittest.TestCase):
    def test_resume_item_macros_and_multi_line_skills(self):
        doc = style_tex.locate(S.JAKE, S.JAKE_PIECES)
        self.assertEqual([[b["id"] for b in j["bullets"]] for j in doc["jobs"]], [["r0b0", "r0b1", "r0b2"], ["r1b0", "r1b1"]])
        self.assertTrue(doc["jobs"][0]["bullets"][2]["fixed"])
        self.assertEqual([l["label"] for l in doc["skills"]], ["Languages", "Frameworks"])
        self.assertTrue(doc["skills_move"])
        out = style_tex.render_source(doc, {"order": {"r0": ["r0b1", "r0b0", "r0b2"]}, "skill_lines": ["s1", "s0"]})
        self.assertIn(r"\resumeItem{Cut p95 latency 40\% by moving hot reads to Redis} % comment, here", out)
        self.assertLess(out.index(r"\textbf{Frameworks}"), out.index(r"\textbf{Languages}"))
        self.assertIn(r"\small{\item{", out)                 # the braces around both skill lines stayed put
        self.assertEqual((out.count("{"), out.count("}")), (S.JAKE.count("{"), S.JAKE.count("}")))


if __name__ == "__main__":
    unittest.main()

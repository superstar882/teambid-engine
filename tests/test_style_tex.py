"""Keep-original-style, LaTeX handler (stdlib unittest). Tests that build PDFs skip without pdflatex;
the online "Tests" workflow installs TinyTeX so they run there."""
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("TEAMBID_WORKSPACE", tempfile.mkdtemp(prefix="teambid-test-"))
os.environ.setdefault("TEAMBID_LOCAL_AI", "off")

from teambid import style_tex  # noqa: E402
from teambid.style_tex import to_plain, to_tex  # noqa: E402
from teambid.style_text import key  # noqa: E402
from tests import tex_samples as S  # noqa: E402
import fitz  # noqa: E402
from teambid import resume_parse  # noqa: E402


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


@unittest.skipUnless(style_tex.available(), "pdflatex isn't installed here (the online Tests workflow has it)")
class Build(unittest.TestCase):
    def test_builds_the_sample(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            pdf, pages = style_tex.compile_tex(S.SAMPLE, Path(tmp), "resume")
            self.assertTrue(pdf.exists())
            self.assertEqual(pages, 1)

    def test_latex_errors_are_reported(self):
        with self.assertRaises(ValueError):
            style_tex.compile_tex(S.SAMPLE.replace("\\end{itemize}", "", 1), Path(tempfile.mkdtemp()), "broken")

    def test_no_shell_commands_and_no_reading_outside_the_folder(self):
        tmp = Path(tempfile.mkdtemp())
        evil = S.SAMPLE.replace("\\begin{document}", "\\begin{document}\\immediate\\write18{touch pwned}", 1)
        try:
            style_tex.compile_tex(evil, tmp, "evil")
        except ValueError:
            pass
        self.assertFalse((tmp / "pwned").exists())
        with self.assertRaises(ValueError):
            style_tex.compile_tex(S.SAMPLE.replace("\\begin{document}", "\\begin{document}\\input{/etc/hostname}", 1), tmp, "read")
        # pdfTeX's own file-reading primitives: the file's bytes (hex) or its md5 must never reach the PDF
        host = Path("/etc/hostname")
        data = host.read_bytes() if host.exists() else b""
        if not data:
            return
        secrets = (data[:32].hex().upper(), hashlib.md5(data).hexdigest().upper())
        for name, prim in (("dump", r"\pdffiledump length 32 {/etc/hostname}"),
                           ("md5", r"\pdfmdfivesum file {/etc/hostname}")):
            with self.subTest(name):
                src = S.SAMPLE.replace("\\begin{document}", "\\begin{document}\\edef\\x{" + prim + "}\\x", 1)
                try:
                    pdf, _ = style_tex.compile_tex(src, tmp, name)
                except ValueError:
                    continue
                with fitz.open(pdf) as d:
                    text = "".join("".join(p.get_text() for p in d).split())
                for s in secrets:
                    self.assertNotIn(s, text)

    def test_find_then_build(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            src = Path(tmp) / "dana.tex"
            src.write_text(S.SAMPLE, encoding="utf-8")
            doc = style_tex.find(src, S.PIECES)
            self.assertEqual(doc["pages"], 1)
            files = style_tex.build(doc, {"order": {"r1": ["r1b1", "r1b0"]}}, Path(tmp), "out")
            self.assertEqual((files["pages"], files["paper"]), (1, "A4"))
            with fitz.open(files["pdf"]) as d:
                text = d[0].get_text()
            self.assertLess(text.index("Go unit tests"), text.index("cron jobs"))
            self.assertTrue(Path(files["source"]).read_text(encoding="utf-8").startswith("\\documentclass"))

    def test_extract_text_reads_a_tex_upload(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            src = Path(tmp) / "dana.tex"
            src.write_text(S.SAMPLE, encoding="utf-8")
            text, meta = resume_parse.extract_text(src)
        self.assertEqual((meta["source"], meta["file"]), ("tex", "dana.tex"))
        for b in [b for j in S.PIECES["jobs"] for b in j["bullets"]]:
            self.assertIn(key(b), key(text))        # what Claude copies from this text is found in the .tex


class BuildErrors(unittest.TestCase):
    def test_timeout(self):
        with mock.patch("teambid.style_tex.shutil.which", return_value="pdflatex"):
            with mock.patch("teambid.style_tex.subprocess.run", side_effect=subprocess.TimeoutExpired("pdflatex", 60)):
                with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                    with self.assertRaises(ValueError) as ctx:
                        style_tex.compile_tex(S.SAMPLE, Path(tmp), "x")
                    self.assertIn("longer than 60 s", str(ctx.exception))

    def test_retries_run_out(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            with mock.patch("teambid.style_tex.shutil.which", return_value="pdflatex"):
                call_count = [0]
                def mock_run(*args, **kwargs):
                    if "pdflatex" in args[0]:
                        call_count[0] += 1
                        log_file = Path(kwargs["cwd"]) / "x.log"
                        log_file.write_text(f"! LaTeX Error: File `pkg{call_count[0]}.sty' not found.", encoding="utf-8")
                        return subprocess.CompletedProcess(args[0], 1, "", "")
                    else:
                        return subprocess.CompletedProcess(args[0], 0, "", "")
                with mock.patch("teambid.style_tex.subprocess.run", side_effect=mock_run):
                    with self.assertRaises(ValueError) as ctx:
                        style_tex.compile_tex(S.SAMPLE, Path(tmp), "x")
                    self.assertTrue(str(ctx.exception).startswith("LaTeX error:"))
                    self.assertIn("not found", str(ctx.exception))
                    self.assertNotIn("made no PDF", str(ctx.exception))

    def test_latex_never_sees_the_runs_secrets(self):
        envs = {}

        def run(cmd, **kw):
            envs.setdefault(Path(cmd[0]).name, kw.get("env"))
            if cmd[0] == "pdflatex":
                log = Path(kw["cwd"]) / "x.log"
                if "tlmgr" not in envs:          # first run: a package is missing, so tlmgr runs too
                    log.write_text("! LaTeX Error: File `pkg.sty' not found.", encoding="utf-8")
                    return subprocess.CompletedProcess(cmd, 1, "", "")
                log.write_text("ok", encoding="utf-8")
                d = fitz.open()
                d.new_page()
                d.save(Path(kw["cwd"]) / "x.pdf")
                d.close()
            return subprocess.CompletedProcess(cmd, 0, "", "")
        fake = {"ANTHROPIC_API_KEY": "sk-secret", "GH_TOKEN": "gh-secret", "TEAMBID_SITE_PASSWORD": "pw-secret",
                "TEXMFHOME": "/tex/home"}
        with mock.patch.dict(os.environ, fake), \
             mock.patch("teambid.style_tex.shutil.which", return_value="pdflatex"), \
             mock.patch("teambid.style_tex.subprocess.run", side_effect=run):
            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                self.assertEqual(style_tex.compile_tex(S.SAMPLE, Path(tmp), "x")[1], 1)
        for name in ("pdflatex", "tlmgr"):        # on failure, print only the leaked names, never the whole env
            env = envs[name]
            self.assertIsNotNone(env, name)
            self.assertEqual(sorted(set(env) & {"ANTHROPIC_API_KEY", "GH_TOKEN", "TEAMBID_SITE_PASSWORD"}), [], name)
            self.assertEqual([k for k, v in env.items() if "secret" in v], [], name)
            self.assertEqual((env["openin_any"], env["openout_any"], env["shell_escape"]), ("p", "p", "f"))
            self.assertEqual(env["PATH"], os.environ["PATH"])
            self.assertEqual(env["TEXMFHOME"], "/tex/home")

    def test_relabel(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            src = Path(tmp) / "test.tex"
            src.write_text(S.SAMPLE, encoding="utf-8")
            with mock.patch("teambid.style_tex.compile_tex", side_effect=ValueError("LaTeX error: boom")):
                with self.assertRaises(ValueError) as ctx:
                    resume_parse.extract_text(src)
                self.assertIn("upload its PDF instead", str(ctx.exception))

    def test_extract_text_pdf_outside_try(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            src = Path(tmp) / "test.tex"
            src.write_text(S.SAMPLE, encoding="utf-8")
            # Mock compile_tex to return a real PDF
            def mock_compile(*args, **kwargs):
                out_dir = args[1]
                d = fitz.open()
                d.new_page()
                pdf_path = Path(out_dir) / f"{args[2]}.pdf"
                d.save(pdf_path)
                d.close()
                return pdf_path, 1
            # Mock _columns to raise an error during PDF processing
            with mock.patch("teambid.style_tex.compile_tex", side_effect=mock_compile):
                with mock.patch("teambid.resume_parse._columns", side_effect=ValueError("bad page")):
                    with self.assertRaises(ValueError) as ctx:
                        resume_parse.extract_text(src)
                    # The error should be from _columns, not wrapped in "upload its PDF instead"
                    self.assertEqual(str(ctx.exception), "bad page")
                    self.assertNotIn("upload its PDF instead", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

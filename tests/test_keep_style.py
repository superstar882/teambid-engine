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


if __name__ == "__main__":
    unittest.main()

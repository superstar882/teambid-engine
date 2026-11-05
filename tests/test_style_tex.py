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


if __name__ == "__main__":
    unittest.main()

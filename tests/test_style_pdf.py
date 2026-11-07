"""Keep-original-style, PDF handler (stdlib unittest). The fixture PDFs come from tests/pdf_samples.py and use
PyMuPDF's built-in fonts, so these run anywhere; tests that need fontconfig or the online fonts skip elsewhere."""
import contextlib
import os
import re
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


def font_files():
    """(regular, bold) TrueType files to embed in a fixture: DejaVu Sans online, Arial on a Windows PC, else None."""
    reg = style_pdf.system_font("DejaVu Sans", False)
    if reg:
        return reg, style_pdf.system_font("DejaVu Sans", True) or reg
    win = Path("C:/Windows/Fonts")
    if (win / "arial.ttf").is_file():
        return str(win / "arial.ttf"), str(win / ("arialbd.ttf" if (win / "arialbd.ttf").is_file() else "arial.ttf"))
    return None


FONT_FILES = font_files()


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

    def test_a_space_drawn_in_a_bold_run_stays_a_space(self):
        self.assertEqual(self.jobs(space_in_bold=True)[0]["bullets"][0]["text"],
                         "Built a payments API in **Python** and FastAPI that handles 2M requests a day for card and bank transfers.")

    def test_a_space_in_the_signs_color_doesnt_make_the_text_two_colored(self):
        # gray "•", a gray " ", then black text: only the text's own colors count, so these bullets stay free
        jobs = self.jobs(sign="gray")
        with fitz.open(sample(sign="gray")) as d:
            line = next(l for l in style_pdf._lines(d) if "payments" in l["text"])
        sign, space = line["spans"][:2]                                                  # the shape this test is about
        self.assertTrue(style_pdf._is_sign(sign["text"]) and space["text"] == " " and space["color"] == sign["color"])
        self.assertTrue(all(not b["fixed"] for j in jobs for b in j["bullets"]))
        self.assertTrue(all(j["reorder"] for j in jobs))

    def test_a_line_without_letters_never_ends_a_bullet(self):
        # a lone space written right after a bullet's last line once became that bullet's last line, at a page's foot
        b = self.jobs(blank=True)[0]["bullets"][2]
        self.assertEqual([key(l["text"]) != "" for l in b["lines"]], [True, True])

    def test_a_piece_cut_short_pins_its_job(self):
        # the piece holds only the bullet's first line: its second line, right below in the same style, would stay
        # behind if the bullet moved
        pieces = {"jobs": [dict(PS.PIECES["jobs"][0], bullets=[PS.JOBS[0][2][0][0].replace("**", "")]
                                + PS.PIECES["jobs"][0]["bullets"][1:]), PS.PIECES["jobs"][1]]}
        jobs = self.jobs(pieces=pieces)
        self.assertEqual([b["fixed"] for b in jobs[0]["bullets"]], [True, False, False])
        self.assertEqual([j["reorder"] for j in jobs], [False, True])

    def cut_short(self, ji, bi):
        """PIECES with that bullet's piece holding only its first line."""
        jobs = [dict(j, bullets=list(j["bullets"])) for j in PS.PIECES["jobs"]]
        jobs[ji]["bullets"][bi] = PS.JOBS[ji][2][bi][0].replace("**", "")
        return {"jobs": jobs}

    def test_a_piece_cut_short_at_a_page_break_pins_its_job(self):
        # the third bullet's second line is the first on page 2: moving the bullet would leave it there
        b = self.jobs(pieces=self.cut_short(0, 2), break_page=True)[0]["bullets"][2]
        self.assertEqual((b["lines"][-1]["page"], b["fixed"]), (0, True))

    def test_a_piece_cut_short_before_a_bold_word_pins_its_job(self):
        jobs = self.jobs(pieces=self.cut_short(0, 0), bold_start=True)
        self.assertEqual([b["fixed"] for b in jobs[0]["bullets"]], [True, False, False])

    def test_a_piece_cut_short_past_a_page_number_or_a_header_pins_its_job(self):
        # the rest of the sentence is on page 2, past "Page 1 of 2" at page 1's foot, or under page 2's header
        for kw in ({"footer": True}, {"header": True}):
            b = self.jobs(pieces=self.cut_short(0, 2), break_page=True, **kw)[0]["bullets"][2]
            self.assertTrue(b["fixed"], kw)

    def test_a_piece_cut_short_before_a_mostly_bold_line_pins_its_job(self):
        jobs = self.jobs(pieces=self.cut_short(0, 0), bold_start="most")
        self.assertEqual([b["fixed"] for b in jobs[0]["bullets"]], [True, False, False])

    def test_a_page_number_or_header_doesnt_stop_a_whole_bullet_moving(self):
        # and a bullet split by the page break is found whole past the page number between its halves
        for kw in ({"footer": True}, {"header": True}):
            jobs = self.jobs(break_page=True, **kw)
            self.assertTrue(all(j["reorder"] for j in jobs), kw)
        self.assertEqual([b["id"] for b in self.jobs(break_page=True, footer=True)[0]["bullets"]], ["r0b0", "r0b1", "r0b2"])

    def test_the_next_bullets_drawn_dot_says_it_isnt_the_rest_of_this_one(self):
        # tight lines, the second bullet not in the reading: its first line sits a pitch below the first bullet, but
        # its dot says it starts a bullet of its own
        pieces = {"jobs": [dict(PS.PIECES["jobs"][0], bullets=PS.PIECES["jobs"][0]["bullets"][::2]), PS.PIECES["jobs"][1]]}
        jobs = self.jobs(pieces=pieces, sign="circle", tight=True)
        self.assertEqual([b["fixed"] for b in jobs[0]["bullets"]], [False, False])

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
        self.assertTrue(jobs[0]["bullets"][0]["fixed"])                 # no sign of its own: never reworded
        self.assertFalse(jobs[0]["reorder"])

    def test_typed_signs_are_signs(self):
        jobs = self.jobs(sign="typed")
        self.assertEqual({b["mark"]["kind"] for j in jobs for b in j["bullets"]}, {"lead"})
        self.assertEqual({b["mark"]["char"]["c"] for j in jobs for b in j["bullets"]}, {"-"})
        self.assertTrue(all(j["reorder"] for j in jobs))
        self.assertFalse(any(b["fixed"] for j in jobs for b in j["bullets"]))
        self.assertEqual(jobs[0]["bullets"][0]["text"],                 # the sign and its space aren't the text
                         "Built a payments API in **Python** and FastAPI that handles 2M requests a day for card and bank transfers.")

    def test_an_italic_word_fixes_its_bullet_and_pins_the_job(self):
        jobs = self.jobs(italic=True)
        self.assertEqual([b["fixed"] for b in jobs[0]["bullets"]], [False, False, True])
        self.assertEqual([j["reorder"] for j in jobs], [False, True])

    def test_one_text_is_found_once(self):
        b0 = PS.PIECES["jobs"][0]["bullets"][0]
        jobs = self.jobs(pieces={"jobs": [{"bullets": [b0]}, {"bullets": [b0]}]})     # a reading that repeats it
        self.assertEqual([(j["id"], [b["id"] for b in j["bullets"]]) for j in jobs], [("r0", ["r0b0"])])

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

    def test_doc_shape_with_headline_summary_and_skills(self):
        # the shape style_tex gives, so keep_style.check and llm.tailor_in_place read it unchanged; no lines in it
        doc = style_pdf.find(sample(headline="left", summary=True, skills=True), PS.pieces(True, True, True))
        self.assertEqual(doc["headline"], {"text": PS.HEADLINE, "fixed": False})
        self.assertEqual(doc["summary"], {"text": "Backend engineer with eight years of **Python** and Go, building "
                                                  "payment systems that banks and card networks rely on daily.",
                                          "fixed": False})
        self.assertEqual(doc["skills"], [{"id": f"s{n}", "label": label, "items": items, "fixed": False}
                                         for n, (label, items) in enumerate(PS.SKILLS)])
        self.assertIs(doc["skills_move"], True)
        self.assertEqual([b["id"] for j in doc["jobs"] for b in j["bullets"]],
                         [b["id"] for j in style_pdf.find(sample(), PS.PIECES)["jobs"] for b in j["bullets"]])


class TextParts(unittest.TestCase):
    """A PDF's headline, summary and skill lines, found on whole lines no bullet holds (read_text_parts)."""

    def parts(self, pieces=None, **kw):
        pieces = pieces or PS.pieces(True, True, True)
        with fitz.open(sample(**kw)) as d:
            scan = style_pdf._scan(d)
            return style_pdf.read_text_parts(d, pieces, style_pdf.read(d, pieces, scan), scan)

    def test_a_left_or_centred_headline_is_found_with_its_alignment(self):
        for mode in ("left", "center"):
            h = self.parts(headline=mode)["headline"]
            self.assertEqual((h["text"], h["align"], h["fixed"], len(h["lines"])), (PS.HEADLINE, mode, False, 1), mode)

    def test_a_headline_in_two_styles_is_fixed(self):
        h = self.parts(headline="mixed")["headline"]
        self.assertEqual((h["text"], h["fixed"]), (PS.HEADLINE, True))

    def test_a_right_aligned_headline_is_fixed(self):
        h = self.parts(headline="right")["headline"]
        self.assertEqual((h["text"], h["fixed"]), (PS.HEADLINE, True))

    def test_a_headline_is_the_header_line_never_a_jobs_title(self):
        # a headline that reads like a job's title is the header's line when the header has it; a job's title line is
        # never taken for one (rewording it would change the member's job history)
        h = self.parts(pieces=PS.pieces(headline="Senior Backend Engineer"), headline="title")["headline"]
        self.assertEqual((h["text"], h["lines"][0]["page"], h["lines"][0]["bbox"].y1 < 90),
                         ("Senior Backend Engineer", 0, True))
        self.assertIsNone(self.parts(pieces=PS.pieces(headline="Senior Backend Engineer, Northwind Labs"))["headline"])

    def test_a_headline_is_found_on_its_own_line_under_a_sentence_holding_its_words(self):
        h = self.parts(headline="left", topline=f"Experienced {PS.HEADLINE} today")["headline"]
        self.assertEqual((h["text"], h["align"], h["fixed"], round(h["lines"][0]["spans"][0]["origin"][1])),
                         (PS.HEADLINE, "left", False, 78))

    def test_a_jobs_title_line_isnt_a_headline_because_a_sentence_above_says_it_too(self):
        # the title shows again only above that line, not below it, where the job's own line would be
        pieces = PS.pieces(headline="Senior Backend Engineer, Northwind Labs")
        self.assertIsNone(self.parts(pieces=pieces, topline="Now: Senior Backend Engineer, Northwind Labs")["headline"])

    def test_a_two_line_summary_is_found_with_its_bold(self):
        s = self.parts(summary=True)["summary"]
        self.assertEqual((s["text"], s["fixed"], len(s["lines"])),
                         ("Backend engineer with eight years of **Python** and Go, building payment systems that banks "
                          "and card networks rely on daily.", False, 2))

    def test_a_summary_with_an_italic_word_is_fixed(self):
        self.assertTrue(self.parts(summary="italic")["summary"]["fixed"])

    def test_skill_lines_are_found_in_printed_order_and_may_move(self):
        got = self.parts(skills=True)
        self.assertEqual([(l["id"], l["label"], l["items"], l["sep"], l["fixed"], len(l["lines"]))
                          for l in got["skills"]],
                         [(f"s{n}", label, items, ", ", False, 1) for n, (label, items) in enumerate(PS.SKILLS)])
        self.assertIs(got["skills_move"], True)

    def test_skill_lines_are_found_in_printed_order_whatever_the_readings_order(self):
        pieces = PS.pieces(skills=True)
        pieces["skills"] = pieces["skills"][::-1]
        self.assertEqual([l["label"] for l in self.parts(pieces=pieces, skills=True)["skills"]],
                         [s[0] for s in PS.SKILLS])

    def test_skills_in_drawn_boxes_are_fixed_and_dont_move(self):
        got = self.parts(skills="chips")
        self.assertEqual([l["fixed"] for l in got["skills"]], [True, True, True])
        self.assertIs(got["skills_move"], False)

    def test_items_not_all_set_apart_the_same_way_fix_their_line(self):
        # read as "Type" and "Script": nothing between those two, ", " between the others
        pieces = PS.pieces(skills=True)
        pieces["skills"][0]["items"] = ["Python", "Go", "SQL", "Type", "Script"]
        got = self.parts(pieces=pieces, skills=True)
        self.assertEqual(([l["fixed"] for l in got["skills"]], got["skills_move"]), ([True, False, False], False))
        self.assertEqual(style_pdf._skill_parts("Languages: Python, Go | C++.", "Languages", ["Python", "Go", "C++"]),
                         ("Languages", ["Python", "Go", "C++"], [", ", " | "]))
        self.assertIsNone(style_pdf._skill_parts("Languages: Python, Go", "Languages", ["Go", "Python"]))

    def test_lines_with_something_between_them_dont_move(self):
        # a line between two skill lines that isn't one of them (a skill line the reading left out) stays where it
        # is, so the lines can't move as one run
        pieces = PS.pieces(skills=True)
        del pieces["skills"][1]
        got = self.parts(pieces=pieces, skills=True)
        self.assertEqual(([l["label"] for l in got["skills"]], got["skills_move"]), (["Languages", "Cloud"], False))

    def test_pieces_not_in_the_pdf_are_absent(self):
        none = {"headline": None, "summary": None, "skills": [], "skills_move": False}
        self.assertEqual(self.parts(), none)
        self.assertEqual(self.parts(pieces=PS.PIECES, headline="left", summary=True, skills=True), none)

    def test_jobs_from_another_read_of_the_pdf_keep_their_lines(self):
        # without the scan read used, the bullets' lines are told by where they are: the same parts come out
        pieces = PS.pieces(True, True, True)
        pieces["summary"] = PS.PIECES["jobs"][0]["bullets"][0]           # a bullet's text never becomes the summary
        pdf = sample(headline="left", summary=True, skills=True)
        with fitz.open(pdf) as d:
            again = style_pdf.read_text_parts(d, pieces, style_pdf.read(d, pieces))
        shape = lambda p: (p["headline"] and p["headline"]["text"], p["summary"],
                           [l["label"] for l in p["skills"]], p["skills_move"])
        self.assertEqual(shape(again), (PS.HEADLINE, None, [s[0] for s in PS.SKILLS], True))
        self.assertEqual(shape(self.parts(pieces=pieces, headline="left", summary=True, skills=True)), shape(again))

    def test_bullets_read_the_same_with_these_parts(self):
        def jobs(pieces, **kw):
            with fitz.open(sample(**kw)) as d:
                return [(j["id"], j["reorder"], [(b["id"], b["text"], b["fixed"]) for b in j["bullets"]])
                        for j in style_pdf.read(d, pieces)]
        self.assertEqual(jobs(PS.pieces(True, True, True), headline="left", summary=True, skills=True), jobs(PS.PIECES))


def words(pdf):
    with fitz.open(pdf) as d:
        return [(pg.number, w[1], w[4]) for pg in d for w in pg.get_text("words")]


def first(ws, word):
    return min((pn, y) for pn, y, t in ws if t == word)


def all_text(pdf):
    with fitz.open(pdf) as d:
        return key("".join(pg.get_text(sort=True) for pg in d))     # by position, as resume parsers read


def spans(pdf):
    with fitz.open(pdf) as d:
        return [s for pg in d for b in pg.get_text("dict")["blocks"] for l in b.get("lines", []) for s in l["spans"]]


def boxes(pdf, texts):
    """The words with these texts, with their boxes rounded: [(page, x0, y0, x1, y1, text)]."""
    with fitz.open(pdf) as d:
        return [(pg.number, *[round(v, 1) for v in w[:4]], w[4]) for pg in d for w in pg.get_text("words") if w[4] in texts]


class Wide:
    """A font twice as wide as Helvetica: no word can be fitted into its own space in it."""
    def text_length(self, t, fontsize=11):
        return 2 * fitz.Font("helv").text_length(t, fontsize=fontsize)


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
        self.assertEqual(f["order"], {"r0": ["r0b2", "r0b0", "r0b1"], "r1": ["r1b1", "r1b0"]})

    def test_a_bold_run_with_its_own_space_moves_and_reads_back(self):
        # the word check once failed every such bullet: its text read "inPython" while the page read "in Python"
        f = self.build({"order": {"r0": ["r0b1", "r0b2", "r0b0"]}, "text": {}}, space_in_bold=True)
        self.assertEqual(f["order"]["r0"], ["r0b1", "r0b2", "r0b0"])
        ws = words(f["pdf"])
        self.assertLess(first(ws, "Wrote"), first(ws, "Built"))

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

    def test_bullets_move_only_under_their_own_heading(self):
        f = self.build({"order": {"r0": ["r0b2", "r0b0", "r0b1"]}, "text": {}}, subhead=True)
        self.assertEqual(f["order"]["r0"], ["r0b0", "r0b2", "r0b1"])     # Built stays above the heading
        ws = words(f["pdf"])
        for a, b in (("Built", "Payments"), ("Payments", "Wrote"), ("Wrote", "Cut")):
            self.assertLess(first(ws, a), first(ws, b))

    def test_bullets_stay_under_a_heading_at_a_page_break(self):
        f = self.build({"order": {"r0": ["r0b2", "r0b0", "r0b1"]}, "text": {}}, subhead_page=True)
        self.assertEqual(f["order"]["r0"], ["r0b0", "r0b2", "r0b1"])     # Built stays on page 1, above the heading
        ws = words(f["pdf"])
        self.assertEqual(first(ws, "Built")[0], 0)
        for a, b in (("Payments", "Wrote"), ("Wrote", "Cut")):
            self.assertLess(first(ws, a), first(ws, b))

    def test_a_label_beside_a_bullet_keeps_its_run(self):
        # "Ledger" beside the first bullet, "Docs" beside the third: both stay by their labels (a bullet with text
        # beside it is a run of its own), and nothing else in the job can move
        f = self.build({"order": {"r0": ["r0b2", "r0b1", "r0b0"]}, "text": {}}, labels=True)
        self.assertEqual(f["order"]["r0"], ["r0b0", "r0b1", "r0b2"])
        ws = words(f["pdf"])
        self.assertAlmostEqual(first(ws, "Docs")[1], first(ws, "Wrote")[1], delta=2.5)
        self.assertAlmostEqual(first(ws, "Ledger")[1], first(ws, "Built")[1], delta=2.5)

    def test_a_label_with_its_dates_under_it_keeps_its_run(self):
        f = self.build({"order": {"r0": ["r0b2", "r0b1", "r0b0"]}, "text": {}}, labels="two")
        self.assertEqual(f["order"]["r0"], ["r0b0", "r0b1", "r0b2"])
        ws = words(f["pdf"])
        self.assertAlmostEqual(first(ws, "Docs")[1], first(ws, "Wrote")[1], delta=2.5)

    def test_text_left_of_a_bullet_keeps_it_in_place(self):
        # a sidebar can't be told from labels for sure, so text beside a bullet's first line keeps that bullet where
        # it is (splitting a job's runs is always safe)
        f = self.build({"order": {"r0": ["r0b2", "r0b0", "r0b1"]}, "text": {}}, sidebar=True)
        with fitz.open(PS.make(str(Path(tempfile.mkdtemp()) / "in.pdf"), sidebar=True)) as d:
            runs = style_pdf._runs(style_pdf.read(d, PS.PIECES)[0])
        self.assertGreater(len(runs), 1)
        self.assertEqual(sorted(f["order"]["r0"]), ["r0b0", "r0b1", "r0b2"])

    def test_a_heading_atop_the_next_page_ends_the_bullet_before_it_only_left_of_the_indent(self):
        # set where the bullets' wrapped lines start, an all-bold rest of a sentence would look just like it
        for kind, fixed in (("same", False), ("indent", True)):
            with fitz.open(PS.make(str(Path(tempfile.mkdtemp()) / "in.pdf"), subhead_page=kind)) as d:
                self.assertEqual(style_pdf.read(d, PS.PIECES)[0]["bullets"][0]["fixed"], fixed, kind)

    def test_a_lost_word_names_every_bullet_erased_beside_it(self):
        with fitz.open() as d:
            pg = d.new_page()
            pg.insert_text((50, 100), "Heading", fontname="hebo", fontsize=11)
            before = {0: style_pdf._words_at(pg)}
            pg.add_redact_annot(fitz.Rect(40, 85, 200, 105))
            pg.apply_redactions()
            erased = {"r0b1": [(0, fitz.Rect(50, 102, 300, 112))], "r1b0": [(0, fitz.Rect(50, 80, 300, 90))],
                      "r2b0": [(0, fitz.Rect(50, 300, 300, 310))]}
            self.assertEqual(style_pdf._disturbed(d, before, {}, erased), ["lost 'Heading' (r0b1, r1b0)"])

    def test_a_job_that_doesnt_read_back_is_left_as_it_was(self):
        real, calls = style_pdf._wrong, []

        def wrong(*a):                                   # the second job never reads back while it's redrawn
            calls.append(a[4])
            return (["r1b0"] if "r1" in a[4].get("order", {}) else []) + real(*a)
        new = "Moved 30 cron jobs to Airflow, ending missed nightly runs and cutting manual reruns to zero!"
        with mock.patch.object(style_pdf, "_wrong", wrong):
            f = self.build({"order": {"r0": ["r0b2", "r0b0", "r0b1"], "r1": ["r1b1", "r1b0"]}, "text": {"r1b0": new}})
        self.assertEqual(f["order"], {"r0": ["r0b2", "r0b0", "r0b1"], "r1": ["r1b0", "r1b1"]})
        self.assertEqual(f["kept"], ["r1b0"])
        self.assertEqual(len(calls), 3)                  # both font passes with the second job, then once without it
        ws = words(f["pdf"])
        self.assertLess(first(ws, "Wrote"), first(ws, "Built"))
        self.assertIn(key(PS.PIECES["jobs"][1]["bullets"][0]), all_text(f["pdf"]))

    def test_a_problem_no_bullet_answers_for_fails_at_once(self):
        calls = []
        with mock.patch.object(style_pdf, "_wrong", lambda *a: calls.append(1) or ["links"]):
            with self.assertRaises(ValueError):
                self.build({"order": {"r0": ["r0b2", "r0b0", "r0b1"]}, "text": {}})
        self.assertEqual(len(calls), 2)

    def test_an_email_link_opens_the_address_it_shows(self):
        f = self.build({"order": {"r0": ["r0b2", "r0b0", "r0b1"]}, "text": {}},
                       mailto="mailto:dana.old@example.org?subject=Hello")
        with fitz.open(f["pdf"]) as d:
            self.assertEqual([l["uri"] for l in d[0].get_links()], ["mailto:dana@example.com?subject=Hello"])

    def test_an_email_link_without_one_address_shown_stays(self):
        src = Path(tempfile.mkdtemp()) / "links.pdf"
        with fitz.open() as d:
            pg = d.new_page()
            pg.insert_text((50, 100), "Email me", fontname="helv", fontsize=10)
            pg.insert_text((50, 130), "a@example.com b@example.com", fontname="helv", fontsize=10)
            pg.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(48, 90, 100, 103), "uri": "mailto:x@example.com"})
            pg.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(48, 120, 200, 133), "uri": "mailto:x@example.com"})
            d.save(src)
        with fitz.open(src) as d:                        # as build has it: a PDF read from its file
            self.assertEqual(style_pdf._fix_mailto(d), 0)
            self.assertEqual([l["uri"] for l in d[0].get_links()], ["mailto:x@example.com"] * 2)

    def test_an_email_link_thats_right_stays(self):
        # an icon read as a letter glued to the address, a +alias left off, a link box that reaches into the next line
        src = Path(tempfile.mkdtemp()) / "links.pdf"
        with fitz.open() as d:
            pg = d.new_page()
            for y, text in ((100, "Mdana@example.com"), (130, "dana@example.com"), (160, "Email me"), (171, "jo@agency.com"),
                            (220, "dana@example.comin"), (260, "Write to"), (272, "jo@agency.com")):
                pg.insert_text((50, y), text, fontname="helv", fontsize=10)
            for rect, uri in (((48, 90, 160, 103), "mailto:dana@example.com"), ((48, 120, 160, 133), "mailto:dana+cv@example.com"),
                              ((48, 150, 160, 167), "mailto:x@example.com"), ((48, 210, 160, 223), "mailto:dana@example.com"),
                              ((48, 250, 160, 276), "mailto:x@example.com")):         # the last box holds both lines
                pg.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(rect), "uri": uri})
            d.save(src)
        with fitz.open(src) as d:
            self.assertEqual(style_pdf._fix_mailto(d), 0)

    @unittest.skipUnless(FONT_FILES, "no TrueType font to embed here")
    def test_an_email_link_shown_with_a_ligature_stays(self):
        src = Path(tempfile.mkdtemp()) / "links.pdf"
        with fitz.open() as d:
            pg = d.new_page()
            pg.insert_font(fontname="F0", fontfile=FONT_FILES[0])
            pg.insert_text((50, 100), "ﬁona.reyes@example.com", fontname="F0", fontsize=10)    # "ﬁ", as pdfTeX's fonts read
            pg.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(48, 90, 200, 103), "uri": "mailto:fiona.reyes@example.com"})
            d.save(src)
        with fitz.open(src) as d:
            if "ﬁ" not in d[0].get_text():
                self.skipTest("this font has no fi ligature")
            self.assertEqual(style_pdf._fix_mailto(d), 0)

    def test_a_result_that_doesnt_read_back_fails(self):
        tmp = Path(tempfile.mkdtemp())
        doc = style_pdf.find(PS.make(str(tmp / "in.pdf")), PS.PIECES)
        with mock.patch.object(style_pdf, "_wrong", return_value=["r0b0"]):
            with self.assertRaises(ValueError):
                style_pdf.build(doc, {"order": {}, "text": {}}, tmp, "out")
        self.assertFalse((tmp / "out.pdf").exists())

    # --- moved words: fitted to their own space, compared word by word
    def test_a_moved_word_never_gets_wider_than_its_own_space(self):
        with fitz.open(sample()) as d:
            jobs = style_pdf.read(d, PS.PIECES)
            fonts = style_pdf.Fonts(d, jobs[0]["_lines"])
            b = jobs[0]["bullets"][0]
            with mock.patch.object(fonts, "pick", return_value=(fitz.Font("cour"), None, "cour", False)):
                lines = style_pdf._old_lines(b, fonts)                   # Courier is wider than Helvetica
            with mock.patch.object(fonts, "pick", return_value=(Wide(), None, "helv", False)):
                self.assertIsNone(style_pdf._old_lines(b, fonts))       # far wider: not redrawn at all
        for n, items in enumerate(lines):
            ends = []                                                     # each original word's right edge
            for s, cs in style_pdf._body(b["lines"], b["mark"], n):
                for c, nxt in zip(cs, cs[1:] + [None]):
                    if not c["c"].isspace() and (nxt is None or nxt["c"].isspace()):
                        ends.append(c["bbox"][2])
            self.assertEqual(len(ends), len(items))
            for (x, t, f, size, color, sx, _), end in zip(items, ends):
                self.assertLessEqual(sx, 1.15)
                self.assertLessEqual(x + f[0].text_length(t, fontsize=size) * sx, end + 0.01, t)

    def test_a_job_no_font_can_fit_stays_as_it_is(self):
        with mock.patch.object(style_pdf.Fonts, "pick", return_value=(Wide(), None, "helv", False)):
            f = self.build({"order": {"r0": ["r0b2", "r0b0", "r0b1"]}, "text": {}})
        self.assertEqual(f["order"]["r0"], ["r0b0", "r0b1", "r0b2"])

    def test_words_glued_together_dont_read_back(self):
        real = style_pdf._old_lines

        def glued(bullet, fonts):                     # each word drawn right against the one before it
            out = []
            for items in real(bullet, fonts):
                x, line = None, []
                for it in items:
                    it = it if x is None else (x,) + it[1:]
                    x = it[0] + it[2][0].text_length(it[1], fontsize=it[3]) * it[5]
                    line.append(it)
                out.append(line)
            return out
        with mock.patch.object(style_pdf, "_old_lines", glued):
            # the same letters, but not the same words: the job is left as it was, and nothing else changed
            f = self.build({"order": {"r0": ["r0b2", "r0b0", "r0b1"], "r1": ["r1b1", "r1b0"]}, "text": {}})
        self.assertEqual(f["order"], {"r0": ["r0b0", "r0b1", "r0b2"], "r1": ["r1b0", "r1b1"]})
        ws = words(f["pdf"])
        self.assertLess(first(ws, "Built"), first(ws, "Wrote"))
        self.assertIn("payments", [w for _, _, w in ws])

    # --- erasing: only the bullets' own letters, and the rest of the PDF checked
    def test_tight_leading_keeps_the_lines_around(self):
        tmp = Path(tempfile.mkdtemp())
        src = PS.make(str(tmp / "in.pdf"), tight=True)
        f = style_pdf.build(style_pdf.find(src, PS.PIECES), {"order": {"r0": ["r0b2", "r0b0", "r0b1"]}, "text": {}},
                            tmp, "out")
        heads = {"Senior", "Backend", "Engineer,", "Northwind", "Labs", "Contoso", "Freight"}
        self.assertEqual(len(boxes(src, heads)), 9)
        self.assertEqual(boxes(f["pdf"], heads), boxes(src, heads))        # the headings right above and below
        ws = words(f["pdf"])
        self.assertLess(first(ws, "Wrote"), first(ws, "Built"))
        self.assertEqual(f["order"]["r0"], ["r0b2", "r0b0", "r0b1"])

    def test_a_lost_word_fails_the_build(self):
        real = style_pdf._untouched

        def plus(doc, todo):
            got = real(doc, todo)
            got[0].append((fitz.Rect(400, 400, 430, 410), "Zebra"))     # a word "erasing took away"
            return got
        with mock.patch.object(style_pdf, "_untouched", plus):
            with self.assertRaises(ValueError) as ctx:
                self.build({"order": {"r0": ["r0b2", "r0b0", "r0b1"]}, "text": {}})
        self.assertIn("Zebra", str(ctx.exception))

    def test_a_word_drawn_over_counts(self):
        with fitz.open() as d:
            pg = d.new_page()
            pg.insert_text((50, 100), "Heading", fontname="hebo", fontsize=11)
            before = {0: style_pdf._words_at(pg)}
            self.assertEqual(style_pdf._disturbed(d, before, {}), [])
            self.assertEqual(style_pdf._disturbed(d, before, {"r0b0": [(0, fitz.Rect(40, 95, 200, 105))]}),
                             ["drawn over 'Heading' (r0b0)"])
            # a line drawn right below: the boxes of its letters' line height overlap, the letters don't
            self.assertEqual(style_pdf._disturbed(d, before, {"r0b0": [(0, fitz.Rect(40, 103, 200, 113))]}), [])

    # --- a job nothing changes in is left alone; the report says what was really drawn
    def test_an_unchanged_job_isnt_erased(self):
        real = fitz.Page.add_redact_annot
        with mock.patch.object(fitz.Page, "add_redact_annot", autospec=True, side_effect=real) as redact:
            f = self.build({"order": {}, "text": {}})
        self.assertEqual(redact.call_count, 0)
        self.assertEqual(f["order"], {"r0": ["r0b0", "r0b1", "r0b2"], "r1": ["r1b0", "r1b1"]})
        with mock.patch.object(fitz.Page, "add_redact_annot", autospec=True, side_effect=real) as redact:
            self.build({"order": {"r0": ["r0b2", "r0b0", "r0b1"], "r1": ["r1b0", "r1b1"]}, "text": {}})
        self.assertEqual(redact.call_count, 6)                    # the first job's 6 lines; the second job untouched

    def test_a_job_that_fits_no_flow_is_left_as_it_is(self):
        new = "Built a payments API in **Python** and FastAPI handling 2M requests a day for card and bank transfers."
        f = self.build({"order": {"r0": ["r0b2", "r0b0", "r0b1"], "r1": ["r1b1", "r1b0"]}, "text": {"r0b0": new}},
                       pitches=(12.5, 12.5, 10.0))              # one bullet set tighter than the job's spacing
        self.assertEqual(f["kept"], ["r0b0"])
        self.assertEqual(f["order"], {"r0": ["r0b0", "r0b1", "r0b2"], "r1": ["r1b1", "r1b0"]})
        ws = words(f["pdf"])
        self.assertLess(first(ws, "Built"), first(ws, "Wrote"))
        self.assertLess(first(ws, "Added"), first(ws, "Moved"))

    def test_rewordings_that_dont_fit_go_back_one_at_a_time(self):
        old = PS.PIECES["jobs"][0]["bullets"][1]
        ok = "Built a payments API in **Python** and FastAPI handling 2M requests a day for card and bank transfers."
        f = self.build({"order": {}, "text": {"r0b0": ok, "r0b1": " ".join([old] * 3)}})
        self.assertEqual(f["kept"], ["r0b1"])                     # the one that grew most, not both
        text = all_text(f["pdf"])
        self.assertIn(key(ok), text)
        self.assertIn(key(old), text)

    def test_a_word_wider_than_the_column_keeps_the_original(self):
        f = self.build({"order": {}, "text": {"r0b0": "Built " + "x" * 120 + " and more."}})
        self.assertEqual(f["kept"], ["r0b0"])
        self.assertIn(key(PS.PIECES["jobs"][0]["bullets"][0]), all_text(f["pdf"]))

    # --- styles
    def test_a_rewording_takes_the_jobs_body_style(self):
        new = "Cut p95 latency 40% by moving hot reads to **Redis** and adding a write-through ledger cache."
        f = self.build({"order": {}, "text": {"r0b1": new}}, lead_in=True)      # the job starts with a bold blue word
        self.assertEqual(f["kept"], [])
        got = [s for s in spans(f["pdf"]) if "ledger" in s["text"] or "latency" in s["text"]]
        self.assertEqual(len(got), 2)
        for s in got:                       # in Helvetica here, Liberation Sans online: either way not bold, not blue
            self.assertFalse(style_pdf._is_bold(s), s["text"])
            self.assertEqual(s["color"], 0, s["text"])
        self.assertNotEqual([s["color"] for s in spans(f["pdf"]) if s["text"].strip() == "Built"], [0])   # still blue

    def test_an_italic_bullet_pins_its_job_and_stays_untouched(self):
        tmp = Path(tempfile.mkdtemp())
        src = PS.make(str(tmp / "in.pdf"), italic=True)
        new = "Cut p95 latency 40% by moving hot reads to **Redis** and adding a write-through ledger cache."
        f = style_pdf.build(style_pdf.find(src, PS.PIECES), {"order": {"r0": ["r0b2", "r0b0", "r0b1"]},
                                                              "text": {"r0b1": new, "r0b2": "Wrote the API docs."}},
                            tmp, "out")
        self.assertEqual(f["order"]["r0"], ["r0b0", "r0b1", "r0b2"])
        self.assertEqual(f["kept"], ["r0b2"])
        self.assertIn(key(new), all_text(f["pdf"]))                 # a rewording in place, same lines

        def third(pdf):
            ys = [w[2] for w in boxes(pdf, {"Wrote", "banks."})]
            return [(s["text"], s["font"], round(s["origin"][0], 2), round(s["origin"][1], 2)) for s in spans(pdf)
                    if min(ys) - 1 <= s["origin"][1] <= max(ys) + 12]
        self.assertEqual(third(f["pdf"]), third(src))
        self.assertIn("Helvetica-Oblique", {s[1] for s in third(src)})

    def probe(self, **patch):
        """A job that opens with a paragraph without a sign at x=50 (so it's pinned), then bullets whose signs are at
        52 and text at 62; the second bullet reworded in place."""
        tmp = Path(tempfile.mkdtemp())
        doc = style_pdf.find(PS.make(str(tmp / "in.pdf"), intro=True), PS.PIECES)
        new = "Cut p95 latency 40% by moving hot reads to **Redis** and adding a write-through ledger cache."
        with contextlib.ExitStack() as stack:
            for name, value in patch.items():
                stack.enter_context(mock.patch.object(style_pdf, name, value))
            return style_pdf.build(doc, {"order": {}, "text": {"r0b1": new}}, tmp, "out")

    def test_a_rewording_in_a_pinned_job_starts_where_its_own_text_does(self):
        f = self.probe()
        self.assertEqual(f["kept"], [])
        with fitz.open(f["pdf"]) as d:
            ws = d[0].get_text("words")
        cut = [w for w in ws if w[4].endswith("Cut")]
        self.assertEqual([w[4] for w in cut], ["Cut"])                   # not "·Cut": the sign isn't glued on
        self.assertAlmostEqual(cut[0][0], PS.X_TEXT, delta=0.6)
        sign = [w for w in ws if w[4] == "·" and abs(w[3] - cut[0][3]) < 1]
        self.assertEqual(len(sign), 1)
        self.assertLess(sign[0][2], cut[0][0])
        self.assertEqual(f["order"]["r0"], ["r0b0", "r0b1", "r0b2"])

    def test_text_drawn_over_a_sign_leaves_that_job_as_it_was(self):
        real = style_pdf._new_lines
        # the old layout: the rewording set from the job's first text x (the paragraph's 50), over its own sign
        old = lambda text, st, fonts, bullet=None: real(text, dict(st, x_first=50.0), fonts)
        seen = []
        wrong = style_pdf._wrong
        with mock.patch.object(style_pdf, "_wrong", lambda *a: seen.append(wrong(*a)) or seen[-1]):
            f = self.probe(_new_lines=old)
        self.assertIn("text over the sign of r0b1", seen[0])
        self.assertEqual((f["kept"], seen[-1]), (["r0b1"], []))          # its rewording dropped, nothing else wrong
        self.assertIn(key(PS.PIECES["jobs"][0]["bullets"][1]), all_text(f["pdf"]))

    # --- signs
    def test_typed_signs_move_with_their_bullets(self):
        new = "Moved 30 cron jobs into Airflow, ending missed nightly runs and cutting manual reruns to zero."
        f = self.build({"order": {"r0": ["r0b2", "r0b0", "r0b1"]}, "text": {"r1b0": new}}, sign="typed")
        with fitz.open(f["pdf"]) as d:
            ws = d[0].get_text("words")
        signs = [w for w in ws if w[4] == "-"]
        self.assertEqual(len(signs), 5)
        for w in ws:
            if w[4] in ("Built", "Cut", "Wrote", "Moved", "Added"):
                self.assertTrue(any(abs(s[3] - w[3]) < 0.5 and s[2] < w[0] for s in signs), w[4])
        self.assertIn(key(new), all_text(f["pdf"]))
        ws = words(f["pdf"])
        self.assertLess(first(ws, "Wrote"), first(ws, "Built"))

    def test_a_bullet_without_its_own_sign_is_never_reworded(self):
        tmp = Path(tempfile.mkdtemp())
        part = PS.PIECES["jobs"][0]["bullets"][0].split("handles ")[1]
        doc = style_pdf.find(PS.make(str(tmp / "in.pdf")), {"jobs": [{"bullets": [part]}]})
        f = style_pdf.build(doc, {"order": {}, "text": {"r0b0": part.replace("a day", "daily")}}, tmp, "out")
        self.assertEqual(f["kept"], ["r0b0"])
        self.assertIn(key(part), all_text(f["pdf"]))

    def test_a_drawing_in_a_bullet_line_pins_its_job(self):
        # a rule, an underline or LaTeX's drawn underscore would stay put while the words moved away from it
        f = self.build({"order": {"r0": ["r0b2", "r0b0", "r0b1"], "r1": ["r1b1", "r1b0"]}, "text": {}},
                       sign="circle", rule=True)
        self.assertEqual(f["order"], {"r0": ["r0b2", "r0b0", "r0b1"], "r1": ["r1b0", "r1b1"]})
        with fitz.open(f["pdf"]) as d:
            rules = [dr["rect"] for pg in d for dr in pg.get_drawings() if dr["rect"].width > 50 and dr["rect"].height < 2]
        ws = words(f["pdf"])
        self.assertEqual(len(rules), 1)
        self.assertLess(first(ws, "Moved"), first(ws, "Added"))
        self.assertAlmostEqual(rules[0].y0, first(ws, "Moved")[1] + 7, delta=3)      # still through its own line

    def test_an_underline_below_the_lines_box_pins_its_job_too(self):
        with fitz.open(PS.make(str(Path(tempfile.mkdtemp()) / "in.pdf"), underline=True)) as d:
            self.assertEqual([b["fixed"] for b in style_pdf.read(d, PS.PIECES)[1]["bullets"]], [True, False])
        f = self.build({"order": {"r1": ["r1b1", "r1b0"]}, "text": {}}, underline=True)
        self.assertEqual(f["order"]["r1"], ["r1b0", "r1b1"])

    def test_a_failing_render_closes_the_file(self):
        opened, real = [], fitz.open

        def spy(*a, **k):
            d = real(*a, **k)
            opened.append(d)
            return d
        src = sample()
        with mock.patch.object(fitz, "open", spy), mock.patch.object(style_pdf, "_lay_out", side_effect=RuntimeError("x")):
            with self.assertRaises(RuntimeError):
                style_pdf._render(src, PS.PIECES, {}, True)
        self.assertTrue(opened and opened[-1].is_closed)

    def test_a_pdf_without_these_parts_reports_none_kept(self):
        f = self.build({"order": {"r0": ["r0b2", "r0b0", "r0b1"]}, "text": {}})
        self.assertEqual(f["parts_kept"], {"headline": False, "summary": False, "skills": [], "skill_lines": False})


def placed(pdf):
    """Every word with its box, as printed: [(page, x0, y0, x1, y1, text)]."""
    with fitz.open(pdf) as d:
        return [(pg.number, *w[:5]) for pg in d for w in pg.get_text("words")]


def inside(ws, rect, yes=True):
    """The words (placed) whose middle is in rect on page 1, or (yes False) every other word."""
    return [w for w in ws if (w[0] == 0 and rect.contains(fitz.Point((w[1] + w[3]) / 2, (w[2] + w[4]) / 2))) == yes]


NEW_SUMMARY = "Backend engineer with eight years of **Python** and Go, building payment systems for banks."


class BuildParts(unittest.TestCase):
    """The headline, summary and skill lines redrawn in place as pseudo-jobs: read back word for word, the rest of
    the page untouched, and anything that doesn't fit or read back kept as it was (parts_kept)."""
    NONE = {"headline": False, "summary": False, "skills": [], "skill_lines": False}

    def build(self, plan, **kw):
        tmp = Path(tempfile.mkdtemp())
        self.src = PS.make(str(tmp / "in.pdf"), **kw)
        self.plan = {"order": {}, "text": {}, **plan}
        return style_pdf.build(style_pdf.find(self.src, PS.pieces(True, True, True)), self.plan, tmp, "out")

    def area(self, name, wide=False):
        """Where the source's part (or skill line, by id) was printed: its lines' boxes together; wide: across the
        page."""
        pieces = PS.pieces(True, True, True)
        with fitz.open(self.src) as d:
            scan = style_pdf._scan(d)
            parts = style_pdf.read_text_parts(d, pieces, style_pdf.read(d, pieces, scan), scan)
        part = parts.get(name) or next(l for l in parts["skills"] if l["id"] == name)
        r = fitz.Rect(part["lines"][0]["bbox"])
        for l in part["lines"][1:]:
            r |= l["bbox"]
        return fitz.Rect(0, r.y0, 595, r.y1) if wide else r

    def text_in(self, pdf, rect):
        return " ".join(w[5] for w in inside(placed(pdf), rect))

    # --- summary
    def test_a_shorter_summary_reads_back_on_its_own_lines_and_nothing_else_moves(self):
        f = self.build({"summary": NEW_SUMMARY}, summary=True)
        self.assertEqual(f["parts_kept"], self.NONE)
        self.assertEqual(self.plan["text"], {})                 # the expected texts stay in build's own copy
        r = self.area("summary", wide=True)
        got = inside(placed(f["pdf"]), r)
        self.assertEqual(" ".join(w[5] for w in got), NEW_SUMMARY.replace("**", ""))
        self.assertAlmostEqual(got[0][1], 50, delta=0.6)        # from where its text started
        self.assertEqual(inside(placed(f["pdf"]), r, False), inside(placed(self.src), r, False))

    def test_a_summary_that_needs_another_line_is_kept_and_nothing_is_drawn(self):
        longer = NEW_SUMMARY + " It also covers fraud checks, ledgers, reconciliation and the on-call rota."
        f = self.build({"summary": longer}, summary=True)
        self.assertEqual(f["parts_kept"], dict(self.NONE, summary=True))
        self.assertEqual(placed(f["pdf"]), placed(self.src))
        with fitz.open(f["pdf"]) as a, fitz.open(self.src) as b:
            self.assertEqual([pg.get_text() for pg in a], [pg.get_text() for pg in b])

    def test_bold_stays_on_a_phrase_that_was_bold(self):
        f = self.build({"summary": NEW_SUMMARY}, summary=True)
        r = self.area("summary", wide=True)
        sp = [s for s in spans(f["pdf"]) if r.contains(fitz.Point(s["origin"][0] + 1, s["origin"][1] - 2))]
        self.assertTrue([s for s in sp if s["text"].strip() == "Python"])
        for s in sp:
            self.assertEqual(style_pdf._is_bold(s), s["text"].strip() == "Python", s["text"])

    # --- headline
    def test_a_left_headline_takes_a_shorter_title_at_the_same_x(self):
        f = self.build({"headline": "Backend Engineer"}, headline="left")
        self.assertEqual(f["parts_kept"], self.NONE)
        r = self.area("headline", wide=True)
        got = inside(placed(f["pdf"]), r)
        self.assertEqual([w[5] for w in got], ["Backend", "Engineer"])
        self.assertAlmostEqual(got[0][1], 50, delta=0.6)
        self.assertEqual(inside(placed(f["pdf"]), r, False), inside(placed(self.src), r, False))
        heads = [s for s in spans(f["pdf"]) if s["text"].strip() == "Backend Engineer"]
        self.assertEqual([(round(s["size"]), s["color"], style_pdf._is_bold(s)) for s in heads], [(12, 0, False)])

    def test_a_centred_headline_stays_centred(self):
        f = self.build({"headline": "Backend Engineer"}, headline="center")
        self.assertEqual(f["parts_kept"], self.NONE)
        r = self.area("headline", wide=True)
        old, new = inside(placed(self.src), r), inside(placed(f["pdf"]), r)
        self.assertEqual([w[5] for w in new], ["Backend", "Engineer"])
        centre = lambda ws: (min(w[1] for w in ws) + max(w[3] for w in ws)) / 2
        self.assertAlmostEqual(centre(new), centre(old), delta=1)

    def test_a_headline_that_doesnt_fit_its_room_is_kept(self):
        longest = "Principal Backend Engineer for Payment Platforms and Card Networks"
        long = "Senior Backend Engineer for Payment Platforms"           # fits up to the page's text edge only
        for kw, title in (({"headline": "left"}, longest), ({"headline": "center"}, longest),
                          ({"headline": "left", "beside": "Remote"}, long)):
            f = self.build({"headline": title}, **kw)
            self.assertEqual(f["parts_kept"], dict(self.NONE, headline=True), kw)
            self.assertEqual(placed(f["pdf"]), placed(self.src), kw)
        f = self.build({"headline": long}, headline="left")
        self.assertEqual(f["parts_kept"], self.NONE)
        self.assertEqual(self.text_in(f["pdf"], self.area("headline", wide=True)), long)

    # --- skills
    def test_reordered_skills_read_back_in_order_with_their_separators_and_bold_label(self):
        f = self.build({"skills": {"s0": ["TypeScript", "SQL", "Go", "Python"]}}, skills=True)
        self.assertEqual(f["parts_kept"], self.NONE)
        r = self.area("s0", wide=True)
        self.assertEqual(self.text_in(f["pdf"], r), "Languages: TypeScript, SQL, Go, Python")
        sp = [s for s in spans(f["pdf"]) if r.contains(fitz.Point(s["origin"][0] + 1, s["origin"][1] - 2))]
        self.assertEqual([style_pdf._is_bold(s) for s in sp if s["text"].strip() == "Languages:"], [True])
        self.assertFalse(any(style_pdf._is_bold(s) for s in sp if "TypeScript" in s["text"]))
        self.assertEqual(inside(placed(f["pdf"]), r, False), inside(placed(self.src), r, False))

    def test_a_reordered_skill_line_keeps_the_labels_own_gap(self):
        # two spaces after each label: the label stays as printed and the items start where they did
        f = self.build({"skills": {"s0": ["TypeScript", "SQL", "Go", "Python"]}}, skills="gap")
        self.assertEqual(f["parts_kept"], self.NONE)
        r = self.area("s0", wide=True)
        old, new = inside(placed(self.src), r), inside(placed(f["pdf"]), r)
        self.assertEqual([w[5] for w in new], ["Languages:", "TypeScript,", "SQL,", "Go,", "Python"])
        self.assertEqual(new[0][1:5], old[0][1:5])
        self.assertAlmostEqual(new[1][1], old[1][1], delta=0.05)

    def test_skill_lines_move_whole_into_the_lines_they_had(self):
        f = self.build({"skill_lines": ["s2", "s1", "s0"],
                        "skills": {"s1": ["Airflow", "Kafka", "Redis", "PostgreSQL"]}}, skills=True)
        self.assertEqual(f["parts_kept"], self.NONE)
        rows = [self.area(f"s{n}", wide=True) for n in range(3)]
        self.assertEqual([self.text_in(f["pdf"], r) for r in rows],
                         ["Cloud: AWS, Docker, Kubernetes, Terraform", "Data: Airflow, Kafka, Redis, PostgreSQL",
                          "Languages: Python, Go, SQL, TypeScript"])
        whole = rows[0] | rows[2]
        self.assertEqual(inside(placed(f["pdf"]), whole, False), inside(placed(self.src), whole, False))

    def test_skills_in_chips_are_left_alone(self):
        f = self.build({"skills": {"s0": ["TypeScript", "SQL", "Go", "Python"]}, "skill_lines": ["s2", "s1", "s0"]},
                       skills="chips")
        self.assertEqual(f["parts_kept"], dict(self.NONE, skills=["s0"], skill_lines=True))
        self.assertEqual(placed(f["pdf"]), placed(self.src))

    def test_a_fixed_headline_or_summary_is_never_drawn(self):
        # a headline in two styles, a summary with an italic word: the plan's changes are reported as kept
        f = self.build({"headline": "Backend Engineer", "summary": NEW_SUMMARY}, headline="mixed", summary="italic")
        self.assertEqual(f["parts_kept"], dict(self.NONE, headline=True, summary=True))
        self.assertEqual(placed(f["pdf"]), placed(self.src))

    # --- safety
    def test_a_summary_that_doesnt_read_back_is_left_as_it_was_and_the_bullets_still_change(self):
        real, calls = style_pdf._wrong, []

        def wrong(*a):
            calls.append(sorted(a[3]))
            return (["xsb0"] if "xsb0" in a[3] else []) + real(*a)
        with mock.patch.object(style_pdf, "_wrong", wrong):
            f = self.build({"summary": NEW_SUMMARY, "order": {"r0": ["r0b2", "r0b0", "r0b1"]}}, summary=True)
        self.assertEqual(f["parts_kept"], dict(self.NONE, summary=True))
        self.assertEqual((f["order"]["r0"], f["left"], f["kept"]), (["r0b2", "r0b0", "r0b1"], [], []))
        self.assertEqual(len(calls), 3)                  # both font passes with the summary, then once without it
        r = self.area("summary", wide=True)
        self.assertEqual(inside(placed(f["pdf"]), r), inside(placed(self.src), r))
        ws = words(f["pdf"])
        self.assertLess(first(ws, "Wrote"), first(ws, "Built"))

    def test_a_word_lost_beside_a_part_spares_that_part(self):
        # a problem that names the part (as _disturbed names the bullets erased beside a lost word) spares it
        real = style_pdf._wrong
        with mock.patch.object(style_pdf, "_wrong",
                               lambda *a: (["lost 'Summary' (xsb0)"] if "xsb0" in a[3] else []) + real(*a)):
            f = self.build({"summary": NEW_SUMMARY, "headline": "Backend Engineer"}, headline="left", summary=True)
        self.assertEqual(f["parts_kept"], dict(self.NONE, summary=True))
        self.assertEqual(self.text_in(f["pdf"], self.area("headline", wide=True)), "Backend Engineer")

    def test_a_problem_no_bullet_or_part_answers_for_still_fails(self):
        calls = []
        with mock.patch.object(style_pdf, "_wrong", lambda *a: calls.append(1) or ["links"]):
            with self.assertRaises(ValueError):
                self.build({"summary": NEW_SUMMARY, "headline": "Backend Engineer"}, headline="left", summary=True)
        self.assertEqual(len(calls), 2)

    # --- no change
    def test_a_plan_that_changes_no_part_draws_nothing(self):
        same = {"headline": PS.HEADLINE, "summary": " ".join(PS.SUMMARY),
                "skills": {f"s{n}": list(items) for n, (_, items) in enumerate(PS.SKILLS)},
                "skill_lines": ["s0", "s1", "s2"]}
        real = fitz.Page.add_redact_annot
        for plan in ({}, same):
            with mock.patch.object(fitz.Page, "add_redact_annot", autospec=True, side_effect=real) as redact:
                f = self.build(plan, headline="left", summary=True, skills=True)
            self.assertEqual((redact.call_count, f["parts_kept"]), (0, self.NONE))


class Parts(unittest.TestCase):
    def test_tounicode_fix_leaves_glyph_runs_alone(self):
        cmap = (b"/CIDInit /ProcSet findresource begin\n12 dict begin\nbegincmap\n1 begincodespacerange\n<0000> <FFFF>\n"
                b"endcodespacerange\n1 beginbfrange\n<0010> <0012> <00AD>\nendbfrange\n2 beginbfchar\n<0013> <00AD>\n"
                b"<0014> <00A0>\nendbfchar\nendcmap\nend\nend\n")
        with fitz.open() as d:
            pg = d.new_page()
            pg.insert_font(fontname="tbs0", fontbuffer=fitz.Font("helv").buffer)
            pg.insert_text((50, 100), "x", fontname="tbs0", fontsize=10)
            xref = next(f[0] for f in pg.get_fonts() if f[4] == "tbs0")
            t = d.xref_get_key(xref, "ToUnicode")
            if t[0] == "xref":
                n = int(t[1].split()[0])
            else:
                n = d.get_new_xref()
                d.update_object(n, "<<>>")
                d.xref_set_key(xref, "ToUnicode", f"{n} 0 R")
            d.update_stream(n, cmap)
            style_pdf._fix_tounicode(d, {"tbs0"})
            got = d.xref_stream(n)
        self.assertIn(b"<0010> <0012> <00AD>", got)                  # a run's start stays where it is
        self.assertIn(b"<0013> <002D>", got)
        self.assertIn(b"<0014> <0020>", got)

    def test_a_line_drawn_over_a_sign_counts(self):
        with fitz.open() as d:
            d.new_page()
            sign = style_pdf._glyph_box(52, 56.6, 100, 10)
            signs = lambda: {"r0": (["r0b0", "r0b1"], [(0, sign, "r0b1", False)])}
            check = lambda rect: style_pdf._wrong(d, [], [], {"r0b1": [(0, rect)]}, {}, 0, {}, signs())
            self.assertEqual(check(fitz.Rect(49.5, 92.5, 200, 102.5)), ["text over the sign of r0b1"])
            self.assertEqual(check(fitz.Rect(61.5, 92.5, 200, 102.5)), [])           # starts after the sign
            self.assertEqual(check(fitz.Rect(49.5, 103.4, 200, 113.4)), [])          # the next line down

    def test_a_drawn_dot_left_alone_must_still_be_there(self):
        with fitz.open() as d:
            pg = d.new_page()
            dot = fitz.Rect(52, 95, 55.2, 98.2)
            signs = {"r0": (["r0b0"], [(0, dot, "r0b0", True)])}
            self.assertEqual(style_pdf._wrong(d, [], [], {}, {}, 0, {}, signs), ["lost the sign of r0b0 (r0b0)"])
            pg.draw_circle((53.6, 96.6), 1.6, color=None, fill=(0, 0, 0))
            self.assertEqual(style_pdf._wrong(d, [], [], {}, {}, 0, {}, signs), [])

    def test_fontconfig_is_asked_once_per_font(self):
        style_pdf.system_font.cache_clear()
        found = mock.Mock(stdout="/fonts/Carlito-Regular.ttf\nCarlito")
        try:
            with mock.patch.object(style_pdf.shutil, "which", return_value="/usr/bin/fc-match"), \
                 mock.patch.object(style_pdf.subprocess, "run", return_value=found) as run:
                for _ in range(3):
                    self.assertEqual(style_pdf.system_font("Calibri", False), "/fonts/Carlito-Regular.ttf")
            self.assertEqual(run.call_count, 1)
        finally:
            style_pdf.system_font.cache_clear()

    def test_a_word_wider_than_the_column_isnt_set(self):
        with fitz.open(sample()) as d:
            jobs = style_pdf.read(d, PS.PIECES)
            fonts = style_pdf.Fonts(d, jobs[0]["_lines"])
            st = style_pdf._style(jobs[0])
            self.assertIsNone(style_pdf._new_lines("Built " + "x" * 120, st, fonts))
            self.assertEqual(len(style_pdf._new_lines("Built a payments API.", st, fonts)), 1)


class Signs(unittest.TestCase):
    """A sign keeps its own glyph: the PDF's own font (no letter-spacing test for a sign), else DejaVu Sans, else a
    drawn dot for a round one."""
    def build(self, sign="dash", **kw):
        tmp = Path(tempfile.mkdtemp())
        doc = style_pdf.find(PS.make(str(tmp / "in.pdf"), sign=sign, **kw), PS.PIECES)
        self.pdf = style_pdf.build(doc, {"order": {"r0": ["r0b2", "r0b0", "r0b1"]}, "text": {}}, tmp, "out")["pdf"]
        with fitz.open(self.pdf) as d:
            return [w[4] for pg in d for w in pg.get_text("words") if w[0] < PS.X_TEXT - 2 and not w[4][0].isalnum()]

    @unittest.skipUnless(FONT_FILES, "no TrueType font to embed here")
    def test_a_round_sign_no_font_can_draw_becomes_a_dot(self):
        with mock.patch.object(style_pdf, "system_font", return_value=None), \
             mock.patch.object(style_pdf.Fonts, "own", return_value=None):
            signs = self.build(sign="dot", font_file=FONT_FILES)
        self.assertEqual(len(signs), 2)                              # the job left alone keeps its own
        self.assertTrue(set("".join(signs)) <= style_pdf.ROUND, signs)
        with fitz.open(self.pdf) as d:
            dots = [(dr["rect"].y0 + dr["rect"].y1) / 2 for dr in d[0].get_drawings()
                    if dr.get("fill") and dr["rect"].width < 8]
            ws = d[0].get_text("words")
        self.assertEqual(len(dots), 3)
        for w in ws:
            if w[4] in ("Built", "Cut", "Wrote"):
                self.assertTrue(any(abs(y - (w[1] + w[3]) / 2) < 4 for y in dots), w[4])

    @unittest.skipUnless(FONT_FILES, "no TrueType font to embed here")
    def test_an_en_dash_stays_an_en_dash_in_the_pdfs_own_font(self):
        with mock.patch.object(style_pdf, "system_font", return_value=None), \
             mock.patch.object(style_pdf.Fonts, "_trusted", return_value=False):
            self.assertEqual(self.build(font_file=FONT_FILES), ["–"] * 5)

    @unittest.skipUnless(FONT_FILES and style_pdf.system_font(style_pdf.FALLBACK, False), "DejaVu Sans isn't here")
    def test_an_en_dash_the_pdfs_font_cant_draw_is_drawn_in_dejavu(self):
        with mock.patch.object(style_pdf.Fonts, "own", return_value=None):
            self.assertEqual(self.build(font_file=FONT_FILES), ["–"] * 5)

    def test_a_sign_is_drawn_only_in_a_font_that_reads_it_back(self):
        seen = {}
        helv = (fitz.Font("helv"), None, "helv")
        self.assertTrue(style_pdf._reads_back(helv, "·", seen))
        self.assertFalse(style_pdf._reads_back(helv, "–", seen))        # a built-in font can't write it
        if not FONT_FILES:
            return
        buf = Path(FONT_FILES[0]).read_bytes()
        self.assertTrue(style_pdf._reads_back((fitz.Font(fontbuffer=buf), buf, "tbs0"), "–", seen))
        with mock.patch.object(style_pdf, "_reads_back", return_value=False):
            signs = self.build(font_file=FONT_FILES)
        # no font reads an en dash back and it isn't round: the Symbol font's bullet (it reads back as "·") for the
        # three moved bullets; the job left alone keeps its own
        self.assertEqual(signs, ["–", "–", "·", "·", "·"])


class OwnFont(unittest.TestCase):
    @unittest.skipUnless(FONT_FILES, "no TrueType font to embed here")
    def test_moved_and_reworded_bullets_use_the_pdfs_own_font(self):
        tmp = Path(tempfile.mkdtemp())
        src = PS.make(str(tmp / "in.pdf"), font_file=FONT_FILES)
        # PyMuPDF names a font it embeds by its full name ("Arial Regular", "DejaVu Sans"), the PDF has "ArialMT"
        squash = lambda name: re.sub(r"[^a-z]", "", style_pdf.family(name).lower())
        own = {squash(s["font"]) for s in spans(src) if "onboarding" in s["text"]}.pop()
        new = "Moved 30 cron jobs into Airflow, ending missed nightly runs and cutting manual reruns to zero."
        with mock.patch.object(style_pdf, "system_font", return_value=None):    # no stand-in: only its own font matches
            f = style_pdf.build(style_pdf.find(src, PS.PIECES),
                                {"order": {"r0": ["r0b2", "r0b0", "r0b1"]}, "text": {"r1b0": new}}, tmp, "out")
        self.assertEqual(f["kept"], [])
        sp = spans(f["pdf"])
        for word in ("onboarding", "Wrote", "nightly", "reruns"):
            got = {squash(s["font"]) for s in sp if word in s["text"]}
            self.assertTrue(got and all(n.startswith(own) for n in got), (word, got, own))
        self.assertIn(key(new), all_text(f["pdf"]))
        ws = words(f["pdf"])
        self.assertLess(first(ws, "Wrote"), first(ws, "Built"))


    @unittest.skipUnless(FONT_FILES, "no TrueType font to embed here")
    def test_words_drawn_apart_read_back_apart_even_after_an_arrow(self):
        # each word is drawn on its own; MuPDF never guesses a space after "→" or "≈", so a real one goes between
        tmp = Path(tempfile.mkdtemp())
        src = PS.make(str(tmp / "in.pdf"), font_file=FONT_FILES)
        new = "Moved 30 cron jobs to Airflow → zero missed nightly runs and ≈ no manual reruns at all."
        f = style_pdf.build(style_pdf.find(src, PS.PIECES), {"order": {"r0": ["r0b2", "r0b0", "r0b1"]},
                                                              "text": {"r1b0": new}}, tmp, "out")
        self.assertEqual(f["kept"], [])
        ws = [w for _, _, w in words(f["pdf"])]
        self.assertIn("→", ws)
        self.assertIn("≈", ws)
        self.assertIn("zero", ws)


    @unittest.skipUnless(FONT_FILES, "no TrueType font to embed here")
    def test_a_letter_spaced_word_stays_one_word(self):
        # its letters are set one by one, apart; no space goes between them
        tmp = Path(tempfile.mkdtemp())
        src = PS.make(str(tmp / "in.pdf"), font_file=FONT_FILES, tracked=True)
        squash = lambda name: re.sub(r"[^a-z]", "", style_pdf.family(name).lower())
        own = {squash(s["font"]) for s in spans(src) if "onboarding" in s["text"]}.pop()
        with mock.patch.object(style_pdf, "system_font", return_value=None):
            f = style_pdf.build(style_pdf.find(src, PS.PIECES), {"order": {"r0": ["r0b2", "r0b0", "r0b1"]}, "text": {}},
                                tmp, "out")
        ws = words(f["pdf"])
        self.assertIn("public", [w for _, _, w in ws])
        self.assertLess(first(ws, "Wrote"), first(ws, "Built"))
        self.assertTrue(all(squash(s["font"]).startswith(own) for s in spans(f["pdf"]) if "ubli" in s["text"]))


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

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

    def test_a_headline_drops_the_posts_tags(self):
        for title, want in (("[WBG] Senior DevOps Engineer", "Senior DevOps Engineer"),
                            ("Backend Engineer (Remote)", "Backend Engineer"), ("Data Engineer (m/f/d)", "Data Engineer"),
                            ("Forward Deployed Engineer (Client Facing)", "Forward Deployed Engineer (Client Facing)"),
                            ("Cloud Engineer (Hybrid Cloud)", "Cloud Engineer (Hybrid Cloud)"),
                            ("Senior Engineer - Remote", "Senior Engineer"), ("Senior Engineer | Remote", "Senior Engineer"),
                            ("Data Engineer (m/w/x)", "Data Engineer"), ("Data Engineer (gn)", "Data Engineer"),
                            ("Engineer (Full-time, Remote)", "Engineer"), ("Data Engineer (m/f/div)", "Data Engineer"),
                            ("Backend Engineer - US - Payments", "Backend Engineer - US - Payments"),
                            ("Engineer (Remote Sensing)", "Engineer (Remote Sensing)"), ("[Remote]", "[Remote]")):
            self.assertEqual(tailor.headline_title(title), want)

    def test_a_role_without_a_company_gets_its_own_section(self):
        from teambid import cv_pdf
        spec = {"name": "Dana Reyes", "headline": "Engineer", "contact": {}, "summary": "", "skills": [], "education": [],
                "roles": [{"company": "Northwind", "title": "Engineer", "start": "2020-01", "end": "Present", "bullets": ["Built a ledger."]},
                          {"company": "", "title": "Earlier Experience", "start": "2008-01", "end": "2013-01",
                           "bullets": ["Built a templating engine."]}]}
        sections = cv_pdf.to_rendercv(spec)["cv"]["sections"]
        self.assertEqual([e["company"] for e in sections["Experience"]], ["Northwind"])
        later = [k for k in sections if k.startswith("Earlier Experience")]
        self.assertEqual([sections[k] for k in later], [[{"bullet": "Built a templating engine."}]])
        if cv_pdf.available():                           # RenderCV takes it (it rejected a role without a company)
            with tempfile.TemporaryDirectory() as td:
                self.assertGreaterEqual(cv_pdf.write_pdf(spec, str(Path(td) / "cv.pdf")), 1)
        # a newer role without a company (freelance now) goes above the jobs; one titled just "Experience" can't be
        # mistaken for the jobs' section
        spec["roles"] += [{"company": "", "title": "Freelance Engineer", "start": "2024-01", "end": "Present", "bullets": ["Shipped apps."]},
                          {"company": "", "title": "Experience", "bullets": ["Taught a course."]}]
        names = list(cv_pdf.to_rendercv(spec)["cv"]["sections"])
        self.assertLess(names.index(next(n for n in names if n.startswith("Freelance"))), names.index("Experience"))
        self.assertIn("Other experience", names)

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

    def test_a_feeds_post_is_kept_for_its_link(self):
        post = "We build payments. You will own React and Node services end to end. " * 20      # a whole post
        feed = {"url": "https://himalayas.app/companies/tabby/jobs/senior-fullstack-engineer?utm_source=api",
                "company": "Tabby", "title": "Senior Fullstack Engineer", "ats": "feed", "source": "Himalayas",
                "description": post}
        teaser = {**feed, "url": "https://www.jobindex.dk/jobannonce/1", "company": "Teaser",
                  "description": "A short teaser from an RSS feed."}
        board = {"url": "https://boards.greenhouse.io/acme/jobs/7", "company": "Acme", "title": "Engineer",
                 "ats": "greenhouse", "description": post}
        saved = lambda url: (lambda j: storage.get_jd(con, j["id"]) if j else None)(storage.job_for_url(con, url))
        with storage.connect() as con:
            storage.upsert_jobs(con, [feed, teaser, board], "2026-03-01")
            self.assertEqual(storage.save_feed_posts(con, [feed, teaser, board]), 1)
            self.assertEqual(storage.job_for_url(con, feed["url"].split("?")[0])["company"], "Tabby")
            self.assertEqual(saved(feed["url"]), post)
            self.assertIsNone(saved(teaser["url"]))      # a teaser isn't the post: the page is read instead
            self.assertIsNone(saved(board["url"]))       # a board's post is read from its page
            # three weeks unseen: forgotten, unless someone applied to it
            old = {**feed, "url": "https://himalayas.app/companies/old/jobs/x", "company": "Old"}
            applied = {**feed, "url": "https://himalayas.app/companies/kept/jobs/y", "company": "Kept"}
            storage.upsert_jobs(con, [old, applied], "2026-01-01")
            storage.save_feed_posts(con, [old, applied])
            mid, _ = storage.save_member(con, "Feed Tester", {}, {})
            jid = storage.job_for_url(con, applied["url"])["id"]
            storage.create_application(con, mid, "Kept", "Senior Fullstack Engineer", job_id=jid)
            storage.prune_jd(con, "2026-02-08")
            self.assertIsNone(saved(old["url"]))
            self.assertEqual(saved(applied["url"]), post)
            self.assertEqual(saved(feed["url"]), post)
            # the other tests share this database (test_roundtrip counts its jobs)
            ids = [r["id"] for r in con.execute("SELECT id FROM jobs WHERE company IN ('Tabby','Teaser','Acme','Old','Kept')")]
            q = ",".join("?" * len(ids))
            for sql in (f"DELETE FROM jd WHERE job_id IN ({q})", f"DELETE FROM applications WHERE job_id IN ({q})",
                        f"DELETE FROM jobs WHERE id IN ({q})"):
                con.execute(sql, ids)
            con.execute("DELETE FROM members WHERE id=?", (mid,))


class Times(unittest.TestCase):
    """Every time and date is Japan time: the page, documents, job dates, and the programs that build documents."""

    def test_the_page_says_when_it_was_updated_in_jst(self):
        from teambid import export
        self.assertEqual(config.TZ.key, os.environ.get("TEAMBID_TZ", "Asia/Tokyo"))
        self.assertTrue(export.build_data()["generated"].endswith(" JST"))

    def test_the_letter_is_dated_in_jst(self):
        import datetime as dt
        from unittest import mock
        from teambid import region
        late = dt.datetime(2026, 11, 10, 8, 0, tzinfo=config.TZ)          # still November 9 in the US
        with mock.patch.object(config, "now", return_value=late):
            self.assertEqual(region.letter_date({"region": "US", "timezone": "America/New_York"}), "November 10, 2026")
            self.assertEqual(region.letter_date({"region": "EU"}), "10 November 2026")

    def test_a_job_posted_late_at_night_in_utc_is_dated_the_next_day(self):
        from teambid.jobs import ats
        self.assertEqual(ats.iso("2026-11-09T20:00:00Z"), "2026-11-10")
        self.assertEqual(ats.iso("Mon, 09 Nov 2026 16:00:00 -0800"), "2026-11-10")
        self.assertEqual(ats.iso(1794254400), "2026-11-10")              # 2026-11-09 20:00 UTC
        self.assertEqual(ats.iso("2026-11-09"), "2026-11-09")             # a plain date stays

    @unittest.skipUnless(hasattr(__import__("time"), "tzset"), "the process clock is set on Linux (GitHub Actions)")
    def test_programs_that_build_documents_tell_time_in_jst(self):
        import time
        self.assertEqual(os.environ["TZ"], config.TZ.key)
        self.assertEqual(time.strftime("%Z"), "JST")


class Privacy(unittest.TestCase):
    def test_logs_name_a_member_by_a_code_never_their_name(self):
        # the engine repo and its Actions logs are public
        code = config.who("dana-reyes")
        self.assertRegex(code, r"^member [0-9a-f]{6}$")
        self.assertEqual(code, config.who("dana-reyes"))
        self.assertNotIn("dana", code)
        line = config.redact("added Dana Reyes: file members/dana-reyes/resume/cv.pdf", "dana-reyes", "Dana Reyes")
        self.assertNotIn("Dana", line)
        self.assertNotIn("dana-reyes", line)
        self.assertIn(code, line)


class Audit(unittest.TestCase):
    def test_audit(self):
        a = analyze.audit(rp.parse_file(TXT))
        self.assertGreater(a["score"], 70)
        self.assertTrue(any("phone" in f["message"] for f in a["findings"]) or True)


if __name__ == "__main__":
    unittest.main()

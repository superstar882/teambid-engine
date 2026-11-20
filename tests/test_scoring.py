import datetime as dt
import unittest

from teambid.jobs import facts as F
from teambid.jobs import matcher as M

TODAY = dt.date(2026, 10, 21)
MEMBER = {"name": "Test", "prefs": {"countries": ["US"], "level": "mid", "days": 30, "lanes": ["backend"], "target_titles": []},
          "profile": {"years_experience": 3, "lanes": ["backend"],
                      "skills": {"proven": ["Python", "Go", "PostgreSQL"], "listed_only": ["Docker", "AWS"]}}}
LANES = M._lane_pattern(["backend"])


def job(title, **kw):
    return {"id": 1, "title": title, "company": "Acme", "location": "Remote - US", "posted": "2026-10-20", **kw}


class SkillScoringTest(unittest.TestCase):
    def test_description_decides(self):
        good = {"must": ["Python", "Go", "PostgreSQL", "Kubernetes"], "nice": ["AWS"], "years": 3}
        sc, why = M.score_job(job("Backend Engineer"), MEMBER, LANES, TODAY, good)
        self.assertIsNotNone(sc)
        self.assertIn("has 3 of 4 required skills", why)
        self.assertTrue(any(w.startswith("missing: Kubernetes") for w in why))

    def test_missing_most_required_skills_is_dropped(self):
        bad = {"must": ["Rust", "Scala", "Elixir", "Python"], "years": None}
        self.assertEqual(M.score_job(job("Backend Engineer"), MEMBER, LANES, TODAY, bad), (None, "skills"))

    def test_years_far_above_is_dropped(self):
        f = {"must": ["Python", "Go"], "years": 8}
        self.assertEqual(M.score_job(job("Backend Engineer"), MEMBER, LANES, TODAY, f), (None, "years"))
        sc, why = M.score_job(job("Backend Engineer"), MEMBER, LANES, TODAY, {"must": ["Python", "Go"], "years": 5})
        self.assertTrue(any("asks 5+ years" in w for w in why))

    def test_any_engineering_title_can_match_on_skills(self):
        title = "Member of Technical Staff"           # no lane word, no target title
        self.assertEqual(M.score_job(job(title), MEMBER, LANES, TODAY), (None, "title"))
        sc, _ = M.score_job(job(title), MEMBER, LANES, TODAY, {"must": ["Python", "Go", "PostgreSQL"], "years": 2})
        self.assertIsNotNone(sc)
        self.assertEqual(M.score_job(job("Account Executive"), MEMBER, LANES, TODAY, {"must": ["Python"]})[0], None)


class FactsTest(unittest.TestCase):
    def test_analyze(self):
        text = ("Requirements:\n- 5+ years of experience with Python and PostgreSQL\n- Kubernetes\n"
                "Nice to have:\n- Go\nThis role is fully remote within Europe (CET).")
        f = F.analyze(text, "Backend Engineer")
        self.assertIn("Python", f["must"])
        self.assertEqual(f["years"], 5)
        self.assertIn("Europe", f["regions"])
        self.assertTrue(f["full_remote"])


class PostedWindowTest(unittest.TestCase):
    def test_two_days_means_the_scans_day_and_the_two_before(self):
        # days are JST; while they were US Pacific (a day behind Japan) 2 days took in this much, and the team kept it
        m = {**MEMBER, "prefs": {**MEMBER["prefs"], "days": 2}}
        f = {"must": ["Python", "Go"], "years": 2}
        for posted, ok in (("2026-10-21", True), ("2026-10-20", True), ("2026-10-19", True), ("2026-10-18", False)):
            sc, why = M.score_job(job("Backend Engineer", posted=posted), m, LANES, TODAY, f)
            self.assertEqual(sc is not None, ok, posted)


if __name__ == "__main__":
    unittest.main()


class BoardDateTest(unittest.TestCase):
    def test_newest_board_copy_per_role(self):
        import sqlite3
        con = sqlite3.connect(":memory:")
        con.execute("CREATE TABLE jobs (company, title, source, posted, last_seen)")
        con.executemany("INSERT INTO jobs VALUES (?,?,?,?,?)", [
            ("Dante", "Full Stack Engineer", "Company board", "2024-03-19", "d1"),       # old opening, relisted by a feed
            ("Acme", "Software Engineer", "Company board", "2026-01-05", "d1"),
            ("Acme", "Software Engineer", "Company board", "2026-10-24", "d1"),         # second, fresh opening
            ("Dante", "Full Stack Engineer", "Himalayas", "2026-10-25", "d1")])
        M._BOARD_DATES.clear()
        got = M.board_dates(con, "d1")
        self.assertEqual(got[M.dedupe_key("Dante", "Full Stack Engineer")], "2024-03-19")
        self.assertEqual(got[M.dedupe_key("Acme", "Software Engineer")], "2026-10-24")


class DjinniTest(unittest.TestCase):
    def test_djinni_jobs_skip_members_in_the_us(self):
        f = {"must": ["Python", "Go"], "years": 2}
        dj = job("Backend Engineer", location="Remote", source="Djinni")
        self.assertEqual(M.score_job(dj, MEMBER, LANES, TODAY, f), (None, "abroad"))
        eu = {**MEMBER, "prefs": {**MEMBER["prefs"], "countries": ["Poland"]}}
        self.assertIsNotNone(M.score_job(dj, eu, LANES, TODAY, f)[0])
        self.assertIsNotNone(M.score_job(job("Backend Engineer", location="Remote"), MEMBER, LANES, TODAY, f)[0])


class UsPlaceCheckTest(unittest.TestCase):
    def test_remote_post_naming_only_other_places(self):
        us = {"US"}
        self.assertEqual(M.only_elsewhere({"Europe", "Germany"}, us), ["Germany", "Europe"])
        self.assertEqual(M.only_elsewhere({"Europe", "US"}, us), [])            # "US or Europe"
        self.assertEqual(M.only_elsewhere({"Europe", "worldwide"}, us), [])
        self.assertEqual(M.only_elsewhere(set(), us), [])                       # says nothing: a US member keeps it
        self.assertEqual(M.only_elsewhere({"UK"}, us, ["San Francisco, CA", "New York, NY"]), [])   # US company
        self.assertEqual(M.only_elsewhere({"LATAM"}, us, ["Lisbon, Portugal"]), ["LATAM"])
        self.assertEqual(M.only_elsewhere({"Germany"}, {"US", "Europe"}), [])

    def test_us_state_or_city_in_the_text(self):
        self.assertTrue(M.US_NAMED.search("Hubs in New York and London"))
        self.assertFalse(M.US_NAMED.search("Python, or Go, in a team in Poland, Ukraine and Georgia"))


class ReposterTest(unittest.TestCase):
    def test_repost_sites_are_known(self):
        self.assertTrue(M.is_reposter("Lifelancer"))
        self.assertTrue(M.is_reposter("Jobgether"))
        self.assertFalse(M.is_reposter("Veeva"))
        self.assertFalse(M.is_reposter(""))


class BlockedCompanyTest(unittest.TestCase):
    def test_companies_the_team_removed(self):
        for name in ("RemoteJobsOne", "remotejobsone", "Micro1", "micro1", "micro1 Inc."):
            self.assertTrue(M.is_blocked(name), name)
        for name in ("Microsoft", "Micron", "Remote", "", None):
            self.assertFalse(M.is_blocked(name), name)

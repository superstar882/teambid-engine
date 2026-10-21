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


if __name__ == "__main__":
    unittest.main()

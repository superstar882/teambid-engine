import base64
import json
import unittest

from teambid import admin, resume_parse
from tests.fixtures import DATA_TXT


class AdminTest(unittest.TestCase):
    def setUp(self):
        self.profile = resume_parse.parse(DATA_TXT)

    def test_edit_profile_rebuilds_from_typed_facts(self):
        p = admin.edit_profile(self.profile, {
            "summary": "Backend engineer.",
            "roles": [{"title": "Senior Backend Engineer", "company": "Acme", "start": "Apr 2021", "end": "present",
                       "bullets": "Built payment APIs in Go and PostgreSQL serving 2M users\nCut p95 latency 40% with Redis"},
                      {"title": "", "company": ""}],
            "skills": "Go, PostgreSQL, Redis, Kubernetes, Some Custom Tool",
            "education": [{"school": "MIT", "degree": "B.S.", "field": "CS", "end": "2015"}],
            "certifications": "AWS Solutions Architect"})
        self.assertEqual(len(p["roles"]), 1)
        r = p["roles"][0]
        self.assertEqual((r["start"], r["end"], r["current"]), ("2021-04", "Present", True))
        self.assertIn("Go", r["stack"])
        self.assertIn("Kubernetes", p["skills"]["listed_only"])
        self.assertIn("Some Custom Tool", p["skills"]["other_listed"])
        self.assertIn("2M", " ".join(p["metrics"]) + p["raw_text"])
        self.assertGreater(p["years_experience"], 4)
        self.assertEqual(p["education"][0]["school"], "MIT")

    def test_prefs_are_cleaned(self):
        pr = admin.edit_prefs({"countries": ["US"], "min_score": 40}, {"countries": "Denmark, UK", "min_score": "250", "onsite_ok": 1,
                                                                        "avoid_companies": "Foo, Foo, Bar"})
        self.assertEqual(pr["countries"], ["Europe", "UK"])
        self.assertEqual(pr["min_score"], 95)
        self.assertTrue(pr["onsite_ok"])
        self.assertEqual(pr["avoid_companies"], ["Foo", "Bar"])

    def test_queue_joins_parts(self):
        body = base64.b64encode(json.dumps({"name": "Zoë"}).encode()).decode()
        e = {"a": {"kind": "adminreq", "rid": "r1", "action": "add", "parts": 2, "at": "1"},
             "b": {"kind": "adminpart", "rid": "r1", "n": 1, "text": body[5:]}, "c": {"kind": "adminpart", "rid": "r1", "n": 0, "text": body[:5]},
             "d": {"kind": "adminreq", "rid": "r2", "action": "edit", "parts": 1, "at": "2"},
             "e": {"kind": "admindone", "rid": "r2"}}
        q = admin.queue(e)
        self.assertEqual([x["rid"] for x in q], ["r1"])
        self.assertEqual(q[0]["body"]["name"], "Zoë")


if __name__ == "__main__":
    unittest.main()

"""European members: dates, region defaults, A4 + 2-page budget, EU location matching, salary currencies."""
import datetime as dt
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from teambid import local_ai, region as RG, render, resume_parse as rp, tailor  # noqa: E402
from teambid.jobs import matcher  # noqa: E402
from tests import fixtures  # noqa: E402

local_ai.DISABLED = True
fixtures.make()
EU = fixtures.HERE / "lena_schmidt_eu.txt"
EU_JD = """Backend Engineer (Python/Go) - Remote within EMEA
Salary: €70,000 - €85,000 per year
Requirements
- 4+ years with Python or Go, PostgreSQL, Kafka
- Docker and Kubernetes
Nice to have
- Terraform
"""


class EuropeanCV(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = rp.parse_file(EU)

    def test_dates_and_roles(self):
        r = self.p["roles"]
        self.assertEqual((r[0]["title"], r[0]["company"], r[0]["start"], r[0]["end"]), ("Backend Engineer", "Parcelway GmbH", "2022-03", "Present"))
        self.assertEqual((r[1]["start"], r[1]["end"]), ("2019-01", "2022-02"))
        self.assertEqual(r[2]["start"], "2016-09")          # 15.09.2016 is day-first
        self.assertEqual(r[2]["kind"], "intern")             # working student
        self.assertEqual((r[2]["title"], r[2]["company"]), ("Working Student, Software Development", "Datenwerk"))
        self.assertGreater(self.p["years_experience"], 7)

    def test_region_defaults(self):
        prefs = matcher.default_prefs(self.p)
        self.assertEqual(prefs["region"], "EU")
        self.assertEqual(prefs["countries"], ["Germany", "Europe"])
        self.assertEqual(prefs["timezone"], "Europe/Berlin")
        self.assertEqual(RG.detect("London, UK")["countries"], ["UK", "Europe"])
        self.assertEqual(RG.detect("Austin, TX")["timezone"], "America/Chicago")

    def test_eu_job_location(self):
        prefs = matcher.default_prefs(self.p)
        self.assertTrue(matcher.place_ok("Remote - EMEA", "Backend Engineer", prefs)[0])
        self.assertTrue(matcher.place_ok("Remote, Germany", "Backend Engineer", prefs)[0])
        self.assertFalse(matcher.place_ok("Berlin, Germany", "Backend Engineer", prefs)[0])    # remote-only team: on-site is out
        self.assertFalse(matcher.place_ok("Hybrid - Berlin", "Backend Engineer", prefs)[0])
        self.assertFalse(matcher.place_ok("Remote - US only", "Backend Engineer", prefs)[0])

    def test_denmark_member_remote_jobs(self):
        prefs = {"countries": RG.detect("Copenhagen, Denmark")["countries"], "remote_ok": True, "onsite_ok": False}
        for loc in ("Remote - Denmark", "Remote - EMEA", "Remote, Berlin", "Remote - Nordics", "Remote (DACH)", "Remote - Worldwide"):
            self.assertTrue(matcher.place_ok(loc, "Backend Engineer", prefs)[0], loc)
        for loc in ("Remote - US", "Remote - UK", "Hybrid - Copenhagen"):
            self.assertFalse(matcher.place_ok(loc, "Backend Engineer", prefs)[0], loc)
        self.assertTrue(matcher.RESTRICT["US"].search("Candidates must be located in the United States."))
        self.assertTrue(matcher.NO_SPONSOR.search("We are unable to sponsor visas."))

    def test_documents_follow_the_job(self):
        self.assertEqual(RG.job_region("Remote - US"), "US")
        self.assertEqual(RG.job_region("Remote, Berlin"), "EU")
        self.assertEqual(RG.job_region("Remote, Copenhagen"), "EU")
        self.assertEqual(RG.job_region("Remote", salary="£60k - £70k"), "UK")
        self.assertEqual(RG.job_region("Remote", "Pay range $140,000 - $170,000"), "US")
        self.assertIsNone(RG.job_region("Remote"))

    def test_salary_currencies(self):
        self.assertTrue(tailor.analyze_jd(EU_JD)["salary"].startswith("€70"))
        self.assertTrue(tailor.analyze_jd("Pay: £55k - £65k")["salary"].startswith("£55"))

    def test_a4_two_page_budget(self):
        import fitz
        jd = tailor.analyze_jd(EU_JD, "Backend Engineer", "Acme")
        out = render.write_resume(tailor.build_resume(self.p, jd), tempfile.mkdtemp(), "eu", self.p["years_experience"], "EU")
        page = fitz.open(out["pdf"])[0].rect
        self.assertAlmostEqual(page.width, 595, delta=2)     # A4 width in points
        self.assertLessEqual(out["pages"], 2)
        self.assertEqual(RG.page_budget("EU", 7), 2)
        self.assertEqual(RG.page_budget("US", 7), 1)

    def test_letter_date_style(self):
        self.assertRegex(RG.letter_date({"region": "EU", "timezone": "Europe/Berlin"}), r"^\d{1,2} [A-Z][a-z]+ \d{4}$")
        self.assertRegex(RG.letter_date({"region": "US"}), r"^[A-Z][a-z]+ \d{1,2}, \d{4}$")


if __name__ == "__main__":
    unittest.main()

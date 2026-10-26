import unittest

from teambid.jobs import matcher

US = {"countries": ["US"], "remote_ok": True, "onsite_ok": False}


class RemoteOnlyTest(unittest.TestCase):
    def test_workplace_tag_beats_remote_flag(self):
        # Ashby marks hybrid jobs isRemote=true; the scanner tags them [Hybrid] from workplaceType
        self.assertFalse(matcher.place_ok("San Mateo, CA / San Francisco, CA / [Hybrid]", "Software Engineer", US)[0])
        self.assertFalse(matcher.place_ok("Austin, TX / [On-site]", "Software Engineer", US)[0])
        self.assertTrue(matcher.place_ok("Remote - US", "Software Engineer", US)[0])

    def test_post_text_in_office(self):
        for t in ("We work in person in the San Francisco Bay Area.", "This role is hybrid, 3 days a week in the office.",
                  "You'll be expected to work from the office 3 days per week.", "Location type: Hybrid"):
            self.assertTrue(matcher.IN_OFFICE.search(t), t)
        for t in ("This is a fully remote role.", "Remote or hybrid, your choice.", "We are remote-first."):
            self.assertTrue(matcher.FULL_REMOTE.search(t), t)

    def test_location_line_names_an_office(self):
        # Himalayas lists this as "United States only"; only the post says where the work is
        fox = ("Title: Software Engineer II Grade: P2 Location: Atlanta, GA Compensation: Salary USD $100,000 - $130,000/ Year "
               "Relocation Eligibility: No Sponsorship availability: No")
        self.assertTrue(matcher.office_location(fox))
        self.assertTrue(matcher.office_location("Location: San Francisco, CA (Hybrid)"))
        for t in ("Location: Remote (US)", "Location: Austin, TX or Remote", "Location: United States, Canada",
                  "Location: Remote within the US. Our Austin, TX office is optional", "pay depends on geographic location."):
            self.assertFalse(matcher.office_location(t), t)
        from teambid.jobs import facts
        self.assertTrue(facts.analyze(fox, "Software Engineer II")["in_office"])



class CompanyOfficesTest(unittest.TestCase):
    def test_offices_from_postings(self):
        from teambid.jobs import company
        ranked = [p for p, _ in company.offices(["Stockholm HQ / Remote", "NYC", "London / Remote", "NYC"])]
        self.assertEqual(ranked[0], "Stockholm")                 # marked HQ wins
        self.assertIn("NYC", ranked)
        self.assertEqual(company.offices(["Remote - US", "United States / Remote", "US West", "& 13 other countries"]), [])
        self.assertEqual([p for p, _ in company.offices(["UK - London", "Budapest, Hungary"])], ["Budapest, Hungary", "London"])


class OpenToNonUsTest(unittest.TestCase):
    def test_evidence_and_us_only(self):
        E = {"Europe"}
        self.assertTrue(matcher.open_to("We hire anywhere in Europe (CET +/- 2).", E))
        self.assertTrue(matcher.open_to("We are US-based but hire globally.", E))
        self.assertTrue(matcher.open_to("Open to candidates in EMEA.", E))
        self.assertFalse(matcher.open_to("Fully remote team.", E))
        self.assertTrue(matcher.US_ONLY.search("You must reside in the United States."))
        self.assertTrue(matcher.US_ONLY.search("Our team works Pacific Time hours."))
        self.assertFalse(matcher.US_ONLY.search("We are a US-based company."))
        self.assertTrue(matcher.open_to("Remote across Latin America (UTC-3).", {"LATAM"}))

    def test_regions(self):
        from teambid import region
        self.assertEqual(region.detect("São Paulo, Brazil")["region"], "LATAM")
        self.assertEqual(region.detect("Novi Sad")["region"], "EU")
        self.assertEqual(matcher.norm_countries(["Serbia"]), ["Europe"])
        self.assertTrue(matcher.place_ok("Remote - Americas", "Engineer", {"countries": ["LATAM"]})[0])


if __name__ == "__main__":
    unittest.main()

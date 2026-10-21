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



class CompanyOfficesTest(unittest.TestCase):
    def test_offices_from_postings(self):
        from teambid.jobs import company
        ranked = [p for p, _ in company.offices(["Stockholm HQ / Remote", "NYC", "London / Remote", "NYC"])]
        self.assertEqual(ranked[0], "Stockholm")                 # marked HQ wins
        self.assertIn("NYC", ranked)
        self.assertEqual(company.offices(["Remote - US", "United States / Remote", "US West", "& 13 other countries"]), [])
        self.assertEqual([p for p, _ in company.offices(["UK - London", "Budapest, Hungary"])], ["Budapest, Hungary", "London"])


if __name__ == "__main__":
    unittest.main()

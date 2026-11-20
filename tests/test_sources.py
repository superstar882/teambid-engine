"""More job sources: boards found in public lists of job links, the Rippling / Gem / Oracle readers, the Arbeitnow feed.
No network: every API answer is a stand-in shaped like the real one (checked 2026-11-20)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from teambid import config
from teambid.jobs import ats, boardfind as BF, discover, feeds, jd


class BoardOfTest(unittest.TestCase):
    def test_job_links_name_their_board(self):
        cases = {
            "https://job-boards.greenhouse.io/acme/jobs/123": ("greenhouse", "acme"),
            "https://boards.greenhouse.io/embed/job_app?for=acme&token=1": ("greenhouse", "acme"),
            "https://jobs.lever.co/acme/0f5e1c2a-1111-2222-3333-444455556666/apply": ("lever", "acme"),
            "https://jobs.ashbyhq.com/Acme%20AI/abc": ("ashby", "acme ai"),
            "https://acme.wd5.myworkdayjobs.com/en-US/External_Careers/job/Remote/Engineer_R1": ("workday", "acme|wd5|External_Careers"),
            "https://jobs.smartrecruiters.com/AcmeInc/7445": ("smartrecruiters", "acmeinc"),
            "https://apply.workable.com/acme/j/ABC/": ("workable", "acme"),
            "https://careers-acme.icims.com/jobs/4341/job?mobile=true": ("icims", "careers-acme"),
            "https://acme.breezy.hr/p/123": ("breezy", "acme"),
            "https://acme.jobs.personio.de/job/1": ("personio", "acme"),
            "https://ats.rippling.com/acme-careers/jobs/93ada67c-8527-427c-b2f6-4a5557b00674": ("rippling", "acme-careers"),
            "https://jobs.gem.com/acme/am9icG9zdDox": ("gem", "acme"),
            "https://hdhe.fa.em3.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX/job/400055053": ("oracle", "hdhe.fa.em3.oraclecloud.com|CX"),
        }
        for url, want in cases.items():
            self.assertEqual(BF.board_of(url), want, url)

    def test_careers_links(self):
        self.assertEqual(BF.careers("ashby", "acme ai"), "https://jobs.ashbyhq.com/acme%20ai")
        self.assertEqual(BF.careers("workday", "acme|wd5|Ext"), "https://acme.wd5.myworkdayjobs.com/Ext")
        self.assertEqual(BF.careers("oracle", "h.oraclecloud.com|CX"), "https://h.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX/requisitions")
        self.assertEqual(BF.careers("icims", "careers-acme"), "https://careers-acme.icims.com/jobs")

    def test_links_that_name_no_board(self):
        for url in ("https://www.bamboohr.com/pricing", "https://api.recruitee.com/x", "https://acme.com/careers?gh_jid=1",
                    "https://jobs.lever.co/", "https://simplify.jobs/p/123", ""):
            self.assertIsNone(BF.board_of(url), url)


class BoardFinderTest(unittest.TestCase):
    LIST = [{"company_name": "Acme AI", "url": "https://jobs.ashbyhq.com/acmeai/1", "active": True, "date_updated": 1795000000},
            {"company_name": "Known Co", "url": "https://jobs.lever.co/known/2", "active": True, "date_updated": 1795000000},
            {"company_name": "Empty Co", "url": "https://jobs.gem.com/emptyco/3", "active": True, "date_updated": 1795000000},
            {"company_name": "Old Co", "url": "https://jobs.ashbyhq.com/oldco/4", "active": False, "date_updated": 1600000000}]

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="teambid-bf-"))
        self.patches = [mock.patch.object(discover, "REGISTRY", self.tmp / "found-boards.json"),
                        mock.patch.object(BF, "scanned", return_value={("lever", "known")}),
                        mock.patch.object(BF, "_crawl", return_value={})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def fetch(self, slug, system, *a):
        return [{"title": "Backend Engineer", "url": f"https://x/{slug}"}] if (system, slug) == ("ashby", "acmeai") else []

    def test_new_boards_with_open_jobs_are_kept(self):
        with mock.patch.object(BF, "_lists", return_value=self.LIST), mock.patch.object(BF.ats, "fetch", side_effect=self.fetch) as f:
            n = BF.run("2026-11-20", log=lambda *_: None, workers=1)
        self.assertEqual(n, 1)
        tried = sorted((c.args[1], c.args[0]) for c in f.call_args_list)
        self.assertEqual(tried, [("ashby", "acmeai"), ("gem", "emptyco")])      # not the scanned board nor the stale listing
        self.assertEqual(discover.boards(), {("ashby", "acmeai"): "Acme AI"})
        reg = json.loads(discover.REGISTRY.read_text())
        self.assertEqual(reg["boards"]["ashby:acmeai"]["careers"], "https://jobs.ashbyhq.com/acmeai")
        self.assertEqual(reg["misses"], {"gem:emptyco": "2026-11-20"})
        with mock.patch.object(BF, "_lists", return_value=self.LIST), \
             mock.patch.object(BF, "scanned", return_value={("lever", "known"), ("ashby", "acmeai")}), \
             mock.patch.object(BF.ats, "fetch", side_effect=AssertionError("tried again")):
            self.assertEqual(BF.run("2026-12-01", log=lambda *_: None, workers=1), 0)     # a miss waits 30 days
        with mock.patch.object(BF, "_lists", return_value=self.LIST), \
             mock.patch.object(BF, "scanned", return_value={("lever", "known"), ("ashby", "acmeai")}), \
             mock.patch.object(BF.ats, "fetch", return_value=[]) as again:
            BF.run("2026-12-25", log=lambda *_: None, workers=1)
        again.assert_called_once()

    def test_the_crawl_index_runs_once_a_week(self):
        with mock.patch.object(BF, "_lists", return_value=[]), mock.patch.object(BF, "_crawl", return_value={}) as crawl, \
             mock.patch.object(BF.ats, "fetch", return_value=[]):
            BF.run("2026-11-20", log=lambda *_: None, workers=1)
            BF.run("2026-11-23", log=lambda *_: None, workers=1)
            BF.run("2026-11-27", log=lambda *_: None, workers=1)
        self.assertEqual(crawl.call_count, 2)

    def test_a_busy_crawl_index_is_skipped(self):
        busy = mock.Mock(status_code=504, text="<html>504 Gateway Time-out</html>")
        with mock.patch.object(BF.ats.http(), "get", return_value=busy) as get:
            self.assertIsNone(BF._crawl_host("jobs.ashbyhq.com/*", week=1))          # no answer: try again tomorrow
        get.assert_called_once()

    def test_crawl_index_lines_give_boards(self):
        lines = "\n".join(json.dumps({"url": u}) for u in ("https://jobs.ashbyhq.com/acme/1", "https://jobs.ashbyhq.com/acme/2",
                                                          "https://jobs.ashbyhq.com/beta", "https://jobs.ashbyhq.com/api/x"))
        pages = mock.Mock(status_code=200, text='{"pages": 1}')
        page = mock.Mock(status_code=200, text=lines)
        with mock.patch.object(BF.ats.http(), "get", side_effect=[pages, page]):
            self.assertEqual(BF._crawl_host("jobs.ashbyhq.com/*", week=1), {("ashby", "acme"), ("ashby", "beta")})


class CrawlTest(unittest.TestCase):
    def test_a_crawl_that_finds_nothing_is_tried_again_tomorrow(self):
        with mock.patch.object(BF, "_newest_index", return_value="https://index/x"),              mock.patch.object(BF, "_crawl_host", return_value=set()):
            self.assertIsNone(BF._crawl(week=1, log=lambda *_: None))
        with mock.patch.object(BF, "_newest_index", return_value="https://index/x"),              mock.patch.object(BF, "_crawl_host", side_effect=[None, {("ashby", "acme")}] + [set()] * 30):
            self.assertEqual(BF._crawl(week=1, log=lambda *_: None), {("ashby", "acme"): ""})


class ReaderTest(unittest.TestCase):
    def test_rippling_board_and_its_job_pages(self):
        board = {"items": [{"id": "1", "name": "Senior Backend Engineer", "url": "https://ats.rippling.com/acme/jobs/1",
                            "locations": [{"name": "Remote (US)", "workplaceType": "REMOTE"}]},
                           {"id": "2", "name": "Office Manager", "url": "https://ats.rippling.com/acme/jobs/2",
                            "locations": [{"name": "Austin, TX", "workplaceType": "ON_SITE"}]},
                           {"id": "3", "name": "Platform Engineer", "url": "https://ats.rippling.com/acme/jobs/3",
                            "locations": [{"name": "Berlin", "workplaceType": "HYBRID"}]}],
                 "page": 0, "pageSize": 100, "totalItems": 3, "totalPages": 1}
        post = {"createdOn": "2026-11-19T18:05:44.354000-07:00", "companyName": "Acme",
                "description": {"company": "<p>About Acme</p>", "role": "<p>Build <b>Go</b> services.</p>"}}
        with mock.patch.object(ats, "get", return_value=board), mock.patch.object(ats, "_rippling_post", return_value=post) as page:
            jobs = ats.fetch("acme", "rippling")
        self.assertEqual([(j["title"], j["location"]) for j in jobs],
                         [("Senior Backend Engineer", "Remote (US)"), ("Office Manager", "Austin, TX [On-site]"),
                          ("Platform Engineer", "Berlin [Hybrid]")])
        self.assertEqual(page.call_count, 2)                          # only engineering titles open their page
        self.assertEqual(jobs[0]["posted"], "2026-11-20")             # JST
        self.assertTrue(jobs[0]["description"].startswith("Build Go services."))
        self.assertIsNone(jobs[1]["posted"])

    def test_rippling_page_data(self):
        page = ('<html><script id="__NEXT_DATA__" type="application/json">' + json.dumps(
            {"props": {"pageProps": {"apiData": {"jobPost": {"name": "Engineer", "createdOn": "2026-11-19"}}}}}) + "</script></html>")
        with mock.patch.object(ats.http(), "get", return_value=mock.Mock(ok=True, text=page)):
            self.assertEqual(ats._rippling_post("https://ats.rippling.com/acme/jobs/1")["name"], "Engineer")
        with mock.patch.object(ats.http(), "get", return_value=mock.Mock(ok=False, text="")):
            self.assertEqual(ats._rippling_post("https://ats.rippling.com/acme/jobs/1"), {})

    def test_gem_board(self):
        d = [{"title": "Backend Engineer", "absolute_url": "https://jobs.gem.com/acme/a1", "location": {"name": "United States"},
              "location_type": "remote", "first_published_at": "2026-11-19T00:36:12.573Z", "content_plain": "Build APIs in Go."},
             {"title": "Product Engineer", "absolute_url": "https://jobs.gem.com/acme/a2", "location": {"name": "San Francisco"},
              "location_type": "hybrid", "created_at": "2026-11-01T00:00:00Z", "content": "<p>Hybrid role</p>"},
             {"title": "Data Engineer", "absolute_url": "https://jobs.gem.com/acme/a3", "location": {"name": "New York"},
              "location_type": "in_office", "first_published_at": "2026-11-18T00:00:00Z", "content_plain": "x"}]
        with mock.patch.object(ats, "get", return_value=d):
            jobs = ats.fetch("acme", "gem")
        self.assertEqual([j["location"] for j in jobs], ["Remote United States", "San Francisco [Hybrid]", "New York [On-site]"])
        self.assertEqual(jobs[0]["posted"], "2026-11-19")
        self.assertEqual(jobs[1]["description"], "Hybrid role")

    def test_oracle_career_site(self):
        lst = {"items": [{"requisitionList": [
            {"Id": "400099874", "Title": "Senior Software Engineer", "PostedDate": str(config.today()), "PrimaryLocation": "Dallas, TX, United States",
             "WorkplaceTypeCode": None, "WorkplaceType": "", "secondaryLocations": [{"Name": "Remote, United States"}]},
            {"Id": "400099875", "Title": "Personal Assistant", "PostedDate": "2026-11-19", "PrimaryLocation": "London, United Kingdom",
             "WorkplaceType": "", "secondaryLocations": []}]}]}
        det = {"items": [{"WorkplaceTypeCode": "ORA_WORKPLACE_TYPE_REMOTE", "WorkplaceType": "Remote",
                          "ExternalDescriptionStr": "<p>Build services.</p>", "ExternalQualificationsStr": "<ul><li>5+ years of Java</li></ul>"}]}
        calls = []

        def get(url, params=None, **kw):
            calls.append(url)
            return det if "Details" in url else lst
        with mock.patch.object(ats, "get", side_effect=get):
            jobs = ats.fetch("hdhe.fa.em3.oraclecloud.com|CX", "oracle", queries=("software engineer", "developer"))
        self.assertEqual([j["title"] for j in jobs], ["Senior Software Engineer", "Personal Assistant"])    # each job once
        self.assertEqual(jobs[0]["url"], "https://hdhe.fa.em3.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX/job/400099874")
        self.assertEqual(jobs[0]["location"], "Dallas, TX, United States / Remote, United States")    # already says remote
        self.assertIn("5+ years of Java", jobs[0]["description"])
        self.assertEqual(jobs[1]["location"], "London, United Kingdom")
        self.assertEqual(sum("Details" in u for u in calls), 1)                           # only engineering titles
        old = json.loads(json.dumps(lst))
        old["items"][0]["requisitionList"][0]["PostedDate"] = "2026-01-05"
        calls.clear()
        with mock.patch.object(ats, "get", side_effect=lambda url, params=None, **kw: calls.append(url) or (det if "Details" in url else old)):
            jobs = ats.fetch("hdhe.fa.em3.oraclecloud.com|CX", "oracle", queries=("software engineer",))
        self.assertFalse(any("Details" in u for u in calls))                              # an old post isn't opened
        self.assertNotIn("description", jobs[0])

    def test_a_job_system_that_answers_nothing(self):
        with mock.patch.object(ats, "get", return_value=None):
            for system, slug in (("rippling", "x"), ("gem", "x"), ("oracle", "h.oraclecloud.com|CX"), ("oracle", "bad")):
                self.assertEqual(ats.fetch(slug, system), [], system)


class ArbeitnowTest(unittest.TestCase):
    def test_remote_jobs_only(self):
        page = {"data": [{"slug": "a", "company_name": "Acme", "title": "Backend Engineer", "description": "<p>Go and Postgres</p>",
                          "remote": True, "url": "https://www.arbeitnow.com/jobs/companies/acme/backend-engineer-a",
                          "location": "Berlin", "created_at": 1795176044},
                         {"slug": "b", "company_name": "Beta", "title": "Developer", "description": "", "remote": False,
                          "url": "https://www.arbeitnow.com/jobs/b", "location": "Munich", "created_at": 1795176044}],
                "links": {"next": None}}
        with mock.patch.object(feeds, "get", return_value=page) as get:
            out = feeds.arbeitnow()
        get.assert_called_once()                                    # no next page
        self.assertEqual([(j["company"], j["location"], j["source"], j["ats"]) for j in out],
                         [("Acme", "Remote Berlin", "Arbeitnow", "feed")])
        self.assertEqual(out[0]["description"], "Go and Postgres")
        self.assertTrue(out[0]["posted"].startswith("2026-"))


class PostByLinkTest(unittest.TestCase):
    """Documents and the matcher read a post from its link."""

    def test_gem(self):
        posts = [{"id": "a1", "title": "Backend Engineer", "absolute_url": "https://jobs.gem.com/acme/a1",
                  "location": {"name": "Remote"}, "content_plain": "Build APIs."}]
        with mock.patch.object(jd.requests, "get", return_value=mock.Mock(json=lambda: posts)):
            got = jd.fetch("https://jobs.gem.com/acme/a1")
        self.assertEqual((got["title"], got["text"]), ("Backend Engineer", "Build APIs."))

    def test_oracle(self):
        det = {"items": [{"Title": "Senior Software Engineer", "PrimaryLocation": "Dallas, TX", "ExternalDescriptionStr": "<p>Build.</p>",
                          "ExternalQualificationsStr": "<p>5+ years</p>"}]}
        with mock.patch.object(jd.requests, "get", return_value=mock.Mock(json=lambda: det)) as get:
            got = jd.fetch("https://hdhe.fa.em3.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX/job/400099874")
        self.assertEqual(got["title"], "Senior Software Engineer")
        self.assertIn("5+ years", got["text"])
        self.assertIn('ById;Id="400099874",siteNumber=CX', str(get.call_args))

    def test_rippling(self):
        post = {"name": "Platform Engineer", "companyName": "Acme", "workLocations": ["Remote"],
                "description": {"company": "<p>About</p>", "role": "<p>Run Kubernetes.</p>"}}
        with mock.patch.object(ats, "_rippling_post", return_value=post):
            got = jd.fetch("https://ats.rippling.com/acme/jobs/1")
        self.assertEqual((got["title"], got["company"]), ("Platform Engineer", "Acme"))
        self.assertTrue(got["text"].startswith("Run Kubernetes."))


if __name__ == "__main__":
    unittest.main()

import contextlib
import html
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from teambid import config
from teambid.jobs import ats
from teambid.jobs import discover as D
from teambid.jobs import scanner


class DiscoverTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reg = mock.patch.object(D, "REGISTRY", Path(self.tmp.name) / "found-boards.json")
        self.reg.start()

    def tearDown(self):
        self.reg.stop()
        self.tmp.cleanup()

    def test_slugs(self):
        self.assertEqual(D.slugs("Grafana Labs")[:2], ["grafana", "grafanalabs"])
        self.assertIn("autorabit", D.slugs("AutoRABIT Holding Inc."))

    def test_board_kept_only_when_it_lists_the_same_job(self):
        boards = {("greenhouse", "acme"): [{"title": "Office Manager", "url": "u1"}],                 # another Acme
                  ("lever", "acme"): [{"title": "Backend Engineer", "url": "u2", "posted": "2025-01-02"}]}
        feed = [{"company": "Acme", "title": "Backend Engineer (Remote)", "source": "Himalayas", "ats": "feed"},
                {"company": "Nobody", "title": "Backend Engineer", "source": "Jobicy", "ats": "feed"}]
        with mock.patch.object(D.ats, "fetch", lambda s, a: boards.get((a, s), [])):
            jobs = D.run(feed, covered=set(), day="2026-10-26", log=lambda *_: None)
        self.assertEqual([(j["company"], j["source"], j["url"]) for j in jobs], [("Acme", "Company board", "u2")])
        reg = json.loads(D.REGISTRY.read_text())
        self.assertEqual(reg["boards"]["acme"]["careers"], "https://jobs.lever.co/acme")
        self.assertEqual(reg["misses"], {"nobody": "2026-10-26"})
        self.assertEqual(D.boards(), {("lever", "acme"): "Acme"})
        with mock.patch.object(D.ats, "fetch", side_effect=AssertionError("tried again")):      # known and missed: not again
            self.assertEqual(D.run(feed, set(), "2026-11-01", log=lambda *_: None), [])

    def test_the_newest_posts_are_checked_first(self):
        # a feed can date an old job today: that company's board is looked for the day it shows up, before the rest
        feed = [{"company": f"Big{i}", "title": t, "source": "Himalayas", "ats": "feed", "posted": "2026-11-01"}
                for i in range(3) for t in ("Backend Engineer", "Data Engineer", "Platform Engineer")]
        feed.append({"company": "Small", "title": "Senior Software Engineer", "source": "Himalayas", "ats": "feed",
                     "posted": "2026-11-09"})
        tried = []
        with mock.patch.object(D, "_probe", side_effect=lambda name, titles: tried.append(name)):
            D.run(feed, covered=set(), day="2026-11-09", log=lambda *_: None, limit=2, workers=1)
        self.assertEqual(tried, ["Small", "Big0"])                 # then the most jobs (ties keep their order)

    def test_a_zoho_recruit_board_gives_the_real_opening_date(self):
        # the feed dates the job today; the company's own board says when it was opened
        jobs = [{"id": "7001", "Posting_Title": "Senior Software Engineer", "Date_Opened": "2023-01-01", "Remote_Job": True,
                 "City": None, "State": None, "Country": None, "Publish": True, "Job_Description": "<p>Build <b>APIs</b>.</p>"},
                {"id": "7002", "Posting_Title": "Sales Lead", "Date_Opened": "2026-10-02", "Remote_Job": False,
                 "City": "Austin", "State": "Texas", "Country": "United States", "Publish": True}]
        page = (f'<html><input type="hidden" value="{html.escape(json.dumps([{"x": 1}]))}" id="meta">'
                f'<input type="hidden" value="{html.escape(json.dumps(jobs))}" id="jobs"></html>')
        resp = mock.Mock(ok=True, text=page)
        with mock.patch.object(ats, "http", return_value=mock.Mock(get=mock.Mock(return_value=resp))):
            got = ats.fetch("acme", "zohorecruit")
            with mock.patch.object(D.ats, "fetch", side_effect=lambda s, a: got if (s, a) == ("acme", "zohorecruit") else []):
                found = D.run([{"company": "Acme", "title": "Senior Software Engineer", "source": "Himalayas", "ats": "feed",
                                "posted": "2026-11-09"}], covered=set(), day="2026-11-09", log=lambda *_: None)
        self.assertEqual([(j["title"], j["posted"], j["location"], j["url"]) for j in got],
                         [("Senior Software Engineer", "2023-01-01", "Remote ",
                           "https://acme.zohorecruit.com/jobs/Careers/7001/Senior-Software-Engineer"),
                          ("Sales Lead", "2026-10-02", "Austin, Texas, United States",
                           "https://acme.zohorecruit.com/jobs/Careers/7002/Sales-Lead")])
        self.assertEqual(got[0]["description"], "Build APIs .")
        self.assertEqual([(j["company"], j["source"], j["posted"]) for j in found][:1], [("Acme", "Company board", "2023-01-01")])
        self.assertEqual(json.loads(D.REGISTRY.read_text())["boards"]["acme"]["careers"],
                         "https://acme.zohorecruit.com/jobs/Careers")


class FullScanTest(unittest.TestCase):
    """A full scan looks for the careers pages of feed-only companies (a counter once shadowed run()'s per_ats argument,
    and every full scan skipped the search); a quick test scan of some boards doesn't."""

    def scan(self, **kw):
        tmp = Path(tempfile.mkdtemp())
        names = ("himalayas", "remoteok", "remotive", "hackernews", "himalayas_countries", "jobicy", "fourdayweek",
                 "workingnomads", "getonboard", "djinni", "jobindex_dk", "jobtech_se", "github_br", "weworkremotely")
        feed = [{"company": "Acme", "title": "Backend Engineer", "url": "https://feed/1", "ats": "feed", "source": "Himalayas"}]
        patches = [
            mock.patch.object(config, "CACHE", tmp), mock.patch.object(config, "DB_PATH", tmp / "teambid.db"),
            mock.patch.object(scanner, "LOCK", tmp / "lock"), mock.patch.object(scanner, "MARK", tmp / "mark"),
            mock.patch.object(scanner, "load_boards", return_value=[("greenhouse", "other")]),
            mock.patch.object(scanner.discover, "boards", return_value={}),
            mock.patch.object(scanner.ats, "fetch", return_value=[{"company": "Other", "title": "Data Engineer",
                                                                    "url": "https://b/1", "ats": "greenhouse"}]),
            mock.patch.multiple(scanner.feeds, **{n: mock.Mock(return_value=list(feed) if n == "himalayas" else []) for n in names}),
            mock.patch.object(scanner, "_with_facts", side_effect=lambda js: js),
            mock.patch.object(scanner.facts, "build", return_value=(0, 0)), mock.patch.object(scanner.facts, "prune"),
            mock.patch.object(scanner.matcher, "match_all", return_value=[]), mock.patch.object(scanner, "write_team_report"),
            mock.patch.object(scanner.ats, "NetWatch", return_value=mock.Mock(stop=mock.Mock(return_value=0), windows=[])),
            mock.patch("teambid.jobs.forms.read_all"), mock.patch("teambid.jobs.company.refresh", return_value=(0, 0))]
        with contextlib.ExitStack() as stack:
            for pt in patches:
                stack.enter_context(pt)
            found = stack.enter_context(mock.patch.object(scanner.discover, "run", return_value=[]))
            self.assertEqual(scanner.run(log=lambda *_: None, workers=1, **kw), 0)
        return found

    def test_a_full_scan_looks_for_careers_pages(self):
        found = self.scan()
        found.assert_called_once()
        self.assertEqual([j["company"] for j in found.call_args[0][0]], ["Acme"])      # the feed's jobs
        self.assertEqual(found.call_args[0][1], {"other"})                             # companies the boards cover

    def test_a_quick_scan_of_some_boards_does_not(self):
        self.scan(per_ats=1).assert_not_called()

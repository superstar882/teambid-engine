import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from teambid.jobs import discover as D


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

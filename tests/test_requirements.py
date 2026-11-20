"""What a job requires: Claude's reading of the post (checked against it), the member's resume against each requirement,
and every listed job read first. No network: Claude and the job pages are stand-ins."""
import datetime as dt
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import requests

from teambid import config, llm, local_ai, storage, tailor
from teambid.jobs import facts as F
from teambid.jobs import matcher as M
from teambid.jobs import reqs

local_ai.DISABLED = True

TODAY = dt.date(2026, 10, 21)
POST = """About us
We build developer tools.

What we need to see:
- 8+ years experience in at least one of **Rust, Python, Go, or Node.js**, with working familiarity in at least one more.
- Solid understanding of asynchronous programming and event-driven systems.
- Proficiency in LLM applications, agent workflows and tool calls.

Ways to stand out from the crowd:
- Knowledge of OpenTelemetry, tracing or observability pipelines.
"""
READING = {"required": [
    {"name": "Rust, Python, Go or Node.js", "any": ["Rust", "Python", "Go", "Node.js"],
     "quote": "8+ years experience in at least one of Rust, Python, Go, or Node.js", "core": True},
    {"name": "Asynchronous programming", "any": ["asynchronous programming", "event-driven"],
     "quote": "Solid understanding of asynchronous programming", "core": False},
    {"name": "LLM applications", "any": ["LLM applications", "LLM", "tool calling"],
     "quote": "Proficiency in LLM applications, agent workflows and tool calls", "core": False},
    {"name": "Kubernetes", "any": ["Kubernetes"], "quote": "Deep Kubernetes operator experience", "core": True}],   # not in the post
    "preferred": [{"name": "OpenTelemetry", "any": ["OpenTelemetry", "tracing"], "quote": "Knowledge of OpenTelemetry, tracing"}],
    "years": 8}

MEMBER = {"name": "Test", "slug": "test", "prefs": {"countries": ["US"], "level": "senior", "days": 30, "lanes": ["backend"],
                                                    "target_titles": ["Software Engineer"]},
          "profile": {"years_experience": 9, "lanes": ["backend"],
                      "raw_text": "Senior engineer. Built event-driven order services in C# and .NET; asynchronous programming "
                                  "with Azure queues. Angular and TypeScript front ends. Kubernetes (k8s) deployments.",
                      "skills": {"proven": ["C#", ".NET", "Angular", "TypeScript", "Kubernetes", "LLMs"], "listed_only": []}}}
LANES = M._lane_pattern(["backend"])


def job(title="Senior Software Engineer", **kw):
    return {"id": 1, "title": title, "company": "Acme", "location": "Remote - US", "posted": "2026-10-20", **kw}


def item(name, *terms, core=False):
    return {"name": name, "any": list(terms or [name]), "core": core}


class ConfirmTest(unittest.TestCase):
    def test_only_requirements_quoted_from_the_post_are_kept(self):
        got = reqs.confirm(READING, POST)
        self.assertEqual([r["name"] for r in got["required"]], ["Rust, Python, Go or Node.js", "Asynchronous programming",
                                                                 "LLM applications"])     # Kubernetes isn't in the post
        self.assertTrue(got["required"][0]["core"])
        self.assertEqual([r["name"] for r in got["preferred"]], ["OpenTelemetry"])
        self.assertEqual(got["years"], 8)
        self.assertNotIn("quote", got["required"][0])

    def test_years_must_be_in_the_post(self):
        self.assertIsNone(reqs.confirm({**READING, "years": 12}, POST)["years"])
        self.assertIsNone(reqs.confirm({**READING, "years": "eight"}, POST)["years"])

    def test_at_most_three_core_requirements(self):
        many = {"required": [{"name": f"Skill {i}", "any": [f"skill{i}"], "quote": "Solid understanding of asynchronous programming",
                              "core": True} for i in range(5)]}
        self.assertEqual(sum(r["core"] for r in reqs.confirm(many, POST)["required"]), 3)

    def test_an_item_without_terms_is_dropped(self):
        bad = {"required": [{"name": "Async", "any": [], "quote": "Solid understanding of asynchronous programming"},
                            "not a dict"]}
        self.assertEqual(reqs.confirm(bad, POST)["required"], [])


class ReadTest(unittest.TestCase):
    def setUp(self):
        self.p = mock.patch.object(reqs, "PAUSE", 0)
        self.p.start()

    def tearDown(self):
        self.p.stop()

    def test_read_returns_the_checked_requirements(self):
        with mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm, "_call", return_value="```json\n" + json.dumps(READING) + "\n```") as call:
            got = reqs.read(POST, "Senior Software Engineer")
        self.assertEqual(len(got["required"]), 3)
        self.assertEqual(got["by"], reqs.MODEL)
        self.assertEqual(call.call_args[0][3], reqs.MODEL)

    def test_a_busy_api_is_tried_again(self):
        busy = requests.HTTPError(response=mock.Mock(status_code=429, headers={}))
        with mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm, "_call", side_effect=[busy, json.dumps(READING)]) as call:
            self.assertEqual(len(reqs.read(POST)["required"]), 3)
        self.assertEqual(call.call_count, 2)

    def test_no_key_or_a_broken_reply_reads_nothing(self):
        with mock.patch.object(llm, "available", return_value=False):
            self.assertIsNone(reqs.read(POST))
        bad = requests.HTTPError(response=mock.Mock(status_code=400, headers={}))
        with mock.patch.object(llm, "available", return_value=True), mock.patch.object(llm, "_call", side_effect=bad):
            self.assertIsNone(reqs.read(POST))
        with mock.patch.object(llm, "available", return_value=True), mock.patch.object(llm, "_call", return_value="no json"):
            self.assertIsNone(reqs.read(POST))


class ShowsTest(unittest.TestCase):
    def setUp(self):
        self.ev = M.evidence(MEMBER)

    def test_a_skill_by_any_of_its_names(self):
        self.assertEqual(M.shows(item("Container orchestration", "k8s"), *self.ev), "k8s")       # alias of Kubernetes
        self.assertEqual(M.shows(item("LLM apps", "LLM applications", "LLM"), *self.ev), "LLM")

    def test_a_phrase_in_the_resume(self):
        self.assertEqual(M.shows(item("Async", "asynchronous programming"), *self.ev), "asynchronous programming")
        self.assertEqual(M.shows(item("Device drivers", "device drivers", "kernel drivers"), *self.ev), "")

    def test_a_skill_inside_a_longer_term_doesnt_count(self):
        prof = {**MEMBER["profile"], "skills": {"proven": ["Python"], "listed_only": []}, "raw_text": "Python services."}
        ev = M.evidence({**MEMBER, "profile": prof})
        self.assertEqual(M.shows(item("Python native extensions", "Python native extensions", "PyO3"), *ev), "")
        self.assertEqual(M.shows(item("Python", "Python"), *ev), "Python")

    def test_short_generic_words_dont_count(self):
        self.assertEqual(M.shows(item("AI", "AI"), *M.evidence({**MEMBER, "profile": {**MEMBER["profile"],
                                                                                   "raw_text": "AI tools"}})), "")


class RequirementScoringTest(unittest.TestCase):
    def facts(self, required, preferred=(), years=None, **kw):
        return {"must": ["C#"], "nice": [], "years": 2, "req": {"required": list(required), "preferred": list(preferred),
                                                                 "years": years, "by": reqs.MODEL}, **kw}

    def test_a_missing_core_requirement_drops_the_job(self):
        f = self.facts([item("Rust, Python, Go or Node.js", "Rust", "Python", "Go", "Node.js", core=True),
                        item("Async", "asynchronous programming"), item("LLMs", "LLM")])
        self.assertEqual(M.score_job(job(), MEMBER, LANES, TODAY, f), (None, "core"))

    def test_a_post_about_hardware_doesnt_match_a_web_developer(self):
        f = self.facts([item("Multicore hardware", "multicore"), item("Operating systems", "operating systems", "OS internals", core=True),
                        item("Device drivers", "device drivers"), item("Concurrency", "concurrency", "multithreading")])
        self.assertEqual(M.score_job(job("Senior System Software Engineer"), MEMBER, LANES, TODAY, f)[0], None)

    def test_low_coverage_drops_the_job(self):
        f = self.facts([item("C#", "C#"), item("Ruby", "Ruby"), item("Elixir", "Elixir"), item("Scala", "Scala")])
        self.assertEqual(M.score_job(job(), MEMBER, LANES, TODAY, f), (None, "skills"))

    def test_claudes_reading_decides_over_the_rules(self):
        f = self.facts([item("C#", "C#", core=True), item(".NET", ".NET"), item("Async", "asynchronous programming"),
                        item("Kafka", "Kafka")], [item("Angular", "Angular")], years=5)
        sc, why = M.score_job(job(), MEMBER, LANES, TODAY, f)
        self.assertIn("has 3 of 4 required skills", why)
        self.assertIn("missing: Kafka", why)
        self.assertIn("asks 5+ years: you have 9", why)           # Claude's years, not the rules' 2

    def test_requirements_outweigh_the_title(self):
        full = self.facts([item("C#", "C#"), item(".NET", ".NET"), item("Angular", "Angular")])
        half = self.facts([item("C#", "C#"), item(".NET", ".NET"), item("Kafka", "Kafka"), item("Go", "Go")])
        best, _ = M.score_job(job(), MEMBER, LANES, TODAY, full)
        some, _ = M.score_job(job(), MEMBER, LANES, TODAY, half)
        self.assertGreaterEqual(best, 75)
        self.assertLess(some, 60)                                  # half the requirements is not a best match

    def test_the_rules_skills_when_claude_found_none(self):
        f = {"must": ["C#", "Ruby", "Elixir", "Scala", "Rust"], "years": None, "req": {"required": [], "preferred": [], "years": None}}
        self.assertEqual(M.score_job(job(), MEMBER, LANES, TODAY, f), (None, "skills"))
        sc, why = M.score_job(job(), MEMBER, LANES, TODAY, {"must": [], "years": None})
        self.assertIn("post names no specific skills", why)
        self.assertLess(sc, 60)


class HeadingsTest(unittest.TestCase):
    def test_more_ways_posts_name_their_requirements(self):
        jd = tailor.analyze_jd(POST + "\nBenefits\n- Python lunch club\n", "Senior Software Engineer")
        self.assertIn("Rust", jd["required"])
        self.assertIn("OpenTelemetry", jd["preferred"])
        self.assertNotIn("OpenTelemetry", jd["required"])
        md = tailor.analyze_jd("#### **What you bring:**\n- Kafka and Airflow\n#### **Bonus points:**\n- dbt\n"
                               "#### **What you will be doing**\n- Talk to Snowflake users\n", "Data Engineer")
        self.assertEqual(md["required"], ["Kafka", "Airflow"])
        self.assertEqual(md["preferred"], ["dbt"])
        for head in ("Required qualifications", "What we look for", "Your expertise:", "What makes you a great fit"):
            self.assertEqual(tailor.analyze_jd(f"{head}\n- Kafka\nAbout us\n- Airflow\n")["required"], ["Kafka"], head)


class PrefetchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="teambid-req-"))
        self.old = config.DB_PATH
        config.DB_PATH = self.tmp / "t.db"
        self.p = mock.patch.object(M, "READ_PAUSE", 0)
        self.p.start()

    def tearDown(self):
        self.p.stop()
        config.DB_PATH = self.old

    def jobs(self, con, n, host="acme.wd5.myworkdayjobs.com"):
        storage.upsert_jobs(con, [{"url": f"https://{host}/x/job/{i}", "company": "Acme", "title": "Engineer", "ats": "workday"}
                                  for i in range(n)], "2026-10-21")
        return [dict(r) for r in con.execute("SELECT * FROM jobs ORDER BY id")]

    def test_a_failed_read_is_tried_again(self):
        calls = []

        def fetch(url):
            calls.append(url)
            if len(calls) == 1:
                raise requests.ConnectionError("reset")
            return {"text": "A real post. " * 60}
        with storage.connect() as con:
            js = self.jobs(con, 1)
            with mock.patch.object(M.JD, "fetch", side_effect=fetch):
                M._prefetch_jds(con, js)
            self.assertEqual(len(calls), 2)
            self.assertTrue(storage.get_jd(con, js[0]["id"]).startswith("A real post."))

    def test_a_post_that_couldnt_be_read_is_read_next_time(self):
        with storage.connect() as con:
            js = self.jobs(con, 1)
            with mock.patch.object(M.JD, "fetch", return_value={"text": "Loading..."}):     # a page shell, not the post
                M._prefetch_jds(con, js)
            self.assertEqual(storage.get_jd(con, js[0]["id"]), "")
            with mock.patch.object(M.JD, "fetch", return_value={"text": "The post. " * 60}) as fetch:
                M._prefetch_jds(con, js)
            fetch.assert_called_once()
            self.assertTrue(storage.get_jd(con, js[0]["id"]).startswith("The post."))

    def test_one_site_gets_a_few_requests_at_a_time(self):
        now, most, lock = [0], [0], threading.Lock()

        def fetch(url):
            with lock:
                now[0] += 1
                most[0] = max(most[0], now[0])
            time.sleep(0.02)
            with lock:
                now[0] -= 1
            return {"text": "The post. " * 60}
        with storage.connect() as con:
            js = self.jobs(con, 12)
            with mock.patch.object(M.JD, "fetch", side_effect=fetch):
                M._prefetch_jds(con, js)
        self.assertLessEqual(most[0], M.PER_SITE)


class MatchReadsEveryJobTest(unittest.TestCase):
    """A whole match run: unread posts aren't listed, Claude reads each candidate once, its reading decides."""
    DAY = str(config.today())
    POSTS = {"https://acme.wd5.myworkdayjobs.com/x/job/agents": POST,
             "https://boards.greenhouse.io/acme/jobs/7": "Requirements\n- 5+ years of C# and .NET\n- SQL Server\n" * 20}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="teambid-req-"))
        self.old = config.DB_PATH, config.MEMBERS
        config.DB_PATH, config.MEMBERS = self.tmp / "t.db", self.tmp / "members"
        self.patches = [mock.patch.object(M, "READ_PAUSE", 0), mock.patch.object(reqs, "PAUSE", 0),
                        mock.patch.object(llm, "available", return_value=True),
                        mock.patch("teambid.jobs.forms.read", return_value=None)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        config.DB_PATH, config.MEMBERS = self.old

    def claude(self, system, user, *a, **k):
        if "SQL Server" in user:
            return json.dumps({"required": [{"name": "C# and .NET", "any": ["C#", ".NET"], "quote": "5+ years of C# and .NET",
                                             "core": True}, {"name": "SQL Server", "any": ["SQL Server"], "quote": "SQL Server"}],
                               "preferred": [], "years": 5})
        return json.dumps(READING)

    def fetch(self, url):
        if url not in self.POSTS:
            raise requests.ConnectionError("blocked")
        return {"text": self.POSTS[url]}

    def test_match_run(self):
        prof = {**MEMBER["profile"], "skills": {"proven": ["C#", ".NET", "SQL Server", "Angular"], "listed_only": []}}
        jobs = [{"url": u, "company": "Acme", "title": t, "location": "Remote - US", "ats": a, "source": "Company board",
                 "posted": self.DAY} for u, t, a in (
            ("https://acme.wd5.myworkdayjobs.com/x/job/agents", "Senior Software Engineer, Agentic AI", "workday"),
            ("https://boards.greenhouse.io/acme/jobs/7", "Senior Backend Engineer", "greenhouse"),
            ("https://acme.wd5.myworkdayjobs.com/x/job/blocked", "Senior Software Engineer, Platform", "workday"))]
        with storage.connect() as con:
            storage.upsert_jobs(con, jobs, self.DAY)
            mid, slug = storage.save_member(con, "Pat Example", prof, MEMBER["prefs"])
            member = storage.member(con, slug)
            with mock.patch.object(M.JD, "fetch", side_effect=self.fetch), \
                 mock.patch.object(llm, "_call", side_effect=self.claude) as call:
                res = M.match_member(con, member, log=lambda *_: None)
                rows = {r["title"]: json.loads(r["reasons"]) for r in con.execute(
                    "SELECT j.title, m.reasons FROM matches m JOIN jobs j ON j.id=m.job_id WHERE m.member_id=?", (mid,))}
                self.assertEqual(list(rows), ["Senior Backend Engineer"])
                self.assertIn("has 2 of 2 required skills", rows["Senior Backend Engineer"])
                self.assertEqual(res["filtered"].get("core"), 1)          # the agents job wants Rust, Python, Go or Node.js
                self.assertEqual(res["filtered"].get("unread"), 1)        # the blocked post was never read: not listed
                self.assertEqual(call.call_count, 2)
                saved = F.load(con)
                self.assertTrue(all("req" in f for f in saved.values()))
                M.match_member(con, member, log=lambda *_: None)          # the next run reads nothing again
                self.assertEqual(call.call_count, 2)

    def test_the_scans_texts_are_read_without_fetching(self):
        url = "https://jobs.lever.co/acme/0f5e1c2a-1111-2222-3333-444455556666"
        with storage.connect() as con:
            storage.upsert_jobs(con, [{"url": url, "company": "Acme", "title": "Senior Backend Engineer", "location": "Remote - US",
                                       "ats": "lever", "source": "Company board", "posted": self.DAY}], self.DAY)
            jid = con.execute("SELECT id FROM jobs").fetchone()["id"]
            F.save(con, [(jid, F.analyze(self.POSTS["https://boards.greenhouse.io/acme/jobs/7"], "Senior Backend Engineer"))], self.DAY)
            _, slug = storage.save_member(con, "Pat Example", {**MEMBER["profile"], "skills": {"proven": ["C#", ".NET", "SQL Server"]}},
                                          MEMBER["prefs"])
            with mock.patch.object(M.JD, "fetch", side_effect=AssertionError("no fetching")), \
                 mock.patch.object(llm, "_call", side_effect=self.claude):
                M.match_member(con, storage.member(con, slug), log=lambda *_: None,
                               texts={storage.url_key(url): self.POSTS["https://boards.greenhouse.io/acme/jobs/7"]})
            self.assertEqual(F.load(con)[jid]["req"]["required"][0]["name"], "C# and .NET")


class RematchAllTest(unittest.TestCase):
    def test_the_whole_team_in_one_run_named_by_log_codes(self):
        from teambid import service
        tmp = Path(tempfile.mkdtemp(prefix="teambid-req-"))
        old, config.DB_PATH = config.DB_PATH, tmp / "t.db"
        try:
            with storage.connect() as con:
                for name in ("Pat Example", "Sam Sample"):
                    storage.save_member(con, name, MEMBER["profile"], MEMBER["prefs"])
            with mock.patch.object(M, "match_member", side_effect=lambda con, m, **k: {"name": m["name"], "matches": 1}) as mm:
                got = service.rematch("all")
            self.assertEqual(mm.call_count, 2)
            self.assertEqual(sorted(r["name"] for r in got), sorted(config.who(s) for s in ("pat-example", "sam-sample")))
            self.assertNotIn("Pat", json.dumps(got))
        finally:
            config.DB_PATH = old


class FactsKeepTest(unittest.TestCase):
    def test_a_rebuild_keeps_the_form_and_claudes_reading(self):
        tmp = Path(tempfile.mkdtemp(prefix="teambid-req-"))
        old, config.DB_PATH = config.DB_PATH, tmp / "t.db"
        try:
            url = "https://boards.greenhouse.io/acme/jobs/9"
            with storage.connect() as con:
                storage.upsert_jobs(con, [{"url": url, "company": "Acme", "title": "Backend Engineer"}], "2026-10-21")
                jid = con.execute("SELECT id FROM jobs").fetchone()["id"]
                F.save(con, [(jid, {"v": F.VERSION - 1, "form": {"us_only": True}, "req": {"required": [item("C#")]}})], "2026-10-20")
                F.build(con, [{"url": url, "title": "Backend Engineer", "description": "Requirements\n- Python\n" * 30}],
                        "2026-10-21", processes=1)
                f = F.load(con)[jid]
            self.assertEqual(f["v"], F.VERSION)
            self.assertEqual(f["form"], {"us_only": True})
            self.assertEqual(f["req"]["required"][0]["name"], "C#")
        finally:
            config.DB_PATH = old


if __name__ == "__main__":
    unittest.main()

import json
import unittest
from unittest import mock

from teambid import docs, llm


class QueueTest(unittest.TestCase):
    def test_joins_parts_skips_done_and_incomplete(self):
        e = {
            "a": {"kind": "docreq", "rid": "r1", "member": "maya", "parts": 2, "at": "2026-10-20T10:00"},
            "b": {"kind": "docpart", "rid": "r1", "n": 1, "text": "world"},
            "c": {"kind": "docpart", "rid": "r1", "n": 0, "text": "hello "},
            "d": {"kind": "docreq", "rid": "r2", "member": "maya", "parts": 0, "url": "https://x", "at": "2026-10-20T09:00"},
            "e": {"kind": "docdone", "rid": "r2", "member": "maya"},
            "f": {"kind": "docreq", "rid": "r3", "member": "maya", "parts": 3, "at": "2026-10-20T11:00"},   # parts still uploading
            "g": {"member": "maya", "job": "x", "status": "saved"},                                       # plain progress row
        }
        q = docs.queue(e)
        self.assertEqual([x["rid"] for x in q], ["r1"])
        self.assertEqual(q[0]["text"], "hello world")


PROFILE = {"name": "Maya Chen", "raw_text": "Cut page load time 40% for 40,000 users with React and TypeScript",
           "skills": {"all": ["React", "TypeScript"]},
           "roles": [{"company": "Acme", "title": "Frontend Engineer", "bullets": [{"text": "Cut page load time 40% for 40,000 users with React and TypeScript"}]}]}
SPEC = {"summary": "Frontend engineer who ships fast React apps.",
        "roles": [{"company": "Acme", "title": "Frontend Engineer", "bullets": ["Cut page load time 40% for 40,000 users with React and TypeScript"]}]}


class ClaudeGuardTest(unittest.TestCase):
    def _run(self, reply):
        with mock.patch.object(llm, "available", return_value=True), mock.patch.object(llm, "_call", return_value=json.dumps(reply)):
            return llm.rewrite_resume(SPEC, PROFILE, "We need React performance work for our checkout.")

    def test_honest_rewording_is_kept_and_mapped_back(self):
        new = "Cut checkout page load time 40% for 40,000 users with React and TypeScript"
        spec, note = self._run({"summary": SPEC["summary"], "bullets": {"r0b0": new}})
        self.assertEqual(spec["roles"][0]["bullets"][0], new)
        self.assertEqual(spec["rewritten"][new], SPEC["roles"][0]["bullets"][0])

    def test_changed_number_or_new_tool_is_rejected(self):
        for bad in ("Cut page load time 60% for 40,000 users with React and TypeScript",
                    "Cut page load time 40% for 40,000 users with React, TypeScript and Kubernetes"):
            spec, _ = self._run({"summary": SPEC["summary"], "bullets": {"r0b0": bad}})
            self.assertEqual(spec["roles"][0]["bullets"][0], SPEC["roles"][0]["bullets"][0], bad)


if __name__ == "__main__":
    unittest.main()

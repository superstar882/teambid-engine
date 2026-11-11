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

    def test_oldest_first_by_the_time_the_server_saved_it(self):
        # "at" is the sender's own clock, which can be hours off; "saved_at" is the database's
        e = {"a": {"kind": "docreq", "rid": "fast-clock", "parts": 0, "url": "https://x", "at": "2026-11-11T19:22:20Z",
                   "saved_at": "2026-11-11T10:22:32.653132+00:00"},
             "b": {"kind": "docreq", "rid": "later", "parts": 0, "url": "https://y", "at": "2026-11-11T15:20:09Z",
                   "saved_at": "2026-11-11T15:20:10.294053+00:00"}}
        self.assertEqual([x["rid"] for x in docs.queue(e)], ["fast-clock", "later"])


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

    def test_a_reply_without_json_says_so(self):
        with mock.patch.object(llm, "available", return_value=True), mock.patch.object(llm, "_call", return_value="Sorry."):
            spec, note = llm.rewrite_resume(SPEC, PROFILE, "We need React.")
        self.assertEqual(spec, SPEC)
        self.assertEqual(note, "Claude resume step skipped: no JSON in Claude's reply")


def api_reply(text, stop="end_turn"):
    r = mock.Mock(status_code=200)
    r.json.return_value = {"stop_reason": stop, "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": text}]}
    return r


class ClaudeCallTest(unittest.TestCase):
    """The models think before they answer and the thinking counts toward max_tokens (Haiku used 7,272 of 8,000 on
    one resume and the JSON stopped mid-bullet), so a reply cut off at the limit is an error, never half a text."""

    def test_returns_the_text_blocks(self):
        with mock.patch.object(llm.requests, "post", return_value=api_reply("Hi Acme team,")):
            self.assertEqual(llm._call("rules", "facts"), "Hi Acme team,")

    def test_a_reply_cut_off_at_the_limit_is_an_error(self):
        with mock.patch.object(llm.requests, "post", return_value=api_reply('{"bullets": {"r0b0": "Built a sc', "max_tokens")):
            with self.assertRaisesRegex(RuntimeError, "cut off at the 16,000-token limit"):
                llm._call("rules", "facts")

    def test_a_cut_off_letter_keeps_the_fact_only_draft(self):
        with mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm.requests, "post", return_value=api_reply("Hi Acme team,\n\nI build", "max_tokens")):
            text, note = llm.write_letter(PROFILE, "We need React.", "Acme", "Frontend Engineer", "the draft")
        self.assertEqual(text, "the draft")
        self.assertIn("cut off", note)

    def test_every_call_leaves_room_to_think_and_answer(self):
        with mock.patch.object(llm, "available", return_value=True), \
             mock.patch.object(llm.requests, "post", return_value=api_reply("{}")) as post:
            llm.write_letter(PROFILE, "We need React.", "Acme", "Frontend Engineer", "the draft")     # asked twice: "{}" is rejected
            llm.rewrite_resume(SPEC, PROFILE, "We need React.")
            llm.read_resume("Maya Chen\nFrontend Engineer")
        self.assertEqual([c.kwargs["json"]["max_tokens"] for c in post.call_args_list], [16000, 16000, 16000, 32000])


if __name__ == "__main__":
    unittest.main()

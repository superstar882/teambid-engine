"""The results website must never contain readable member data, and the browser must be able to decrypt it."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from teambid import export  # noqa: E402

SAMPLE = {"generated": "now", "last_scan": "2026-10-20", "members": [{"name": "Test Person Secretname", "contact": {"email": "x@y.z"}}]}


class Encryption(unittest.TestCase):
    def test_roundtrip_and_wrong_password(self):
        blob = export.encrypt(SAMPLE, "correct horse battery staple")
        self.assertNotIn("Secretname", json.dumps(blob))
        self.assertEqual(export.decrypt(blob, "correct horse battery staple"), SAMPLE)
        with self.assertRaises(Exception):
            export.decrypt(blob, "wrong password here")

    def test_fresh_salt_and_iv(self):
        a, b = export.encrypt(SAMPLE, "same password 123"), export.encrypt(SAMPLE, "same password 123")
        self.assertNotEqual(a["salt"], b["salt"])
        self.assertNotEqual(a["iv"], b["iv"])

    def test_short_password_rejected(self):
        with self.assertRaises(RuntimeError):
            export.set_password("short")


if __name__ == "__main__":
    unittest.main()

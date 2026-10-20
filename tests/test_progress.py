"""Team progress: encrypted, unlinkable item ids, junk rows ignored (offline; no Supabase calls)."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from teambid import progress  # noqa: E402

SB = {"salt": "AAECAwQFBgcICQoLDA0ODw==", "iterations": 1000}


class Progress(unittest.TestCase):
    def setUp(self):
        self.aes, self.mac = progress.keys("team password 123", SB)

    def test_seal_roundtrip_hides_content(self):
        p = progress.seal(self.aes, {"member": "maya-chen", "status": "applied", "note": "referral from Sam"})
        self.assertNotIn("maya", p)
        self.assertEqual(progress.unseal(self.aes, p)["status"], "applied")

    def test_item_ids_stable_and_private(self):
        a = progress.item_id(self.mac, "maya-chen", "jobs.lever.co/x/1")
        self.assertEqual(a, progress.item_id(self.mac, "maya-chen", "jobs.lever.co/x/1"))
        self.assertNotEqual(a, progress.item_id(self.mac, "raj-patel", "jobs.lever.co/x/1"))
        self.assertNotIn("maya", a)
        other, mac2 = progress.keys("a different password", SB)
        self.assertNotEqual(a, progress.item_id(mac2, "maya-chen", "jobs.lever.co/x/1"))

    def test_junk_and_wrong_key_rejected(self):
        with self.assertRaises(Exception):
            progress.unseal(self.aes, "bm90IHJlYWwgZGF0YSBhdCBhbGwgMTIzNDU2Nzg5MA==")
        wrong, _ = progress.keys("wrong password 999", SB)
        with self.assertRaises(Exception):
            progress.unseal(wrong, progress.seal(self.aes, {"status": "offer"}))


if __name__ == "__main__":
    unittest.main()

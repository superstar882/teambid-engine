import sqlite3
import tempfile
import unittest
from pathlib import Path

from teambid import cloud


class CloudBundleTest(unittest.TestCase):
    def test_round_trip_keeps_data_and_skips_secrets(self):
        with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
            src, dst = Path(a), Path(b)
            con = sqlite3.connect(src / "teambid.db")
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("CREATE TABLE t (x TEXT)")
            con.execute("INSERT INTO t VALUES ('hello')")
            con.commit()                                   # left open: the row may only be in the WAL file
            (src / "members" / "maya" / "vault").mkdir(parents=True)
            (src / "members" / "maya" / "vault" / "notes.md").write_text("vault", encoding="utf-8")
            (src / "cache").mkdir()
            (src / "cache" / "embeddings.sqlite").write_bytes(b"emb")
            (src / "cache" / "remotive-2026-10-20.json").write_text("{}", encoding="utf-8")
            (src / ".site-password").write_text("secret", encoding="utf-8")
            (src / ".publish.json").write_text("{}", encoding="utf-8")

            blob = cloud.encrypt_bytes(cloud.pack(src), "team pw")
            con.close()
            self.assertNotIn(b"hello", blob)
            with self.assertRaises(ValueError):
                cloud.decrypt_bytes(blob, "wrong")

            (dst / "teambid.db").write_bytes(b"old")       # an older local copy gets backed up, not lost
            cloud.unpack(cloud.decrypt_bytes(blob, "team pw"), dst)
            got = sqlite3.connect(dst / "teambid.db")
            self.assertEqual(got.execute("SELECT x FROM t").fetchone()[0], "hello")
            got.close()
            self.assertEqual((dst / "members" / "maya" / "vault" / "notes.md").read_text(encoding="utf-8"), "vault")
            self.assertTrue((dst / "cache" / "embeddings.sqlite").exists())
            self.assertEqual(len(list((dst / "backups").glob("teambid-*.db"))), 1)
            for gone in (".site-password", ".publish.json", "cache/remotive-2026-10-20.json"):
                self.assertFalse((dst / gone).exists(), gone)


if __name__ == "__main__":
    unittest.main()

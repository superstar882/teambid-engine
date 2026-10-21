import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "teambid" / "static"
SMOKE = Path(__file__).resolve().parent / "page_smoke.cjs"


@unittest.skipUnless(shutil.which("node"), "node not installed")
class PageScriptTest(unittest.TestCase):
    """Runs each page's script top to bottom in a fake browser (with a remembered password set), so errors such as
    using a helper before it is defined (which left the team page stuck on the lock screen) fail here, not live."""

    def check(self, name):
        js = "\n".join(re.findall(r"<script>(.*?)</script>", (STATIC / name).read_text(encoding="utf-8"), re.S))
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "page.js"
            f.write_text(js, encoding="utf-8")
            r = subprocess.run(["node", "--check", str(f)], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            r = subprocess.run(["node", str(SMOKE), str(f)], capture_output=True, text=True, timeout=60)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_results_page(self):
        self.check("results.html")

    def test_local_app(self):
        self.check("index.html")


if __name__ == "__main__":
    unittest.main()

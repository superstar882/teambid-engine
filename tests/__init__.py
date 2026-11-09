"""Tests never touch a real workspace: TeamBid's paths point at a throwaway folder before any test module loads, also when
one test file runs on its own (python -m unittest tests.test_discover) or tb.py imported config first."""
import os
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="teambid-test-"))
os.environ["TEAMBID_WORKSPACE"] = str(_TMP)
if "teambid.config" in sys.modules:
    _c = sys.modules["teambid.config"]
    _c.WORKSPACE, _c.DB_PATH, _c.MEMBERS, _c.CACHE, _c.REPORTS = (_TMP, _TMP / "teambid.db", _TMP / "members", _TMP / "cache",
                                                                  _TMP / "reports")

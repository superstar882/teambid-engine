"""Paths and settings. Everything a member creates lives under WORKSPACE (local disk, never uploaded anywhere).

Override with environment variables:
  TEAMBID_WORKSPACE   where the database and member folders live (default: <project>/workspace)
  TEAMBID_TZ          time zone for dates in files and reports (default America/Los_Angeles)
  TEAMBID_SCAN_TZ / TEAMBID_SCAN_HOUR   when the daily scan is due (default Asia/Tokyo 17:00)
  ANTHROPIC_API_KEY   optional: better resume parsing and writing through the Claude API
  TEAMBID_MODEL       Claude model for the optional API features (default claude-sonnet-5-5)
"""
import datetime as dt
import os
from pathlib import Path
from zoneinfo import ZoneInfo

PROJECT = Path(__file__).resolve().parent.parent
DATA = PROJECT / "data"                      # shipped data: boards list, seed companies, knowledge
WORKSPACE = Path(os.environ.get("TEAMBID_WORKSPACE", PROJECT / "workspace"))
DB_PATH = WORKSPACE / "teambid.db"
MEMBERS = WORKSPACE / "members"
CACHE = WORKSPACE / "cache"
REPORTS = WORKSPACE / "reports"              # team-level scan reports

BOARDS = DATA / "boards.json"
SEED_COMPANIES = DATA / "seed_companies.yaml"
KNOWLEDGE = DATA / "knowledge"

TZ = ZoneInfo(os.environ.get("TEAMBID_TZ", "America/Los_Angeles"))
SCAN_TZ = ZoneInfo(os.environ.get("TEAMBID_SCAN_TZ", "Asia/Tokyo"))
SCAN_HOUR = int(os.environ.get("TEAMBID_SCAN_HOUR", "17"))   # 3 h after Quick Bid's 14:00 scan, so they never overlap

KEY_FILE = WORKSPACE / ".anthropic-key"      # set with "tb.py claude-key"; never uploaded
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "") or (KEY_FILE.read_text(encoding="utf-8").strip() if KEY_FILE.exists() else "")
MODEL = os.environ.get("TEAMBID_MODEL", "claude-sonnet-5-5")

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"


def now():
    return dt.datetime.now(TZ)


def today():
    return now().date()


def ensure_dirs():
    for p in (WORKSPACE, MEMBERS, CACHE, REPORTS):
        p.mkdir(parents=True, exist_ok=True)


def member_dir(slug):
    d = MEMBERS / slug
    for sub in ("resume", "vault", "applications", "reports"):
        (d / sub).mkdir(parents=True, exist_ok=True)
    return d

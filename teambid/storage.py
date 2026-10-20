"""SQLite storage shared by the whole team.

Tables
  members       one row per person: profile (parsed resume facts) and preferences, both JSON
  jobs          every open job seen by the shared scan (one row per posting, identity = normalized URL)
  jd            cached job-description text for jobs someone looked at closely
  matches       member x job: score, tier, reasons, status (new / shortlisted / skipped)
  applications  what a member is actually working on: tailored docs, status pipeline, notes
  events        history of status changes
  runs          one row per scan / match run with full stats as JSON
"""
import json
import re
import sqlite3
from contextlib import contextmanager

from . import config

APP_STATUSES = ("drafting", "applied", "interview", "offer", "rejected", "withdrawn", "closed")
MATCH_STATUSES = ("new", "shortlisted", "skipped", "applying")

SCHEMA = """
CREATE TABLE IF NOT EXISTS members (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slug TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  email TEXT,
  profile TEXT NOT NULL DEFAULT '{}',
  prefs TEXT NOT NULL DEFAULT '{}',
  resume_file TEXT,
  created TEXT NOT NULL,
  updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url_key TEXT NOT NULL UNIQUE,
  url TEXT NOT NULL,
  company TEXT NOT NULL,
  title TEXT NOT NULL,
  location TEXT,
  ats TEXT,
  source TEXT,
  posted TEXT,
  first_seen TEXT NOT NULL,
  last_seen TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS jobs_last_seen ON jobs(last_seen);
CREATE TABLE IF NOT EXISTS jd (
  job_id INTEGER PRIMARY KEY REFERENCES jobs(id),
  text TEXT NOT NULL,
  fetched TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS matches (
  member_id INTEGER NOT NULL REFERENCES members(id),
  job_id INTEGER NOT NULL REFERENCES jobs(id),
  score INTEGER NOT NULL,
  tier TEXT NOT NULL,
  reasons TEXT,
  status TEXT NOT NULL DEFAULT 'new',
  first_matched TEXT NOT NULL,
  last_matched TEXT NOT NULL,
  PRIMARY KEY (member_id, job_id)
);
CREATE INDEX IF NOT EXISTS matches_member ON matches(member_id, first_matched);
CREATE TABLE IF NOT EXISTS applications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  member_id INTEGER NOT NULL REFERENCES members(id),
  job_id INTEGER REFERENCES jobs(id),
  company TEXT NOT NULL,
  title TEXT NOT NULL,
  url TEXT,
  folder TEXT,
  status TEXT NOT NULL DEFAULT 'drafting',
  fit INTEGER,
  notes TEXT,
  created TEXT NOT NULL,
  updated TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  member_id INTEGER, application_id INTEGER, job_id INTEGER,
  at TEXT NOT NULL, status TEXT NOT NULL, note TEXT
);
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  started TEXT NOT NULL,
  finished TEXT,
  secs INTEGER,
  stats TEXT
);
"""


def url_key(url):
    u = re.sub(r"[?#].*$", "", (url or "").strip().lower())
    u = re.sub(r"/(apply|application)(/.*)?$", "", u)
    return re.sub(r"^https?://(www\.)?", "", u).rstrip("/")


@contextmanager
def connect():
    config.ensure_dirs()
    con = sqlite3.connect(config.DB_PATH, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")      # the UI can read while a scan writes
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript(SCHEMA)
    try:
        yield con
        con.commit()
    finally:
        con.close()


def stamp():
    return config.now().strftime("%Y-%m-%d %H:%M")


# ---------- members ----------
def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "member"


def save_member(con, name, profile, prefs, resume_file=None, email=None, slug=None):
    slug = slug or slugify(name)
    row = con.execute("SELECT id FROM members WHERE slug=?", (slug,)).fetchone()
    if row:
        con.execute("UPDATE members SET name=?, email=COALESCE(?, email), profile=?, prefs=?, "
                    "resume_file=COALESCE(?, resume_file), updated=? WHERE id=?",
                    (name, email, json.dumps(profile), json.dumps(prefs), resume_file, stamp(), row["id"]))
        return row["id"], slug
    cur = con.execute("INSERT INTO members (slug, name, email, profile, prefs, resume_file, created, updated) "
                      "VALUES (?,?,?,?,?,?,?,?)",
                      (slug, name, email, json.dumps(profile), json.dumps(prefs), resume_file, stamp(), stamp()))
    return cur.lastrowid, slug


def members(con):
    return [member_row(r) for r in con.execute("SELECT * FROM members ORDER BY name")]


def member(con, key):
    r = con.execute("SELECT * FROM members WHERE slug=? OR CAST(id AS TEXT)=?", (str(key), str(key))).fetchone()
    return member_row(r) if r else None


def member_row(r):
    d = dict(r)
    d["profile"] = json.loads(d["profile"] or "{}")
    d["prefs"] = json.loads(d["prefs"] or "{}")
    return d


def delete_member(con, member_id):
    for t in ("matches", "applications", "events"):
        con.execute(f"DELETE FROM {t} WHERE member_id=?", (member_id,))
    con.execute("DELETE FROM members WHERE id=?", (member_id,))


# ---------- jobs ----------
def upsert_jobs(con, jobs, day):
    """Bulk insert/refresh. jobs: dicts with url, company, title, location, ats, source, posted (ISO date or None)."""
    rows = [(url_key(j["url"]), j["url"], j["company"][:200], j["title"][:300], (j.get("location") or "")[:300],
             j.get("ats"), j.get("source"), j.get("posted"), day, day) for j in jobs if j.get("url")]
    con.executemany(
        "INSERT INTO jobs (url_key, url, company, title, location, ats, source, posted, first_seen, last_seen) "
        "VALUES (?,?,?,?,?,?,?,?,?,?) ON CONFLICT(url_key) DO UPDATE SET last_seen=excluded.last_seen, "
        "title=excluded.title, location=excluded.location, posted=COALESCE(excluded.posted, jobs.posted)", rows)
    return len(rows)


def add_manual_job(con, url, company, title, location="", source="manual"):
    day = str(config.today())
    upsert_jobs(con, [{"url": url, "company": company, "title": title, "location": location, "source": source}], day)
    return con.execute("SELECT id FROM jobs WHERE url_key=?", (url_key(url),)).fetchone()["id"]


def save_jd(con, job_id, text):
    con.execute("INSERT INTO jd (job_id, text, fetched) VALUES (?,?,?) ON CONFLICT(job_id) DO UPDATE SET "
                "text=excluded.text, fetched=excluded.fetched", (job_id, text, stamp()))


def get_jd(con, job_id):
    r = con.execute("SELECT text FROM jd WHERE job_id=?", (job_id,)).fetchone()
    return r["text"] if r else None


# ---------- matches / applications ----------
def set_match_status(con, member_id, job_id, status):
    if status not in MATCH_STATUSES:
        raise ValueError(f"status must be one of {MATCH_STATUSES}")
    con.execute("UPDATE matches SET status=? WHERE member_id=? AND job_id=?", (status, member_id, job_id))
    con.execute("INSERT INTO events (member_id, job_id, at, status) VALUES (?,?,?,?)", (member_id, job_id, stamp(), status))


def create_application(con, member_id, company, title, url=None, job_id=None, folder=None, fit=None, notes=None):
    cur = con.execute("INSERT INTO applications (member_id, job_id, company, title, url, folder, fit, notes, created, updated) "
                      "VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (member_id, job_id, company, title, url, folder, fit, notes, stamp(), stamp()))
    if job_id:
        con.execute("UPDATE matches SET status='applying' WHERE member_id=? AND job_id=?", (member_id, job_id))
    con.execute("INSERT INTO events (member_id, application_id, job_id, at, status) VALUES (?,?,?,?,?)",
                (member_id, cur.lastrowid, job_id, stamp(), "drafting"))
    return cur.lastrowid


def set_application_status(con, app_id, status, note=None):
    if status not in APP_STATUSES:
        raise ValueError(f"status must be one of {APP_STATUSES}")
    r = con.execute("SELECT member_id, job_id FROM applications WHERE id=?", (app_id,)).fetchone()
    con.execute("UPDATE applications SET status=?, notes=COALESCE(?, notes), updated=? WHERE id=?", (status, note, stamp(), app_id))
    con.execute("INSERT INTO events (member_id, application_id, job_id, at, status, note) VALUES (?,?,?,?,?,?)",
                (r["member_id"], app_id, r["job_id"], stamp(), status, note))


def start_run(con, kind):
    return con.execute("INSERT INTO runs (kind, started) VALUES (?,?)", (kind, config.now().isoformat(timespec="seconds"))).lastrowid


def finish_run(con, run_id, secs, stats):
    con.execute("UPDATE runs SET finished=?, secs=?, stats=? WHERE id=?",
                (config.now().isoformat(timespec="seconds"), int(secs), json.dumps(stats, default=str), run_id))

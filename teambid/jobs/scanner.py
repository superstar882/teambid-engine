"""The shared scan: read every company board once, store all open jobs, then match each member.

One scan serves the whole team (27K boards x N members would be N times slower). Robust by design:
- checkpoint: every finished board is appended to cache/scan-<date>.jsonl, so a crash/sleep/shutdown resumes;
- NetWatch: boards finished during an internet outage are dropped from the checkpoint and re-checked next run;
- one bad board can't stop the scan; Workday 'too many requests' is retried and counted;
- progress lines every 1,000 boards (log and UI).
"""
import json
import sys
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from .. import config, storage
from . import ats, feeds, matcher

LOCK = config.CACHE / "scan-running.txt"      # holds {"pid", "started"} while a scan runs
MARK = config.CACHE / "last-scan.txt"


def pid_alive(pid):
    """True if a process with this id is running (Windows-safe: never sends a signal)."""
    if not pid:
        return False
    if sys.platform == "win32":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))      # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return bool(ok) and code.value == 259                               # STILL_ACTIVE
    import os
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def running():
    """{'pid', 'started'} of the scan in progress, or None. A lock left by a killed scan counts as not running."""
    if not LOCK.exists():
        return None
    try:
        info = json.loads(LOCK.read_text())
    except ValueError:
        info = {"pid": None, "started": LOCK.read_text().strip()}           # lock written by an older version
    if info.get("pid") and not pid_alive(info["pid"]):
        LOCK.unlink(missing_ok=True)
        return None
    if not info.get("pid") and time.time() - LOCK.stat().st_mtime > 4 * 3600:
        LOCK.unlink(missing_ok=True)
        return None
    return info


def load_boards(only=None, per_ats=None):
    """All boards (or the first per_ats of each job system, for quick test scans)."""
    if not config.BOARDS.exists():
        return []
    data = json.loads(config.BOARDS.read_text(encoding="utf-8"))
    return [(a, s) for a, slugs in data.items() if a in ats.SYSTEMS and (not only or a in only)
            for s in (slugs[:per_ats] if per_ats else slugs)]


def team_queries(con):
    """Workday/Himalayas keyword searches: the union of every member's target titles (most common first)."""
    c = Counter()
    for m in storage.members(con):
        for t in m["prefs"].get("target_titles") or m["profile"].get("target_titles", []):
            c[t.lower()] += 1
    base = ["software engineer", "data engineer", "machine learning", "developer"]
    return list(dict.fromkeys([t for t, _ in c.most_common(6)] + base))[:8]


def is_due():
    """Due once per scan-day (TEAMBID_SCAN_TZ) at/after TEAMBID_SCAN_HOUR, unless a scan is already running."""
    import datetime as dt
    local = dt.datetime.now(config.SCAN_TZ)
    ran = MARK.read_text().strip() if MARK.exists() else ""
    busy = running() is not None
    return local.hour >= config.SCAN_HOUR and ran != str(local.date()) and not busy


def run(days=2, only=None, limit=None, log=print, workers=32, per_ats=None):
    import datetime as dt
    config.ensure_dirs()
    import os
    LOCK.write_text(json.dumps({"pid": os.getpid(), "started": config.now().isoformat(timespec="seconds")}))
    t_start, timing, problems = time.monotonic(), {}, []
    net = ats.NetWatch()
    day = str(config.today())
    ck = config.CACHE / f"scan-{day}.jsonl"
    try:
        with storage.connect() as con:
            run_id = storage.start_run(con, "scan")
            queries = team_queries(con)
        boards = load_boards(only, per_ats)
        if limit:
            boards = boards[:limit]
        saved = {}
        if ck.exists():
            for line in ck.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                    saved[(r["ats"], r["slug"])] = r["jobs"]
                except (ValueError, KeyError):
                    continue
            log(f"resuming: {len(saved):,} boards already done today (checkpoint)")
        out = open(ck, "a", encoding="utf-8")
        lock, done, span, per_ats = threading.Lock(), [0], {}, Counter()
        t0 = time.monotonic()

        def one(b):
            if b in saved:
                with lock:
                    done[0] += 1
                return saved[b]
            start, js = time.monotonic(), []
            try:
                js = ats.fetch(b[1], b[0], queries)
                return js
            except Exception:
                return []
            finally:
                end = time.monotonic()
                with lock:
                    out.write(json.dumps({"ats": b[0], "slug": b[1], "t": round(time.time()), "jobs": js}) + "\n")
                    out.flush()
                    done[0] += 1
                    per_ats[b[0]] += 1
                    s = span.setdefault(b[0], [start, end])
                    s[0], s[1] = min(s[0], start), max(s[1], end)
                    if done[0] % 1000 == 0 or done[0] == len(boards):
                        log(f"boards: {done[0]:,}/{len(boards):,} ({100 * done[0] / max(1, len(boards)):.0f}%), now on {b[0]}, {(end - t0) / 60:.1f} min")

        log(f"scanning {len(boards):,} company boards with {workers} workers...")
        try:
            with ThreadPoolExecutor(workers) as ex:
                board_jobs = [j for js in ex.map(one, boards) for j in js]
        finally:
            out.close()
        timing["boards"] = time.monotonic() - t0
        for j in board_jobs:
            j.setdefault("source", "Company board")
        all_jobs = list(board_jobs)
        for name, fn in (("Himalayas", lambda: feeds.himalayas(queries)), ("RemoteOK", feeds.remoteok),
                         ("Remotive", feeds.remotive), ("HN Who is hiring", feeds.hackernews)):
            t1 = time.monotonic()
            try:
                js = fn()
            except Exception as e:
                problems.append(f"{name}: {type(e).__name__} {str(e)[:100]}")
                js = []
            if not js:
                problems.append(f"{name}: returned 0 jobs")
            timing[name] = time.monotonic() - t1
            all_jobs += js
        problems += [f"{a}: {n} boards kept saying 'too many requests'" for a, n in ats.BLOCKED.items()]
        t1 = time.monotonic()
        with storage.connect() as con:
            n = storage.upsert_jobs(con, all_jobs, day)
        timing["store"] = time.monotonic() - t1
        log(f"stored {n:,} open jobs")
        t1 = time.monotonic()
        match_stats = matcher.match_all(days=days, log=log)
        timing["match"] = time.monotonic() - t1
        down = net.stop()
        secs = time.monotonic() - t_start
        by_ats = Counter(j.get("ats") for j in all_jobs)
        stats = {"boards": len(boards), "jobs": len(all_jobs), "by_ats": dict(by_ats),
                 "by_source": dict(Counter(j.get("source") for j in all_jobs)), "boards_per_ats": dict(per_ats),
                 "secs_per_ats": {k: round(v[1] - v[0]) for k, v in span.items()},
                 "timing": {k: round(v) for k, v in timing.items()}, "problems": problems, "members": match_stats,
                 "internet_down_secs": down}
        with storage.connect() as con:
            storage.finish_run(con, run_id, secs, stats)
        write_team_report(stats, secs)
        if down >= 60:
            keep, dropped = [], 0
            for line in ck.read_text(encoding="utf-8").splitlines():
                try:
                    t = json.loads(line).get("t", 0)
                except ValueError:
                    continue
                if any(s - 5 <= t <= e + 25 for s, e in net.windows):
                    dropped += 1
                else:
                    keep.append(line)
            ck.write_text("".join(x + "\n" for x in keep), encoding="utf-8")
            log(f"internet was down ~{down // 60} min: {dropped:,} boards will be re-checked by the next run")
            return 2
        ck.unlink(missing_ok=True)
        MARK.write_text(str(dt.datetime.now(config.SCAN_TZ).date()))
        log(f"done in {secs / 60:.1f} min: {len(all_jobs):,} jobs")
        return 0
    finally:
        LOCK.unlink(missing_ok=True)
        for old in config.CACHE.glob("scan-*.jsonl"):
            if old != ck:
                old.unlink(missing_ok=True)


def write_team_report(stats, secs):
    day = config.today()
    L = [f"# Team scan: {day}", "", f"{stats['jobs']:,} open jobs from {stats['boards']:,} company boards + feeds in {secs / 60:.1f} min.", "",
         "## Matches per member", "", "| Member | Matches | New today | Best fits |", "|---|---|---|---|"]
    for m in stats["members"]:
        L.append(f"| {m['name']} | {m['matches']} | {m['new']} | {m['best']} |")
    L += ["", "## By job system", "", "| System | Boards | Jobs | Time |", "|---|---|---|---|"]
    for a, n in sorted(stats["boards_per_ats"].items(), key=lambda kv: -kv[1]):
        L.append(f"| {a} | {n:,} | {stats['by_ats'].get(a, 0):,} | {stats['secs_per_ats'].get(a, 0) / 60:.1f} min |")
    L += ["", "## Problems", ""] + ([f"- {p}" for p in stats["problems"]] or ["None."])
    (config.REPORTS / f"{day}.md").write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(run())

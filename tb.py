"""TeamBid command line.

  python tb.py ui [--port 8765]                     start the web app (http://localhost:8765)
  python tb.py add "Full Name" resume.pdf [--email x] [--llm]   onboard a member (parse, audit, vault)
  python tb.py members                              list members with level, lanes, audit score, new matches
  python tb.py audit <member>                       resume audit with the fix list
  python tb.py vault <member>                       rebuild the member's vault
  python tb.py reparse <member|all>                 read the resume file again (after reader fixes), keep preferences
  python tb.py scan [--days 2] [--per-ats N] [--only greenhouse,ashby]   shared scan of all boards + match everyone
  python tb.py scan-if-due                          for the scheduler: scan once a day after TEAMBID_SCAN_HOUR
  python tb.py stop                                 stop the running scan (progress is kept; the next scan today resumes)
  python tb.py match <member> [--days 7]            re-match one member against the last scan (after editing prefs)
  python tb.py matches <member> [--new] [--tier best]
  python tb.py apply <member> (--job ID | --url URL | --jd file.txt) [--company X --title Y] [--polish]
  python tb.py status <application-id> <drafting|applied|interview|offer|rejected|withdrawn|closed> [note]
  python tb.py check file.txt [--limit 500] [--bullet]   writing checker
  python tb.py schedule                             register the hourly Windows task that runs scan-if-due
  python tb.py site-password                        set/change the team password for the results website
  python tb.py progress-setup <supabase-url> <key>  store team progress (status + notes from the results page) in Supabase
  python tb.py sync                                 pull the team's progress into TeamBid (publish does this too)
  python tb.py import-qb <member> [--db path]       copy Quick Bid applications into the member's Applications (safe to re-run)
  python tb.py export                               build the encrypted results website in site/
  python tb.py publish [--repo teambid]             export + push to GitHub Pages (creates the public repo the first time)
                                                    after that, every finished scan publishes automatically
  python tb.py cloud setup <owner/repo>            keep the workspace (encrypted) in that repo; the scan then runs on GitHub
  python tb.py cloud pull|push [--force]           sync by hand (normally automatic: pull before, push after each change)
  python tb.py cloud status | scan                 show sync state / start the cloud scan now
  python tb.py docs [--check]                      build documents requested on the results page (cloud workflow)
  python tb.py claude-key [--remove]                save a Claude API key (here + GitHub secret): Claude then writes letters
  python tb.py test                                 run the test suite
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

from teambid import analyze, config, service, storage, vault, writing  # noqa: E402
from teambid.jobs import scanner  # noqa: E402


def _auto_publish():
    """After a finished scan: re-export and push the encrypted results site, if publishing was set up once."""
    from teambid import export
    if not export.auto_publish_enabled():
        return 0
    try:
        r = export.publish()
        print(f"published results: {r['url']}", flush=True)
        return 0
    except Exception as e:
        print(f"publish failed (scan results are saved; run 'python tb.py publish' to retry): {e}", flush=True)
        return 0


def _claude_key(remove=False):
    """Save (or remove) the Claude API key on this PC and as the engine repo's ANTHROPIC_API_KEY secret.
    The key is typed hidden and never printed."""
    import getpass
    import subprocess
    from teambid import cloud
    rp = cloud.repo()
    if remove:
        config.KEY_FILE.unlink(missing_ok=True)
        if rp:
            subprocess.run(["gh", "secret", "delete", "ANTHROPIC_API_KEY", "-R", rp], capture_output=True)
        print("Claude key removed. Documents use the free path again.")
        return
    key = getpass.getpass("Paste your Claude API key (hidden), then Enter: ").strip()
    if not key.startswith("sk-ant-"):
        sys.exit("That doesn't look like a Claude API key (it starts with sk-ant-). Nothing saved.")
    import requests
    r = requests.get("https://api.anthropic.com/v1/models", headers={"x-api-key": key, "anthropic-version": "2023-06-01"}, timeout=30)
    if r.status_code != 200:
        sys.exit(f"The key didn't work (HTTP {r.status_code}). Nothing saved.")
    config.ensure_dirs()
    config.KEY_FILE.write_text(key, encoding="utf-8")
    if rp:
        s = subprocess.run(["gh", "secret", "set", "ANTHROPIC_API_KEY", "-R", rp], input=key, text=True, capture_output=True)
        print("saved for the cloud too" if s.returncode == 0 else f"saved on this PC; GitHub secret failed: {s.stderr.strip()[:200]}")
    print(f"Claude key works and is saved. From now on Claude ({config.MODEL}) writes the cover letters and rewords the resumes.")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="tb", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("ui"); s.add_argument("--port", type=int, default=8765); s.add_argument("--host", default="127.0.0.1")
    s = sub.add_parser("add"); s.add_argument("name"); s.add_argument("resume"); s.add_argument("--email"); s.add_argument("--llm", action="store_true")
    sub.add_parser("members")
    s = sub.add_parser("audit"); s.add_argument("member")
    s = sub.add_parser("vault"); s.add_argument("member")
    s = sub.add_parser("reparse"); s.add_argument("member")
    s = sub.add_parser("scan"); s.add_argument("--days", type=int, default=2); s.add_argument("--limit", type=int); s.add_argument("--only")
    s.add_argument("--per-ats", type=int, help="test scan: first N boards of each job system")
    sub.add_parser("scan-if-due")
    sub.add_parser("stop")
    s = sub.add_parser("match"); s.add_argument("member"); s.add_argument("--days", type=int)
    s = sub.add_parser("matches"); s.add_argument("member"); s.add_argument("--new", action="store_true"); s.add_argument("--tier")
    s = sub.add_parser("apply"); s.add_argument("member"); s.add_argument("--job", type=int); s.add_argument("--url"); s.add_argument("--jd")
    s.add_argument("--company"); s.add_argument("--title"); s.add_argument("--polish", action="store_true")
    s = sub.add_parser("status"); s.add_argument("app_id", type=int); s.add_argument("status"); s.add_argument("note", nargs="*")
    s = sub.add_parser("check"); s.add_argument("file"); s.add_argument("--limit", type=int); s.add_argument("--bullet", action="store_true")
    sub.add_parser("schedule")
    sub.add_parser("site-password")
    s = sub.add_parser("progress-setup"); s.add_argument("url"); s.add_argument("key")
    sub.add_parser("sync")
    s = sub.add_parser("import-qb"); s.add_argument("member"); s.add_argument("--db", default=str(Path(__file__).resolve().parent.parent / "Quick Bid" / "data" / "jobs.db"))
    sub.add_parser("export")
    s = sub.add_parser("publish"); s.add_argument("--repo", help="GitHub repo name (default: the one used before, else teambid)")
    s = sub.add_parser("cloud"); s.add_argument("action", choices=["setup", "pull", "push", "status", "scan"])
    s.add_argument("repo", nargs="?"); s.add_argument("--force", action="store_true")
    s = sub.add_parser("docs"); s.add_argument("--check", action="store_true")
    s = sub.add_parser("claude-key"); s.add_argument("--remove", action="store_true")
    sub.add_parser("test")
    a = ap.parse_args(argv)
    from teambid import cloud
    # cloud mode: get the newest workspace before reading it, refuse changes while the cloud scan runs, upload after
    if a.cmd in CHANGES:
        cloud.before_change()
    elif a.cmd in READS:
        cloud.refresh()
    if a.cmd == "scan-if-due" and cloud.enabled():
        print("the daily scan runs in the cloud (GitHub Actions); nothing to do on this PC")
        return
    _run(a, ap)
    if a.cmd in CHANGES:
        cloud.after_change()


READS = {"members", "audit", "matches", "export"}
CHANGES = {"add", "vault", "reparse", "match", "apply", "status", "import-qb", "sync", "publish", "scan"}


def _run(a, ap):

    if a.cmd == "ui":
        from teambid import server
        server.serve(a.host, a.port)
    elif a.cmd == "add":
        r = service.onboard(a.name, resume_path=a.resume, email=a.email, use_llm=a.llm)
        p = r["profile"]
        print(f"added {a.name} ({r['slug']}): {len(p['roles'])} roles, {p['years_experience']} yrs, level {p['level']}, lanes {', '.join(p['lanes'])}")
        print(f"resume audit {r['vault']['audit']['score']}/100. Vault: {r['vault']['folder']}")
        print(f"matched against the last scan: {r['matched']['matches']} jobs" if r.get("matched") else "matches appear after the next scan")
        for n in p.get("parse_notes", []):
            print("note:", n)
    elif a.cmd == "members":
        for m in service.team_overview()["members"]:
            print(f"{m['slug']:<20} {m['name']:<24} {m['level'] or '-':<7} {','.join(m['lanes'] or []):<26} audit {m['audit']:>3}  new matches {m['new_matches']}")
    elif a.cmd == "audit":
        with storage.connect() as con:
            m = storage.member(con, a.member)
        print(analyze.to_markdown(m["name"], analyze.audit(m["profile"], m["prefs"].get("region", "US"))))
    elif a.cmd == "reparse":
        with storage.connect() as con:
            slugs = [m["slug"] for m in storage.members(con)] if a.member == "all" else [a.member]
        for sl in slugs:
            print(service.reparse(sl))
    elif a.cmd == "vault":
        with storage.connect() as con:
            print(vault.build(con, storage.member(con, a.member))["folder"])
    elif a.cmd == "scan":
        rc = scanner.run(days=a.days, only=a.only.split(",") if a.only else None, limit=a.limit, per_ats=a.per_ats)
        if rc:
            sys.exit(rc)
        _auto_publish()
    elif a.cmd == "scan-if-due":
        if scanner.is_due():
            rc = scanner.run()
            sys.exit(rc or _auto_publish())
    elif a.cmd == "stop":
        print(service.stop_scan())
    elif a.cmd == "match":
        print(service.rematch(a.member, a.days))
    elif a.cmd == "matches":
        for r in service.member_matches(a.member, tier=a.tier, new_only=a.new):
            print(f"#{r['job_id']:<7} {r['score']:>3} {r['tier']:<8} {r['status']:<11} {r['company'][:22]:<22} {r['title'][:50]:<50} {r['url']}")
    elif a.cmd == "apply":
        jd_text = Path(a.jd).read_text(encoding="utf-8") if a.jd else None
        r = service.apply(a.member, job_id=a.job, url=a.url, jd_text=jd_text, company=a.company, title=a.title, polish=a.polish)
        f = r["fit"]
        print(f"{f['verdict']} (covers {f['coverage']}% of must-haves). Keyword coverage {r['keywords']['pct']}%. Pages: {r['files']['pages']}")
        for n in f["notes"]:
            print("-", n)
        print("fact check:", "OK" if not r["problems"] else r["problems"])
        print("letter check:", writing.format_report(r["letter_check"]))
        print("folder:", r["folder"])
    elif a.cmd == "status":
        with storage.connect() as con:
            storage.set_application_status(con, a.app_id, a.status, " ".join(a.note) or None)
        print(f"application {a.app_id} -> {a.status}")
    elif a.cmd == "check":
        text = Path(a.file).read_text(encoding="utf-8")
        print(writing.format_report(writing.check(text, a.limit, "bullet" if a.bullet else "prose")))
    elif a.cmd == "schedule":
        # hourly hidden task; scan-if-due runs one scan per day after SCAN_HOUR (SCAN_TZ), then publishes automatically
        import subprocess
        config.ensure_dirs()
        bat = config.PROJECT / "run_scan.cmd"
        bat.write_text(f'@echo off\r\ncd /d "{config.PROJECT}"\r\n"{sys.executable}" -u tb.py scan-if-due >> "{config.CACHE / "scan.log"}" 2>&1\r\n',
                       encoding="utf-8")
        vbs = config.PROJECT / "run_scan_hidden.vbs"
        vbs.write_text('CreateObject("WScript.Shell").Run """" & CreateObject("Scripting.FileSystemObject")'
                       '.GetParentFolderName(WScript.ScriptFullName) & "\\run_scan.cmd""", 0, True\r\n', encoding="utf-8")
        ps = (f'$a = New-ScheduledTaskAction -Execute "wscript.exe" -Argument \'"{vbs}"\' -WorkingDirectory "{config.PROJECT}"; '
              '$t = New-ScheduledTaskTrigger -Once -At (Get-Date).Date.AddHours((Get-Date).Hour + 1) -RepetitionInterval (New-TimeSpan -Hours 1); '
              '$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -WakeToRun '
              '-ExecutionTimeLimit (New-TimeSpan -Hours 4) -MultipleInstances IgnoreNew; '
              'Register-ScheduledTask -TaskName "TeamBid daily scan" -Action $a -Trigger $t -Settings $s -Force | Out-Null; '
              '(Get-ScheduledTaskInfo -TaskName "TeamBid daily scan").NextRunTime')
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True)
        print((r.stdout or r.stderr).strip())
        print(f"Registered 'TeamBid daily scan': checks hourly (hidden), scans once a day after {config.SCAN_HOUR}:00 {config.SCAN_TZ}, "
              "then publishes the encrypted results site. Log: workspace/cache/scan.log")
    elif a.cmd == "site-password":
        from teambid import export
        export.set_password()
        print(f"Saved on this PC only ({export.PW_FILE}). Share it with the team privately. Run publish again to re-encrypt.")
    elif a.cmd == "progress-setup":
        from teambid import progress
        sb = progress.configure(a.url, a.key)
        print(f"saved (team id {sb['team']}). Run 'python tb.py publish' so the page gets the progress buttons.")
    elif a.cmd == "sync":
        from teambid import progress
        print(progress.sync())
    elif a.cmd == "import-qb":
        print(service.import_quickbid(a.member, a.db))
    elif a.cmd == "export":
        from teambid import export
        print(export.export())
    elif a.cmd == "publish":
        from teambid import export
        r = export.publish(a.repo)
        print(f"published: {r['url']}  (repo {r['repo']})")
        print("members:", r["members"], "| first publish: GitHub Pages can take 1-2 minutes to go live")
    elif a.cmd == "cloud":
        from teambid import cloud
        if a.action == "setup":
            if not a.repo:
                ap.error("cloud setup needs owner/repo")
            cloud._save_state(repo=a.repo)
            print(f"cloud workspace: {a.repo}. Run 'python tb.py cloud push' once to upload it.")
        elif a.action == "pull":
            print(cloud.pull(force=a.force))
        elif a.action == "push":
            print(cloud.push(force=a.force))
        elif a.action == "scan":
            print(cloud.run_scan_now())
        else:
            s = cloud.state()
            print(json.dumps({**s, "cloud_version": cloud.remote_version() if s.get("repo") else None,
                              "cloud_scan_running": cloud.busy() if s.get("repo") else None}, indent=1))
    elif a.cmd == "docs":
        from teambid import docs
        if a.check:                            # the workflow skips the heavy steps when nothing is waiting
            n = len(docs.pending())
            print(f"pending={n}")
            out = os.environ.get("GITHUB_OUTPUT")
            if out:
                with open(out, "a", encoding="utf-8") as f:
                    print(f"pending={n}", file=f)
        else:
            print(docs.run_all())
    elif a.cmd == "claude-key":
        _claude_key(a.remove)
    elif a.cmd == "test":
        import unittest
        suite = unittest.defaultTestLoader.discover(str(config.PROJECT / "tests"))
        sys.exit(0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()

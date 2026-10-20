"""Export everything to a password-protected static website (GitHub Pages) and publish it.

  python tb.py export   [--password-file F]      build site/ (encrypted)
  python tb.py publish  [--repo teambid]         export + commit + push to <you>.github.io/<repo>/<random-words>/
  python tb.py site-password                     set or change the team password (saved only on this PC)

How the protection works: the data is encrypted on this PC with AES-256-GCM; the key comes from the team password via
PBKDF2-HMAC-SHA256 with 600,000 iterations (OWASP 2023 guidance) and a random salt. Only the encrypted file is committed.
The page asks for the password and decrypts in the browser (Web Crypto API). Without the password, the repo and the
page contain nothing readable. Use a long password (4+ random words); anyone who has it can read everything.
The password is never written into the site or the repo; a copy is kept in workspace/.site-password for re-publishing.
"""
import base64
import getpass
import json
import os
import subprocess
from pathlib import Path

from . import analyze, config, storage

SITE = config.PROJECT / "site"
PW_FILE = config.WORKSPACE / ".site-password"
PUB_FILE = config.WORKSPACE / ".publish.json"      # repo, random page folder, commit identity (local only)
ITERATIONS = 600_000
WORDS = ("amber anchor apple arrow aspen atlas autumn badge basil beacon birch bison blaze bloom breeze brook cactus canyon cedar "
         "cobalt comet coral cosmos cotton crane crystal delta desert dune eagle ember falcon fern fjord flint forest frost galaxy "
         "garnet glacier granite harbor hazel heron horizon island ivory jade jasper juniper kayak lagoon lantern lemon lilac lotus "
         "maple marble meadow mesa meteor mint monsoon mosaic nebula nectar north oasis ocean olive onyx opal orbit orchid otter "
         "pebble pepper pine planet plum polar prairie quartz quill raven reef ridge river rocket saffron sage sapphire sequoia "
         "shadow sierra silver sparrow spruce summit sunset tango thistle thunder tidal timber topaz tundra valley velvet violet "
         "walnut willow winter zephyr").split()


def random_words(n=4):
    import secrets
    return "-".join(secrets.SystemRandom().sample(WORDS, n))     # n different words


def pub_settings(repo=None):
    """Publishing settings, created on first use: repo name, a random-words page folder, commit name/email."""
    cfg = json.loads(PUB_FILE.read_text(encoding="utf-8")) if PUB_FILE.exists() else {}
    changed = False
    if repo and cfg.get("repo") != repo:
        cfg["repo"], changed = repo, True
    defaults = {"repo": "teambid", "page": random_words(), "auto_publish": True}     # optional: owner, git_name, git_email
    for k, v in defaults.items():
        if k not in cfg:
            cfg[k], changed = v, True
    if changed:
        config.ensure_dirs()
        PUB_FILE.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    return cfg


# ---------------------------------------------------------------- password
def get_password(password_file=None, ask=True):
    if password_file:
        return Path(password_file).read_text(encoding="utf-8").strip()
    if os.environ.get("TEAMBID_SITE_PASSWORD"):
        return os.environ["TEAMBID_SITE_PASSWORD"]
    if PW_FILE.exists():
        return PW_FILE.read_text(encoding="utf-8").strip()
    if not ask:
        raise RuntimeError("No team password set. Run: python tb.py site-password")
    return set_password()


def set_password(pw=None):
    if pw is None:
        pw = getpass.getpass("Team password for the results site (12+ characters, e.g. 4 random words): ")
        if pw != getpass.getpass("Repeat it: "):
            raise RuntimeError("The two passwords don't match")
    if len(pw) < 12:
        raise RuntimeError("Use at least 12 characters (4 random words is a good password)")
    config.ensure_dirs()
    PW_FILE.write_text(pw, encoding="utf-8")
    return pw


# ---------------------------------------------------------------- data (everything the team should see)
def build_data(include_skipped=True):
    with storage.connect() as con:
        members = storage.members(con)
        last_scan = con.execute("SELECT max(last_seen) d FROM jobs WHERE source NOT IN ('manual','quickbid')").fetchone()["d"]
        out = []
        for i, m in enumerate(members):
            rows = [dict(r) for r in con.execute(
                "SELECT m.job_id, m.score, m.tier, m.status, m.reasons, m.first_matched, j.company, j.title, j.location, j.url, "
                "j.url_key, j.posted, j.source, a.status AS app_status, a.notes AS app_notes FROM matches m JOIN jobs j ON j.id=m.job_id "
                "LEFT JOIN applications a ON a.member_id=m.member_id AND a.job_id=m.job_id WHERE m.member_id=? AND j.last_seen=?"
                + ("" if include_skipped else " AND m.status != 'skipped'") + " ORDER BY m.score DESC", (m["id"], last_scan))]
            for r in rows:
                r["reasons"] = json.loads(r["reasons"] or "[]")
                # one status the page understands: application status wins, else the match status
                r["progress"] = r["app_status"] if r["app_status"] in ("applied", "interview", "offer", "rejected") else \
                    {"shortlisted": "saved", "skipped": "skipped"}.get(r["status"], "")
                r["note"] = r.pop("app_notes") or ""
                r.pop("app_status")
            apps = [dict(a) for a in con.execute(
                "SELECT a.id, a.company, a.title, a.url, a.status, a.fit, a.notes, a.created, a.updated, j.url_key "
                "FROM applications a LEFT JOIN jobs j ON j.id=a.job_id WHERE a.member_id=? ORDER BY a.updated DESC", (m["id"],))]
            p, pr = m["profile"], m["prefs"]
            audit = analyze.audit(p, pr.get("region", "US"))
            out.append({
                "id": f"m{i + 1}", "slug": m["slug"], "name": m["name"], "contact": p.get("contact", {}), "headline": p.get("headline", ""),
                "summary": p.get("summary", ""), "level": pr.get("level") or p.get("level"), "lanes": pr.get("lanes") or p.get("lanes", []),
                "years": p.get("years_experience"), "region": pr.get("region", "US"), "countries": pr.get("countries", []),
                "target_titles": pr.get("target_titles") or p.get("target_titles", []),
                "skills": p.get("skills", {}), "education": p.get("education", []), "certifications": p.get("certifications", []),
                "roles": [{"title": r["title"], "company": r["company"], "start": r["start"], "end": r["end"], "kind": r.get("kind"),
                           "stack": r.get("stack", []), "bullets": [b["text"] for b in r["bullets"]]} for r in p.get("roles", [])],
                "audit": {"score": audit["score"], "grade": audit["grade"], "findings": audit["findings"]},
                "matches": rows, "best": sum(1 for r in rows if r["tier"] == "best"), "applications": apps})
    return {"generated": config.now().strftime("%Y-%m-%d %H:%M %Z"), "last_scan": last_scan, "members": out}


def _with_progress(data, password):
    from . import progress
    data["progress"] = progress.page_config(password)
    return data


# ---------------------------------------------------------------- encryption
def encrypt(data, password):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    salt, iv = os.urandom(16), os.urandom(12)
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS).derive(password.encode("utf-8"))
    ct = AESGCM(key).encrypt(iv, json.dumps(data, ensure_ascii=False).encode("utf-8"), None)
    b = lambda x: base64.b64encode(x).decode("ascii")
    return {"v": 1, "kdf": "PBKDF2-SHA256", "iterations": ITERATIONS, "salt": b(salt), "iv": b(iv), "data": b(ct)}


def decrypt(blob, password):
    """Used by the tests to prove the round trip; the browser does the same with Web Crypto."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    d = lambda k: base64.b64decode(blob[k])
    key = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=d("salt"), iterations=blob["iterations"]).derive(password.encode("utf-8"))
    return json.loads(AESGCM(key).decrypt(d("iv"), d("data"), None))


PAGE = (Path(__file__).resolve().parent / "static" / "results.html")


def export(out=SITE, password=None, include_skipped=True, page=None):
    """site/<page>/ holds the encrypted page; the site root only has a neutral placeholder."""
    out = Path(out)
    page = page or pub_settings()["page"]
    folder = out / page
    folder.mkdir(parents=True, exist_ok=True)
    password = password or get_password()
    data = _with_progress(build_data(include_skipped), password)
    (folder / "data.enc.json").write_text(json.dumps(encrypt(data, password)), encoding="utf-8")
    for leftover in (out / "data.json", folder / "data.json", out / "data.enc.json"):   # nothing readable, no old copies
        leftover.unlink(missing_ok=True)
    (folder / "index.html").write_text(PAGE.read_text(encoding="utf-8"), encoding="utf-8")
    old_root = out / "index.html"
    (out / "index.html").write_text("<!doctype html><meta charset=utf-8><meta name=robots content='noindex, nofollow'>"
                                    "<title>teambid</title><p>Nothing here.</p>", encoding="utf-8")
    (out / "robots.txt").write_text("User-agent: *\nDisallow: /\n", encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    (out / "README.md").write_text("# teambid\n\nEncrypted output generated by TeamBid. Data in this repo is encrypted "
                                   "(AES-256-GCM) and unreadable without the team password.\n", encoding="utf-8")
    return {"folder": str(folder), "page": page, "members": [(m["name"], len(m["matches"])) for m in data["members"]],
            "last_scan": data["last_scan"]}


def _run(args, cwd):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(args[:3])}: {(r.stderr or r.stdout).strip()[:400]}")
    return r.stdout.strip()


def publish(repo=None, password=None, include_skipped=True):
    """Export (encrypted), then commit and push to github.com/<you>/<repo>. First run creates the public repo + Pages.
    The page lives at https://<you>.github.io/<repo>/<random-words>/ ; the folder name is kept in workspace/.publish.json."""
    cfg = pub_settings(repo)
    repo = cfg["repo"]
    from . import progress
    if progress.settings():            # pull the team's latest statuses first, so the new export includes them
        try:
            progress.sync(password or get_password(ask=False), log=lambda *_: None)
        except Exception as e:
            print(f"progress sync skipped: {e}")
    info = export(SITE, password, include_skipped, cfg["page"])
    from . import cloud
    runner = cloud.in_runner()             # GitHub Actions: site/ is already a clone with a deploy-key remote
    owner = cfg.get("owner") or _run(["gh", "api", "user", "--jq", ".login"], SITE)
    if not (SITE / ".git").exists():
        _run(["git", "init", "-q", "-b", "main"], SITE)
    for k, opt in (("git_name", "user.name"), ("git_email", "user.email")):
        if cfg.get(k):
            _run(["git", "config", opt, cfg[k]], SITE)
    remote = f"https://github.com/{owner}/{repo}.git"
    cur = subprocess.run(["git", "remote", "get-url", "origin"], cwd=SITE, capture_output=True, text=True)
    if not runner and cur.returncode == 0 and cur.stdout.strip().rstrip("/") != remote:
        _run(["git", "remote", "set-url", "origin", remote], SITE)
    (SITE / ".gitignore").write_text("data.json\n", encoding="utf-8")
    _run(["git", "add", "-A"], SITE)
    staged = _run(["git", "diff", "--cached", "--name-only"], SITE).split()
    if any(Path(x).name == "data.json" for x in staged):
        raise RuntimeError("Refusing to publish: an unencrypted data.json is staged")
    if staged:
        _run(["git", "commit", "-q", "-m", f"Update results (scan {info['last_scan']})"], SITE)
    page_url = f"https://{owner}.github.io/{repo}/{cfg['page']}/"
    if runner:
        _run(["git", "push", "-q", "origin", "HEAD:main"], SITE)
        return {**info, "repo": f"https://github.com/{owner}/{repo}", "url": page_url}
    exists = subprocess.run(["gh", "repo", "view", f"{owner}/{repo}"], cwd=SITE, capture_output=True).returncode == 0
    if not exists:
        if cur.returncode == 0:
            _run(["git", "remote", "remove", "origin"], SITE)
        _run(["gh", "repo", "create", f"{owner}/{repo}", "--public", "--description", "TeamBid output (encrypted)",
              "--source", ".", "--remote", "origin", "--push"], SITE)
    else:
        if subprocess.run(["git", "remote", "get-url", "origin"], cwd=SITE, capture_output=True).returncode != 0:
            _run(["git", "remote", "add", "origin", remote], SITE)
        _run(["git", "push", "-q", "-u", "origin", "main"], SITE)
    ensure_pages(owner, repo)
    return {**info, "repo": f"https://github.com/{owner}/{repo}", "url": f"https://{owner}.github.io/{repo}/{cfg['page']}/"}


def ensure_pages(owner, repo, tries=5):
    """Turn on GitHub Pages (main branch, root) if it isn't on. Right after a repo is created GitHub can refuse this,
    so it retries; a missing Pages site is reported instead of passing silently."""
    import time
    for i in range(tries):
        if subprocess.run(["gh", "api", f"repos/{owner}/{repo}/pages"], cwd=SITE, capture_output=True).returncode == 0:
            return True
        subprocess.run(["gh", "api", "-X", "POST", f"repos/{owner}/{repo}/pages", "-f", "source[branch]=main", "-f", "source[path]=/"],
                       cwd=SITE, capture_output=True)
        time.sleep(3 * (i + 1))
    raise RuntimeError(f"GitHub Pages is not enabled for {owner}/{repo}. Turn it on in the repo's Settings > Pages (branch main, / root).")


def auto_publish_enabled():
    return PUB_FILE.exists() and json.loads(PUB_FILE.read_text(encoding="utf-8")).get("auto_publish", True) and \
        (PW_FILE.exists() or bool(os.environ.get("TEAMBID_SITE_PASSWORD")))

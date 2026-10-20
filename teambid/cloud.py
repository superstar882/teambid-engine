"""Cloud copy of the workspace, so the daily scan can run on GitHub Actions while the PC is off.

The whole workspace (database, member folders, reports, embeddings cache) is packed into one file, encrypted with the
team password (AES-256-GCM, key from PBKDF2-SHA256), and kept as the asset "workspace.enc" of the release "workspace"
in the engine repo. Nothing readable ever leaves this computer.

  pull   download + decrypt + unpack (the old database is kept in workspace/backups/ first)
  push   pack + encrypt + upload

The PC pulls before it reads or changes anything and pushes after a change. While the cloud scan runs, changes on
the PC are refused (otherwise one side would overwrite the other).
Settings: workspace/.cloud.json {"repo": "owner/name"}; TEAMBID_CLOUD=1 marks the GitHub runner (hooks off there).
"""
import io
import json
import os
import sqlite3
import subprocess
import tarfile
import tempfile
import threading
import time
from pathlib import Path

from . import config

STATE = config.WORKSPACE / ".cloud.json"
TAG, ASSET, MAGIC = "workspace", "workspace.enc", b"TBW1"
ITERATIONS = 600_000
WORKFLOW = "scan.yml"
# never packed: secrets, machine-local settings, logs, the scan lock/checkpoint, feed downloads, backups
SKIP_NAMES = {".site-password", ".publish.json", ".cloud.json", ".anthropic-key", "scan-running.txt", "scan.log"}
SKIP_DIRS = {"backups"}


def in_runner():
    return bool(os.environ.get("TEAMBID_CLOUD"))


def state():
    return json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {}


def _save_state(**kw):
    s = {**state(), **kw}
    config.ensure_dirs()
    STATE.write_text(json.dumps(s, indent=1), encoding="utf-8")
    return s


def repo():
    return os.environ.get("TEAMBID_CLOUD_REPO") or state().get("repo") or (os.environ.get("GITHUB_REPOSITORY") if in_runner() else None)


def enabled():
    """True on the PC once the cloud copy is set up (the runner calls pull/push itself)."""
    return bool(state().get("repo")) and not in_runner()


def _gh(*args, check=True):
    r = subprocess.run(["gh", *args], capture_output=True, text=True, encoding="utf-8")
    if check and r.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args[:2])}: {(r.stderr or r.stdout).strip()[:300]}")
    return r


# ---------------------------------------------------------------- pack / encrypt
def _key(password, salt):
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    return PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=ITERATIONS).derive(password.encode("utf-8"))


def encrypt_bytes(raw, password):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt, iv = os.urandom(16), os.urandom(12)
    return MAGIC + salt + iv + AESGCM(_key(password, salt)).encrypt(iv, raw, MAGIC)


def decrypt_bytes(blob, password):
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    if blob[:4] != MAGIC:
        raise ValueError("not a TeamBid workspace file")
    salt, iv = blob[4:20], blob[20:32]
    try:
        return AESGCM(_key(password, salt)).decrypt(iv, blob[32:], MAGIC)
    except Exception:
        raise ValueError("cannot decrypt the cloud workspace: wrong team password?") from None


def _skip(rel):
    parts = rel.parts
    name = parts[-1]
    return (parts[0] in SKIP_DIRS or parts[0].startswith(".incoming-") or name in SKIP_NAMES or name.startswith("teambid.db")
            or (parts[0] == "cache" and (name.startswith("scan-") or name.endswith(".json"))))


def pack(workspace=None):
    """tar.gz of the workspace. The database goes in through SQLite's backup API, so it is consistent even mid-write."""
    ws = Path(workspace or config.WORKSPACE)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6) as tar:
        db = ws / "teambid.db"
        if db.exists():
            with tempfile.TemporaryDirectory() as td:
                snap = Path(td) / "teambid.db"
                src, dst = sqlite3.connect(db, timeout=60), sqlite3.connect(snap)
                src.backup(dst)
                src.close(), dst.close()
                tar.add(snap, "teambid.db")
        for f in sorted(ws.rglob("*")):
            rel = f.relative_to(ws)
            if f.is_file() and not _skip(rel):
                tar.add(f, rel.as_posix())
    return buf.getvalue()


def unpack(raw, workspace=None, keep_backups=3):
    ws = Path(workspace or config.WORKSPACE)
    ws.mkdir(parents=True, exist_ok=True)
    # unpack next to the workspace: os.replace can't move files between drives (temp on C:, workspace on F:)
    with tempfile.TemporaryDirectory(dir=ws, prefix=".incoming-") as td:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
            tar.extractall(td, filter="data")                    # "data" filter: no absolute paths, no "..", no links out
        new_db = Path(td) / "teambid.db"
        if new_db.exists():
            db = ws / "teambid.db"
            if db.exists():
                bk = ws / "backups"
                bk.mkdir(exist_ok=True)
                # SQLite's backup API also copies changes still in the -wal file, which a plain file copy would miss
                src, dst = sqlite3.connect(db, timeout=60), sqlite3.connect(bk / f"teambid-{time.strftime('%Y%m%d-%H%M%S')}.db")
                src.backup(dst)
                src.close(), dst.close()
                for old in sorted(bk.glob("teambid-*.db"))[:-keep_backups]:
                    old.unlink()
            os.replace(new_db, db)
            for side in ("-wal", "-shm"):                         # the old journal belongs to the replaced file
                (ws / f"teambid.db{side}").unlink(missing_ok=True)
        for f in Path(td).rglob("*"):
            if f.is_file():
                dest = ws / f.relative_to(td)
                dest.parent.mkdir(parents=True, exist_ok=True)
                os.replace(f, dest)


# ---------------------------------------------------------------- remote (GitHub release asset)
def remote_version(rp=None):
    rp = rp or repo()
    # the releases list (not /tags/) also shows a draft release, which is what an empty repo gets
    r = _gh("api", f"repos/{rp}/releases", "--jq",
            f'.[] | select(.tag_name=="{TAG}") | .assets[] | select(.name=="{ASSET}") | "\\(.id)-\\(.updated_at)"', check=False)
    return (r.stdout.strip().splitlines() or [None])[0] if r.returncode == 0 else None


def busy(rp=None, _cache={}):
    """True while the cloud scan workflow is running (cached for a minute)."""
    rp = rp or repo()
    hit = _cache.get(rp)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    r = _gh("run", "list", "-R", rp, "--workflow", WORKFLOW, "--json", "status", "--limit", "3", check=False)
    try:
        val = any(x["status"] in ("in_progress", "queued", "waiting", "requested", "pending") for x in json.loads(r.stdout or "[]"))
    except ValueError:
        val = False
    _cache[rp] = (time.time(), val)
    return val


def _password():
    from . import export
    return export.get_password(ask=False)


def pull(password=None, force=False, log=print):
    rp = repo()
    ver = remote_version(rp)
    if not ver:
        raise RuntimeError(f"no cloud workspace in {rp} yet (run 'python tb.py cloud push' once)")
    if not force and ver == state().get("version"):
        return {"pulled": False, "version": ver}
    with tempfile.TemporaryDirectory() as td:
        _gh("release", "download", TAG, "-R", rp, "-p", ASSET, "-D", td, "--clobber")
        blob = (Path(td) / ASSET).read_bytes()
    unpack(decrypt_bytes(blob, password or _password()))
    if not in_runner():
        _save_state(version=ver, pending=False, pulled_at=config.now().isoformat(timespec="seconds"))
    log(f"pulled the cloud workspace ({len(blob) / 1e6:.1f} MB)")
    return {"pulled": True, "version": ver}


def push(password=None, force=False, log=print):
    rp = repo()
    if not in_runner():
        ver = remote_version(rp)
        if ver and ver != state().get("version") and not force:
            raise RuntimeError("the cloud has newer data than this PC. Run 'python tb.py cloud pull' first "
                               "(your current database is kept in workspace/backups/)")
    blob = encrypt_bytes(pack(), password or _password())
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / ASSET
        f.write_bytes(blob)
        if _gh("release", "view", TAG, "-R", rp, check=False).returncode != 0:
            _gh("release", "create", TAG, "-R", rp, "--title", "workspace (encrypted)", "--notes",
                "Encrypted TeamBid workspace (AES-256-GCM). Unreadable without the team password.", str(f))
        else:
            _gh("release", "upload", TAG, "-R", rp, str(f), "--clobber")
    ver = remote_version(rp)
    if not in_runner():
        _save_state(version=ver, pending=False, pushed_at=config.now().isoformat(timespec="seconds"))
    log(f"pushed the workspace to the cloud ({len(blob) / 1e6:.1f} MB)")
    return {"pushed": True, "version": ver}


# ---------------------------------------------------------------- hooks used by the CLI and the web app
_lock = threading.RLock()
_timer = [None]
_checked = [0.0]


def refresh(min_gap=0, log=print):
    """Pull if the cloud is newer and this PC has nothing waiting to upload."""
    if not enabled() or time.time() - _checked[0] < min_gap:
        return
    with _lock:
        _checked[0] = time.time()
        try:
            if state().get("pending"):
                return
            pull(log=log)
        except Exception as e:
            log(f"cloud pull skipped: {e}")


def before_change(log=print):
    """Call before changing anything. Refuses while the cloud scan runs."""
    if not enabled():
        return
    if busy():
        raise RuntimeError("the daily cloud scan is running right now. Try again when it finishes (about 1-2 hours); "
                           "changes made now would be overwritten")
    refresh(log=log)


def after_change(delay=None, log=print):
    """Call after a change. delay=None pushes now; a number waits that many seconds so several clicks go up as one."""
    if not enabled():
        return
    _save_state(pending=True)
    if delay is None:
        with _lock:
            push(log=log)
        return
    with _lock:
        if _timer[0]:
            _timer[0].cancel()

        def go():
            with _lock:
                try:
                    push(log=log)
                except Exception as e:
                    log(f"cloud push failed (will retry on the next change, or run 'python tb.py cloud push'): {e}")
        _timer[0] = threading.Timer(delay, go)
        _timer[0].daemon = True
        _timer[0].start()


def flush(log=print):
    """Push now if a delayed push is waiting (used when the web app stops)."""
    with _lock:
        if _timer[0]:
            _timer[0].cancel()
            _timer[0] = None
        if enabled() and state().get("pending"):
            push(log=log)


def run_scan_now(rp=None):
    """Start the cloud scan workflow by hand."""
    _gh("workflow", "run", WORKFLOW, "-R", rp or repo())
    return {"started": True, "watch": f"https://github.com/{rp or repo()}/actions"}

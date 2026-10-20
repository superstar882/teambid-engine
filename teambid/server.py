"""TeamBid web app: a JSON API + one-page UI on Python's built-in HTTP server (no extra packages).

Security: binds to 127.0.0.1 by default (only this computer). To share on a team network, run with --host 0.0.0.0
AND set TEAMBID_TOKEN; every API call then needs the token (the UI asks for it once). File downloads are limited
to the workspace folder.
"""
import json
import mimetypes
import os
import re
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import analyze, cloud, config, service, storage, writing

STATIC = Path(__file__).resolve().parent / "static"
TOKEN = os.environ.get("TEAMBID_TOKEN", "")
READ_ONLY_POSTS = {"/api/check", "/api/scan/stop"}      # POSTs that change nothing kept in the workspace


class Handler(BaseHTTPRequestHandler):
    server_version = "TeamBid/1.0"

    def log_message(self, fmt, *args):
        pass

    # ---------- helpers
    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def _authed(self, q):
        return not TOKEN or self.headers.get("X-Token") == TOKEN or q.get("token", [""])[0] == TOKEN

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def _route(self, method):
        u = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(u.query)
        path = u.path
        try:
            if method == "GET" and path in ("/", "/index.html"):
                return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            if path.startswith("/api/") or path == "/files":
                if not self._authed(q):
                    return self._send(401, {"error": "token required"})
            if path == "/files":
                return self._file(q.get("path", [""])[0])
            body = self._json() if method == "POST" else {}
            changes = method == "POST" and path.startswith("/api/") and path not in READ_ONLY_POSTS
            if changes:
                cloud.before_change()
            elif path == "/api/overview":
                cloud.refresh(min_gap=120)                    # pick up the cloud scan's results while the app stays open
            res = self._api(method, path, q, body)
            if res is None:
                return self._send(404, {"error": "not found"})
            if changes:
                cloud.after_change(delay=20)                  # several clicks go up as one upload
            return self._send(200, res)
        except KeyError as e:
            return self._send(404, {"error": f"not found: {e}"})
        except (ValueError, RuntimeError) as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:
            traceback.print_exc()
            return self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def _file(self, p):
        f = Path(p).resolve()
        if not str(f).startswith(str(config.WORKSPACE.resolve())) or not f.is_file():
            return self._send(403, {"error": "not allowed"})
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Disposition", f'attachment; filename="{f.name}"')
        data = f.read_bytes()
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    # ---------- API
    def _api(self, method, path, q, b):
        m = re.match
        if path == "/api/overview":
            return service.team_overview()
        if path == "/api/members" and method == "POST":
            if not b.get("name") or not b.get("file_b64"):
                raise ValueError("Name and resume file are required")
            r = service.onboard(b["name"], resume_b64=b["file_b64"], filename=b.get("filename"), email=b.get("email"),
                                prefs=b.get("prefs"), use_llm=bool(b.get("use_llm")))
            return {"slug": r["slug"], "audit": r["vault"]["audit"], "notes": r["profile"].get("parse_notes", []), "llm": r["llm"],
                    "matched": r.get("matched")}
        if (g := m(r"^/api/member/([\w-]+)$", path)):
            if method == "POST":
                v = service.update_member(g[1], b.get("profile"), b.get("prefs"))
                return {"ok": True, "audit": v["audit"]}
            with storage.connect() as con:
                mem = storage.member(con, g[1])
            if not mem:
                raise KeyError(g[1])
            prof = dict(mem["profile"])
            prof.pop("raw_text", None)
            return {"slug": mem["slug"], "name": mem["name"], "email": mem["email"], "profile": prof, "prefs": mem["prefs"],
                    "audit": analyze.audit(mem["profile"], mem["prefs"].get("region", "US")), "resume_file": mem["resume_file"]}
        if (g := m(r"^/api/member/([\w-]+)/delete$", path)) and method == "POST":
            with storage.connect() as con:
                mem = storage.member(con, g[1])
                storage.delete_member(con, mem["id"])
            return {"ok": True}
        if (g := m(r"^/api/member/([\w-]+)/matches$", path)):
            return service.member_matches(g[1], status=q.get("status", [None])[0], tier=q.get("tier", [None])[0],
                                          new_only=q.get("new", ["0"])[0] == "1", limit=int(q.get("limit", ["300"])[0]))
        if (g := m(r"^/api/member/([\w-]+)/rematch$", path)) and method == "POST":
            return service.rematch(g[1], b.get("days"))
        if (g := m(r"^/api/member/([\w-]+)/match/(\d+)$", path)) and method == "POST":
            with storage.connect() as con:
                mem = storage.member(con, g[1])
                storage.set_match_status(con, mem["id"], int(g[2]), b["status"])
            return {"ok": True}
        if (g := m(r"^/api/member/([\w-]+)/applications$", path)):
            return service.applications(g[1])
        if (g := m(r"^/api/application/(\d+)$", path)) and method == "POST":
            with storage.connect() as con:
                storage.set_application_status(con, int(g[1]), b["status"], b.get("note"))
            return {"ok": True}
        if path == "/api/apply" and method == "POST":
            r = service.apply(b["slug"], job_id=b.get("job_id"), url=b.get("url") or None, jd_text=b.get("jd_text") or None,
                              company=b.get("company") or None, title=b.get("title") or None, polish=bool(b.get("polish")))
            r.pop("spec", None)
            return r
        if path == "/api/check" and method == "POST":
            res = writing.check(b.get("text", ""), b.get("limit") or None, b.get("kind", "prose"))
            return {"result": res, "report": writing.format_report(res)}
        if path == "/api/scan" and method == "POST":
            if cloud.enabled():
                return {**cloud.run_scan_now(), "message": "The scan runs on GitHub. Results show up here when it finishes (about 1-2 hours)."}
            return service.start_scan_background(int(b.get("days", 2)), b.get("limit"))
        if path == "/api/scan/stop" and method == "POST":
            return service.stop_scan()
        if path == "/api/scan/log":
            return {"lines": service.scan_log_tail(40), "running": service.scanner.running() is not None}
        if (g := m(r"^/api/member/([\w-]+)/vault$", path)):
            d = config.member_dir(g[1]) / "vault"
            return sorted(str(p.relative_to(d)).replace("\\", "/") for p in d.rglob("*.md"))
        if (g := m(r"^/api/member/([\w-]+)/vault/(.+)$", path)):
            d = (config.member_dir(g[1]) / "vault").resolve()
            f = (d / urllib.parse.unquote(g[2])).resolve()
            if not str(f).startswith(str(d)) or not f.is_file():
                raise KeyError(g[2])
            return {"name": f.name, "text": f.read_text(encoding="utf-8"), "path": str(f)}
        if path == "/api/knowledge":
            return sorted(p.name for p in config.KNOWLEDGE.glob("*.md"))
        if (g := m(r"^/api/knowledge/([\w.-]+\.md)$", path)):
            return {"text": (config.KNOWLEDGE / g[1]).read_text(encoding="utf-8")}
        return None


def serve(host="127.0.0.1", port=8765):
    config.ensure_dirs()
    cloud.refresh()
    with storage.connect():
        pass
    if host not in ("127.0.0.1", "localhost") and not TOKEN:
        print("WARNING: sharing on the network without TEAMBID_TOKEN means anyone on it can read every member's data.")
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"TeamBid running at http://{'localhost' if host in ('127.0.0.1', '0.0.0.0') else host}:{port}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            cloud.flush()
        except Exception as e:
            print(f"cloud push failed, run 'python tb.py cloud push': {e}")

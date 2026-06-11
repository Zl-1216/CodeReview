"""Tiny git smart-http server for e2e tests.

Exposes a single bare repo at http://host:port/{name}.git over the
smart-http protocol (the only protocol that works through a default
Python `http.server`-style framework, since `git://` needs `git daemon`).

Usage:
    python _git_smart_http.py <bare_repo_path> <port>

This is a test-only fixture, intentionally minimal: GET
/info/refs?service=git-upload-pack returns the ref list as a pkt-line
stream; POST /git-upload-pack runs `git upload-pack --stateless-rpc`
and streams the response back. Enough to satisfy a real `git clone
--depth 1` from our cache code — when used with a real public repo
served over https.

This file is intentionally NOT used by the project's e2e script. It
exists so contributors who want to wire up a local clone target can
spin up a smart-http server without standing up Apache + git-http-backend.
For the official e2e path, see scripts/verify_remote.sh.
"""
import os
import subprocess
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

if len(sys.argv) != 3:
    print("usage: _git_smart_http.py <bare_repo> <port>", file=sys.stderr)
    sys.exit(2)

REPO = os.path.abspath(sys.argv[1])
PORT = int(sys.argv[2])
REPO_NAME = os.path.basename(REPO).removesuffix(".git")


def pkt_line(s: bytes) -> bytes:
    """Format `s` as a git pkt-line: 4-hex-len prefix + payload + LF."""
    n = len(s) + 4
    return f"{n:04x}".encode() + s


def run_git(args, input_bytes=None):
    return subprocess.run(
        # -c http.sslVerify=false makes the server's own git accept our
        # self-signed cert when this script is run with --tls.
        ["git", "-c", "http.sslVerify=false", *args],
        cwd=REPO,
        input=input_bytes,
        capture_output=True,
        check=True,
    )


def build_info_refs() -> bytes:
    """Ref advertisement for GET /info/refs?service=git-upload-pack.

    The smart-http protocol requires:
      1. A pkt-line "version" header: 001e# service=git-upload-pack\\n
      2. A flush packet: 0000
      3. The body from `git upload-pack --advertise-refs`
    Without the version+flush, modern `git` clients reject the response
    with "invalid server response".
    """
    preamble = (
        b"001e# service=git-upload-pack\n"
        b"0000"
    )
    body = run_git(["upload-pack", "--stateless-rpc", "--advertise-refs", REPO]).stdout
    return preamble + body


def handle_upload_pack(body: bytes) -> bytes:
    """Stateless-rpc `git upload-pack` response to the client's want/have."""
    return run_git(["upload-pack", "--stateless-rpc", REPO], body).stdout


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # silence default access log
        pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        # /<name>.git/info/refs?service=git-upload-pack
        if u.path.endswith("/info/refs") and u.query.startswith("service=git-upload-pack"):
            body = build_info_refs()
            self.send_response(200)
            self.send_header("Content-Type", f"application/x-{u.query.split('=', 1)[1]}-advertisement")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(404)

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path.endswith("/git-upload-pack"):
            n = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(n) if n else b""
            resp = handle_upload_pack(body)
            self.send_response(200)
            self.send_header("Content-Type", "application/x-git-upload-pack-result")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)
            return
        self.send_error(404)


if __name__ == "__main__":
    print(f"git smart-http serving {REPO} on http://127.0.0.1:{PORT}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()

import io
import json
import os
import tarfile
import time
import urllib.request
from unittest import mock

import pytest

import own_server


def make_tar(files: dict, extra=None) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, content in files.items():
            data = content.encode()
            ti = tarfile.TarInfo(f"repo-abc123/{name}")
            ti.size = len(data)
            tar.addfile(ti, io.BytesIO(data))
        for ti, payload in (extra or []):
            tar.addfile(ti, payload)
    return buf.getvalue()


def fake_get(tarball: bytes):
    resp = mock.Mock()
    resp.status_code = 200
    resp.iter_content = lambda n: iter([tarball[i:i + n] for i in range(0, len(tarball), n)])
    return mock.Mock(return_value=resp)


@pytest.fixture(autouse=True)
def init_engine():
    own_server.init()
    yield
    for p in list(own_server._load().values()):  # never leave processes behind
        own_server._kill(p.get("pid"))
        own_server._kill(p.get("tunnel_pid"))


def wait_done(pid, timeout=90):
    end = time.time() + timeout
    while time.time() < end:
        info = own_server._load()[pid]
        if info["status"] != "building":
            return info
        time.sleep(0.5)
    raise AssertionError("deploy did not finish")


APP = '''import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"env": dict(os.environ)}).encode()
        self.send_response(200); self.send_header("Content-Type","application/json"); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass
HTTPServer(("127.0.0.1", int(os.environ["PORT"])), H).serve_forever()
'''


def test_deploy_runs_app_and_does_not_leak_server_secrets():
    os.environ["SUPER_SECRET_SERVER_VALUE"] = "leak-me"
    tarball = make_tar({"app.py": APP})
    with mock.patch("own_server.requests.get", fake_get(tarball)):
        pid = own_server.start_deploy("ghp_x", "alice", "demo", "user_1", env={"MY_VAR": "hello", "PATH": "/evil", "NODE_OPTIONS": "--inspect"})
        info = wait_done(pid)
    assert info["status"] == "running", info.get("error")
    assert info["type"] == "python"

    env = json.loads(urllib.request.urlopen(f"http://127.0.0.1:{info['port']}", timeout=10).read())["env"]
    # the server's own secrets must never reach a deployed app
    for secret in ("GROQ_API_KEY", "SECRET_KEY", "GITHUB_CLIENT_SECRET", "ENCRYPTION_KEY", "SUPER_SECRET_SERVER_VALUE", "SMTP_PASSWORD"):
        assert secret not in env, f"{secret} leaked into deployed app"
    assert env["MY_VAR"] == "hello" and env["PORT"] == str(info["port"])
    assert env["PATH"] != "/evil" and "inspect" not in env.get("NODE_OPTIONS", "")   # protected vars can't be hijacked

    own_server.stop_project(pid, "user_1")
    time.sleep(0.5)
    assert own_server._load()[pid]["status"] == "stopped" and not own_server.is_alive(info["pid"])


def test_other_users_cannot_touch_a_deployment():
    with mock.patch("own_server.requests.get", fake_get(make_tar({"index.html": "<h1>hi</h1>"}))):
        pid = own_server.start_deploy("t", "a", "b", "owner_user")
        wait_done(pid)
    with pytest.raises(PermissionError):
        own_server.stop_project(pid, "someone_else")
    with pytest.raises(PermissionError):
        own_server.read_log(pid, "someone_else")
    assert own_server.list_projects("someone_else") == []
    own_server.stop_project(pid, "owner_user", remove=True)


def test_static_site_serves_and_binary_files_survive():
    png = bytes(range(256)) * 4
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for name, data in (("index.html", b"<h1>hello static</h1>"), ("logo.png", png)):
            ti = tarfile.TarInfo(f"r-1/{name}"); ti.size = len(data); tar.addfile(ti, io.BytesIO(data))
    with mock.patch("own_server.requests.get", fake_get(buf.getvalue())):
        pid = own_server.start_deploy("t", "a", "b", "u1")
        info = wait_done(pid)
    assert info["status"] == "running" and info["type"] == "static"
    base = f"http://127.0.0.1:{info['port']}"
    assert b"hello static" in urllib.request.urlopen(base, timeout=10).read()
    assert urllib.request.urlopen(base + "/logo.png", timeout=10).read() == png     # old engine corrupted/skipped binaries
    own_server.stop_project(pid, "u1")


def test_malicious_tarball_cannot_write_outside_project(tmp_path):
    evil = tarfile.TarInfo("repo-1/../../escaped.txt"); evil.size = 4
    link = tarfile.TarInfo("repo-1/link"); link.type = tarfile.SYMTYPE; link.linkname = "/etc/passwd"
    tarball = make_tar({"index.html": "ok"}, extra=[(evil, io.BytesIO(b"pwnd")), (link, io.BytesIO(b""))])
    dest = tmp_path / "proj"; dest.mkdir()
    with mock.patch("own_server.requests.get", fake_get(tarball)):
        own_server._download("t", "a", "b", dest)
    assert (dest / "index.html").exists()
    assert not (tmp_path / "escaped.txt").exists() and not (tmp_path.parent / "escaped.txt").exists()
    assert not (dest / "link").exists()


def test_limits_failures_and_monorepo_choice():
    with pytest.raises(ValueError):
        own_server.start_deploy("t", "a", "b", "u", root="../..")
    # two apps, no folder chosen -> clear error that names the folders
    mono = make_tar({"backend/app.py": "print(1)", "web/index.html": "<p>x</p>"})
    with mock.patch("own_server.requests.get", fake_get(mono)):
        pid = own_server.start_deploy("t", "a", "b", "u2")
        info = wait_done(pid)
    assert info["status"] == "failed" and "backend" in info["error"] and "web" in info["error"]

    # per-user limit
    own_server.config.OWN_SERVER_MAX_PER_USER = 1
    try:
        with mock.patch("own_server.requests.get", fake_get(make_tar({"index.html": "x"}))):
            first = own_server.start_deploy("t", "a", "b", "u3")
            with pytest.raises(RuntimeError, match="at most"):
                own_server.start_deploy("t", "a", "b", "u3")
            wait_done(first)
            own_server.stop_project(first, "u3")
    finally:
        own_server.config.OWN_SERVER_MAX_PER_USER = 3


def test_ttl_reaper_expires_deployments():
    with mock.patch("own_server.requests.get", fake_get(make_tar({"index.html": "x"}))):
        pid = own_server.start_deploy("t", "a", "b", "u4")
        info = wait_done(pid)
    assert info["status"] == "running"
    own_server._update(pid, expires_at=time.time() - 1)
    own_server._reap_once()
    assert own_server._load()[pid]["status"] == "expired" and not own_server.is_alive(info["pid"])

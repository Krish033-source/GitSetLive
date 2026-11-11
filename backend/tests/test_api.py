import json
import sqlite3
import time
from unittest import mock

import config
import db
import encryption
import github
import security
from conftest import make_user


# ------------------------------------------------------------ migration
def test_legacy_db_is_merged_and_tokens_encrypted():
    """The old login inserted a new user + workspace on EVERY login. Simulate that and migrate."""
    conn = sqlite3.connect(str(config.DB_PATH))
    conn.executescript("""
        DROP TABLE users; DROP TABLE workspaces; DROP TABLE workspace_members;
        CREATE TABLE users (id TEXT PRIMARY KEY, github_id TEXT, username TEXT, email TEXT, github_token TEXT, created_at TIMESTAMP, updated_at TIMESTAMP);
        CREATE TABLE workspaces (id TEXT PRIMARY KEY, name TEXT, owner_id TEXT, created_at TIMESTAMP);
        CREATE TABLE workspace_members (id TEXT PRIMARY KEY, workspace_id TEXT, user_id TEXT, role TEXT);
    """)
    for i, (uid, tok) in enumerate([("user_old", "gho_old"), ("user_new", "gho_new")]):
        conn.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?)", (uid, "42", "krish", "k@x.com", tok, f"2026-01-0{i+1}", f"2026-01-0{i+1}"))
        conn.execute("INSERT INTO workspaces VALUES (?,?,?,?)", (f"ws_{i}", "krish's Workspace", uid, f"2026-01-0{i+1}"))
        conn.execute("INSERT INTO workspace_members VALUES (?,?,?,?)", (f"wm_{i}", f"ws_{i}", uid, "admin"))
    conn.execute("INSERT INTO deployments (id, user_id, repo_name) VALUES ('d1','user_old','demo')")
    conn.commit(); conn.close()

    db.init_db()
    db.init_db()  # idempotent

    with db.db() as c:
        users = c.execute("SELECT * FROM users").fetchall()
        assert len(users) == 1 and users[0]["id"] == "user_new"
        assert users[0]["github_token"] is None
        assert encryption.decrypt(users[0]["github_token_enc"]) == "gho_new"
        assert c.execute("SELECT user_id FROM deployments").fetchone()[0] == "user_new"
        assert c.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] == 1
        try:
            c.execute("INSERT INTO users (id, github_id) VALUES ('x','42')")
            assert False, "github_id must now be unique"
        except sqlite3.IntegrityError:
            pass


# ----------------------------------------------------------------- auth
def test_protected_routes_need_a_valid_session(client):
    assert client.get("/repos").status_code == 401
    assert client.get("/repos", headers={"Authorization": "Bearer gsl_bogus"}).status_code == 401
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/config").json()["own_server_enabled"] is True


def test_github_token_in_old_style_url_is_not_accepted(client):
    u = make_user()
    assert client.get(f"/repos?token={u['token']}").status_code == 401


def test_full_oauth_login_flow(client):
    r = client.get("/login")
    assert r.status_code == 302 and "github.com/login/oauth/authorize" in r.headers["location"]
    assert "delete_repo" not in r.headers["location"]       # least privilege by default
    state = r.cookies.get("gsl_oauth_state")
    assert state and f"state={state}" in r.headers["location"]
    assert "delete_repo" in client.get("/login?extra=delete_repo").headers["location"]

    def fake_post(url, **kw):
        m = mock.Mock(); m.json.return_value = {"access_token": "gho_real", "scope": "repo,user:email,read:user"}; return m

    def fake_gh(method, path, token, **kw):
        m = mock.Mock()
        m.json.return_value = ({"id": 777, "login": "bob", "email": None, "avatar_url": "http://a"} if path == "/user"
                               else [{"email": "bob@x.com", "primary": True, "verified": True}])
        return m

    with mock.patch("routers.auth.requests.post", fake_post), mock.patch("routers.auth.github.request", fake_gh):
        client.cookies.set("gsl_oauth_state", state)
        cb = client.get(f"/callback?code=abc&state={state}")
        assert cb.status_code == 302
        loc = cb.headers["location"]
        assert loc.startswith("http://localhost:3000/callback#token=gsl_")     # fragment, not query
        token = loc.split("#token=")[1]

        # logging in again must NOT create a second user (old bug)
        client.cookies.set("gsl_oauth_state", state)
        client.get(f"/callback?code=abc&state={state}")

    with db.db() as c:
        assert c.execute("SELECT COUNT(*) FROM users WHERE github_id='777'").fetchone()[0] == 1
        row = c.execute("SELECT github_token, github_token_enc, email FROM users WHERE github_id='777'").fetchone()
        assert row["github_token"] is None and "gho_real" not in row["github_token_enc"] and row["email"] == "bob@x.com"
        assert c.execute("SELECT COUNT(*) FROM workspaces").fetchone()[0] == 1

    h = {"Authorization": f"Bearer {token}"}
    me = client.get("/me", headers=h).json()
    assert me["username"] == "bob" and me["can_delete_repos"] is False
    assert client.post("/logout", headers=h).status_code == 200
    assert client.get("/me", headers=h).status_code == 401          # revoked


def test_callback_rejects_forged_or_missing_state(client):
    assert "error=" in client.get("/callback?code=abc&state=forged").headers["location"]
    good = security.make_state()
    assert "error=" in client.get(f"/callback?code=abc&state={good}").headers["location"]  # no cookie


def test_expired_session_is_rejected(client):
    u = make_user()
    with db.db() as c:
        c.execute("UPDATE sessions SET expires_at='2000-01-01T00:00:00Z'")
    assert client.get("/me", headers=u["headers"]).status_code == 401


def test_rate_limit(client):
    u = make_user()
    codes = []
    with mock.patch("routers.scan.github.fetch_snapshot", side_effect=github.GitHubError(404, "nf")):
        for _ in range(32):
            codes.append(client.get("/analyze?owner=a&repo=b", headers=u["headers"]).status_code)
    assert 429 in codes and codes[0] == 404


# ------------------------------------------------------------ workspaces
def test_workspace_roles_are_enforced(client):
    admin, viewer, outsider = make_user("admin", "1"), make_user("vera", "2"), make_user("olly", "3")
    ws = client.post("/workspaces", json={"name": "Team"}, headers=admin["headers"]).json()["id"]

    # invite by GitHub username works even when the email is private
    assert client.post(f"/workspaces/{ws}/invite", json={"identifier": "@Vera", "role": "viewer"}, headers=admin["headers"]).status_code == 200
    # a viewer can NOT invite (old bug: any member could, even as admin)
    r = client.post(f"/workspaces/{ws}/invite", json={"identifier": "olly", "role": "admin"}, headers=viewer["headers"])
    assert r.status_code == 403
    # non-members can't even list members
    assert client.get(f"/workspaces/{ws}/members", headers=outsider["headers"]).status_code == 403
    assert client.get(f"/workspaces/{ws}/members", headers=viewer["headers"]).status_code == 200
    # role validation + last-admin protection
    assert client.post(f"/workspaces/{ws}/invite", json={"identifier": "olly", "role": "root"}, headers=admin["headers"]).status_code == 422
    assert client.patch(f"/workspaces/{ws}/members/{admin['id']}", json={"role": "viewer"}, headers=admin["headers"]).status_code == 409
    assert client.delete(f"/workspaces/{ws}/members/{admin['id']}", headers=admin["headers"]).status_code == 409
    assert client.delete(f"/workspaces/{ws}/members/{viewer['id']}", headers=viewer["headers"]).status_code == 200  # leave


# --------------------------------------------------- deployments / safety
def test_deployment_urls_must_be_http(client):
    u = make_user()
    bad = client.post("/deployments", json={"repo_name": "r", "provider": "render", "live_url": "javascript:alert(1)"}, headers=u["headers"])
    assert bad.status_code == 400
    ok = client.post("/deployments", json={"repo_name": "r", "provider": "render", "live_url": "https://r.onrender.com"}, headers=u["headers"])
    assert ok.status_code == 200
    s = client.get("/stats", headers=u["headers"]).json()
    assert s["deployments"]["live"] == 1 and s["success_rate"] == 100


def test_users_cannot_see_each_others_data(client):
    a, b = make_user("a", "1"), make_user("b", "2")
    client.post("/deployments", json={"repo_name": "secret-repo", "provider": "other"}, headers=a["headers"])
    assert client.get("/deployments", headers=b["headers"]).json()["deployments"] == []
    dep = client.get("/deployments", headers=a["headers"]).json()["deployments"][0]["id"]
    assert client.delete(f"/deployments/{dep}", headers=b["headers"]).status_code == 404


def test_env_vars_encrypted_and_values_never_returned(client):
    u = make_user()
    r = client.put("/env", json={"owner": "alice", "repo": "app", "vars": [{"key": "API_KEY", "value": "supersecret"}]}, headers=u["headers"])
    assert r.status_code == 200
    got = client.get("/env?owner=alice&repo=app", headers=u["headers"]).json()
    assert got["vars"][0]["key"] == "API_KEY" and "supersecret" not in json.dumps(got)
    with db.db() as c:
        assert "supersecret" not in c.execute("SELECT value_enc FROM project_env").fetchone()[0]
    assert client.put("/env", json={"owner": "alice", "repo": "app", "vars": [{"key": "bad key", "value": "x"}]}, headers=u["headers"]).status_code == 422


def test_delete_repo_requires_confirmation_and_scope(client):
    u = make_user()
    assert client.post("/repos/alice/app/delete", json={"confirm": "nope"}, headers=u["headers"]).status_code == 400
    r = client.post("/repos/alice/app/delete", json={"confirm": "app"}, headers=u["headers"])
    assert r.status_code == 403 and r.json()["detail"]["code"] == "needs_scope"


# ----------------------------------------------------- scan → fix → PR
def _snapshot():
    files = {"main.py": 'import os\nfrom fastapi import FastAPI\napp = FastAPI()\n\nif __name__ == "__main__":\n    import uvicorn\n    uvicorn.run(app, host="127.0.0.1", port=8000)\n',
             "requirements.txt": "fastapi\nuvicorn\n", "README.md": "# demo\n"}
    return github.Snapshot(ref="main", files=files, paths=sorted(files))


def test_scan_drops_hallucinated_ai_findings_and_applies_precise_fixes(client):
    u = make_user()
    ai_reply = [
        {"severity": "critical", "category": "security", "title": "Invented problem", "file": "main.py",
         "line_context": "this_code_does_not_exist()", "detail": "x", "replace": "y"},
        {"severity": "warning", "category": "logic", "title": "Port shadowing", "file": "main.py",
         "line_context": 'uvicorn.run(app, host="127.0.0.1", port=8000)', "detail": "d",
         "replace": 'uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))'},
    ]
    snap = _snapshot()
    with mock.patch("routers.scan.github.fetch_snapshot", return_value=snap), \
         mock.patch("routers.scan.ai.chat_json", return_value=ai_reply):
        res = client.post("/scan", json={"owner": "alice", "repo": "demo"}, headers=u["headers"]).json()

    titles = [f["title"] for f in res["findings"]]
    assert "Invented problem" not in titles                      # verified against the real file
    assert any(f["source"] == "ai" and f["fixable"] for f in res["findings"])
    assert all("fix" not in f for f in res["findings"])         # fixes stay server-side
    assert res["ai"]["ok"] and res["score"] < 100

    fixable = [f["id"] for f in res["findings"] if f["fixable"]]
    committed = {}

    def fake_commit(token, owner, repo, changes, message, **kw):
        committed.update({c["path"]: c["content"] for c in changes}); committed["_kw"] = kw
        return {"branch": "gitsetlive/fixes-1", "commit_sha": "abc", "commit_url": "u", "pr_url": "https://github.com/alice/demo/pull/1", "pr_number": 1}

    info = {"default_branch": "main", "permissions": {"push": True}}
    with mock.patch("routers.common.github.get_repo", return_value=info), \
         mock.patch("routers.scan.github.get_file", side_effect=lambda t, o, r, p, ref=None: {"text": snap.files[p], "sha": "s"} if p in snap.files else None), \
         mock.patch("routers.scan.github.commit_files", side_effect=fake_commit):
        out = client.post("/scan/apply", json={"owner": "alice", "repo": "demo", "scan_id": res["scan_id"], "finding_ids": fixable}, headers=u["headers"])
    assert out.status_code == 200 and out.json()["pr_url"].endswith("/pull/1")
    assert "0.0.0.0" in committed["main.py"] and "from fastapi import FastAPI" in committed["main.py"]  # rest of file intact
    assert committed["_kw"]["new_branch"].startswith("gitsetlive/")                                     # PR, never straight to main

    # someone else's scan id can't be applied
    other = make_user("mallory", "9")
    with mock.patch("routers.common.github.get_repo", return_value=info):
        r = client.post("/scan/apply", json={"owner": "alice", "repo": "demo", "scan_id": res["scan_id"], "finding_ids": fixable}, headers=other["headers"])
    assert r.status_code == 404


def test_scan_still_returns_static_results_when_ai_is_down(client):
    import ai
    u = make_user()
    with mock.patch("routers.scan.github.fetch_snapshot", return_value=_snapshot()), \
         mock.patch("routers.scan.ai.chat_json", side_effect=ai.AIError("down")):
        res = client.post("/scan", json={"owner": "a", "repo": "b"}, headers=u["headers"]).json()
    assert res["ai"]["ok"] is False and res["findings"]


def test_propose_validates_ai_edits_against_real_files(client):
    u = make_user()
    snap = _snapshot()
    reply = {"summary": "add health", "changes": [
        {"path": "main.py", "action": "edit", "edits": [{"search": "app = FastAPI()", "replace": 'app = FastAPI()\n\n@app.get("/health")\ndef health():\n    return {"ok": True}'}], "reason": "r"},
        {"path": "main.py", "action": "edit", "edits": [{"search": "nonexistent", "replace": "x"}]},
        {"path": "../etc/passwd", "action": "create", "content": "x"},
        {"path": "README.md", "action": "create", "content": "overwrite!"},
        {"path": ".env.example", "action": "create", "content": "A=\n"}]}
    with mock.patch("routers.ai_tools.github.fetch_snapshot", return_value=snap), mock.patch("routers.ai_tools.ai.chat_json", return_value=reply):
        res = client.post("/ai/propose", json={"owner": "a", "repo": "b", "prompt": "add a health endpoint"}, headers=u["headers"]).json()
    paths = [c["path"] for c in res["changes"]]
    assert paths == ["main.py", ".env.example"] and len(res["warnings"]) == 3
    assert "/health" in res["changes"][0]["content"] and res["changes"][0]["diff"].startswith("--- a/main.py")
    assert res["changes"][1]["sensitive"] is True


# ------------------------------------------------------------ github util
def test_safe_path_blocks_traversal():
    for bad in ("../x", "a/../b", "/abs", ".git/config", "a\\b", "", "a//b"):
        try:
            github.safe_path(bad); assert False, bad
        except github.GitHubError:
            pass
    assert github.safe_path("src/app.py") == "src/app.py"

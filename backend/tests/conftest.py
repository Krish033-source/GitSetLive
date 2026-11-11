import os
import sys
import tempfile
from pathlib import Path

# Must be set BEFORE any backend module is imported.
_tmp = tempfile.mkdtemp(prefix="gsl-test-")
os.environ.update({
    "SECRET_KEY": "test-secret-key-at-least-16-chars",
    "DATA_DIR": _tmp,
    "ENV": "development",
    "GROQ_API_KEY": "gsk_fake_for_tests",
    "GITHUB_CLIENT_ID": "cid",
    "GITHUB_CLIENT_SECRET": "csecret",
    "FRONTEND_URL": "http://localhost:3000",
    "OWN_SERVER_ENABLED": "true",
})
os.environ.pop("ENCRYPTION_KEY", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import db  # noqa: E402
import encryption  # noqa: E402
import security  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    for f in Path(_tmp).glob("app.db*"):
        f.unlink()
    db.init_db()
    security.reset_rate_limits()
    yield


def make_user(username="alice", github_id="1", scopes="repo,read:user,user:email", email=None):
    uid = db.new_id("user")
    with db.db() as conn:
        conn.execute(
            "INSERT INTO users (id, github_id, username, email, github_token_enc, scopes, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (uid, github_id, username, email or f"{username}@example.com", encryption.encrypt("ghp_" + username),
             scopes, db.now(), db.now()))
        ws = db.new_id("ws")
        conn.execute("INSERT INTO workspaces (id, name, owner_id, created_at) VALUES (?,?,?,?)",
                     (ws, f"{username}'s Workspace", uid, db.now()))
        conn.execute("INSERT INTO workspace_members (id, workspace_id, user_id, role) VALUES (?,?,?,?)",
                     (db.new_id("wm"), ws, uid, "admin"))
    token = security.create_session(uid, "pytest")
    return {"id": uid, "token": token, "ws": ws, "headers": {"Authorization": f"Bearer {token}"}}


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app, follow_redirects=False) as c:
        yield c

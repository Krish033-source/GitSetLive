"""SQLite layer: connection helper, schema, and idempotent migrations.

`init_db()` is safe to call on every startup. It creates missing tables,
adds missing columns to older databases, merges duplicate users created by
the old login flow, and encrypts any GitHub tokens that were stored in
plaintext.
"""

import json
import logging
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

import config
import encryption

log = logging.getLogger("gitsetlive.db")


def now() -> str:
    """UTC ISO timestamp, always with an explicit 'Z' so browsers parse it correctly."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


@contextmanager
def db() -> Iterator[sqlite3.Connection]:
    """Commit on success, roll back on error, always close — no leaked connections."""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


SCHEMA = [
    """CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        github_id TEXT,
        username TEXT,
        email TEXT,
        avatar_url TEXT,
        github_token TEXT,
        github_token_enc TEXT,
        scopes TEXT,
        created_at TIMESTAMP,
        updated_at TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        token_hash TEXT NOT NULL UNIQUE,
        user_agent TEXT,
        created_at TEXT,
        last_used_at TEXT,
        expires_at TEXT NOT NULL
    )""",
    """CREATE TABLE IF NOT EXISTS workspaces (
        id TEXT PRIMARY KEY,
        name TEXT,
        owner_id TEXT,
        created_at TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS workspace_members (
        id TEXT PRIMARY KEY,
        workspace_id TEXT,
        user_id TEXT,
        role TEXT
    )""",
    """CREATE TABLE IF NOT EXISTS deployments (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        workspace_id TEXT,
        repo_name TEXT,
        repo_url TEXT,
        service_id TEXT,
        status TEXT,
        live_url TEXT,
        created_at TIMESTAMP,
        updated_at TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS activity_logs (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        workspace_id TEXT,
        action TEXT,
        details TEXT,
        created_at TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS api_keys (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        platform TEXT,
        encrypted_key TEXT,
        platform_account_name TEXT,
        created_at TIMESTAMP,
        UNIQUE(user_id, platform)
    )""",
    """CREATE TABLE IF NOT EXISTS scan_results (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        repo_name TEXT,
        scan_type TEXT,
        issues TEXT,
        created_at TIMESTAMP
    )""",
    """CREATE TABLE IF NOT EXISTS project_env (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL,
        repo TEXT NOT NULL,
        key TEXT NOT NULL,
        value_enc TEXT NOT NULL,
        updated_at TEXT,
        UNIQUE(user_id, repo, key)
    )""",
]

# columns added after v1 — (table, column, type)
NEW_COLUMNS = [
    ("users", "avatar_url", "TEXT"),
    ("users", "github_token_enc", "TEXT"),
    ("users", "scopes", "TEXT"),
    ("deployments", "provider", "TEXT"),
    ("deployments", "project_id", "TEXT"),
    ("deployments", "stack", "TEXT"),
    ("scan_results", "repo_full_name", "TEXT"),
    ("scan_results", "score", "INTEGER"),
    ("scan_results", "summary", "TEXT"),
]

INDEXES = [
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_github_id ON users(github_id) WHERE github_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id)",
    "CREATE INDEX IF NOT EXISTS idx_deployments_user ON deployments(user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_activity_user ON activity_logs(user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_scans_user ON scan_results(user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_members_ws ON workspace_members(workspace_id)",
    "CREATE INDEX IF NOT EXISTS idx_members_user ON workspace_members(user_id)",
]


def _columns(conn: sqlite3.Connection, table: str) -> set:
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}  # nosec - constant table


def _merge_user(conn: sqlite3.Connection, keep: str, dup: str) -> None:
    """Fold a duplicate user row (same GitHub account) into the one we keep."""
    conn.execute("UPDATE workspaces SET owner_id=? WHERE owner_id=?", (keep, dup))

    for row in conn.execute(
        "SELECT id, workspace_id FROM workspace_members WHERE user_id=?", (dup,)
    ).fetchall():
        already = conn.execute(
            "SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?",
            (row["workspace_id"], keep),
        ).fetchone()
        if already:
            conn.execute("DELETE FROM workspace_members WHERE id=?", (row["id"],))
        else:
            conn.execute("UPDATE workspace_members SET user_id=? WHERE id=?", (keep, row["id"]))

    for table in ("deployments", "activity_logs", "scan_results"):
        conn.execute(f"UPDATE {table} SET user_id=? WHERE user_id=?", (keep, dup))  # nosec - table is a constant

    conn.execute("UPDATE OR IGNORE api_keys SET user_id=? WHERE user_id=?", (keep, dup))
    conn.execute("DELETE FROM api_keys WHERE user_id=?", (dup,))
    conn.execute("DELETE FROM users WHERE id=?", (dup,))


def _merge_default_workspaces(conn: sqlite3.Connection) -> None:
    """The old login created a fresh "<user>'s Workspace" on every login."""
    for u in conn.execute("SELECT id, username FROM users").fetchall():
        if not u["username"]:
            continue
        name = f"{u['username']}'s Workspace"
        rows = conn.execute(
            "SELECT id FROM workspaces WHERE owner_id=? AND name=? ORDER BY created_at ASC",
            (u["id"], name),
        ).fetchall()
        if len(rows) < 2:
            continue
        keep = rows[0]["id"]
        for extra in rows[1:]:
            ws = extra["id"]
            for m in conn.execute(
                "SELECT id, user_id FROM workspace_members WHERE workspace_id=?", (ws,)
            ).fetchall():
                exists = conn.execute(
                    "SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?",
                    (keep, m["user_id"]),
                ).fetchone()
                if exists:
                    conn.execute("DELETE FROM workspace_members WHERE id=?", (m["id"],))
                else:
                    conn.execute("UPDATE workspace_members SET workspace_id=? WHERE id=?", (keep, m["id"]))
            conn.execute("UPDATE deployments SET workspace_id=? WHERE workspace_id=?", (keep, ws))
            conn.execute("UPDATE activity_logs SET workspace_id=? WHERE workspace_id=?", (keep, ws))
            conn.execute("DELETE FROM workspaces WHERE id=?", (ws,))


def _migrate_users(conn: sqlite3.Connection) -> dict:
    """Dedupe users per GitHub account and encrypt plaintext tokens."""
    stats = {"merged_users": 0, "encrypted_tokens": 0}

    rows = conn.execute(
        "SELECT id, github_id FROM users WHERE github_id IS NOT NULL "
        "ORDER BY COALESCE(updated_at, created_at) DESC"
    ).fetchall()
    groups: dict = {}
    for r in rows:
        groups.setdefault(str(r["github_id"]), []).append(r["id"])

    for ids in groups.values():
        keep, dups = ids[0], ids[1:]
        for dup in dups:
            _merge_user(conn, keep, dup)
            stats["merged_users"] += 1

    if stats["merged_users"]:
        _merge_default_workspaces(conn)

    for r in conn.execute(
        "SELECT id, github_token FROM users WHERE github_token IS NOT NULL AND github_token != ''"
    ).fetchall():
        conn.execute(
            "UPDATE users SET github_token_enc=COALESCE(github_token_enc, ?), github_token=NULL WHERE id=?",
            (encryption.encrypt(r["github_token"]), r["id"]),
        )
        stats["encrypted_tokens"] += 1

    return stats


def init_db() -> None:
    with db() as conn:
        for stmt in SCHEMA:
            conn.execute(stmt)

        for table, col, ctype in NEW_COLUMNS:
            if col not in _columns(conn, table):
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ctype}")  # nosec - constants from NEW_COLUMNS

        stats = _migrate_users(conn)

        for stmt in INDEXES:
            conn.execute(stmt)

    if stats["merged_users"] or stats["encrypted_tokens"]:
        log.warning("DB migration: %s", stats)


# ------------------------------------------------------------------ helpers
def log_activity(user_id: str, action: str, details: Optional[dict] = None,
                 workspace_id: Optional[str] = None) -> None:
    try:
        with db() as conn:
            conn.execute(
                "INSERT INTO activity_logs (id, user_id, workspace_id, action, details, created_at) "
                "VALUES (?,?,?,?,?,?)",
                (new_id("log"), user_id, workspace_id, action, json.dumps(details or {}), now()),
            )
    except Exception:  # activity logging must never break a request
        log.exception("could not write activity log")

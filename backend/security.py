"""Authentication and abuse protection.

Sessions
--------
The old login handed the browser a Fernet-encrypted copy of the user's *GitHub
token* and treated that as the session: it never expired, couldn't be revoked,
and was passed around in URLs. Now:

* login creates a random opaque session token (stored only as an HMAC hash),
* it expires after SESSION_DAYS and can be revoked (logout / logout-all),
* it is sent in the `Authorization: Bearer` header — never in a URL,
* the user's real GitHub token stays encrypted in the database.
"""

import hashlib
import hmac
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from fastapi import Depends, Header, HTTPException

import config
import db
import encryption

SESSION_PREFIX = "gsl_"


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash(token: str) -> str:
    return hmac.new(config.SECRET_KEY.encode(), token.encode(), hashlib.sha256).hexdigest()


# ------------------------------------------------------------------ sessions
def create_session(user_id: str, user_agent: str = "") -> str:
    token = SESSION_PREFIX + secrets.token_urlsafe(40)
    now = datetime.now(timezone.utc)
    with db.db() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < ?", (_iso(now),))
        conn.execute(
            "INSERT INTO sessions (id, user_id, token_hash, user_agent, created_at, last_used_at, expires_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                db.new_id("ses"), user_id, _hash(token), (user_agent or "")[:200],
                _iso(now), _iso(now), _iso(now + timedelta(days=config.SESSION_DAYS)),
            ),
        )
    return token


def get_user_by_token(token: str) -> Optional[dict]:
    if not token or not token.startswith(SESSION_PREFIX):
        return None
    now = datetime.now(timezone.utc)
    with db.db() as conn:
        row = conn.execute(
            """SELECT s.id AS session_id, s.last_used_at, u.id, u.username, u.email,
                      u.avatar_url, u.scopes, u.github_token_enc
               FROM sessions s JOIN users u ON u.id = s.user_id
               WHERE s.token_hash = ? AND s.expires_at > ?""",
            (_hash(token), _iso(now)),
        ).fetchone()
        if not row:
            return None

        github_token = encryption.decrypt(row["github_token_enc"])
        if not github_token:  # key rotated / corrupt — force a clean re-login
            conn.execute("DELETE FROM sessions WHERE id=?", (row["session_id"],))
            return None

        if (row["last_used_at"] or "") < _iso(now - timedelta(minutes=10)):
            conn.execute("UPDATE sessions SET last_used_at=? WHERE id=?", (_iso(now), row["session_id"]))

    return {
        "id": row["id"],
        "username": row["username"],
        "email": row["email"],
        "avatar_url": row["avatar_url"],
        "scopes": [s for s in (row["scopes"] or "").replace(" ", ",").split(",") if s],
        "github_token": github_token,
        "session_id": row["session_id"],
    }


def revoke_session(session_id: str) -> None:
    with db.db() as conn:
        conn.execute("DELETE FROM sessions WHERE id=?", (session_id,))


def revoke_all_sessions(user_id: str) -> int:
    with db.db() as conn:
        return conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,)).rowcount


def _bearer(header: Optional[str]) -> Optional[str]:
    if not header:
        return None
    parts = header.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def current_user(authorization: Optional[str] = Header(None)) -> dict:
    """FastAPI dependency: the logged-in user, or a 401."""
    user = get_user_by_token(_bearer(authorization) or "")
    if not user:
        raise HTTPException(
            status_code=401,
            detail={"message": "You're not logged in, or your session expired.", "code": "unauthenticated"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


# ------------------------------------------------------------- OAuth `state`
STATE_MAX_AGE = 600


def _sign(value: str) -> str:
    return hmac.new(config.SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()[:32]


def make_state() -> str:
    """Signed, time-limited random value. It is stored in an HttpOnly cookie AND
    sent to GitHub; the callback only proceeds if both copies match (CSRF defence)."""
    body = f"{secrets.token_urlsafe(16)}.{int(time.time())}"
    return f"{body}.{_sign(body)}"


def check_state(state: str, cookie: str) -> bool:
    if not state or not cookie or not hmac.compare_digest(state, cookie):
        return False
    try:
        body, sig = state.rsplit(".", 1)
        _, ts = body.rsplit(".", 1)
        age = time.time() - int(ts)
    except ValueError:
        return False
    return hmac.compare_digest(sig, _sign(body)) and 0 <= age <= STATE_MAX_AGE


# -------------------------------------------------------------- rate limiting
_hits: dict = defaultdict(deque)
_lock = threading.Lock()


def _check_rate(key: str, limit: int, window: int) -> int:
    """Returns 0 if allowed, else the number of seconds until the next slot."""
    now = time.monotonic()
    with _lock:
        q = _hits[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return max(1, int(window - (now - q[0])) + 1)
        q.append(now)
        return 0


def rate_limit(bucket: str, limit: int, window: int) -> Callable:
    """Per-user sliding-window limiter, used as a route dependency.
    In-memory, so it is per-process — fine for one worker; use Redis if you scale out."""

    def dependency(user: dict = Depends(current_user)) -> None:
        wait = _check_rate(f"{bucket}:{user['id']}", limit, window)
        if wait:
            raise HTTPException(
                status_code=429,
                detail={"message": f"Too many requests. Try again in {wait}s.", "code": "rate_limited"},
                headers={"Retry-After": str(wait)},
            )

    return dependency


def reset_rate_limits() -> None:  # used by tests
    with _lock:
        _hits.clear()

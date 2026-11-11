"""GitHub OAuth login, sessions and the current-user endpoints."""

import logging
from urllib.parse import urlencode

import requests
from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse

import config
import db
import encryption
import github
import security

log = logging.getLogger("gitsetlive.auth")
router = APIRouter(tags=["auth"])

STATE_COOKIE = "gsl_oauth_state"
BASE_SCOPES = ["repo", "read:user", "user:email"]


def _frontend(path: str) -> str:
    return f"{config.FRONTEND_URL}{path}"


def _login_error(message: str) -> RedirectResponse:
    resp = RedirectResponse(_frontend("/login?" + urlencode({"error": message})), status_code=302)
    resp.delete_cookie(STATE_COOKIE, path="/")
    return resp


@router.get("/login")
def login(extra: str = ""):
    """Browser navigates here (top-level) and is redirected to GitHub.
    `extra=delete_repo` requests the dangerous delete_repo scope only when needed."""
    if not config.GITHUB_CLIENT_ID or not config.GITHUB_CLIENT_SECRET:
        return _login_error("GitHub login isn't configured on the server yet.")

    scopes = list(BASE_SCOPES)
    if "delete_repo" in extra.split(","):
        scopes.append("delete_repo")

    state = security.make_state()
    url = "https://github.com/login/oauth/authorize?" + urlencode(
        {"client_id": config.GITHUB_CLIENT_ID, "scope": " ".join(scopes), "state": state, "allow_signup": "true"}
    )
    resp = RedirectResponse(url, status_code=302)
    resp.set_cookie(STATE_COOKIE, state, max_age=security.STATE_MAX_AGE, httponly=True,
                    samesite="lax", secure=config.COOKIE_SECURE, path="/")
    return resp


def upsert_user(github_id: str, username: str, email, avatar, token: str, scopes: str) -> str:
    enc = encryption.encrypt(token)
    with db.db() as conn:
        row = conn.execute("SELECT id FROM users WHERE github_id=?", (github_id,)).fetchone()
        if row:
            conn.execute(
                "UPDATE users SET username=?, email=COALESCE(?, email), avatar_url=?, github_token_enc=?, "
                "github_token=NULL, scopes=?, updated_at=? WHERE id=?",
                (username, email, avatar, enc, scopes, db.now(), row["id"]),
            )
            return row["id"]

        user_id, ws_id = db.new_id("user"), db.new_id("ws")
        conn.execute(
            "INSERT INTO users (id, github_id, username, email, avatar_url, github_token_enc, scopes, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (user_id, github_id, username, email, avatar, enc, scopes, db.now(), db.now()),
        )
        conn.execute("INSERT INTO workspaces (id, name, owner_id, created_at) VALUES (?,?,?,?)",
                     (ws_id, f"{username}'s Workspace", user_id, db.now()))
        conn.execute("INSERT INTO workspace_members (id, workspace_id, user_id, role) VALUES (?,?,?,?)",
                     (db.new_id("wm"), ws_id, user_id, "admin"))
        return user_id


@router.get("/callback")
def callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error:
        return _login_error("GitHub login was cancelled.")
    if not (code and security.check_state(state, request.cookies.get(STATE_COOKIE, ""))):
        return _login_error("Your login attempt expired or was invalid. Please try again.")

    try:
        tok = requests.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={"client_id": config.GITHUB_CLIENT_ID, "client_secret": config.GITHUB_CLIENT_SECRET, "code": code},
            timeout=15,
        ).json()
        access_token = tok.get("access_token")
        if not access_token:
            log.warning("OAuth exchange failed: %s", tok.get("error"))
            return _login_error("GitHub didn't accept the login. Please try again.")
        scopes = tok.get("scope", "")

        profile = github.request("GET", "/user", access_token).json()
        email = profile.get("email")
        if not email and "user:email" in scopes:
            try:
                emails = github.request("GET", "/user/emails", access_token).json()
                primary = [e for e in emails if e.get("primary") and e.get("verified")]
                email = (primary or emails or [{}])[0].get("email")
            except github.GitHubError:
                email = None

        user_id = upsert_user(str(profile["id"]), profile["login"], email, profile.get("avatar_url"),
                              access_token, scopes)
        session = security.create_session(user_id, request.headers.get("user-agent", ""))
        db.log_activity(user_id, "login", {})
    except (requests.RequestException, github.GitHubError, KeyError, ValueError):
        log.exception("OAuth callback failed")
        return _login_error("Something went wrong while signing you in. Please try again.")

    # Token goes in the URL *fragment*: never sent to a server, never logged, never in a Referer header.
    resp = RedirectResponse(_frontend(f"/callback#token={session}"), status_code=302)
    resp.delete_cookie(STATE_COOKIE, path="/")
    return resp


@router.get("/me")
def me(user: dict = Depends(security.current_user)):
    return {"id": user["id"], "username": user["username"], "email": user["email"],
            "avatar_url": user["avatar_url"], "scopes": user["scopes"],
            "can_delete_repos": "delete_repo" in user["scopes"]}


@router.post("/logout")
def logout(user: dict = Depends(security.current_user)):
    security.revoke_session(user["session_id"])
    return {"ok": True}


@router.post("/logout-all")
def logout_all(user: dict = Depends(security.current_user)):
    return {"ok": True, "revoked": security.revoke_all_sessions(user["id"])}

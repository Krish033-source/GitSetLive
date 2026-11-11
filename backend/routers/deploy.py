"""Deployments: 'Our Servers' engine, deployment history, per-repo env vars, dashboard stats, activity."""

import json
import re
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

import db
import encryption
import github
import own_server
import security
from routers.common import clean_url, fail

router = APIRouter(tags=["deploy"])
STATUSES = ("deploying", "live", "failed", "stopped")
PROVIDERS = ("render", "vercel", "own", "other")


# ------------------------------------------------------------ status mirror
def on_own_status(pid: str, info: dict) -> None:
    status = {"building": "deploying", "running": "live", "failed": "failed"}.get(info.get("status"), "stopped")
    with db.db() as conn:
        conn.execute("UPDATE deployments SET status=?, live_url=?, updated_at=? WHERE project_id=?",
                     (status, info.get("tunnel_url"), db.now(), pid))


def register_hooks() -> None:
    own_server.set_status_hook(on_own_status)


# ------------------------------------------------------------ env variables
def load_env(user_id: str, repo_full: str) -> dict:
    with db.db() as conn:
        rows = conn.execute("SELECT key, value_enc FROM project_env WHERE user_id=? AND repo=?",
                            (user_id, repo_full.lower())).fetchall()
    out = {}
    for r in rows:
        v = encryption.decrypt(r["value_enc"])
        if v is not None:
            out[r["key"]] = v
    return out


@router.get("/env")
def get_env(owner: str, repo: str, user: dict = Depends(security.current_user)):
    github.check_repo(owner, repo)
    with db.db() as conn:
        rows = conn.execute("SELECT key, updated_at FROM project_env WHERE user_id=? AND repo=? ORDER BY key",
                            (user["id"], f"{owner}/{repo}".lower())).fetchall()
    return {"vars": [{"key": r["key"], "updated_at": r["updated_at"]} for r in rows]}


class EnvVar(BaseModel):
    key: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
    value: Optional[str] = Field(default=None, max_length=4000)  # null = keep the stored value


class EnvBody(BaseModel):
    owner: str
    repo: str
    vars: List[EnvVar] = Field(max_length=50)


@router.put("/env")
def put_env(body: EnvBody, user: dict = Depends(security.current_user)):
    github.check_repo(body.owner, body.repo)
    repo = f"{body.owner}/{body.repo}".lower()
    keys = [v.key for v in body.vars]
    if len(set(keys)) != len(keys):
        fail(400, "Duplicate variable names.", "duplicate")
    with db.db() as conn:
        existing = {r["key"] for r in conn.execute(
            "SELECT key FROM project_env WHERE user_id=? AND repo=?", (user["id"], repo))}
        for v in body.vars:
            if v.value is None:
                if v.key not in existing:
                    fail(400, f"{v.key} needs a value.", "missing_value")
                continue
            conn.execute(
                "INSERT INTO project_env (id, user_id, repo, key, value_enc, updated_at) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(user_id, repo, key) DO UPDATE SET value_enc=excluded.value_enc, updated_at=excluded.updated_at",
                (db.new_id("env"), user["id"], repo, v.key, encryption.encrypt(v.value), db.now()))
        for gone in existing - set(keys):
            conn.execute("DELETE FROM project_env WHERE user_id=? AND repo=? AND key=?", (user["id"], repo, gone))
    return {"ok": True, "count": len(keys)}


# ------------------------------------------------------------ Our Servers
class OwnDeploy(BaseModel):
    owner: str
    repo: str
    root: str = Field(default="", max_length=200)


@router.post("/deploy/own")
def deploy_own(body: OwnDeploy, user: dict = Depends(security.current_user),
               _rl=Depends(security.rate_limit("deploy", 5, 600))):
    if not own_server.is_enabled():
        fail(403, "“Our Servers” is turned off on this server. Use Render or Vercel instead.", "disabled")
    info = github.get_repo(user["github_token"], body.owner, body.repo)
    perms = info.get("permissions") or {}
    mine = (info.get("owner") or {}).get("login", "").lower() == user["username"].lower()
    if not (mine or perms.get("push") or perms.get("admin")):
        fail(403, "You can only deploy repositories you own or can push to.", "forbidden")

    try:
        pid = own_server.start_deploy(user["github_token"], body.owner, body.repo, user["id"], body.root,
                                      load_env(user["id"], f"{body.owner}/{body.repo}"))
    except PermissionError as e:
        fail(403, str(e), "disabled")
    except ValueError as e:
        fail(400, str(e), "invalid")
    except RuntimeError as e:
        fail(409, str(e), "limit")

    with db.db() as conn:
        conn.execute(
            "INSERT INTO deployments (id, user_id, repo_name, repo_url, status, created_at, updated_at, provider, project_id) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (db.new_id("dep"), user["id"], body.repo, f"https://github.com/{body.owner}/{body.repo}", "deploying",
             db.now(), db.now(), "own", pid))
    db.log_activity(user["id"], "own_server_deploy", {"repo": body.repo, "project_id": pid})
    return own_server.get_project(pid, user["id"])


def _guard(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except KeyError:
        fail(404, "No such deployment.", "not_found")
    except PermissionError:
        fail(403, "You don't own this deployment.", "forbidden")


@router.get("/deploy/own")
def own_list(user: dict = Depends(security.current_user)):
    return {"enabled": own_server.is_enabled(), "projects": own_server.list_projects(user["id"])}


@router.get("/deploy/own/{pid}")
def own_get(pid: str, user: dict = Depends(security.current_user)):
    return _guard(own_server.get_project, pid, user["id"])


@router.get("/deploy/own/{pid}/logs")
def own_logs(pid: str, tail: int = 300, user: dict = Depends(security.current_user)):
    return {"log": _guard(own_server.read_log, pid, user["id"], max(10, min(tail, 1000)))}


@router.post("/deploy/own/{pid}/stop")
def own_stop(pid: str, remove: bool = False, user: dict = Depends(security.current_user)):
    _guard(own_server.stop_project, pid, user["id"], remove)
    return {"ok": True}


# ----------------------------------------------------- deployment history
def _member(conn, workspace_id: str, user_id: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM workspace_members WHERE workspace_id=? AND user_id=?",
                             (workspace_id, user_id)).fetchone())


@router.get("/deployments")
def list_deployments(workspace_id: Optional[str] = None, user: dict = Depends(security.current_user)):
    with db.db() as conn:
        if workspace_id:
            if not _member(conn, workspace_id, user["id"]):
                fail(403, "You're not a member of this workspace.", "forbidden")
            rows = conn.execute("SELECT * FROM deployments WHERE workspace_id=? ORDER BY created_at DESC LIMIT 50",
                                (workspace_id,)).fetchall()
        else:
            rows = conn.execute("SELECT * FROM deployments WHERE user_id=? ORDER BY created_at DESC LIMIT 50",
                                (user["id"],)).fetchall()
    keys = ("id", "repo_name", "repo_url", "status", "live_url", "provider", "project_id", "workspace_id", "created_at", "updated_at")
    return {"deployments": [{k: r[k] for k in keys} for r in rows]}


class DeploymentIn(BaseModel):
    repo_name: str = Field(min_length=1, max_length=100)
    provider: str = Field(pattern="^(render|vercel|own|other)$")
    live_url: Optional[str] = None
    status: str = Field(default="live", pattern="^(deploying|live|failed|stopped)$")
    workspace_id: Optional[str] = None


@router.post("/deployments")
def record_deployment(body: DeploymentIn, user: dict = Depends(security.current_user)):
    """Record a deployment made on Render/Vercel so it shows up in history and stats."""
    url = clean_url(body.live_url)
    with db.db() as conn:
        if body.workspace_id and not _member(conn, body.workspace_id, user["id"]):
            fail(403, "You're not a member of this workspace.", "forbidden")
        dep_id = db.new_id("dep")
        conn.execute(
            "INSERT INTO deployments (id, user_id, workspace_id, repo_name, status, live_url, provider, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (dep_id, user["id"], body.workspace_id, body.repo_name, body.status, url, body.provider, db.now(), db.now()))
    db.log_activity(user["id"], "deployment_recorded", {"repo": body.repo_name, "provider": body.provider}, body.workspace_id)
    return {"id": dep_id}


class DeploymentPatch(BaseModel):
    status: Optional[str] = Field(default=None, pattern="^(deploying|live|failed|stopped)$")
    live_url: Optional[str] = None


@router.patch("/deployments/{dep_id}")
def patch_deployment(dep_id: str, body: DeploymentPatch, user: dict = Depends(security.current_user)):
    url = clean_url(body.live_url) if body.live_url else None
    with db.db() as conn:
        n = conn.execute(
            "UPDATE deployments SET status=COALESCE(?, status), live_url=COALESCE(?, live_url), updated_at=? "
            "WHERE id=? AND user_id=?", (body.status, url, db.now(), dep_id, user["id"])).rowcount
    if not n:
        fail(404, "Deployment not found.", "not_found")
    return {"ok": True}


@router.delete("/deployments/{dep_id}")
def delete_deployment(dep_id: str, user: dict = Depends(security.current_user)):
    with db.db() as conn:
        n = conn.execute("DELETE FROM deployments WHERE id=? AND user_id=?", (dep_id, user["id"])).rowcount
    if not n:
        fail(404, "Deployment not found.", "not_found")
    return {"ok": True}


# ------------------------------------------------------------ stats / feed
@router.get("/stats")
def stats(user: dict = Depends(security.current_user)):
    with db.db() as conn:
        dep = conn.execute("SELECT status, COUNT(*) n FROM deployments WHERE user_id=? GROUP BY status", (user["id"],)).fetchall()
        scans = conn.execute(
            "SELECT repo_full_name, score, created_at FROM scan_results WHERE user_id=? AND repo_full_name IS NOT NULL "
            "ORDER BY created_at DESC", (user["id"],)).fetchall()
    by = {r["status"]: r["n"] for r in dep}
    total = sum(by.values())
    finished = by.get("live", 0) + by.get("failed", 0)
    latest = {}
    for r in scans:
        latest.setdefault(r["repo_full_name"], {"score": r["score"], "created_at": r["created_at"]})
    return {"deployments": {"total": total, "live": by.get("live", 0), "failed": by.get("failed", 0)},
            "success_rate": round(100 * by.get("live", 0) / finished) if finished else None,
            "scan_count": len(scans), "latest_scores": latest}


@router.get("/activity")
def activity(limit: int = 30, user: dict = Depends(security.current_user)):
    with db.db() as conn:
        rows = conn.execute("SELECT action, details, created_at FROM activity_logs WHERE user_id=? "
                            "ORDER BY created_at DESC LIMIT ?", (user["id"], max(1, min(limit, 100)))).fetchall()
    out = []
    for r in rows:
        try:
            details = json.loads(r["details"] or "{}")
        except ValueError:
            details = {}
        out.append({"action": r["action"], "details": details, "created_at": r["created_at"]})
    return {"activities": out}

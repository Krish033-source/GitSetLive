"""Team workspaces with enforced roles (admin / developer / viewer)."""

from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel, Field

import config
import db
import mailer
import security
from routers.common import fail

router = APIRouter(tags=["workspaces"])
ROLES = ("admin", "developer", "viewer")


def _role(conn, ws_id: str, user_id: str):
    r = conn.execute("SELECT role FROM workspace_members WHERE workspace_id=? AND user_id=?", (ws_id, user_id)).fetchone()
    return r["role"] if r else None


def _admin_count(conn, ws_id: str) -> int:
    return conn.execute("SELECT COUNT(*) n FROM workspace_members WHERE workspace_id=? AND role='admin'", (ws_id,)).fetchone()["n"]


@router.get("/workspaces")
def list_workspaces(user: dict = Depends(security.current_user)):
    with db.db() as conn:
        rows = conn.execute(
            """SELECT w.id, w.name, w.owner_id, wm.role,
                      (SELECT COUNT(*) FROM workspace_members x WHERE x.workspace_id = w.id) AS member_count
               FROM workspaces w JOIN workspace_members wm ON wm.workspace_id = w.id
               WHERE wm.user_id=? ORDER BY w.created_at""", (user["id"],)).fetchall()
    return {"workspaces": [dict(r) for r in rows]}


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=60)


@router.post("/workspaces")
def create_workspace(body: WorkspaceCreate, user: dict = Depends(security.current_user)):
    ws_id = db.new_id("ws")
    with db.db() as conn:
        conn.execute("INSERT INTO workspaces (id, name, owner_id, created_at) VALUES (?,?,?,?)",
                     (ws_id, body.name.strip(), user["id"], db.now()))
        conn.execute("INSERT INTO workspace_members (id, workspace_id, user_id, role) VALUES (?,?,?,?)",
                     (db.new_id("wm"), ws_id, user["id"], "admin"))
    db.log_activity(user["id"], "workspace_created", {"workspace_id": ws_id}, ws_id)
    return {"id": ws_id}


@router.get("/workspaces/{ws_id}/members")
def members(ws_id: str, user: dict = Depends(security.current_user)):
    with db.db() as conn:
        if not _role(conn, ws_id, user["id"]):
            fail(403, "You're not a member of this workspace.", "forbidden")
        rows = conn.execute(
            "SELECT u.id AS user_id, u.username, u.email, u.avatar_url, wm.role FROM workspace_members wm "
            "JOIN users u ON u.id = wm.user_id WHERE wm.workspace_id=? ORDER BY wm.role, u.username", (ws_id,)).fetchall()
    return {"members": [dict(r) for r in rows]}


class InviteBody(BaseModel):
    identifier: str = Field(min_length=2, max_length=120, description="email or GitHub username")
    role: str = Field(default="developer", pattern="^(admin|developer|viewer)$")


@router.post("/workspaces/{ws_id}/invite")
def invite(ws_id: str, body: InviteBody, bg: BackgroundTasks, user: dict = Depends(security.current_user)):
    ident = body.identifier.strip().lstrip("@").lower()
    with db.db() as conn:
        if _role(conn, ws_id, user["id"]) != "admin":
            fail(403, "Only workspace admins can invite people.", "forbidden")
        target = conn.execute("SELECT id, username, email FROM users WHERE lower(email)=? OR lower(username)=?",
                              (ident, ident)).fetchone()
        if not target:
            fail(404, "No GitSetLive account matches that. Ask them to sign in with GitHub once, then invite them again.", "not_found")
        if _role(conn, ws_id, target["id"]):
            fail(409, "They're already in this workspace.", "exists")
        conn.execute("INSERT INTO workspace_members (id, workspace_id, user_id, role) VALUES (?,?,?,?)",
                     (db.new_id("wm"), ws_id, target["id"], body.role))
        ws = conn.execute("SELECT name FROM workspaces WHERE id=?", (ws_id,)).fetchone()
    db.log_activity(user["id"], "workspace_invite", {"workspace_id": ws_id, "invitee": target["username"]}, ws_id)

    if target["email"] and mailer.enabled():
        name = ws["name"] if ws else "a workspace"
        bg.add_task(mailer.send_email, target["email"], f"You've been added to {name} on GitSetLive",
                    f"Hi {target['username']},\n\n{user['username']} added you to “{name}” as {body.role}.\n\nOpen GitSetLive: {config.FRONTEND_URL}\n")
    return {"ok": True, "username": target["username"]}


class RolePatch(BaseModel):
    role: str = Field(pattern="^(admin|developer|viewer)$")


@router.patch("/workspaces/{ws_id}/members/{member_id}")
def change_role(ws_id: str, member_id: str, body: RolePatch, user: dict = Depends(security.current_user)):
    with db.db() as conn:
        if _role(conn, ws_id, user["id"]) != "admin":
            fail(403, "Only workspace admins can change roles.", "forbidden")
        current = _role(conn, ws_id, member_id)
        if not current:
            fail(404, "That person isn't in this workspace.", "not_found")
        if current == "admin" and body.role != "admin" and _admin_count(conn, ws_id) <= 1:
            fail(409, "A workspace needs at least one admin.", "last_admin")
        conn.execute("UPDATE workspace_members SET role=? WHERE workspace_id=? AND user_id=?", (body.role, ws_id, member_id))
    return {"ok": True}


@router.delete("/workspaces/{ws_id}/members/{member_id}")
def remove_member(ws_id: str, member_id: str, user: dict = Depends(security.current_user)):
    with db.db() as conn:
        my_role = _role(conn, ws_id, user["id"])
        if member_id != user["id"] and my_role != "admin":
            fail(403, "Only workspace admins can remove other people.", "forbidden")
        target = _role(conn, ws_id, member_id)
        if not target:
            fail(404, "That person isn't in this workspace.", "not_found")
        if target == "admin" and _admin_count(conn, ws_id) <= 1:
            fail(409, "A workspace needs at least one admin. Make someone else admin first.", "last_admin")
        conn.execute("DELETE FROM workspace_members WHERE workspace_id=? AND user_id=?", (ws_id, member_id))
    return {"ok": True}


@router.delete("/workspaces/{ws_id}")
def delete_workspace(ws_id: str, user: dict = Depends(security.current_user)):
    with db.db() as conn:
        ws = conn.execute("SELECT owner_id FROM workspaces WHERE id=?", (ws_id,)).fetchone()
        if not ws:
            fail(404, "Workspace not found.", "not_found")
        if ws["owner_id"] != user["id"]:
            fail(403, "Only the workspace owner can delete it.", "forbidden")
        conn.execute("DELETE FROM workspace_members WHERE workspace_id=?", (ws_id,))
        conn.execute("UPDATE deployments SET workspace_id=NULL WHERE workspace_id=?", (ws_id,))
        conn.execute("DELETE FROM workspaces WHERE id=?", (ws_id,))
    return {"ok": True}

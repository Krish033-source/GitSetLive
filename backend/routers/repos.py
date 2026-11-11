"""Repository listing, creation and deletion."""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

import db
import github
import security
from routers.common import REPO_NAME, cached_repos, clear_repo_cache, fail

router = APIRouter(tags=["repos"])


@router.get("/repos")
def list_repos(refresh: bool = False, user: dict = Depends(security.current_user)):
    return cached_repos(user, refresh)


class RepoCreate(BaseModel):
    name: str = Field(pattern=REPO_NAME)
    description: Optional[str] = Field(default=None, max_length=350)
    private: bool = True


@router.post("/repos")
def create_repo(body: RepoCreate, user: dict = Depends(security.current_user)):
    r = github.request("POST", "/user/repos", user["github_token"], expected=(201,), json={
        "name": body.name, "description": body.description or "", "private": body.private,
        "auto_init": True,  # a README commit, so scan / AI Builder / deploy work immediately
    })
    clear_repo_cache(user["id"])
    db.log_activity(user["id"], "repo_created", {"repo": body.name})
    return github.slim_repo(r.json())


class RepoDelete(BaseModel):
    confirm: str


@router.post("/repos/{owner}/{name}/delete")
def delete_repo(owner: str, name: str, body: RepoDelete, user: dict = Depends(security.current_user)):
    github.check_repo(owner, name)
    if body.confirm != name:
        fail(400, "Type the exact repository name to confirm deletion.", "confirm_mismatch")
    if "delete_repo" not in user["scopes"]:
        fail(403, "Deleting repositories needs an extra GitHub permission that you haven't granted yet.",
             "needs_scope", scope="delete_repo")
    github.request("DELETE", f"/repos/{owner}/{name}", user["github_token"], expected=(204,))
    clear_repo_cache(user["id"])
    github.invalidate_snapshots(owner, name)
    db.log_activity(user["id"], "repo_deleted", {"repo": name})
    return {"ok": True}

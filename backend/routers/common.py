"""Helpers shared by all routers."""

import re
import threading
import time
from typing import Optional

from fastapi import HTTPException

import github

REPO_NAME = r"^[A-Za-z0-9_.-]{1,100}$"


def fail(status: int, message: str, code: str = "error", **extra) -> None:
    """Raise an HTTP error in the one shape the frontend understands."""
    raise HTTPException(status_code=status, detail={"message": message, "code": code, **extra})


def require_push(token: str, owner: str, repo: str) -> dict:
    """Return the repo (from GitHub) after checking the user may write to it."""
    info = github.get_repo(token, owner, repo)
    perms = info.get("permissions") or {}
    if not (perms.get("push") or perms.get("admin") or perms.get("maintain")):
        fail(403, "You don't have write access to this repository.", "forbidden")
    return info


_lock = threading.Lock()
_cache: dict = {}
REPO_TTL = 60


def cached_repos(user: dict, refresh: bool = False) -> list:
    with _lock:
        hit = _cache.get(user["id"])
        if hit and not refresh and time.time() - hit[0] < REPO_TTL:
            return hit[1]
    repos = github.list_repos(user["github_token"])
    with _lock:
        _cache[user["id"]] = (time.time(), repos)
    return repos


def clear_repo_cache(user_id: str) -> None:
    with _lock:
        _cache.pop(user_id, None)


def clean_url(url: Optional[str]) -> Optional[str]:
    """Only http(s) links — blocks javascript:/data: URLs from ever being rendered as hrefs."""
    if not url:
        return None
    url = url.strip()
    if not re.match(r"^https?://[^\s<>\"']+$", url, re.I) or len(url) > 500:
        fail(400, "Enter a valid http(s) URL.", "invalid_url")
    return url

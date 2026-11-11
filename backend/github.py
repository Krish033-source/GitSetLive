"""Thin, defensive GitHub client.

Key differences from the old per-file approach:
* repo contents are fetched as ONE tarball (not one API call per file), so scans
  are fast, binary files are handled and the rate limit isn't burned;
* multi-file changes are committed through the Git Data API as a SINGLE atomic
  commit (optionally on a new branch + pull request);
* every path/name coming from a client is validated before it reaches a URL.
"""

import base64
import hashlib
import io
import re
import tarfile
import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import quote

import requests

API = "https://api.github.com"
NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


class GitHubError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class GitHubAuthError(GitHubError):
    pass


# --------------------------------------------------------------- validation
def check_repo(owner: str, repo: Optional[str] = None) -> None:
    if not NAME_RE.match(owner or "") or (repo is not None and not NAME_RE.match(repo or "")):
        raise GitHubError(400, "Invalid owner or repository name.")


def safe_path(path: str) -> str:
    """Reject anything that could escape the repo root or touch git internals."""
    if not path or len(path) > 255 or "\x00" in path or "\\" in path:
        raise GitHubError(400, f"Invalid file path: {path!r}")
    if path.startswith("/") or path.endswith("/"):
        raise GitHubError(400, f"Invalid file path: {path!r}")
    parts = path.split("/")
    if any(p in ("", ".", "..") for p in parts) or parts[0].lower() == ".git":
        raise GitHubError(400, f"Invalid file path: {path!r}")
    return path


# -------------------------------------------------------------------- HTTP
def _headers(token: str, accept: str = "application/vnd.github+json") -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "GitSetLive",
    }


def _message(r: requests.Response) -> str:
    try:
        data = r.json()
        msg = data.get("message") or r.text[:200]
        errs = data.get("errors")
        if errs and isinstance(errs, list):
            msg += " — " + "; ".join(str(e.get("message", e)) if isinstance(e, dict) else str(e) for e in errs[:2])
        return msg
    except ValueError:
        return r.text[:200] or f"GitHub returned HTTP {r.status_code}"


def request(method: str, path: str, token: str, *, expected=(200,), accept: Optional[str] = None,
            timeout: int = 25, **kwargs) -> requests.Response:
    url = path if path.startswith("http") else API + path
    try:
        r = requests.request(method, url, headers=_headers(token, accept or "application/vnd.github+json"),
                             timeout=timeout, **kwargs)
    except requests.RequestException:
        raise GitHubError(502, "Could not reach GitHub. Check your connection and try again.")

    if r.status_code == 401:
        raise GitHubAuthError(401, "GitHub rejected your login (token revoked or expired). Please log in again.")
    if r.status_code in (403, 429) and r.headers.get("x-ratelimit-remaining") == "0":
        raise GitHubError(429, "GitHub API rate limit reached. Please wait a bit and try again.")
    if r.status_code not in expected:
        raise GitHubError(r.status_code, _message(r))
    return r


# ----------------------------------------------------------------- repos
def slim_repo(r: dict) -> dict:
    return {
        "id": r.get("id"),
        "name": r.get("name"),
        "full_name": r.get("full_name"),
        "owner": {"login": (r.get("owner") or {}).get("login")},
        "private": bool(r.get("private")),
        "fork": bool(r.get("fork")),
        "archived": bool(r.get("archived")),
        "description": r.get("description"),
        "language": r.get("language"),
        "stargazers_count": r.get("stargazers_count", 0),
        "updated_at": r.get("pushed_at") or r.get("updated_at"),
        "default_branch": r.get("default_branch"),
        "html_url": r.get("html_url"),
        "permissions": r.get("permissions") or {},
    }


def list_repos(token: str, limit: int = 300) -> List[dict]:
    out: List[dict] = []
    page = 1
    while len(out) < limit:
        r = request("GET", "/user/repos", token, params={
            "per_page": 100, "page": page, "sort": "pushed",
            "affiliation": "owner,collaborator,organization_member",
        })
        items = r.json()
        if not isinstance(items, list) or not items:
            break
        out.extend(slim_repo(i) for i in items)
        if len(items) < 100:
            break
        page += 1
    return out[:limit]


def get_repo(token: str, owner: str, repo: str) -> dict:
    check_repo(owner, repo)
    return request("GET", f"/repos/{owner}/{repo}", token).json()


def get_file(token: str, owner: str, repo: str, path: str, ref: Optional[str] = None) -> Optional[dict]:
    """Returns {"text": str, "sha": str} or None when the file doesn't exist."""
    check_repo(owner, repo)
    safe_path(path)
    r = request("GET", f"/repos/{owner}/{repo}/contents/{quote(path)}", token,
                params={"ref": ref} if ref else None, expected=(200, 404))
    if r.status_code == 404:
        return None
    data = r.json()
    if not isinstance(data, dict) or data.get("type") != "file":
        return None
    sha = data["sha"]
    if data.get("encoding") == "base64" and data.get("content"):
        raw = base64.b64decode(data["content"])
    else:  # files > 1 MB come back without inline content
        blob = request("GET", f"/repos/{owner}/{repo}/git/blobs/{sha}", token).json()
        raw = base64.b64decode(blob.get("content", "")) if blob.get("encoding") == "base64" else b""
    return {"text": raw.decode("utf-8", errors="replace"), "sha": sha}


# ---------------------------------------------------------------- snapshot
SKIP_DIRS = {".git", "node_modules", ".next", "__pycache__", "venv", ".venv", "env",
             "dist", "build", "vendor", ".idea", ".vscode", "coverage", ".cache", "target"}
BINARY_EXT = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".bmp", ".svgz", ".pdf", ".zip",
              ".gz", ".tar", ".tgz", ".7z", ".rar", ".woff", ".woff2", ".ttf", ".otf", ".eot",
              ".mp4", ".mp3", ".wav", ".mov", ".avi", ".bin", ".exe", ".dll", ".so", ".dylib",
              ".pyc", ".class", ".jar", ".db", ".sqlite", ".sqlite3", ".lock", ".map"}
SKIP_FILES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock"}


@dataclass
class Snapshot:
    ref: str
    files: Dict[str, str] = field(default_factory=dict)   # path -> text (text files only)
    paths: List[str] = field(default_factory=list)        # every path in the repo
    truncated: bool = False
    binary_count: int = 0


_snap_lock = threading.Lock()
_snap_cache: Dict[tuple, tuple] = {}
SNAP_TTL = 90


def invalidate_snapshots(owner: str, repo: str) -> None:
    with _snap_lock:
        for k in [k for k in _snap_cache if k[0] == owner.lower() and k[1] == repo.lower()]:
            _snap_cache.pop(k, None)


def fetch_snapshot(token: str, owner: str, repo: str, ref: Optional[str] = None, *,
                   use_cache: bool = True, max_files: int = 600, max_file_bytes: int = 200_000,
                   max_total_bytes: int = 8_000_000, max_tar_bytes: int = 60_000_000) -> Snapshot:
    check_repo(owner, repo)
    key = (owner.lower(), repo.lower(), ref or "", hashlib.sha256(token.encode()).hexdigest()[:8])
    if use_cache:
        with _snap_lock:
            hit = _snap_cache.get(key)
            if hit and time.time() - hit[0] < SNAP_TTL:
                return hit[1]

    url = f"{API}/repos/{owner}/{repo}/tarball" + (f"/{quote(ref, safe='')}" if ref else "")
    try:
        resp = requests.get(url, headers=_headers(token), stream=True, timeout=(10, 60), allow_redirects=True)
    except requests.RequestException:
        raise GitHubError(502, "Could not reach GitHub to download the repository.")

    if resp.status_code == 401:
        raise GitHubAuthError(401, "GitHub rejected your login. Please log in again.")
    if resp.status_code in (404, 409):
        raise GitHubError(404, "Repository not found, empty, or you don't have access to it.")
    if resp.status_code != 200:
        raise GitHubError(resp.status_code, f"GitHub returned HTTP {resp.status_code} while downloading the repo.")

    snap = Snapshot(ref=ref or "default")
    total = 0
    with tempfile.SpooledTemporaryFile(max_size=20_000_000) as tmp:
        size = 0
        for chunk in resp.iter_content(chunk_size=1 << 16):
            size += len(chunk)
            if size > max_tar_bytes:
                raise GitHubError(413, "Repository is too large to analyse (over 60 MB).")
            tmp.write(chunk)
        tmp.seek(0)

        with tarfile.open(fileobj=tmp, mode="r:gz") as tar:
            for m in tar:
                if not m.isfile():
                    continue
                parts = m.name.split("/", 1)
                if len(parts) < 2 or not parts[1]:
                    continue
                path = parts[1]
                segs = path.split("/")
                if len(snap.paths) < 5000:
                    snap.paths.append(path)
                if any(s in SKIP_DIRS for s in segs[:-1]) or segs[-1] in SKIP_FILES:
                    continue
                dot = segs[-1].rfind(".")
                if dot > 0 and segs[-1][dot:].lower() in BINARY_EXT:
                    snap.binary_count += 1
                    continue
                if m.size > max_file_bytes:
                    snap.truncated = True
                    continue
                if len(snap.files) >= max_files or total + m.size > max_total_bytes:
                    snap.truncated = True
                    continue
                f = tar.extractfile(m)
                if not f:
                    continue
                raw = f.read()
                if b"\x00" in raw[:4096]:
                    snap.binary_count += 1
                    continue
                snap.files[path] = raw.decode("utf-8", errors="replace")
                total += m.size

    snap.paths.sort()
    if use_cache:
        with _snap_lock:
            if len(_snap_cache) >= 6:
                oldest = min(_snap_cache, key=lambda k: _snap_cache[k][0])
                _snap_cache.pop(oldest, None)
            _snap_cache[key] = (time.time(), snap)
    return snap


# ------------------------------------------------------------------ commits
def commit_files(token: str, owner: str, repo: str, changes: List[dict], message: str, *,
                 base_branch: str, new_branch: Optional[str] = None, pr_title: Optional[str] = None,
                 pr_body: str = "") -> dict:
    """Commit many files in ONE commit.

    changes: [{"path": str, "content": str | None}]  (content=None deletes the file)
    If new_branch is given the commit goes there (and a PR is opened when pr_title is set);
    otherwise it is committed straight onto base_branch.
    """
    check_repo(owner, repo)
    if not changes:
        raise GitHubError(400, "Nothing to commit.")
    for c in changes:
        safe_path(c["path"])

    base = f"/repos/{owner}/{repo}"
    ref = request("GET", f"{base}/git/ref/heads/{quote(base_branch, safe='/')}", token, expected=(200, 404, 409))
    if ref.status_code != 200:
        return _commit_to_empty_repo(token, owner, repo, changes, message, base_branch)

    base_sha = ref.json()["object"]["sha"]
    base_commit = request("GET", f"{base}/git/commits/{base_sha}", token).json()

    tree_entries = []
    for c in changes:
        if c.get("content") is None:
            tree_entries.append({"path": c["path"], "mode": "100644", "type": "blob", "sha": None})
        else:
            blob = request("POST", f"{base}/git/blobs", token, expected=(201,),
                           json={"content": c["content"], "encoding": "utf-8"}).json()
            tree_entries.append({"path": c["path"], "mode": "100644", "type": "blob", "sha": blob["sha"]})

    tree = request("POST", f"{base}/git/trees", token, expected=(201,),
                   json={"base_tree": base_commit["tree"]["sha"], "tree": tree_entries}).json()
    commit = request("POST", f"{base}/git/commits", token, expected=(201,),
                     json={"message": message, "tree": tree["sha"], "parents": [base_sha]}).json()

    branch = new_branch
    if new_branch:
        name = new_branch
        for attempt in range(4):
            r = request("POST", f"{base}/git/refs", token, expected=(201, 422),
                        json={"ref": f"refs/heads/{name}", "sha": commit["sha"]})
            if r.status_code == 201:
                branch = name
                break
            name = f"{new_branch}-{attempt + 2}"  # name already taken
        else:
            raise GitHubError(409, "Could not create a unique branch name. Try again.")
    else:
        request("PATCH", f"{base}/git/refs/heads/{quote(base_branch, safe='/')}", token,
                json={"sha": commit["sha"], "force": False})
        branch = base_branch

    result = {"branch": branch, "commit_sha": commit["sha"],
              "commit_url": f"https://github.com/{owner}/{repo}/commit/{commit['sha']}",
              "pr_url": None, "pr_number": None}

    if new_branch and pr_title:
        pr = request("POST", f"{base}/pulls", token, expected=(201,),
                     json={"title": pr_title, "head": branch, "base": base_branch, "body": pr_body}).json()
        result["pr_url"] = pr.get("html_url")
        result["pr_number"] = pr.get("number")

    invalidate_snapshots(owner, repo)
    return result


def _commit_to_empty_repo(token, owner, repo, changes, message, branch) -> dict:
    """A brand-new repo with no commits has no ref/tree yet; the Contents API can create the first commit."""
    last = None
    for c in changes:
        if c.get("content") is None:
            continue
        r = request("PUT", f"/repos/{owner}/{repo}/contents/{quote(c['path'])}", token, expected=(200, 201),
                    json={"message": message, "branch": branch,
                          "content": base64.b64encode(c["content"].encode()).decode()})
        last = r.json()
    if not last:
        raise GitHubError(400, "Nothing to commit.")
    sha = (last.get("commit") or {}).get("sha", "")
    invalidate_snapshots(owner, repo)
    return {"branch": branch, "commit_sha": sha, "commit_url": f"https://github.com/{owner}/{repo}/commit/{sha}",
            "pr_url": None, "pr_number": None, "note": "Repository was empty — committed directly."}

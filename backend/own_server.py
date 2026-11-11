"""own_server.py — GitSetLive's built-in deploy engine ("Deploy to Our Servers").

What changed from the prototype
-------------------------------
* ENV SCRUBBING: deployed apps used to inherit the server's whole environment
  (GROQ_API_KEY, GITHUB_CLIENT_SECRET, ENCRYPTION_KEY, SMTP_PASSWORD...). They now
  get a minimal clean environment plus only the variables the user configured.
* `npm install --ignore-scripts` (dependency lifecycle scripts no longer run with
  the server's privileges) and a per-project Python venv (no pip installs into
  the server's own site-packages).
* Deploys run in a background thread and are polled (no 2-minute blocked request).
* Repos are fetched as one tarball (binary files work) and extracted with
  path-traversal / symlink protection.
* Monorepo support (`root` folder), per-user and global limits, automatic expiry (TTL),
  log viewer, state kept in DATA_DIR with atomic writes.
* RLIMIT fixes: RLIMIT_AS breaks Node (V8 reserves a huge virtual range) and
  RLIMIT_NPROC is per-USER, not per process tree, so neither is applied to Node.

SECURITY - read this
--------------------
There is NO container/VM sandbox. Deployed code runs as the same OS user as this
server and can read files on this machine (including app.db). Therefore:
  - it is disabled by default in production (OWN_SERVER_ENABLED=false),
  - the API only lets users deploy repos they own / can push to,
  - run it only inside a throw-away container/VM that holds nothing you can't lose.
"""

import json
import logging
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

import requests

import analyzer
import config

log = logging.getLogger("gitsetlive.own_server")

PROJECTS_DIR = config.DATA_DIR / "own_server_projects"
LOG_DIR = config.DATA_DIR / "own_server_logs"
STATE_FILE = config.DATA_DIR / "own_server_state.json"
PORT_START, PORT_END = 4000, 4999
GITHUB_API = "https://api.github.com"
MAX_TAR_BYTES = 50 * 1024 * 1024
MAX_EXTRACT_BYTES = 250 * 1024 * 1024
MAX_FILES = 6000
ACTIVE = ("building", "running")

TUNNEL_URL_RE = re.compile(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com")
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
PROTECTED_ENV = {"PATH", "HOME", "PORT", "HOST", "LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONPATH", "PYTHONHOME",
                 "PYTHONSTARTUP", "NODE_OPTIONS", "NODE_PATH", "TMPDIR", "SHELL", "USER"}

_lock = threading.RLock()
_procs: Dict[int, subprocess.Popen] = {}
_hook: Optional[Callable[[str, dict], None]] = None
_reaper_started = False


def _find_cloudflared() -> Optional[str]:
    cand = config.CLOUDFLARED_PATH or shutil.which("cloudflared") or shutil.which("cloudflared.exe")
    return cand if cand and os.path.isfile(cand) else None


def is_enabled() -> bool:
    return config.OWN_SERVER_ENABLED


def set_status_hook(fn: Callable[[str, dict], None]) -> None:
    """main.py registers a function that mirrors status changes into the deployments table."""
    global _hook
    _hook = fn


# ------------------------------------------------------------------- state
def _load() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(state: dict) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def _update(project_id: str, **fields) -> Optional[dict]:
    """Patch one project's state. (`pid` in fields is the OS process id, hence `project_id` here.)"""
    with _lock:
        state = _load()
        if project_id not in state:
            return None
        state[project_id].update(fields)
        _save(state)
        info = dict(state[project_id])
    if _hook and ("status" in fields or "tunnel_url" in fields):
        try:
            _hook(project_id, info)
        except Exception:  # noqa: BLE001
            log.exception("status hook failed")
    return info


def _public(info: dict) -> dict:
    keys = ("id", "name", "owner", "repo", "root", "type", "framework", "status", "message", "error", "tunnel_url",
            "tunnel_note", "port", "created_at", "expires_at", "alive")
    out = {k: info.get(k) for k in keys}
    out["local_url"] = f"http://localhost:{info['port']}" if info.get("port") else None
    return out


# --------------------------------------------------------------- processes
def is_alive(pid: Optional[int]) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True, timeout=5)
            return str(pid) in out.stdout
        except Exception:  # noqa: BLE001
            return False
    try:  # our own child? reap zombies so they don't look alive
        done, _ = os.waitpid(pid, os.WNOHANG)
        if done == pid:
            _procs.pop(pid, None)
            return False
        return True
    except ChildProcessError:
        pass
    except OSError:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _kill(pid: Optional[int]) -> None:
    if not pid or not is_alive(pid):
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
        else:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
            for _ in range(15):
                if not is_alive(pid):
                    return
                time.sleep(0.2)
            os.killpg(os.getpgid(pid), signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
    is_alive(pid)  # reap


def _limits(is_python: bool):
    """preexec_fn for deployed processes (POSIX). Also starts a new session so the whole group can be killed."""
    def apply():
        os.setsid()
        try:
            import resource
            resource.setrlimit(resource.RLIMIT_CPU, (3600, 3600))
            resource.setrlimit(resource.RLIMIT_NOFILE, (512, 512))
            resource.setrlimit(resource.RLIMIT_FSIZE, (200 * 1024 * 1024,) * 2)
            if is_python:  # NOT for Node: V8 needs a huge virtual address range
                resource.setrlimit(resource.RLIMIT_AS, (1536 * 1024 * 1024,) * 2)
        except Exception:  # noqa: BLE001
            pass
    return apply


def _clean_env(port: int, home: Path, extra: Dict[str, str]) -> dict:
    home.mkdir(parents=True, exist_ok=True)
    (home / "tmp").mkdir(exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", ""), "HOME": str(home), "LANG": "C.UTF-8", "PORT": str(port),
        "HOST": "127.0.0.1", "NODE_ENV": "production", "PYTHONUNBUFFERED": "1", "PYTHONDONTWRITEBYTECODE": "1",
        "TMPDIR": str(home / "tmp"), "npm_config_cache": str(home / ".npm"), "PIP_CACHE_DIR": str(home / ".pip"),
        "NODE_OPTIONS": "--max-old-space-size=384",
    }
    if os.name == "nt":
        for k in ("SYSTEMROOT", "COMSPEC", "PATHEXT", "TEMP", "TMP"):
            if os.environ.get(k):
                env[k] = os.environ[k]
    for k, v in (extra or {}).items():
        if ENV_NAME_RE.match(k) and k not in PROTECTED_ENV and isinstance(v, str):
            env[k] = v
    return env


def _spawn(cmd, cwd, env, log_path: Path, is_python=False) -> subprocess.Popen:
    out = open(log_path, "ab")
    kw = dict(cwd=str(cwd), env=env, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kw["preexec_fn"] = _limits(is_python)
    proc = subprocess.Popen(cmd, **kw)
    _procs[proc.pid] = proc
    return proc


def _step(cmd, cwd, env, build_log: Path, timeout: int, label: str) -> None:
    with open(build_log, "ab") as f:
        f.write(f"\n$ {' '.join(map(str, cmd))}\n".encode())
        f.flush()
        try:
            r = subprocess.run(cmd, cwd=str(cwd), env=env, stdout=f, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"{label} took longer than {timeout}s and was stopped.")
        except FileNotFoundError:
            raise RuntimeError(f"'{cmd[0]}' isn't installed on this server ({label}).")
    if r.returncode != 0:
        raise RuntimeError(f"{label} failed (exit code {r.returncode}). See the build log.")


# ---------------------------------------------------------------- fetching
def _download(token: str, owner: str, repo: str, dest: Path) -> None:
    try:
        resp = requests.get(f"{GITHUB_API}/repos/{owner}/{repo}/tarball", stream=True, timeout=(10, 60),
                            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                                     "User-Agent": "GitSetLive"})
    except requests.RequestException:
        raise RuntimeError("Couldn't reach GitHub to download the repository.")
    if resp.status_code != 200:
        raise RuntimeError("Couldn't download the repository (not found, empty, or no access).")

    dest = dest.resolve()
    with tempfile.TemporaryFile() as tmp:
        size = 0
        for chunk in resp.iter_content(1 << 16):
            size += len(chunk)
            if size > MAX_TAR_BYTES:
                raise RuntimeError("Repository is larger than 50 MB - too big for this server.")
            tmp.write(chunk)
        tmp.seek(0)
        total = n = 0
        with tarfile.open(fileobj=tmp, mode="r:gz") as tar:
            for m in tar:
                parts = m.name.split("/", 1)
                if len(parts) < 2 or not parts[1] or not (m.isfile() or m.isdir()):
                    continue  # skips symlinks, hardlinks, devices
                target = (dest / parts[1]).resolve()
                if dest not in target.parents and target != dest:
                    continue  # path traversal attempt
                if m.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                n += 1
                total += m.size
                if n > MAX_FILES or total > MAX_EXTRACT_BYTES:
                    raise RuntimeError("Repository has too many / too large files to run here.")
                target.parent.mkdir(parents=True, exist_ok=True)
                with tar.extractfile(m) as src, open(target, "wb") as out:
                    shutil.copyfileobj(src, out)


def _tree(root: Path) -> Tuple[list, Callable[[str], Optional[str]]]:
    paths = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", ".venv", ".home")]
        for f in files:
            paths.append(Path(dirpath, f).relative_to(root).as_posix())

    def read(p: str) -> Optional[str]:
        try:
            return (root / p).read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
    return paths, read


# ---------------------------------------------------------------- pipeline
def _free_port() -> int:
    used = {p.get("port") for p in _load().values()}
    for port in range(PORT_START, PORT_END):
        if port in used:
            continue
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free port is available on this server right now.")


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _venv_python(app_dir: Path) -> str:
    return str(app_dir / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))


def _build_and_run(pid: str, token: str, owner: str, repo: str, root: str, user_env: dict) -> None:
    proj = PROJECTS_DIR / pid
    build_log, run_log = LOG_DIR / f"{pid}.build.log", LOG_DIR / f"{pid}.run.log"
    try:
        _update(pid, message="Downloading repository…")
        proj.mkdir(parents=True, exist_ok=True)
        _download(token, owner, repo, proj)

        paths, read = _tree(proj)
        apps = analyzer.detect_apps(paths, read)
        if root:
            app = next((a for a in apps if a["root"] == root), None)
            if not app:
                raise RuntimeError(f"No deployable app found in folder “{root}”.")
        elif len(apps) == 1:
            app = apps[0]
        elif not apps:
            raise RuntimeError("Nothing to deploy: no package.json, requirements.txt or index.html found.")
        else:
            names = ", ".join(a["root"] or "(root)" for a in apps)
            raise RuntimeError(f"This repo contains several apps ({names}). Pick one folder to deploy.")

        app_dir = proj / app["root"] if app["root"] else proj
        port = _free_port()
        env = _clean_env(port, proj / ".home", user_env)
        _update(pid, type=app["type"], framework=app["framework"], root=app["root"], port=port,
                message=f"Installing dependencies ({app['framework']})…")

        t = app["type"]
        is_py = False
        if t == "python":
            if app["framework"] == "django":
                raise RuntimeError("Django isn't supported on 'Our Servers' yet. Use Render.")
            _step([sys.executable, "-m", "venv", ".venv"], app_dir, env, build_log, 120, "Creating virtualenv")
            py = _venv_python(app_dir)
            if (app_dir / "requirements.txt").exists():
                _step([py, "-m", "pip", "install", "--no-input", "-r", "requirements.txt"], app_dir, env, build_log,
                      400, "pip install")
            if app["framework"] == "fastapi":
                _step([py, "-m", "pip", "install", "--no-input", "uvicorn"], app_dir, env, build_log, 200, "pip install uvicorn")
            m = re.search(r"(\w+):(\w+)", app.get("start_command") or "")
            if app["framework"] == "fastapi" and m:
                cmd = [py, "-m", "uvicorn", f"{m.group(1)}:{m.group(2)}", "--host", "127.0.0.1", "--port", str(port)]
            elif app["framework"] == "flask" and m:
                cmd = [py, "-m", "flask", "--app", f"{m.group(1)}:{m.group(2)}", "run", "--host", "127.0.0.1", "--port", str(port)]
            elif app.get("entry"):
                cmd = [py, app["entry"]]
            else:
                raise RuntimeError("Couldn't find an entry file (main.py / app.py).")
            is_py = True
        elif t == "node":
            npm = shutil.which("npm")
            if not npm:
                raise RuntimeError("Node.js/npm isn't installed on this server.")
            if (app_dir / "package.json").exists():
                _step([npm, "install", "--ignore-scripts", "--no-audit", "--no-fund"], app_dir, env, build_log, 400, "npm install")
            fw = app["framework"]
            if app.get("build_command") and fw in ("next", "vite", "create-react-app", "nuxt", "nestjs"):
                _update(pid, message="Building…")
                _step([npm, "run", "build"], app_dir, env, build_log, 400, "npm run build")
            sc = app.get("start_command") or ""
            if app["kind"] == "web-static":
                out_dir = app_dir / (app["output_dir"] or "dist")
                cmd = [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(out_dir)]
            elif fw == "next":
                cmd = [npm, "exec", "--", "next", "start", "-p", str(port), "-H", "127.0.0.1"]
            elif sc == "npm start":
                cmd = [npm, "start"]
            elif sc.startswith("node "):
                cmd = ["node", sc[5:]]
            else:
                raise RuntimeError("No start script found. Add a \"start\" script to package.json.")
        elif t == "static":
            cmd = [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", str(app_dir)]
        else:
            raise RuntimeError("Docker-only projects can't run on 'Our Servers'. Use Render.")

        _update(pid, message="Starting…")
        proc = _spawn(cmd, app_dir, env, run_log, is_python=is_py)
        _update(pid, pid=proc.pid)

        deadline = time.time() + 30
        while time.time() < deadline:
            if proc.poll() is not None:
                tail = run_log.read_text(errors="replace")[-1200:] if run_log.exists() else ""
                raise RuntimeError(f"The app exited right after starting (code {proc.returncode}).\n{tail}")
            if _port_open(port):
                break
            time.sleep(0.5)

        _update(pid, message="Opening public link…")
        tpid, turl, tnote = _start_tunnel(pid, port)
        _update(pid, status="running", message="Live", tunnel_pid=tpid, tunnel_url=turl, tunnel_note=tnote)
    except Exception as e:  # noqa: BLE001 - every failure must end in a visible "failed" state
        log.warning("deploy %s failed: %s", pid, e)
        info = _load().get(pid, {})
        _kill(info.get("pid"))
        _kill(info.get("tunnel_pid"))
        _update(pid, status="failed", error=str(e)[:1500], message="Failed")


def _start_tunnel(pid: str, port: int):
    binary = _find_cloudflared()
    if not binary:
        return None, None, "cloudflared is not installed on this server, so there is no public link (local only)."
    log_path = LOG_DIR / f"{pid}.tunnel.log"
    out = open(log_path, "wb")
    kw = dict(stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    else:
        kw["preexec_fn"] = os.setsid
    try:
        proc = subprocess.Popen([binary, "tunnel", "--no-autoupdate", "--protocol", "http2",
                                 "--url", f"http://127.0.0.1:{port}"], **kw)
    except OSError:
        return None, None, "cloudflared failed to launch."
    _procs[proc.pid] = proc
    deadline = time.time() + 20
    while time.time() < deadline:
        m = TUNNEL_URL_RE.search(log_path.read_text(errors="replace"))
        if m:
            return proc.pid, m.group(0), None
        if proc.poll() is not None:
            return None, None, f"cloudflared exited early (code {proc.returncode})."
        time.sleep(0.5)
    return proc.pid, None, "The tunnel is still starting - refresh in a few seconds."


# --------------------------------------------------------------- public API
def start_deploy(token: str, owner: str, repo: str, user_id: str, root: str = "", env: Optional[dict] = None) -> str:
    if not is_enabled():
        raise PermissionError("'Our Servers' is turned off on this server.")
    root = (root or "").strip().strip("/")
    if root and (".." in root.split("/") or "\\" in root or ":" in root):
        raise ValueError("Invalid folder.")

    with _lock:
        state = _load()
        active = [p for p in state.values() if p.get("status") in ACTIVE]
        if len(active) >= config.OWN_SERVER_MAX_TOTAL:
            raise RuntimeError("The server is full right now. Try again later.")
        if sum(1 for p in active if p.get("user_id") == user_id) >= config.OWN_SERVER_MAX_PER_USER:
            raise RuntimeError(f"You can run at most {config.OWN_SERVER_MAX_PER_USER} deployments at once. Stop one first.")
        pid = uuid.uuid4().hex[:8]
        now = time.time()
        state[pid] = {"id": pid, "name": repo, "owner": owner, "repo": repo, "root": root, "user_id": user_id,
                      "status": "building", "message": "Queued…", "error": None, "type": None, "framework": None,
                      "port": None, "pid": None, "tunnel_pid": None, "tunnel_url": None, "tunnel_note": None,
                      "created_at": now, "expires_at": now + config.OWN_SERVER_TTL_MINUTES * 60}
        _save(state)

    start_reaper()
    threading.Thread(target=_build_and_run, args=(pid, token, owner, repo, root, env or {}), daemon=True,
                     name=f"deploy-{pid}").start()
    return pid


def _owned(pid: str, user_id: str) -> dict:
    info = _load().get(pid)
    if not info:
        raise KeyError("No such deployment")
    if info.get("user_id") != user_id:
        raise PermissionError("You don't own this deployment")
    return info


def list_projects(user_id: str) -> list:
    out = []
    for info in _load().values():
        if info.get("user_id") == user_id:
            out.append(_public(dict(info, alive=is_alive(info.get("pid")))))
    return sorted(out, key=lambda p: p["created_at"] or 0, reverse=True)


def get_project(pid: str, user_id: str) -> dict:
    info = _owned(pid, user_id)
    return _public(dict(info, alive=is_alive(info.get("pid"))))


def read_log(pid: str, user_id: str, tail: int = 300) -> str:
    _owned(pid, user_id)
    chunks = []
    for name, title in ((f"{pid}.build.log", "BUILD"), (f"{pid}.run.log", "APP OUTPUT")):
        p = LOG_DIR / name
        if p.exists():
            lines = p.read_text(errors="replace").splitlines()[-tail:]
            chunks.append(f"── {title} ──\n" + "\n".join(lines))
    return "\n\n".join(chunks) or "(no output yet)"


def _teardown(info: dict) -> None:
    _kill(info.get("tunnel_pid"))
    _kill(info.get("pid"))
    if info.get("id"):
        shutil.rmtree(PROJECTS_DIR / info["id"], ignore_errors=True)


def stop_project(pid: str, user_id: str, remove: bool = False) -> None:
    info = _owned(pid, user_id)
    _teardown(info)
    if remove:
        with _lock:
            state = _load()
            state.pop(pid, None)
            _save(state)
        for f in LOG_DIR.glob(f"{pid}.*"):
            f.unlink(missing_ok=True)
        if _hook:
            _hook(pid, dict(info, status="stopped"))
    else:
        _update(pid, status="stopped", message="Stopped", tunnel_url=None, pid=None, tunnel_pid=None)


# ------------------------------------------------------------------ reaper
def _reap_once() -> None:
    now = time.time()
    for pid, info in list(_load().items()):
        st = info.get("status")
        if st == "running":
            if now > info.get("expires_at", now + 1):
                _teardown(info)
                _update(pid, status="expired", message="Expired (time limit reached)", tunnel_url=None)
            elif not is_alive(info.get("pid")):
                _kill(info.get("tunnel_pid"))
                _update(pid, status="stopped", message="The app stopped running", tunnel_url=None)
        elif st in ("failed", "stopped", "expired") and now - info.get("expires_at", now) > 24 * 3600:
            with _lock:
                state = _load()
                state.pop(pid, None)
                _save(state)
            for f in LOG_DIR.glob(f"{pid}.*"):
                f.unlink(missing_ok=True)


def start_reaper() -> None:
    global _reaper_started
    with _lock:
        if _reaper_started:
            return
        _reaper_started = True

    def loop():
        while True:
            try:
                _reap_once()
            except Exception:  # noqa: BLE001
                log.exception("reaper error")
            time.sleep(30)
    threading.Thread(target=loop, daemon=True, name="own-server-reaper").start()


def init() -> None:
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    for pid, info in _load().items():  # a restart interrupts in-flight builds
        if info.get("status") == "building":
            _update(pid, status="failed", error="The server restarted while this deploy was building.", message="Failed")
    if is_enabled():
        start_reaper()

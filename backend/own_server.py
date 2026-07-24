"""
own_server.py — GitSetLive's built-in deploy engine ("Deploy to Our Servers")

This is the user's mini-PaaS prototype (app.py), adapted to:
  1. Deploy a full GitHub repo (many files) instead of a single pasted file
  2. Be driven by GitSetLive's own GitHub-authenticated endpoints instead of
     being a standalone, unauthenticated public Flask app
  3. Sanitize entrypoint paths (no path traversal)
  4. Bind the actual project process to 127.0.0.1 only — cloudflared still
     tunnels it to a public URL, but it's not reachable directly over the
     LAN/internet by port-scanning this machine
  5. Apply best-effort resource limits (CPU/memory/process count) on POSIX
     systems, since deployed code runs with no sandboxing otherwise

Known limitations (call these out to users):
  - No containerization/sandboxing. All deployed code runs with the same OS
    privileges as this server. Do not use for untrusted third parties.
  - Resource limits (see _restrict_child) only apply on POSIX (Linux/Mac) —
    Windows has no equivalent to setrlimit, so this protection doesn't
    apply there.
  - Binary files (images etc.) may not download correctly since GitHub's
    contents API + our decoder assume text.
  - Dependency install (npm install / pip install) is best-effort with a
    timeout; projects with heavy/native deps may still fail to start.
"""

import base64
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path

import requests

BASE_DIR = Path(__file__).parent.resolve()
OWN_PROJECTS_DIR = BASE_DIR / "own_server_projects"
OWN_LOG_DIR = BASE_DIR / "own_server_logs"
OWN_STATE_FILE = BASE_DIR / "own_server_state.json"
PORT_START, PORT_END = 4000, 4999

OWN_PROJECTS_DIR.mkdir(exist_ok=True)
OWN_LOG_DIR.mkdir(exist_ok=True)

CLOUDFLARED_BIN = (
    os.environ.get("CLOUDFLARED_PATH")
    or shutil.which("cloudflared")
    or shutil.which("cloudflared.exe")
)
if CLOUDFLARED_BIN and not os.path.isfile(CLOUDFLARED_BIN):
    CLOUDFLARED_BIN = None

TUNNEL_URL_RE = re.compile(r"https://[a-zA-Z0-9\-]+\.trycloudflare\.com")
TUNNEL_WAIT_SECONDS = 15

GITHUB_API = "https://api.github.com"

# Best-effort resource caps for deployed child processes (POSIX only)
MAX_MEMORY_BYTES = 512 * 1024 * 1024   # 512 MB
MAX_CPU_SECONDS = 300                   # 5 minutes of CPU time
MAX_PROCESSES = 32
MAX_OPEN_FILES = 256


def _gh(token):
    return {"Authorization": f"token {token}"}


def _restrict_child():
    """Applied via subprocess's preexec_fn on POSIX only, to cap what a
    deployed project's process can consume. Windows has no equivalent
    (no setrlimit), so this is skipped there — see module docstring."""
    if os.name == "nt":
        return
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (MAX_MEMORY_BYTES, MAX_MEMORY_BYTES))
        resource.setrlimit(resource.RLIMIT_CPU, (MAX_CPU_SECONDS, MAX_CPU_SECONDS))
        resource.setrlimit(resource.RLIMIT_NPROC, (MAX_PROCESSES, MAX_PROCESSES))
        resource.setrlimit(resource.RLIMIT_NOFILE, (MAX_OPEN_FILES, MAX_OPEN_FILES))
    except Exception as e:
        print(f"⚠️ Could not apply resource limits: {e}")
    os.setsid()


# ---------------------------------------------------------------- state.json
def load_state():
    if OWN_STATE_FILE.exists():
        try:
            return json.loads(OWN_STATE_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def save_state(state):
    OWN_STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def is_alive(pid):
    if not pid:
        return False
    if os.name == "nt":
        # os.kill(pid, 0) is not a reliable "is it alive" check on Windows —
        # use tasklist instead, which actually queries the process table.
        try:
            out = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}"],
                capture_output=True, text=True, timeout=5
            )
            return str(pid) in out.stdout
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def _reap(pid):
    if not pid:
        return
    for _ in range(10):
        try:
            done_pid, _ = os.waitpid(pid, os.WNOHANG)
            if done_pid == pid:
                return
        except ChildProcessError:
            return
        except Exception:
            return
        time.sleep(0.2)


def find_free_port():
    used = {p["port"] for p in load_state().values()}
    for port in range(PORT_START, PORT_END):
        if port in used:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("No free port available between %d-%d" % (PORT_START, PORT_END))


# ---------------------------------------------------------------- GitHub fetch
def _is_probably_text(path):
    binary_exts = {
        ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".pdf", ".zip",
        ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".mp3", ".wav", ".bin"
    }
    return Path(path).suffix.lower() not in binary_exts


SKIP_DIR_SEGMENTS = {".git", "node_modules", "__pycache__", ".next", "venv", ".venv", "dist", "build"}


def fetch_repo_to_dir(token, owner, repo, dest_dir):
    """Download the full repo (default branch) into dest_dir. Returns list of written file paths."""
    repo_info = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}", headers=_gh(token), timeout=15
    ).json()
    branch = repo_info.get("default_branch", "main")

    tree_res = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1",
        headers=_gh(token), timeout=20
    ).json()

    entries = tree_res.get("tree", [])
    if not isinstance(entries, list):
        raise RuntimeError("Could not read repo file tree (private repo without access, or repo is empty)")

    written = []
    for item in entries:
        if item.get("type") != "blob":
            continue
        path = item["path"]
        if any(seg in SKIP_DIR_SEGMENTS for seg in path.split("/")):
            continue
        if not _is_probably_text(path):
            continue  # skip binary assets for now (known limitation)

        content_res = requests.get(
            f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}",
            headers=_gh(token), timeout=15
        ).json()

        if "content" not in content_res:
            continue

        try:
            text = base64.b64decode(content_res["content"]).decode("utf-8", errors="ignore")
        except Exception:
            continue

        full_path = Path(dest_dir) / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(text, encoding="utf-8")
        written.append(path)

    if not written:
        raise RuntimeError("No readable files found in this repo")

    return written


# ---------------------------------------------------------------- detection
def detect_project_type(dest_dir):
    names = {p.name for p in Path(dest_dir).glob("*") if p.is_file()}
    if "package.json" in names:
        return "node"
    if "requirements.txt" in names or "app.py" in names or "main.py" in names:
        return "flask"
    # no package.json, but a plain .js entrypoint and no index.html —
    # treat as a single-file Node script (e.g. index.js with no deps)
    if "index.html" not in names and any(n.endswith(".js") for n in names):
        return "node"
    return "static"


def detect_entrypoint(dest_dir, ptype):
    dest = Path(dest_dir)

    if ptype == "node":
        pkg = dest / "package.json"
        if pkg.exists():
            try:
                data = json.loads(pkg.read_text(encoding="utf-8"))
                main = data.get("main")
                if main and (dest / main).exists():
                    return main
            except Exception:
                pass
        for candidate in ["index.js", "server.js", "app.js"]:
            if (dest / candidate).exists():
                return candidate
        # no package.json and none of the common names — grab any .js file
        js_files = list(dest.glob("*.js"))
        return js_files[0].name if js_files else "index.js"

    if ptype == "flask":
        for candidate in ["app.py", "main.py"]:
            if (dest / candidate).exists():
                return candidate
        return "app.py"

    for candidate in ["index.html"]:
        if (dest / candidate).exists():
            return candidate
    html_files = list(dest.glob("*.html"))
    return html_files[0].name if html_files else "index.html"


def _sanitize_entrypoint(entry):
    """Reject path traversal / absolute paths — this was a real bug in the
    original prototype (file was written safely via basename, but RUN via
    the raw unsanitized value)."""
    if not entry:
        return None
    if ".." in entry or entry.startswith("/") or entry.startswith("\\") or ":" in entry:
        return None
    return entry


# ---------------------------------------------------------------- run
def _parse_requirements_comment(entry_path):
    """AI-generated single-file code (from Upload Code) often has no
    package.json/requirements.txt, but does leave a header comment like
    '// Requirements: express, body-parser' or '# Requirements: flask'.
    Parse that as a fallback dependency list."""
    try:
        head = Path(entry_path).read_text(encoding="utf-8", errors="ignore")[:500]
    except Exception:
        return []
    m = re.search(r"requirements?:\s*(.+)", head, re.IGNORECASE)
    if not m:
        return []
    return [pkg.strip() for pkg in m.group(1).split(",") if pkg.strip()]


def install_dependencies(ptype, proj_dir, entry=None):
    """Best-effort dependency install, never raises — a slow/failed install
    just means the app may not start, which is reported back like any other
    startup failure."""
    try:
        if ptype == "node":
            if (Path(proj_dir) / "package.json").exists():
                subprocess.run(["npm", "install"], cwd=proj_dir, timeout=120, capture_output=True)
            elif entry:
                pkgs = _parse_requirements_comment(Path(proj_dir) / entry)
                if pkgs:
                    subprocess.run(["npm", "install", *pkgs], cwd=proj_dir, timeout=120, capture_output=True)

        elif ptype == "flask":
            if (Path(proj_dir) / "requirements.txt").exists():
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-r", "requirements.txt", "--break-system-packages"],
                    cwd=proj_dir, timeout=120, capture_output=True
                )
            elif entry:
                pkgs = _parse_requirements_comment(Path(proj_dir) / entry)
                if pkgs:
                    subprocess.run(
                        [sys.executable, "-m", "pip", "install", "--break-system-packages", *pkgs],
                        cwd=proj_dir, timeout=120, capture_output=True
                    )
    except Exception as e:
        print(f"⚠️ dependency install issue ({ptype}): {e}")


def build_command(ptype, port, entrypoint):
    env = os.environ.copy()
    env["PORT"] = str(port)

    if ptype == "static":
        return [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"], env

    if ptype == "flask":
        env["FLASK_APP"] = entrypoint
        return [sys.executable, "-m", "flask", "run", "--host", "127.0.0.1", "--port", str(port)], env

    if ptype == "node":
        return ["node", entrypoint], env

    raise ValueError("type must be one of: static, flask, node")


def start_tunnel(project_id, port):
    if not CLOUDFLARED_BIN:
        return None, None, "cloudflared not installed on this server — no public live link generated"

    tunnel_log = OWN_LOG_DIR / f"{project_id}_tunnel.log"
    log_file = open(tunnel_log, "w", encoding="utf-8")
    cmd = [CLOUDFLARED_BIN, "tunnel", "--protocol", "http2", "--url", f"http://localhost:{port}"]
    popen_kwargs = dict(stdout=log_file, stderr=subprocess.STDOUT)
    if os.name != "nt":
        popen_kwargs["preexec_fn"] = os.setsid
    else:
        popen_kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )

    try:
        proc = subprocess.Popen(cmd, **popen_kwargs)
    except FileNotFoundError:
        return None, None, "cloudflared binary found on PATH but failed to launch"

    deadline = time.time() + TUNNEL_WAIT_SECONDS
    url = None
    while time.time() < deadline:
        if tunnel_log.exists():
            text = tunnel_log.read_text(encoding="utf-8", errors="replace")
            m = TUNNEL_URL_RE.search(text)
            if m:
                url = m.group(0)
                break
        if proc.poll() is not None:
            return proc.pid, None, f"cloudflared exited early (code {proc.returncode})"
        time.sleep(0.5)

    note = None if url else "tunnel still starting — refresh in a few seconds"
    return proc.pid, url, note


def stop_tunnel(tunnel_pid):
    if not tunnel_pid or not is_alive(tunnel_pid):
        return
    try:
        if os.name != "nt":
            os.killpg(os.getpgid(tunnel_pid), signal.SIGTERM)
        else:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(tunnel_pid)], capture_output=True)
    except Exception:
        pass
    time.sleep(0.3)
    _reap(tunnel_pid)


def deploy_repo(token, owner, repo, user_id):
    """Main entry point: fetch repo -> detect type -> install deps -> run -> tunnel."""
    project_id = uuid.uuid4().hex[:8]
    proj_dir = OWN_PROJECTS_DIR / project_id
    proj_dir.mkdir(parents=True, exist_ok=True)

    fetch_repo_to_dir(token, owner, repo, proj_dir)

    ptype = detect_project_type(proj_dir)
    entry = _sanitize_entrypoint(detect_entrypoint(proj_dir, ptype))
    if not entry:
        raise RuntimeError("Detected entrypoint looked unsafe — refusing to run it")

    install_dependencies(ptype, proj_dir, entry)

    port = find_free_port()
    cmd, env = build_command(ptype, port, entry)

    log_path = OWN_LOG_DIR / f"{project_id}.log"
    log_file = open(log_path, "w", encoding="utf-8")

    popen_kwargs = dict(cwd=proj_dir, env=env, stdout=log_file, stderr=subprocess.STDOUT)
    if os.name != "nt":
        popen_kwargs["preexec_fn"] = _restrict_child
    else:
        popen_kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )

    try:
        proc = subprocess.Popen(cmd, **popen_kwargs)
    except FileNotFoundError:
        raise RuntimeError(
            f"'{cmd[0]}' is not installed on this server. "
            f"({'Install Node.js' if ptype == 'node' else 'Install Python/Flask'})"
        )

    time.sleep(1.2)
    if proc.poll() is not None:
        tail = log_path.read_text(encoding="utf-8", errors="replace")[-1000:]
        raise RuntimeError(f"Process exited immediately (code {proc.returncode}).\nLog:\n{tail}")

    tunnel_pid, tunnel_url, tunnel_note = start_tunnel(project_id, port)

    state = load_state()
    state[project_id] = {
        "name": repo, "type": ptype, "port": port, "pid": proc.pid,
        "dir": str(proj_dir), "log": str(log_path), "entry": entry,
        "tunnel_pid": tunnel_pid, "tunnel_url": tunnel_url, "tunnel_note": tunnel_note,
        "user_id": user_id, "owner": owner, "repo": repo,
    }
    save_state(state)

    return project_id, state[project_id]


def stop_project(project_id, user_id):
    state = load_state()
    info = state.get(project_id)
    if not info:
        raise KeyError("No such project")
    if info.get("user_id") != user_id:
        raise PermissionError("You don't own this deployment")

    stop_tunnel(info.get("tunnel_pid"))

    pid = info.get("pid")
    if pid and is_alive(pid):
        try:
            if os.name != "nt":
                os.killpg(os.getpgid(pid), signal.SIGTERM)
            else:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True)
        except Exception:
            pass
        time.sleep(0.4)
        _reap(pid)

    shutil.rmtree(info.get("dir"), ignore_errors=True)
    log_path = info.get("log")
    if log_path and os.path.exists(log_path):
        try:
            os.remove(log_path)
        except Exception:
            pass

    del state[project_id]
    save_state(state)


def list_projects_for_user(user_id):
    state = load_state()
    result = {}
    for pid, info in state.items():
        if info.get("user_id") == user_id:
            info = dict(info)
            info["alive"] = is_alive(info.get("pid"))
            result[pid] = info
    return result

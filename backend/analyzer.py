"""Deterministic repository analysis — no AI, no network.

Everything here works on plain data (`paths` + a `read(path)` callable / a
{path: text} dict) so it is fast, reproducible and unit-testable. The AI review
in routers/scan.py only adds on top of these verified findings.

A finding looks like:
  {"id", "severity": critical|warning|info, "category", "title", "file", "line",
   "line_context", "detail", "fix": {"op": ...} | None, "source": "static"}
"""

import ast
import hashlib
import json
import re
import sys
from typing import Callable, Dict, List, Optional

SEVERITY_WEIGHT = {"critical": 20, "warning": 8, "info": 2}
SKIP_SEGMENTS = {"node_modules", ".git", ".next", "__pycache__", "venv", ".venv", "dist", "build", "vendor"}
PY_EXT = (".py",)
JS_EXT = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")


# ------------------------------------------------------------------ helpers
def _fid(rule: str, file: Optional[str], line: Optional[int], extra: str = "") -> str:
    return hashlib.sha1(f"{rule}|{file}|{line}|{extra}".encode()).hexdigest()[:10]


def finding(rule, severity, category, title, *, file=None, line=None, context=None, detail="", fix=None, extra=""):
    return {
        "id": _fid(rule, file, line, extra), "rule": rule, "severity": severity, "category": category,
        "title": title, "file": file, "line": line,
        "line_context": (context or "").strip()[:300] or None,
        "detail": detail, "fix": fix, "source": "static",
    }


def _join(root: str, name: str) -> str:
    return f"{root}/{name}" if root else name


def _in_skipped(path: str) -> bool:
    return any(s in SKIP_SEGMENTS for s in path.split("/")[:-1])


_STRING_LIT = re.compile(r"""(["'])(?:\\.|(?!\1).)*\1""")
SUPPRESS = ("nosec", "gsl-ignore")
CODE_ABOUT_CODE = ("re.search(", "re.compile(", "re.match(", "replace_fix(", ".replace(", "add(")


def strip_strings(line: str) -> str:
    """Blank out string literals so patterns that merely appear inside text aren't treated as code."""
    return _STRING_LIT.sub('""', line)


def mask(secret: str) -> str:
    return secret[:4] + "…" if len(secret) > 6 else "…"


# ------------------------------------------------------------------ secrets
KNOWN_SECRETS = [
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})\b")),
    ("Groq API key", re.compile(r"\bgsk_[A-Za-z0-9]{20,}\b")),
    ("Anthropic API key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("OpenAI-style API key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{32,}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("Stripe live key", re.compile(r"\b[sr]k_live_[0-9A-Za-z]{16,}\b")),
    ("Private key", re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----")),
]
GENERIC_SECRET = re.compile(
    r"""(?i)\b([A-Z0-9_]*(?:password|passwd|secret|api[_-]?key|token|private[_-]?key)[A-Z0-9_]*)\s*[:=]\s*(["'])([^"'\s]{8,})\2"""
)
PLACEHOLDER_HINTS = ("your", "changeme", "change_me", "change-me", "example", "xxxx", "placeholder", "<", "${", "{{",
                     "dummy", "secret_here", "replace", "todo", "none", "null", "process.env", "getenv", "environ",
                     "password123", "*****", "...", "test")
DOC_OR_TEST = re.compile(r"(^|/)(tests?|__tests__|fixtures?|mocks?|examples?|samples?|docs?)(/|$)|\.(md|rst|txt|lock)$", re.I)


def scan_secrets(files: Dict[str, str]) -> List[dict]:
    out = []
    for path, text in files.items():
        if _in_skipped(path) or re.search(r"\.env\.(example|sample|template)$", path):
            continue
        skip_generic = bool(DOC_OR_TEST.search(path))
        for i, line in enumerate(text.split("\n"), 1):
            if len(line) > 600 or any(m in line for m in SUPPRESS):
                continue
            hit = False
            for label, rx in KNOWN_SECRETS:
                m = rx.search(line)
                if m:
                    ctx = line.replace(m.group(0), mask(m.group(0)))
                    out.append(finding(
                        "secret-known", "critical", "security", f"{label} committed to the repository",
                        file=path, line=i, context=ctx, extra=label,
                        detail="Anyone who can read this repo can use this credential. Revoke/rotate it NOW, then move it to an "
                               "environment variable. Deleting the line is not enough — it stays in git history."))
                    hit = True
                    break
            if hit or skip_generic:
                continue
            m = GENERIC_SECRET.search(line)
            if not m:
                continue
            value = m.group(3)
            low = (line + value).lower()
            if any(h in low for h in PLACEHOLDER_HINTS) or len(set(value)) < 4:
                continue
            if not (any(c.isdigit() for c in value) or len(value) >= 16):
                continue
            ctx = line.replace(value, mask(value))
            out.append(finding(
                "secret-generic", "warning", "security", f"Hard-coded value for “{m.group(1)}”",
                file=path, line=i, context=ctx,
                detail="Looks like a credential written directly in code. Read it from an environment variable instead "
                       "(os.getenv / process.env) and rotate it if it is real."))
    return out


# --------------------------------------------------------- per-file code rules
def scan_code_rules(path: str, text: str) -> List[dict]:
    low = path.lower()
    is_py, is_js = low.endswith(PY_EXT), low.endswith(JS_EXT)
    if not (is_py or is_js) or _in_skipped(path) or re.search(r"(^|/)tests?(/|$)|\.test\.|\.spec\.", low):
        return []

    out, counts = [], {}
    lines = text.split("\n")
    has_os = bool(re.search(r"^\s*(import os\b|from os import)", text, re.M))
    mentions_port = bool(re.search(r"\bPORT\b", text))

    def add(rule, sev, cat, title, i, detail, fix=None):
        counts[rule] = counts.get(rule, 0) + 1
        if counts[rule] <= 3:
            out.append(finding(rule, sev, cat, title, file=path, line=i, context=lines[i - 1], detail=detail, fix=fix))

    def replace_fix(i, old, new):
        """Prefer a narrow token replacement (several findings can then fix the same line);
        fall back to the whole line when the token is not unique in the file."""
        line = lines[i - 1]
        if old not in line:
            return None
        if text.count(old) == 1:
            return {"op": "replace", "search": old, "replace": new}
        return {"op": "replace", "search": line.strip(), "replace": line.strip().replace(old, new, 1)}

    for i, line in enumerate(lines, 1):
        s = line.strip()
        if not s or s.startswith(("#", "//", "*", "/*")) or any(m in line for m in SUPPRESS):
            continue
        if any(m in s for m in CODE_ABOUT_CODE) and "[" in s and "(" in s and ("re." in s or "replace_fix" in s):
            continue  # a line that *describes* patterns (regexes / fix templates), not code that has the problem
        code = strip_strings(s)
        window = "\n".join(lines[max(0, i - 5):i])

        if is_py:
            m = re.search(r"\bdebug\s*=\s*True\b", code)
            if m and (".run(" in window or "app.debug" in code):
                add("py-debug", "warning", "config", "Debug mode is enabled", i,
                    "Flask/Werkzeug debug exposes an interactive console that allows remote code execution. Never ship it.",
                    replace_fix(i, "debug=True", "debug=False") or replace_fix(i, "debug = True", "debug = False"))
            if re.search(r"\breload\s*=\s*True\b", code) and "uvicorn" in window:
                add("py-reload", "warning", "config", "Auto-reload is enabled in server start-up", i,
                    "reload=True is for development only; it spawns watcher processes and is wasteful in production.",
                    replace_fix(i, "reload=True", "reload=False"))
            m = re.search(r"""\bhost\s*=\s*["'](127\.0\.0\.1|localhost)["']""", s)
            if m and re.search(r"\.run\(|uvicorn\.run\(|serve\(", window):
                add("py-localhost", "critical", "deployment", "Server only listens on localhost", i,
                    "A host of 127.0.0.1/localhost is unreachable from outside the machine, so the deployed app will "
                    "appear dead. Bind to 0.0.0.0.", replace_fix(i, m.group(0), 'host="0.0.0.0"'))
            m = re.search(r"\bport\s*=\s*(\d{2,5})\b", s)
            if m and re.search(r"\.run\(|uvicorn\.run\(", window) and not mentions_port:
                fix = replace_fix(i, m.group(0), f'port=int(os.environ.get("PORT", {m.group(1)}))') if has_os else None
                add("py-port", "warning", "deployment", "Port is hard-coded", i,
                    "Hosts like Render/Railway/Heroku tell your app which port to use via the PORT environment "
                    "variable. A fixed port makes the deploy fail its health check.", fix)
            if re.search(r"allow_origins\s*=\s*\[\s*[\"']\*[\"']\s*\]", s) and "allow_credentials=True" in text.replace(" ", ""):
                add("py-cors", "warning", "security", "CORS allows every origin together with credentials", i,
                    "Wildcard origins combined with credentials is both rejected by browsers and unsafe. List your real "
                    "frontend URL(s) instead.")
            if re.search(r"\bverify\s*=\s*False\b", code):
                add("py-tls", "warning", "security", "TLS certificate verification is disabled", i,
                    "verify=False makes HTTPS requests vulnerable to man-in-the-middle attacks.")
            if re.search(r"\bshell\s*=\s*True\b", code):
                add("py-shell", "info", "security", "subprocess is called with shell=True", i,
                    "If any part of the command comes from user input this allows command injection. Pass a list instead.")
            if re.search(r"""\.execute\(\s*f["']""", s) or re.search(r"""\.execute\(\s*["'][^"']*["']\s*(\+|%)\s*\w""", s):
                add("py-sqli", "warning", "security", "SQL query built with string formatting", i,
                    "Building SQL with f-strings/concatenation allows SQL injection. Use placeholders: "
                    "cursor.execute('... WHERE id = ?', (value,)).")
            if re.match(r"except\s*:", code):
                add("py-bare-except", "info", "error-handling", "Bare `except:` swallows every error", i,
                    "It also catches KeyboardInterrupt/SystemExit and hides real bugs. Catch specific exceptions.")
        else:
            m = re.search(r"\.listen\(\s*(\d{2,5})\b", s)
            if m and "process.env.PORT" not in text:
                add("js-port", "warning", "deployment", "Port is hard-coded", i,
                    "Hosts provide the port through process.env.PORT. A fixed port makes the deploy fail its health check.",
                    replace_fix(i, m.group(0), f".listen(process.env.PORT || {m.group(1)}"))
            if re.search(r"""\.listen\([^)]*["'](localhost|127\.0\.0\.1)["']""", s):
                add("js-localhost", "critical", "deployment", "Server only listens on localhost", i,
                    "Binding to localhost makes the app unreachable once deployed. Use '0.0.0.0'.")
            if re.search(r"rejectUnauthorized\s*:\s*false|NODE_TLS_REJECT_UNAUTHORIZED\s*=\s*['\"]?0", s):
                add("js-tls", "warning", "security", "TLS certificate verification is disabled", i,
                    "This makes HTTPS connections vulnerable to man-in-the-middle attacks.")
    return out


# -------------------------------------------------------------- app detection
def detect_apps(paths: List[str], read: Callable[[str], Optional[str]]) -> List[dict]:
    markers: Dict[str, set] = {}
    for p in paths:
        if _in_skipped(p):
            continue
        d, _, name = p.rpartition("/")
        if name in ("package.json", "requirements.txt", "pyproject.toml", "Pipfile", "Dockerfile",
                    "index.html", "manage.py", "Procfile"):
            markers.setdefault(d, set()).add(name)
        elif name in ("main.py", "app.py", "server.py", "wsgi.py", "application.py", "run.py", "api.py"):
            markers.setdefault(d, set()).add("py-entry")

    apps: List[dict] = []
    for root in sorted(markers):
        m = markers[root]
        if "package.json" in m:
            apps.append(_node_app(root, read))
        elif m & {"requirements.txt", "pyproject.toml", "Pipfile", "manage.py", "py-entry"}:
            apps.append(_python_app(root, paths, read))
        elif "index.html" in m:
            if root.rsplit("/", 1)[-1] == "public":
                continue
            if any(a["root"] != root and (a["root"] == "" or root.startswith(a["root"] + "/")) and a["type"] != "static"
                   for a in apps):
                continue
            apps.append({"root": root, "type": "static", "framework": "static", "kind": "web-static", "name": root or "site",
                         "entry": "index.html", "build_command": None, "start_command": None, "output_dir": root or "."})
        elif "Dockerfile" in m:
            apps.append({"root": root, "type": "docker", "framework": "docker", "kind": "container", "name": root or "container",
                         "entry": "Dockerfile", "build_command": None, "start_command": None, "output_dir": None})
    for a in apps:
        a["recommend"] = recommend(a)
    return apps


def _node_app(root: str, read) -> dict:
    try:
        pkg = json.loads(read(_join(root, "package.json")) or "{}")
        if not isinstance(pkg, dict):
            pkg = {}
    except ValueError:
        pkg = {}
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    scripts = pkg.get("scripts") or {}

    fw, kind, out = "node", "server", None
    if "next" in deps:
        fw, kind, out = "next", "web-ssr", ".next"
    elif "nuxt" in deps:
        fw, kind, out = "nuxt", "web-ssr", ".output"
    elif "vite" in deps:
        fw, kind, out = "vite", "web-static", "dist"
    elif "react-scripts" in deps:
        fw, kind, out = "create-react-app", "web-static", "build"
    elif "@nestjs/core" in deps:
        fw = "nestjs"
    elif "express" in deps:
        fw = "express"
    elif "fastify" in deps:
        fw = "fastify"
    elif "koa" in deps:
        fw = "koa"

    main = pkg.get("main")
    if scripts.get("start") or fw in ("next", "nuxt", "nestjs"):
        start = "npm start"
    elif kind == "web-static":
        start = None
    else:
        start = f"node {main}" if main else None
    return {"root": root, "type": "node", "framework": fw, "kind": kind, "name": pkg.get("name") or root or "app",
            "entry": main, "build_command": "npm run build" if scripts.get("build") else None,
            "start_command": start, "output_dir": out, "has_start_script": bool(scripts.get("start")),
            "has_build_script": bool(scripts.get("build"))}


def _python_app(root: str, paths: List[str], read) -> dict:
    direct = {p.rsplit("/", 1)[-1]: p for p in paths if p.rpartition("/")[0] == root and p.endswith(".py")}
    reqs = (read(_join(root, "requirements.txt")) or "") + (read(_join(root, "pyproject.toml")) or "")
    reqs_low = reqs.lower()

    fw, entry, var = "python", None, "app"
    for cand in ("main.py", "app.py", "server.py", "wsgi.py", "application.py", "run.py", "api.py"):
        if cand not in direct:
            continue
        src = read(direct[cand]) or ""
        m = re.search(r"^(\w+)\s*(?::\s*\w+\s*)?=\s*(FastAPI|Flask)\(", src, re.M)
        if m:
            fw, entry, var = m.group(2).lower(), cand, m.group(1)
            break
        if entry is None:
            entry = cand
    if fw == "python":
        if "manage.py" in direct:
            fw, entry = "django", "manage.py"
        elif "fastapi" in reqs_low:
            fw = "fastapi"
        elif "flask" in reqs_low:
            fw = "flask"

    module = (entry or "app.py")[:-3]
    start = {
        "fastapi": f"uvicorn {module}:{var} --host 0.0.0.0 --port $PORT",
        "flask": f"gunicorn {module}:{var}",
        "django": None,
    }.get(fw, f"python {entry}" if entry else None)
    if fw == "django":
        wsgi = next((p for p in paths if p.endswith("/wsgi.py") and p.startswith(root + "/" if root else "")), None)
        if wsgi:
            start = f"gunicorn {wsgi[:-3].replace('/', '.')}:application" if not root else \
                    f"gunicorn {wsgi[len(root) + 1:-3].replace('/', '.')}:application"

    has_reqs = _join(root, "requirements.txt") in paths
    return {"root": root, "type": "python", "framework": fw, "kind": "server", "name": root or "app", "entry": entry,
            "build_command": "pip install -r requirements.txt" if has_reqs else None, "start_command": start,
            "output_dir": None}


def recommend(app: dict) -> dict:
    t, kind, root = app["type"], app.get("kind"), app["root"]
    render = vercel = None
    notes: List[str] = []

    if t == "python":
        render = {"service": "Web Service", "runtime": "Python 3", "root_dir": root,
                  "build_command": app["build_command"] or "pip install -r requirements.txt",
                  "start_command": app["start_command"] or "python main.py"}
        notes.append("Vercel isn't a good fit for long-running Python servers — use Render (or 'Our Servers').")
    elif t == "node" and kind in ("server", "web-ssr"):
        build = "npm install && npm run build" if app["build_command"] else "npm install"
        render = {"service": "Web Service", "runtime": "Node", "root_dir": root, "build_command": build,
                  "start_command": app["start_command"] or "npm start"}
        if kind == "web-ssr":
            vercel = {"framework": app["framework"].title(), "root_dir": root, "build_command": app["build_command"] or "npm run build",
                      "output_dir": "(auto)", "install_command": "npm install"}
    elif t == "node" and kind == "web-static":
        render = {"service": "Static Site", "runtime": "Static", "root_dir": root,
                  "build_command": "npm install && npm run build", "publish_dir": app["output_dir"]}
        vercel = {"framework": app["framework"], "root_dir": root, "build_command": "npm run build",
                  "output_dir": app["output_dir"], "install_command": "npm install"}
    elif t == "static":
        render = {"service": "Static Site", "runtime": "Static", "root_dir": root, "build_command": "(none)",
                  "publish_dir": app["output_dir"]}
        vercel = {"framework": "Other", "root_dir": root, "build_command": "(none)", "output_dir": app["output_dir"] or ".",
                  "install_command": "(none)"}
    elif t == "docker":
        render = {"service": "Web Service", "runtime": "Docker", "root_dir": root, "build_command": "(uses your Dockerfile)",
                  "start_command": "(uses your Dockerfile CMD)"}

    return {"render": render, "vercel": vercel, "own_server": t in ("python", "node", "static"), "notes": notes}


# ---------------------------------------------------------------- env vars
ENV_PATTERNS = [
    re.compile(r"""os\.environ\.get\(\s*["']([A-Z][A-Z0-9_]+)["']"""),
    re.compile(r"""os\.getenv\(\s*["']([A-Z][A-Z0-9_]+)["']"""),
    re.compile(r"""os\.environ\[\s*["']([A-Z][A-Z0-9_]+)["']\s*\]"""),
    re.compile(r"""process\.env\.([A-Z][A-Z0-9_]+)"""),
    re.compile(r"""process\.env\[\s*["']([A-Z][A-Z0-9_]+)["']\s*\]"""),
    re.compile(r"""import\.meta\.env\.([A-Z][A-Z0-9_]+)"""),
]
IGNORED_ENV = {"PORT", "HOME", "PATH", "NODE_ENV", "PWD", "USER", "LANG", "HOST", "HOSTNAME", "TMPDIR", "CI", "ENV"}


def env_vars_used(files: Dict[str, str], root: str = "") -> List[dict]:
    found: Dict[str, set] = {}
    prefix = root + "/" if root else ""
    for path, text in files.items():
        if _in_skipped(path) or (prefix and not path.startswith(prefix)):
            continue
        if not path.lower().endswith(PY_EXT + JS_EXT):
            continue
        for rx in ENV_PATTERNS:
            for name in rx.findall(text):
                if name not in IGNORED_ENV:
                    found.setdefault(name, set()).add(path)
    return [{"name": n, "files": sorted(f)[:4]} for n, f in sorted(found.items())]


# ----------------------------------------------------------- repo-level rules
KNOWN_PY_LIBS = {
    "fastapi": "fastapi", "flask": "flask", "django": "django", "requests": "requests", "uvicorn": "uvicorn",
    "sqlalchemy": "sqlalchemy", "pydantic": "pydantic", "dotenv": "python-dotenv", "jwt": "PyJWT", "bs4": "beautifulsoup4",
    "yaml": "PyYAML", "PIL": "Pillow", "numpy": "numpy", "pandas": "pandas", "cryptography": "cryptography",
    "httpx": "httpx", "aiohttp": "aiohttp", "starlette": "starlette", "gunicorn": "gunicorn", "celery": "celery",
    "redis": "redis", "pymongo": "pymongo", "psycopg2": "psycopg2-binary", "boto3": "boto3", "openai": "openai",
    "anthropic": "anthropic", "groq": "groq", "stripe": "stripe", "jinja2": "jinja2", "flask_cors": "flask-cors",
    "scipy": "scipy", "matplotlib": "matplotlib", "sklearn": "scikit-learn", "torch": "torch", "cv2": "opencv-python",
    "selenium": "selenium", "multipart": "python-multipart", "flask_sqlalchemy": "flask-sqlalchemy", "jose": "python-jose",
}
NODE_BUILTINS = {
    "assert", "buffer", "child_process", "cluster", "console", "crypto", "dgram", "dns", "events", "fs", "http", "http2",
    "https", "net", "os", "path", "perf_hooks", "process", "querystring", "readline", "stream", "string_decoder", "timers",
    "tls", "tty", "url", "util", "v8", "vm", "worker_threads", "zlib", "module",
}
JS_IMPORT = re.compile(r"""(?:require\(\s*|from\s+|import\(\s*|^\s*import\s+)["']([^"'\n]+)["']""", re.M)


# packages that are installed automatically with another package — not "missing"
IMPLIED = {"fastapi": {"pydantic", "starlette"}, "flask": {"jinja2", "werkzeug"}, "uvicorn": set(),
           "requests": set(), "sqlalchemy": set(), "httpx": set()}


def _pkg_names(requirements: str) -> set:
    names = set()
    for line in requirements.split("\n"):
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        names.add(re.split(r"[<>=!~\[;\s@]", line, 1)[0].lower().replace("_", "-"))
    return names


def _python_dependency_findings(paths, files, apps) -> List[dict]:
    out = []
    py_files = {p: t for p, t in files.items() if p.endswith(".py") and not _in_skipped(p)}
    if not py_files:
        return out
    stdlib = getattr(sys, "stdlib_module_names", set())
    local = {p.rsplit("/", 1)[-1][:-3] for p in paths if p.endswith(".py")}
    local |= {seg for p in paths for seg in p.split("/")[:-1]}

    for app in [a for a in apps if a["type"] == "python"]:
        root = app["root"]
        prefix = root + "/" if root else ""
        nested = [a["root"] for a in apps if a["root"].startswith(prefix) and a["root"] != root] if root else \
                 [a["root"] for a in apps if a["root"]]
        used = {}
        for p, text in py_files.items():
            if prefix and not p.startswith(prefix):
                continue
            if any(p.startswith(n + "/") for n in nested if n):
                continue
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                mod = None
                if isinstance(node, ast.Import):
                    mods = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    mods = [node.module.split(".")[0]]
                else:
                    continue
                for mod in mods:
                    if mod in KNOWN_PY_LIBS and mod not in stdlib and mod not in local:
                        used.setdefault(KNOWN_PY_LIBS[mod], p)

        req_path = _join(root, "requirements.txt")
        req_text = files.get(req_path)
        have = _pkg_names(req_text or "")
        for pkg in list(have):
            have |= IMPLIED.get(pkg, set())
        fw = app["framework"]
        if fw == "fastapi":
            used.setdefault("uvicorn", None)
        if fw == "flask":
            used.setdefault("gunicorn", None)

        if req_text is None and _join(root, "pyproject.toml") not in paths and _join(root, "Pipfile") not in paths:
            if used:
                content = "\n".join(sorted(used)) + "\n"
                out.append(finding("py-no-requirements", "critical", "dependencies", "No requirements.txt",
                                   file=req_path, fix={"op": "create", "content": content}, extra=root,
                                   detail="Render/Railway/Heroku install dependencies from requirements.txt. Without it the "
                                          "deploy fails with “ModuleNotFoundError”. Versions are unpinned — pin them once it works."))
            continue
        if req_text is None:
            continue  # uses pyproject/Pipfile — don't second-guess
        missing = sorted(n for n in used if n.lower().replace("_", "-") not in have)
        if missing:
            first = used.get(missing[0])
            out.append(finding("py-missing-deps", "critical", "dependencies",
                               f"Imported but missing from requirements.txt: {', '.join(missing)}",
                               file=req_path, extra=root + ",".join(missing),
                               context=f"imported in {first}" if first else None,
                               fix={"op": "append", "content": "\n".join(missing) + "\n"},
                               detail="The code imports these packages but the host won't install them, so the app crashes at start-up "
                                      "with ModuleNotFoundError."))
    return out


def _node_dependency_findings(paths, files, apps) -> List[dict]:
    out = []
    for app in [a for a in apps if a["type"] == "node"]:
        root = app["root"]
        prefix = root + "/" if root else ""
        try:
            pkg = json.loads(files.get(_join(root, "package.json"), "{}"))
        except ValueError:
            continue
        declared = set()
        for k in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            declared |= set((pkg.get(k) or {}).keys())
        local_top = {p[len(prefix):].split("/")[0].rsplit(".", 1)[0] for p in paths if p.startswith(prefix)}
        nested = [a["root"] for a in apps if a["root"] != root and a["root"].startswith(prefix)] if root else \
                 [a["root"] for a in apps if a["root"]]

        missing: Dict[str, str] = {}
        for p, text in files.items():
            if not p.startswith(prefix) or not p.lower().endswith(JS_EXT) or _in_skipped(p):
                continue
            if any(p.startswith(n + "/") for n in nested if n):
                continue
            for spec in JS_IMPORT.findall(text):
                if spec.startswith((".", "/", "@/", "~/", "#", "node:", "http")) or spec.startswith("data:"):
                    continue
                parts = spec.split("/")
                name = "/".join(parts[:2]) if spec.startswith("@") else parts[0]
                if name in NODE_BUILTINS or name in declared or name.split("/")[0] in local_top:
                    continue
                missing.setdefault(name, p)
        if missing:
            names = sorted(missing)
            out.append(finding("js-missing-deps", "critical", "dependencies",
                               f"Imported but not in package.json: {', '.join(names[:6])}",
                               file=_join(root, "package.json"), extra=root + ",".join(names),
                               context=f"first import in {missing[names[0]]}",
                               detail=f"Run: npm install {' '.join(names[:6])}  — then commit package.json and package-lock.json. "
                                      "Without it the deploy fails at build/start."))

        needs = {"next": ('"build": "next build"', '"start": "next start"'),
                 "vite": ('"build": "vite build"', None), "create-react-app": ('"build": "react-scripts build"', None)}
        if app["framework"] in needs and '"scripts": {' in files.get(_join(root, "package.json"), ""):
            build_line, start_line = needs[app["framework"]]
            add_lines = []
            if not app.get("has_build_script"):
                add_lines.append(build_line)
            if start_line and not app.get("has_start_script"):
                add_lines.append(start_line)
            if add_lines:
                out.append(finding(
                    "js-no-build-scripts", "warning", "deployment",
                    f"package.json is missing the {' and '.join(l.split(chr(34))[1] for l in add_lines)} script",
                    file=_join(root, "package.json"), extra=root,
                    fix={"op": "replace", "search": '"scripts": {',
                         "replace": '"scripts": {\n    ' + ",\n    ".join(add_lines) + ","},
                    detail="Render (and `npm run build`) can only build/start a Next.js or Vite app if these scripts exist. "
                           "Vercel auto-detects them, Render does not."))

        if app["kind"] == "server" and not app.get("has_start_script"):
            entry = next((e for e in ("server.js", "index.js", "app.js", "main.js") if _join(root, e) in paths), None)
            fix = None
            if entry and '"scripts": {' in files.get(_join(root, "package.json"), ""):
                fix = {"op": "replace", "search": '"scripts": {',
                       "replace": f'"scripts": {{\n    "start": "node {entry}",'}
            out.append(finding("js-no-start", "warning", "deployment", "package.json has no \"start\" script",
                               file=_join(root, "package.json"), extra=root, fix=fix,
                               detail="Render and most hosts run `npm start`. Add a start script that launches your server."))
    return out


GITIGNORE_BASE = [".env", ".env.local", "*.log", ".DS_Store"]
GITIGNORE_PY = ["__pycache__/", "*.pyc", ".venv/", "venv/", "*.db", "*.sqlite3"]
GITIGNORE_NODE = ["node_modules/", ".next/", "dist/", "build/"]
ENV_FILE = re.compile(r"(^|/)\.env(\.[A-Za-z0-9_-]+)?$")
ENV_SAFE = re.compile(r"\.(example|sample|template|dist)$")
SENSITIVE_KEY = re.compile(r"(SECRET|TOKEN|KEY|PASSWORD|PASSWD|PRIVATE|CREDENTIAL)", re.I)


def _gitignore_lines(texts: List[str]) -> set:
    out = set()
    for t in texts:
        for ln in t.split("\n"):
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                out.add(ln.lstrip("/").rstrip("/").removeprefix("**/"))
    return out


def _gitignore_findings(paths, files, apps) -> List[dict]:
    wants = list(GITIGNORE_BASE)
    if any(a["type"] == "python" for a in apps):
        wants += GITIGNORE_PY
    if any(a["type"] == "node" for a in apps):
        wants += GITIGNORE_NODE

    gi_files = {p: t for p, t in files.items() if p.rsplit("/", 1)[-1] == ".gitignore" and not _in_skipped(p)}
    if not gi_files:
        return [finding("no-gitignore", "warning", "security", "No .gitignore file", file=".gitignore",
                        fix={"op": "create", "content": "\n".join(wants) + "\n"},
                        detail="Without it, secrets (.env), dependencies (node_modules) and build output are easy to commit by accident.")]

    lines = _gitignore_lines(list(gi_files.values()))

    def covered(pat: str) -> bool:
        key = pat.strip("/")
        if key in lines:
            return True
        return key == ".env" and bool(lines & {".env*", ".env.*", "*.env"})

    missing = [w for w in wants if not covered(w)]
    must_have = {".env", "node_modules/", "__pycache__/"}
    if not (set(missing) & must_have):
        return []

    shown = missing[:4]
    title = f".gitignore is missing: {', '.join(shown)}" + (f" (+{len(missing) - 4} more)" if len(missing) > 4 else "")
    detail = "These should never be committed (secrets / generated files)."
    if ".gitignore" in gi_files:
        return [finding("gitignore-incomplete", "warning", "security", title, file=".gitignore",
                        fix={"op": "append", "content": "\n".join(missing) + "\n"}, detail=detail)]
    return [finding("gitignore-incomplete", "warning", "security", title, file=".gitignore",
                    fix={"op": "create", "content": "\n".join(missing) + "\n"}, detail=detail)]


def _repo_hygiene_findings(paths, files, apps, envs_by_root) -> List[dict]:
    out = []
    for p in paths:
        if _in_skipped(p):
            continue
        base = p.rsplit("/", 1)[-1]
        if ENV_FILE.search(p) and not ENV_SAFE.search(p):
            text = files.get(p, "")
            risky = [ln for ln in text.split("\n") if "=" in ln and not ln.strip().startswith("#")
                     and SENSITIVE_KEY.search(ln.split("=", 1)[0]) and ln.split("=", 1)[1].strip().strip("\"'")]
            if risky:
                out.append(finding("env-committed", "critical", "security", f"Environment file with secrets is committed ({p})",
                                   file=p, detail="Rotate every key in this file, remove it from the repo (git rm --cached) and add it to "
                                                  ".gitignore. Anything ever pushed stays in git history."))
            else:
                out.append(finding("env-committed-safe", "warning", "security", f"Environment file is tracked by git ({p})", file=p,
                                   detail="It holds no obvious secrets today, but .env files are the #1 way credentials leak. Untrack it "
                                          "and commit a .env.example instead."))
        elif re.search(r"\.(db|sqlite|sqlite3)$", base):
            out.append(finding("db-committed", "warning", "security", f"Database file is committed ({p})", file=p,
                               detail="Database files can contain user data and login tokens. Remove from git and add to .gitignore."))
        elif re.search(r"\.(pem|p12|pfx)$", base) or base in ("id_rsa", "id_ed25519"):
            out.append(finding("key-committed", "critical", "security", f"Private key file is committed ({p})", file=p,
                               detail="Treat this key as compromised: rotate it and remove it from git history."))
    if any("node_modules" in p.split("/") for p in paths):
        out.append(finding("node-modules-committed", "warning", "config", "node_modules is committed",
                           detail="Dependencies belong in package.json, not in git. It bloats the repo and slows every clone/deploy."))

    top = {p for p in paths if "/" not in p}
    if not any(n.lower().startswith("readme") for n in top):
        out.append(finding("no-readme", "info", "docs", "No README", file="README.md",
                           detail="A README tells visitors (and future you) what this is and how to run it. "
                                  "Use “AI Builder → README” to generate one."))
    if not any(n.lower().startswith(("license", "licence")) for n in top):
        out.append(finding("no-license", "info", "docs", "No LICENSE file",
                           detail="Without a license, nobody else may legally use or contribute to your code."))

    for root, envs in envs_by_root.items():
        if not envs:
            continue
        has_example = any(_join(root, n) in paths for n in (".env.example", ".env.sample", ".env.template"))
        if not has_example:
            path = _join(root, ".env.example")
            content = "# Copy this file to .env and fill in the values\n" + "\n".join(f"{e['name']}=" for e in envs) + "\n"
            out.append(finding("no-env-example", "info", "docs", f"No .env.example ({len(envs)} environment variables used)",
                               file=path, extra=root, fix={"op": "create", "content": content},
                               detail="Documents which variables your app needs: " + ", ".join(e["name"] for e in envs[:10])))
    return out


# --------------------------------------------------------------- readiness
def readiness(app: dict, files: Dict[str, str], paths: List[str], findings: List[dict]) -> List[dict]:
    root = app["root"]
    prefix = root + "/" if root else ""
    scoped = [f for f in findings if (f.get("file") or "").startswith(prefix)] if root else findings
    items = []

    def item(i, label, ok, detail, level="required"):
        items.append({"id": i, "label": label, "ok": bool(ok), "detail": detail, "level": level})

    t = app["type"]
    if t == "python":
        item("deps", "Dependencies are declared (requirements.txt)", _join(root, "requirements.txt") in paths or _join(root, "pyproject.toml") in paths,
             "The host installs packages from requirements.txt.")
        item("deps-complete", "Every imported package is listed", not any(f["rule"] in ("py-missing-deps", "py-no-requirements") for f in scoped),
             "Missing packages crash the app at start-up.")
    if t == "node":
        item("deps-complete", "Every imported package is in package.json", not any(f["rule"] == "js-missing-deps" for f in scoped),
             "Missing packages crash the build/start.")
    if t in ("python", "node"):
        item("start", "A start command is known", bool(app.get("start_command")), app.get("start_command") or "Add a start script / entry file.")
        item("bind", "Listens on 0.0.0.0 and the PORT variable",
             not any(f["rule"] in ("py-localhost", "py-port", "js-localhost", "js-port") for f in scoped),
             "Hosts assign the port; binding to localhost makes the app unreachable.")
    item("secrets", "No secrets committed", not any(f["rule"].startswith(("secret-known", "env-committed", "key-committed")) for f in findings),
         "Leaked keys must be rotated.")
    item("gitignore", ".gitignore protects .env", not any(f["rule"] in ("no-gitignore", "gitignore-incomplete") for f in findings),
         "Prevents committing secrets by accident.", "recommended")
    has_health = any(re.search(r"""["']/health(z)?["']""", t_) for p, t_ in files.items() if p.startswith(prefix) and p.endswith(PY_EXT + JS_EXT))
    item("health", "Has a /health endpoint", has_health, "Lets Render/uptime monitors check that the app is alive.", "recommended")
    return items


# ------------------------------------------------------------------ scoring
def score(findings: List[dict]) -> int:
    pts, info_pts = 100, 0
    for f in findings:
        w = SEVERITY_WEIGHT.get(f["severity"], 0)
        if f["severity"] == "info":
            info_pts = min(10, info_pts + w)
        else:
            pts -= w
    return max(0, min(100, pts - info_pts))


def grade(s: int) -> str:
    return "A" if s >= 90 else "B" if s >= 75 else "C" if s >= 60 else "D" if s >= 40 else "F"


# ----------------------------------------------------------------- top level
def analyze(paths: List[str], files: Dict[str, str]) -> dict:
    apps = detect_apps(paths, files.get)
    findings: List[dict] = []
    findings += scan_secrets(files)
    for p, t in files.items():
        findings += scan_code_rules(p, t)
    findings += _python_dependency_findings(paths, files, apps)
    findings += _node_dependency_findings(paths, files, apps)
    findings += _gitignore_findings(paths, files, apps)
    envs_by_root = {a["root"]: env_vars_used(files, a["root"]) for a in apps if a["type"] in ("python", "node")}
    for a in apps:
        a["env_vars"] = envs_by_root.get(a["root"], [])
    findings += _repo_hygiene_findings(paths, files, apps, envs_by_root)

    seen, unique = set(), []
    for f in findings:
        if f["id"] not in seen:
            seen.add(f["id"])
            unique.append(f)
    order = {"critical": 0, "warning": 1, "info": 2}
    unique.sort(key=lambda f: (order.get(f["severity"], 3), f.get("file") or ""))

    for a in apps:
        a["readiness"] = readiness(a, files, paths, unique)
    s = score(unique)
    return {"apps": apps, "findings": unique, "score": s, "grade": grade(s)}


# ------------------------------------------- picking files for the AI review
_PRIORITY = [
    (r"(^|/)(main|app|server|index|api|wsgi|manage)\.(py|js|ts|mjs)$", 50),
    (r"(auth|login|session|token|oauth|security|middleware)", 40),
    (r"(routes?|router|views?|controllers?|handlers?)", 30),
    (r"(config|settings|database|db)\.(py|js|ts)$", 30),
    (r"(^|/)(package\.json|requirements\.txt|Dockerfile|render\.yaml|vercel\.json|Procfile|next\.config\.js)$", 25),
    (r"\.(py|js|ts|jsx|tsx)$", 5),
]


def pick_files_for_ai(files: Dict[str, str], limit: int = 12, per_file: int = 6000, budget: int = 45000) -> Dict[str, str]:
    scored = []
    for p, t in files.items():
        if _in_skipped(p) or DOC_OR_TEST.search(p) or re.search(r"\.(test|spec|min)\.", p):
            continue
        s = sum(w for rx, w in _PRIORITY if re.search(rx, p, re.I))
        if s:
            scored.append((s, -len(t), p))
    scored.sort(reverse=True)
    chosen, used = {}, 0
    for _, _, p in scored:
        if len(chosen) >= limit or used >= budget:
            break
        text = files[p][:per_file]
        chosen[p] = text
        used += len(text)
    return chosen

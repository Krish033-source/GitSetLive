"""Central configuration — everything comes from environment variables
(or backend/.env in development). Import this module instead of calling
os.getenv() all over the codebase."""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent.resolve()
load_dotenv(BASE_DIR / ".env")
load_dotenv()  # also honour a .env in the current working directory


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "") or default)
    except ValueError:
        return default


def _list(name: str, default: list) -> list:
    raw = os.getenv(name, "")
    items = [x.strip() for x in raw.split(",") if x.strip()]
    return items or default


# --------------------------------------------------------------- environment
ENV = os.getenv("ENV", "development").strip().lower()
IS_PROD = ENV in ("prod", "production")
APP_VERSION = "2.0.0"

# Where the SQLite DB, encryption key and own-server state live.
# On Render/Railway/Fly point this at a persistent disk (e.g. /data).
DATA_DIR = Path(os.getenv("DATA_DIR") or BASE_DIR).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = DATA_DIR / "app.db"

# ------------------------------------------------------------------ secrets
GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")

SECRET_KEY = os.getenv("SECRET_KEY", "")
if len(SECRET_KEY) < 16:
    raise RuntimeError(
        "SECRET_KEY is missing or too short (min 16 chars). Generate one with:\n"
        '  python -c "import secrets; print(secrets.token_urlsafe(48))"\n'
        "and put it in backend/.env as SECRET_KEY=<value>"
    )

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
# Groq retires models regularly (llama-3.3-70b-versatile / llama-3.1-8b-instant
# were shut down on 2026-08-16, qwen3-32b in July 2026). The list is a
# preference order and is filtered against Groq's live /models endpoint at
# runtime, so a retired model is skipped automatically. Override with GROQ_MODELS.
GROQ_MODELS = _list(
    "GROQ_MODELS",
    ["openai/gpt-oss-120b", "qwen/qwen3.6-27b", "openai/gpt-oss-20b"],
)

# ------------------------------------------------------------------ web / CORS
FRONTEND_URL = (os.getenv("FRONTEND_URL") or "http://localhost:3000").rstrip("/")
COOKIE_SECURE = FRONTEND_URL.startswith("https://")

_default_origins = [FRONTEND_URL]
if not IS_PROD:
    _default_origins += [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:3001",
        "http://127.0.0.1:3001",
    ]
ALLOWED_ORIGINS = sorted(
    set(_default_origins + [o.rstrip("/") for o in _list("ALLOWED_ORIGINS", [])])
)

SESSION_DAYS = _int("SESSION_DAYS", 14)

# --------------------------------------------------------------------- email
SMTP_EMAIL = os.getenv("SMTP_EMAIL", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = _int("SMTP_PORT", 587)

# ------------------------------------------------------- "Our Servers" engine
# Runs other people's code on this machine. Off by default in production —
# turn it on only on a VPS/container you are comfortable running user code on.
OWN_SERVER_ENABLED = _bool("OWN_SERVER_ENABLED", not IS_PROD)
OWN_SERVER_TTL_MINUTES = _int("OWN_SERVER_TTL_MINUTES", 120)
OWN_SERVER_MAX_PER_USER = _int("OWN_SERVER_MAX_PER_USER", 3)
OWN_SERVER_MAX_TOTAL = _int("OWN_SERVER_MAX_TOTAL", 20)
CLOUDFLARED_PATH = os.getenv("CLOUDFLARED_PATH", "")

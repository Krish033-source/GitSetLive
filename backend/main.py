"""GitSetLive API — FastAPI entry point.

Run locally:   python -m uvicorn main:app --reload --port 5000
Production:    uvicorn main:app --host 0.0.0.0 --port $PORT
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import ai
import config
import db
import github
import mailer
import own_server
from routers import ai_tools, auth, deploy, keys, repos, scan, workspaces

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("gitsetlive")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    own_server.init()
    deploy.register_hooks()
    if not (config.GITHUB_CLIENT_ID and config.GITHUB_CLIENT_SECRET):
        log.warning("GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET are not set — login will not work.")
    if not config.GROQ_API_KEY:
        log.warning("GROQ_API_KEY is not set — AI features are disabled.")
    log.info("GitSetLive %s started (env=%s, own_server=%s)", config.APP_VERSION, config.ENV, own_server.is_enabled())
    yield


app = FastAPI(
    title="GitSetLive API", version=config.APP_VERSION, lifespan=lifespan,
    docs_url=None if config.IS_PROD else "/docs", redoc_url=None,
    openapi_url=None if config.IS_PROD else "/openapi.json",
)

# Auth uses an Authorization header (not cookies), so credentials are not needed cross-origin.
app.add_middleware(
    CORSMiddleware, allow_origins=config.ALLOWED_ORIGINS, allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"], max_age=600,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cache-Control", "no-store")
    return response


# One error shape for the frontend: {"detail": {"message": str, "code": str}}
@app.exception_handler(github.GitHubAuthError)
async def _github_auth(_, exc: github.GitHubAuthError):
    return JSONResponse(status_code=401, content={"detail": {"message": exc.message, "code": "github_auth"}})


@app.exception_handler(github.GitHubError)
async def _github_error(_, exc: github.GitHubError):
    status = exc.status if 400 <= exc.status < 600 else 502
    return JSONResponse(status_code=status, content={"detail": {"message": exc.message, "code": "github_error"}})


@app.exception_handler(ai.AIError)
async def _ai_error(_, exc: ai.AIError):
    return JSONResponse(status_code=503, content={"detail": {"message": str(exc), "code": "ai_unavailable"}})


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception):
    log.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": {"message": "Something went wrong on our side.", "code": "server_error"}})


@app.get("/health")
def health():
    try:
        with db.db() as conn:
            conn.execute("SELECT 1")
        return {"status": "ok", "version": config.APP_VERSION}
    except Exception:  # noqa: BLE001
        return JSONResponse(status_code=503, content={"status": "db_unavailable"})


@app.get("/config")
def public_config():
    """Feature flags the frontend uses to hide things that can't work on this server."""
    return {
        "version": config.APP_VERSION,
        "own_server_enabled": own_server.is_enabled(),
        "ai_enabled": bool(config.GROQ_API_KEY),
        "email_enabled": mailer.enabled(),
        "login_configured": bool(config.GITHUB_CLIENT_ID and config.GITHUB_CLIENT_SECRET),
    }


for r in (auth.router, repos.router, scan.router, ai_tools.router, deploy.router, keys.router, workspaces.router):
    app.include_router(r)

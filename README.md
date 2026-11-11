# GitSetLive

**Scan it. Fix it. Ship it live.** An AI-assisted platform that scans your GitHub repositories for what would break in production, opens fix **pull requests**, answers questions about your code, and walks you through deploying to **Render**, **Vercel** or the built-in **Our Servers** engine.

> Everything the AI or an auto-fix changes goes to a **new branch + pull request** by default. Nothing reaches your main branch without you.

## What it does

| Tool | What you get |
|---|---|
| **Scan & Fix** | Deterministic checks (leaked secrets, localhost binding, hard-coded ports, debug mode, missing dependencies, missing `.gitignore`, committed `.env`/keys/databases…) **plus** an AI review whose findings are *verified against your real files* (hallucinated snippets are discarded). Health score 0-100, per-issue diff, pick what to fix, one pull request. |
| **GitBot** | Multi-turn chat about a repo. Answers only from your code and lists the files it used. |
| **AI Builder** | Describe a change, the AI edits your real files with exact search/replace edits, you review (and can edit) the diffs, then it becomes a pull request. |
| **File Templates** | README, `.env.example`, `.gitignore`, Dockerfile, CI workflow, `render.yaml`, LICENSE, generated from your actual code. |
| **Deploy** | Pre-flight checklist, auto-detected apps (monorepos supported), exact build/start values for Render/Vercel, deployment history. **Our Servers**: run an app on this machine with a temporary public link, live status, logs, encrypted env vars, auto-expiry. |
| **Saved Keys** | A small vault for API keys and tokens: encrypted at rest, list shows only the last 4 characters, a value is revealed only on request (rate-limited and logged), and can be dropped into a deployment's env variables. |
| **Workspaces** | Teams with enforced roles (admin / developer / viewer); invite by GitHub username or email. |

## Architecture

```
frontend/  Next.js (pages router), dark/light UI, no UI dependencies
backend/   FastAPI + SQLite
  main.py            app, CORS, security headers, error handling
  routers/           auth, repos, scan, ai_tools, deploy, workspaces
  analyzer.py        static analysis (no AI, no network), unit tested
  patching.py        safe search/replace fix engine (syntax-checked)
  github.py          GitHub client: tarball snapshots, atomic multi-file commits, PRs
  ai.py              Groq client with live model discovery
  own_server.py      "Our Servers" engine
  db.py, security.py, encryption.py, config.py
```

## Quick start (local)

Requirements: Python 3.11+ (3.12 recommended), Node 20+ (22 recommended).

1. **GitHub OAuth app**: https://github.com/settings/developers, *New OAuth App*.
   Homepage `http://localhost:3000`, **Authorization callback URL `http://localhost:5000/callback`**.
2. **Backend**
   ```bash
   cd backend
   python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   cp .env.example .env        # fill in GITHUB_CLIENT_ID/SECRET, SECRET_KEY, GROQ_API_KEY
   python -m uvicorn main:app --reload --port 5000
   ```
3. **Frontend**
   ```bash
   cd frontend
   npm install
   cp .env.example .env.local  # NEXT_PUBLIC_API=http://localhost:5000
   npm run dev
   ```
4. Open http://localhost:3000 and sign in with GitHub.

**Tests:** `cd backend && pip install -r requirements-dev.txt && python -m pytest` and `cd frontend && npm test`

## Configuration (backend/.env)

See [`backend/.env.example`](backend/.env.example) for every variable. The important ones:

| Variable | Purpose |
|---|---|
| `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` | GitHub OAuth app |
| `SECRET_KEY` | **Required.** Signs OAuth state and hashes session tokens |
| `ENCRYPTION_KEY` | Fernet key for GitHub tokens / env vars at rest. Set explicitly in production |
| `GROQ_API_KEY`, `GROQ_MODELS` | AI. Retired models are skipped automatically (see *Groq models*) |
| `FRONTEND_URL` | Post-login redirect target and allowed CORS origin |
| `DATA_DIR` | Where `app.db` lives. **Must be a persistent disk in production** |
| `ENV=production` | Disables API docs, turns "Our Servers" off by default |
| `OWN_SERVER_ENABLED` | Turn the deploy engine on/off (default: on in development, **off** in production) |

## Deploying GitSetLive itself

> **Full step-by-step guide with a checklist and troubleshooting: [DEPLOY.md](DEPLOY.md).** The summary below is the short version.

### Option A: Vercel (frontend) + Render (backend)
1. **Backend on Render**: *New, Blueprint*, pick this repo (uses [`render.yaml`](render.yaml)), or create a Web Service manually: root directory `backend`, build `pip install -r requirements.txt`, start `uvicorn main:app --host 0.0.0.0 --port $PORT`, health check `/health`.
   - Attach a **persistent disk** at `/data` and set `DATA_DIR=/data`. Without it SQLite is wiped on every deploy and everyone is logged out. Render disks need a paid instance type.
   - Set `ENV=production`, `FRONTEND_URL=<your vercel url>`, `GITHUB_CLIENT_ID/SECRET`, `GROQ_API_KEY`, `ENCRYPTION_KEY`, `SECRET_KEY`.
2. **Frontend on Vercel**: import the repo, **Root Directory = `frontend`**, add `NEXT_PUBLIC_API=<your render url>`.
3. **GitHub OAuth app**: callback URL `https://<your-render-host>/callback` (keep a second OAuth app for local development).
4. Open the Vercel URL and sign in. "Our Servers" shows as disabled here, by design.

### Option B: one VPS with Docker (enables "Our Servers")
```bash
cp backend/.env.example backend/.env      # fill in; FRONTEND_URL / ALLOWED_ORIGINS = your public https URLs
PUBLIC_API_URL=https://api.example.com docker compose up -d --build
```
Put Caddy or nginx in front for HTTPS, e.g. a `Caddyfile`:
```
app.example.com { reverse_proxy 127.0.0.1:3000 }
api.example.com { reverse_proxy 127.0.0.1:5000 }
```
> The Dockerfiles and compose file were **not built or run** while authoring this release. Try them on a throw-away server first.

## "Our Servers": read before enabling

This engine runs *other code* on your machine. v2 hardened it a lot (clean environment so none of your secrets are inherited, `npm install --ignore-scripts`, per-project virtualenv, safe tar extraction, per-user/global limits, automatic expiry, only repos the user owns or can push to), but **there is still no container/VM sandbox**: a deployed app runs as the same OS user and could read files on that machine, including `app.db`. Use it only on a dedicated, disposable VPS/container that holds nothing you can't lose, and keep it off on shared platforms.

## Security model

- **Sessions:** random opaque tokens (stored only as an HMAC hash), 14-day expiry, revocable (*Sign out* / *Sign out everywhere*), sent in the `Authorization` header, never in URLs. The token reaches the browser in a URL *fragment*.
- **OAuth:** signed `state` + HttpOnly cookie (CSRF-safe). `delete_repo` is requested only when someone actually deletes a repository.
- **At rest:** GitHub tokens, project env vars and Saved Keys are Fernet-encrypted; env var values are never returned by the API, and Saved Keys are returned only by an explicit reveal call. This is server-side encryption (not zero-knowledge): the server can decrypt.
- **AI:** repo contents are treated as untrusted data in prompts; AI-proposed edits are validated against the real files, syntax-checked (Python/JSON) and shown to the user before anything is committed. Fixes live server-side, so the client can't smuggle arbitrary file contents through the fix endpoint.
- **Abuse:** per-user rate limits on AI/scan/deploy endpoints (in-memory, per process).
- The session token is kept in `localStorage`: simple and works across Vercel/Render domains, but an XSS bug would expose it. The UI renders Markdown without HTML and never injects user content as HTML (the only `dangerouslySetInnerHTML` is a fixed one-line theme script in `_document.js`).
- Suppress a scanner finding on a line you've reviewed with a `# nosec` (or `gsl-ignore`) comment.

## Upgrading from v1

- **Back up `backend/app.db` first.** Startup migrates it automatically and idempotently: duplicate users created by the old login (one per login) are merged, duplicate default workspaces merged, plaintext GitHub tokens encrypted, `github_id` made unique.
- Everyone must **sign in once more** (sessions work differently). The login now also requests `user:email`, so GitHub shows its consent screen again.
- Your OAuth app, callback URL and `NEXT_PUBLIC_API` stay the same; `SECRET_KEY` and `ENCRYPTION_KEY` keep working. New optional variables: `DATA_DIR`, `ENV`, `GROQ_MODELS`, `OWN_SERVER_*`, `SESSION_DAYS`, `ALLOWED_ORIGINS`.
- `frontend/.env.local` is no longer tracked (use `frontend/.env.example`).
- API routes changed together with the rewritten frontend; anything still calling the old `?token=` endpoints must use `Authorization: Bearer`.

### Groq models
Groq retired `llama-3.3-70b-versatile` and `llama-3.1-8b-instant` on 2026-08-16 and deprecated `qwen/qwen3-32b` in July 2026. The default list is now `openai/gpt-oss-120b, qwen/qwen3.6-27b, openai/gpt-oss-20b`, filtered at runtime against Groq's `/models` endpoint. Override with `GROQ_MODELS` if Groq changes things again.

## API overview

Everything except `/health`, `/config`, `/login`, `/callback` needs `Authorization: Bearer <session>`. Errors look like `{"detail": {"message", "code"}}`. Interactive docs at `/docs` outside production.

| Area | Endpoints |
|---|---|
| Auth | `GET /login`, `GET /callback`, `GET /me`, `POST /logout`, `POST /logout-all` |
| Repos | `GET/POST /repos`, `POST /repos/{owner}/{name}/delete` |
| Scan | `GET /analyze`, `POST /scan`, `GET /scans`, `GET /scans/{id}`, `POST /scan/apply` |
| AI | `POST /ai/chat`, `POST /ai/propose`, `POST /ai/commit` |
| Keys | `GET/PUT /keys`, `POST /keys/{id}/reveal`, `DELETE /keys/{id}` |
| Deploy | `POST/GET /deploy/own`, `GET /deploy/own/{id}[/logs]`, `POST /deploy/own/{id}/stop`, `GET/PUT /env`, `GET/POST /deployments`, `PATCH/DELETE /deployments/{id}` |
| Misc | `GET /stats`, `GET /activity`, `GET /health`, `GET /config` |
| Workspaces | `GET/POST /workspaces`, `GET /workspaces/{id}/members`, `POST .../invite`, `PATCH/DELETE .../members/{user}`, `DELETE /workspaces/{id}` |

## Known limitations / next steps

- SQLite and in-memory rate limiting assume a **single backend process**. For several instances move to Postgres + Redis.
- Scans analyse up to ~600 text files / 8 MB and send ~45 KB of the most important files to the AI; very large monorepos are sampled.
- Auto-fixes are deliberately conservative (exact search/replace); complex problems are reported as "Manual".
- "Our Servers": Django and Docker-only repos unsupported; no container sandbox (see above).
- Not implemented: API-key based one-click Render/Vercel deploys (you get exact settings and a guided flow instead), Postgres, GitHub webhooks.

---

## 📄 License

All Rights Reserved.

Copyright © 2026 [Krishna Lal]. All rights reserved.

This source code is made available for viewing purposes only (e.g. for hackathon judging/review). No permission is granted to copy, modify, distribute, sublicense, sell, or use this software or any portion of it, in source or compiled form, for any purpose without prior written permission from the copyright holder.

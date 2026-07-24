# 🚀 GitSetLive

**AI-powered platform that scans your GitHub repo for bugs, auto-generates fix pull requests, and deploys it live — to Render, Vercel, or our own built-in server — in one click.**

Built for developers (and non-developers!) who want to go from "code on GitHub" to "live on the internet" without wrestling with deployment configs, dependency errors, or CI/CD setup.

---

## ✨ Features

### 🔍 AI Repo Scanner
Scans your repository's real code (not guesses) and reports concrete, verifiable issues — hardcoded secrets, missing dependencies, broken start commands, missing error handling, security gaps — each with a complete working fix, not generic advice.

### 🔧 Auto-Fix Pull Requests
Turns AI-found issues directly into a GitHub Pull Request: creates a branch, commits the fixes, opens the PR. You just review and merge.

### 🤖 GitBot
Ask natural-language questions about any of your repos ("what does this project do?", "where's the auth logic?") and get answers grounded in the actual repo contents.

### ✍️ AI Code & File Generation
Describe what you want in plain English, and GitSetLive generates complete, deployable code (or supporting files like `README.md`, `Dockerfile`, `.env.example`) and pushes it straight to your repo.

### 🚀 Three Ways to Deploy
| Option | Best for | How it works |
|---|---|---|
| **Render** | Backends, full-stack apps | Guided walkthrough of every field + one-click redirect into Render's own "New Web Service" flow |
| **Vercel** | Frontends, Next.js, static sites | Guided walkthrough + one-click redirect into Vercel's "New Project" import flow |
| **Our Servers** | Instant demos, no third-party account needed | Pulls your repo, auto-detects stack (static / Flask / Node), installs dependencies, runs it, and exposes it via a public Cloudflare Tunnel link |

### 👥 Workspaces
Create a team workspace, invite teammates by email (once they've signed in with GitHub at least once), assign roles (admin / developer / viewer).

### 📊 Dashboard
Live view of your repos, deployment history, recent activity feed, and quick access to every tool above — plus a built-in **"How to Use"** guide written for non-technical users.

### 🗑 Repo Management
Create or permanently delete GitHub repos directly from the dashboard.

---

## 🏗 Architecture

```
 Developer (Browser)
        │
        ▼
 Frontend — Next.js (React)
   Login · Dashboard · Deploy · Scan · GitBot · Upload
        │  REST API
        ▼
 Backend — FastAPI (Python)
   ┌───────────────┬───────────────┬──────────────────┐
   │ GitHub sync   │  AI engine    │  Deploy manager   │
   │ OAuth, repos, │  Groq-powered │  Render / Vercel  │
   │ pull requests │  bug scanning │  redirects +      │
   │               │               │  "Our Servers"    │
   └───────┬───────┴───────┬───────┴─────────┬─────────┘
           ▼               ▼                 ▼
     GitHub API       Groq API      Render / Vercel /
                                     built-in mini-PaaS
                                     (own_server.py)
                            │
                            ▼
                       SQLite DB
                (users, keys, deployments,
                 scans, activity, workspaces)
```

---

## 🧰 Tech Stack

| Layer | Technology |
|---|---|
| Frontend | Next.js (Pages Router), React |
| Backend | FastAPI (Python) |
| Database | SQLite |
| AI | Groq API (Llama 3.3/3.1, Qwen3, GPT-OSS — with automatic fallback across models) |
| Auth | GitHub OAuth |
| Token security | Fernet symmetric encryption (via `cryptography`) |
| Own-server deploy engine | Python `subprocess` + Cloudflare Quick Tunnels (`cloudflared`) |
| Email (workspace invites) | SMTP (Gmail-compatible) |

---

## 📁 Project Structure

```
GitSetLive/
├── backend/
│   ├── main.py                    # FastAPI app — all API endpoints
│   ├── own_server.py              # "Deploy to Our Servers" engine
│   ├── database.py                # SQLite schema + init
│   ├── encryption.py              # Fernet key management for stored secrets
│   ├── migrate_fix_apikeys.py     # One-time DB migration script
│   ├── requirements.txt
│   ├── .env                       # Your secrets (not committed)
│   ├── app.db                     # SQLite database (auto-created)
│   ├── own_server_projects/       # Deployed repo code (auto-created)
│   └── own_server_logs/           # Per-deployment logs (auto-created)
│
└── frontend/
    ├── package.json
    ├── .env.local                 # NEXT_PUBLIC_API=http://localhost:5000
    └── pages/
        ├── index.js               # Redirects to /login
        ├── login.js                # GitHub OAuth entry point
        ├── callback.js             # OAuth callback handler
        ├── dashboard.js            # Main dashboard
        ├── deploy.js                # Render / Vercel / Our Servers
        ├── scan.js                  # AI repo scanner + auto-PR
        ├── gitbot.js                # Repo Q&A
        ├── upload-code.js           # AI code generation → GitHub
        └── upload-file.js           # AI file generation → GitHub
```

---

## ⚙️ Setup

### Prerequisites
- Python 3.10+
- Node.js 18+
- A [GitHub OAuth App](https://github.com/settings/developers) (for login)
- A [Groq API key](https://console.groq.com/keys) (for AI features)
- *(Optional)* [`cloudflared`](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) installed and on your PATH — enables public live links for "Deploy to Our Servers"
- *(Optional)* Gmail account + [App Password](https://myaccount.google.com/apppasswords) — enables workspace invite emails

### 1. Backend

```bash
cd backend
pip install -r requirements.txt
```

Create `backend/.env`:

```env
GITHUB_CLIENT_ID=your_github_oauth_client_id
GITHUB_CLIENT_SECRET=your_github_oauth_client_secret
SECRET_KEY=any_random_long_string
FRONTEND_URL=http://localhost:3000
GROQ_API_KEY=your_groq_api_key

# Optional
ENCRYPTION_KEY=            # auto-generated & persisted to .encryption_key if left blank
SMTP_EMAIL=                # for workspace invite emails
SMTP_PASSWORD=
CLOUDFLARED_PATH=          # only needed if cloudflared isn't on your PATH
```

Your GitHub OAuth App's **Authorization callback URL** should be set to:
```
http://localhost:5000/callback
```

Initialize the database and start the server:

```bash
python database.py
python -m uvicorn main:app --reload --port 5000
```

### 2. Frontend

```bash
cd frontend
npm install
```

Create `frontend/.env.local`:

```env
NEXT_PUBLIC_API=http://localhost:5000
```

```bash
npm run dev
```

Visit **http://localhost:3000** — you'll be redirected to `/login`.

---

## 🔑 GitHub OAuth Scopes

GitSetLive requests the `repo` and `delete_repo` scopes so it can:
- Read/write your repositories (create files, branches, PRs)
- Delete a repository if you use the Delete Repo feature

If you've logged in before this feature was added, **log out and log back in** to re-grant the new scope — otherwise Delete Repo will fail with a 403.

---

## 🌐 API Overview

| Endpoint | Purpose |
|---|---|
| `GET /login`, `GET /callback` | GitHub OAuth flow |
| `GET /repos` | List the user's repos |
| `POST /create-repo`, `POST /delete-repo` | Repo management |
| `POST /generate`, `POST /upload` | AI code/file generation → GitHub |
| `POST /gitbot` | Repo Q&A |
| `POST /scan-repo`, `POST /apply-fix` | AI scan + auto-PR |
| `POST /deploy-own-server`, `GET /own-server-projects`, `POST /own-server-stop/{id}` | Built-in deploy engine |
| `GET /deployments/{user_id}`, `GET /activity/{user_id}` | Dashboard history |
| `POST /workspace`, `GET /workspaces/{user_id}`, `GET /workspace/{id}/members`, `POST /workspace/invite` | Team workspaces |

All endpoints that take a `user_id` also require the caller's `token`, and verify the token actually belongs to that `user_id` before returning any data.

---

## ⚠️ Known Limitations

- **"Our Servers" deploys are prototype-grade hosting** — no containerization/sandboxing, no per-project resource limits on Windows (POSIX systems get CPU/memory/process caps), no auto-scaling. Good for demos, not production traffic.
- **In-memory state resets** — if the backend restarts, "Our Servers" deployment tracking can go stale; use the dashboard's Stop button rather than killing terminals directly.
- **Binary files** (images, fonts, etc.) in a repo aren't downloaded correctly by the "Our Servers" engine — text-based projects only, for now.
- **Workspace invites** require the invitee to already have signed in to GitSetLive at least once (no pending/email-only invites yet).
- **AI-generated code** is reviewed by a second AI pass but isn't guaranteed bug-free — always read the diff before merging or deploying.

---

## 🗺 Roadmap Ideas

- Containerized (Docker) sandboxing for "Our Servers" deployments
- Named/persistent Cloudflare tunnels (stable URLs across restarts)
- Live log streaming in the dashboard
- Pending email invites for workspaces
- Per-project environment variable management UI

---

## 📄 License

Add your license of choice here.

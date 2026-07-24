from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import os, requests, base64, json
from dotenv import load_dotenv
from pydantic import BaseModel
import time
import uuid
import sqlite3
from datetime import datetime
import own_server
from cryptography.fernet import Fernet

load_dotenv()

# -------- Encryption --------
# Key must come from .env now — no more silent auto-generated
# .encryption_key file. If this isn't set, every previously encrypted
# Render/Vercel key + every signed login token becomes unreadable, so we
# fail loudly at startup instead of limping along with a random key.
ENCRYPTION_KEY = os.getenv("ENCRYPTION_KEY")
if not ENCRYPTION_KEY:
    raise ValueError(
        "ENCRYPTION_KEY missing in .env. Generate one with:\n"
        '  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"\n'
        "then add it to .env as ENCRYPTION_KEY=<the printed value>"
    )

cipher = Fernet(ENCRYPTION_KEY.encode())

def encrypt_key(api_key: str) -> str:
    """Encrypt API key"""
    return cipher.encrypt(api_key.encode()).decode()

def decrypt_key(encrypted_key: str):
    """Decrypt API key"""
    try:
        return cipher.decrypt(encrypted_key.encode()).decode()
    except Exception:
        return None

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
     "http://localhost:3000",
     "http://127.0.0.1:3000",
     "http://localhost:3001",
     "http://127.0.0.1:3001",
    ],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


CLIENT_ID = os.getenv("GITHUB_CLIENT_ID")
CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET")

#check
SECRET = os.getenv("SECRET_KEY")
if not SECRET:
    raise ValueError("SECRET_KEY missing in .env")


class _TokenBox:
    """Drop-in replacement for itsdangerous.URLSafeSerializer with the same
    .dumps()/.loads() call shape used everywhere below, so no call site or
    frontend request needs to change.

    itsdangerous only *signs* — the payload is plain base64 and anyone who
    gets hold of the string (browser devtools, logs, a referrer header, a
    copy-pasted bug report) can decode it and read the raw GitHub token
    with no key at all. That token has repo write access, so this matters.

    This wraps the same Fernet-based encrypt_key/decrypt_key helper already
    used to store Render/Vercel keys, so the token is actually unreadable
    without SECRET_KEY, not just tamper-evident.
    """

    def dumps(self, value: str) -> str:
        return encrypt_key(value)

    def loads(self, value: str) -> str:
        decrypted = decrypt_key(value)
        if decrypted is None:
            raise ValueError("invalid or corrupt token")
        return decrypted


s = _TokenBox()

GITHUB_API = "https://api.github.com"

import re

def clean_code(text):
    if not text:
        return ""
    text = text.strip()
    # strip an opening fence with ANY language tag (```python, ```javascript, ```js, etc.)
    text = re.sub(r"^```[a-zA-Z0-9_+-]*\s*\n?", "", text)
    # strip a trailing closing fence
    text = re.sub(r"\n?```\s*$", "", text)
    return text.strip()

from fastapi.responses import RedirectResponse
import os, requests

from urllib.parse import urlencode

from fastapi.responses import JSONResponse

@app.get("/login")
def login():
    github_url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={CLIENT_ID}&scope=repo,delete_repo"
    )
    
    return JSONResponse({
        "url": github_url
    })

#  CALLBACK ENDPOINT
@app.get("/callback")
def callback(code: str):
    """Handle GitHub OAuth callback"""
    try:
        # Exchange code for token
        r = requests.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            json={
                "client_id": os.getenv("GITHUB_CLIENT_ID"),
                "client_secret": os.getenv("GITHUB_CLIENT_SECRET"),
                "code": code
            }
        )

        data = r.json()
        token = data.get("access_token")

        if not token:
            return RedirectResponse(
                url=f"{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/login?error=OAuth failed"
            )

        # ✅ Get user info from GitHub
        user_info = requests.get(
            "https://api.github.com/user",
            headers={"Authorization": f"token {token}"}
        ).json()

        github_id = user_info.get("id")
        username = user_info.get("login")
        
        # ✅ If email not in user info, fetch from GitHub emails endpoint
        email = user_info.get("email")
        if not email:
            emails_res = requests.get(
                "https://api.github.com/user/emails",
                headers={"Authorization": f"token {token}"}
            ).json()
            
            if emails_res and isinstance(emails_res, list):
                # Get primary email
                primary = [e for e in emails_res if e.get("primary")]
                email = primary[0].get("email") if primary else emails_res[0].get("email")

        if not email:
            email = f"{username}@github.local"  # Fallback

        print(f"✅ GitHub user: {username}, Email: {email}")

        # Create or get user in DB
        user_result = create_user(github_id, username, email, token)

        # Sign token
        signed = s.dumps(token)

        # Redirect to frontend callback
        return RedirectResponse(
            url=f"{os.getenv('FRONTEND_URL', 'http://localhost:3000')}/callback?token={signed}"
        )

    except Exception as e:
        print(f"❌ OAuth error: {e}")
        return RedirectResponse(
            url=f"{os.getenv('FRONTEND_URL')}/login?error=Auth error"
        )

# -------- Helpers --------
def gh(token):
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

def verify_owner(token: str, user_id: str) -> bool:
    """Confirm the caller's own signed token actually belongs to user_id.

    A bunch of endpoints (deployment history, activity log, workspaces,
    stored Render/Vercel keys, own-server projects) used to accept a bare
    user_id with nothing proving the caller IS that user — anyone who saw
    a user_id anywhere (it shows up in plenty of API responses) could pull
    another user's data, including their decrypted hosting API keys. Every
    one of those endpoints now requires the same signed `token` the
    frontend already stores from login, and this checks it resolves to
    the same user_id being requested.
    """
    if not token or not user_id:
        return False
    try:
        github_token = s.loads(token)
    except Exception:
        return False

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE github_token = ?", (github_token,))
    row = c.fetchone()
    conn.close()

    return bool(row) and row["id"] == user_id


# Add this helper function
def save_deployment(user_id: str, owner: str, repo: str, service_id: str, workspace_id: str = None):
    """Save deployment to history"""
    conn = get_db()
    c = conn.cursor()
    
    deploy_id = f"dep_{uuid.uuid4().hex[:12]}"
    
    c.execute('''INSERT INTO deployments (id, user_id, workspace_id, repo_name, repo_url, service_id, status, created_at, updated_at)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
              (deploy_id, user_id, workspace_id, repo, f"https://github.com/{owner}/{repo}", 
               service_id, "deploying", datetime.now(), datetime.now()))
    
    conn.commit()
    conn.close()
    
    log_activity(user_id, "deployment_started", {
        "repo": repo, 
        "service_id": service_id
    }, workspace_id)
    
    return deploy_id

# -------- Models --------


class ScanRequest(BaseModel):
    token: str
    owner: str
    repo: str

class ApplyFixRequest(BaseModel):
    token: str
    owner: str
    repo: str
    fixes: list
class RepoCreate(BaseModel):
    token: str
    name: str

class RepoDelete(BaseModel):
    token: str
    owner: str
    name: str

class GenerateRequest(BaseModel):
    token: str
    owner: str
    repo: str
    prompt: str

class UploadRequest(BaseModel):
    token: str
    owner: str
    repo: str
    path: str
    content: str

class GitBotRequest(BaseModel):
    token: str
    owner: str
    repo: str
    question: str

class OwnServerDeployRequest(BaseModel):
    token: str
    owner: str
    repo: str
    user_id: str

class OwnServerStopRequest(BaseModel):
    user_id: str
    token: str

@app.get("/repos")
def repos(token: str):
    try:
        token = s.loads(token)

        res = requests.get(
            f"{GITHUB_API}/user/repos",
            headers=gh(token)
        )

        data = res.json()

        if isinstance(data, list):
            return data

        return []

    except Exception as e:
        print("REPOS ERROR:", e)
        return []

@app.post("/create-repo")
def create_repo(data: RepoCreate):
    token = s.loads(data.token)

    url = "https://api.github.com/user/repos"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"   # 🔥 IMPORTANT
    }

    payload = {
        "name": data.name,
        "private": False
    }

    r = requests.post(url, headers=headers, json=payload)

    print("STATUS:", r.status_code)
    print("RESPONSE:", r.text)

    if r.status_code == 201:
        return {"success": True}

    return {"success": False, "error": r.text}


@app.post("/delete-repo")
def delete_repo(data: RepoDelete):
    try:
        token = s.loads(data.token)
    except Exception:
        return {"error": "Invalid or expired token"}

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    r = requests.delete(
        f"{GITHUB_API}/repos/{data.owner}/{data.name}",
        headers=headers
    )

    print("DELETE STATUS:", r.status_code)

    if r.status_code == 204:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT id FROM users WHERE github_token = ?", (token,))
        user_result = c.fetchone()
        conn.close()
        if user_result:
            log_activity(user_result["id"], "repo_deleted", {"repo": data.name})
        return {"success": True}

    if r.status_code == 403:
        return {
            "success": False,
            "error": "GitHub denied this — your login session may not have delete permission yet. "
                     "Please log out and log back in (to re-grant access), then try again."
        }

    if r.status_code == 404:
        return {"success": False, "error": "Repository not found (check the name, or you may not own it)"}

    return {"success": False, "error": r.text}

# -------- AI --------
MODELS = [
    "llama-3.3-70b-versatile",   # best
    "llama-3.1-8b-instant",      # fast fallback
    "qwen/qwen3-32b",            # alternative
    "openai/gpt-oss-20b"         # last fallback
]

def ai(prompt):
    for model in MODELS:
        try:
            print(f"Trying model: {model}")

            r = requests.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {os.getenv('GROQ_API_KEY')}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are a senior software engineer."},
                        {"role": "user", "content": prompt}
                    ]
                },
                timeout=20
            )

            data = r.json()
            print("Response:", data)

            # ✅ success case
            if "choices" in data:
                print(f"✅ Success with {model}")
                return data["choices"][0]["message"]["content"]

            # ❌ known errors → try next
            if "error" in data:
                print(f"❌ Failed {model}: {data['error']}")
                continue

        except Exception as e:
            print(f"❌ Exception with {model}: {str(e)}")
            continue

    # every model in MODELS failed (or raised) — this used to be reachable
    # only sometimes because it was indented inside the for-loop, so the
    # function could silently return None here instead, which crashed
    # every caller that tried to call .replace()/.strip() on the result.
    return "❌ All AI models failed. Try again later."

def get_user_info(token):
    return requests.get(
        f"{GITHUB_API}/user",
        headers=gh(token)
    ).json()


# -------- Generate --------
@app.post("/generate")
def generate(data: GenerateRequest):
    token_raw = s.loads(data.token)

    # Get complete repo tree
    tree = get_repo_tree(token_raw, data.owner, data.repo)

    important_files = []

    for f in tree:
        if f["type"] != "blob":
            continue

        path = f["path"].lower()

        if any(x in path for x in [
            "main.py",
            "app.py",
            "package.json",
            "requirements.txt",
            "dockerfile",
            "render.yaml",
            ".env.example",
            "server.js",
            "index.js",
            "manage.py",
            "readme"
        ]):
            important_files.append(f["path"])

    # Fallback: first 10 files
    if not important_files:
        important_files = [
            f["path"]
            for f in tree
            if f["type"] == "blob"
        ][:10]

    context = ""

    for path in important_files:
        try:
            content = get_file_content(
                token_raw,
                data.owner,
                data.repo,
                path
            )

            context += f"\n\n===== {path} =====\n"
            context += content[:3000]

        except Exception:
            pass

    gen = ai(f"""
You are a code generator for a single-file deployment system (GitSetLive's
"Upload Code" feature). Whatever you generate will be pushed to exactly ONE
file at one path in the repo — there is no mechanism to create additional
files (no separate templates/, static/, or extra .html/.css/.js files).

HARD RULES — the code will break if you violate these:
1. Everything must live in ONE single file, fully self-contained and ready
   to run/deploy as-is, with no other files referenced.
2. If the project is Flask (or any Python web framework): do NOT use
   render_template() or render_template_string() pointing at external
   files, and do NOT reference static/ or templates/ folders. Instead,
   embed any HTML directly as Python strings inside app.py (e.g. return
   an HTML string directly from the route, with <style> and <script>
   tags inline in that same string for any CSS/JS). Do not use Flask's
   `session` with an external SECRET_KEY file — hardcode a placeholder
   value with a comment telling the user to change it.
3. If the project is Node.js: do NOT require() or serve separate .html/
   .css/.js files from disk. Embed the full HTML (with inline <style>
   and <script>) as a template string directly inside the single .js
   file and send it as the response body.
4. If the project is a static site: output ONE .html file with <style>
   and <script> tags inline — no external .css or .js files.
5. Include a requirements.txt / package.json equivalent as a comment
   at the top of the file listing exactly what needs to be installed,
   since this system does not auto-generate a separate dependency file
   for this feature.
6. The result must run immediately after being uploaded and started —
   no missing imports, no references to files that don't exist.

Repository context:

{context}

User Request:

{data.prompt}

Generate complete, production-ready, single-file code following the rules above.
""")

    gen = clean_code(gen)

    review = ai(f"""
Review the following code. It MUST remain a single, self-contained file —
if it references any external template, static, or asset files, rewrite it
so everything (HTML/CSS/JS included) lives inline in this one file instead.
Fix any other bugs you find.

Return ONLY code.

{gen}
""")

    review = clean_code(review)

    return {
        "initial": gen,
        "final": review
    }

# -------- Upload --------
@app.post("/upload")
def upload(data: UploadRequest):
    token = s.loads(data.token)
    
    content_lower = data.content.lower()
    
    # Check for common issues
    issues = []
    
    # Python checks
    if data.path.endswith('.py'):
        if 'http.server' in content_lower and 'HTTPServer' in data.content:
            issues.append("⚠️ Using http.server - Not recommended for Render. Use FastAPI instead.")
        if 'localhost' in content_lower:
            issues.append("⚠️ Hardcoded 'localhost' found - Change to '0.0.0.0'")
        if 'port 8080' in content_lower or "'8080'" in data.content:
            issues.append("⚠️ Hardcoded port 8080 - Use PORT env variable or 10000")
    
    # Node checks
    if data.path.endswith('.js') or data.path == 'server.js':
        if 'http.createServer' in data.content and 'express' not in content_lower:
            issues.append("⚠️ Using raw http - Use Express.js instead")
        if "'localhost'" in data.content or '"localhost"' in data.content:
            issues.append("⚠️ Hardcoded localhost - Use 0.0.0.0")
    
    # If issues found, return them
    if issues:
        return {
            "warning": "Code may not deploy on Render",
            "issues": issues,
            "message": "Fix these issues and try again, or override to upload anyway"
        }

    encoded = base64.b64encode(data.content.encode()).decode()

    payload = {
        "message": "upload via urrepoai",
        "content": encoded
    }

    return requests.put(
        f"{GITHUB_API}/repos/{data.owner}/{data.repo}/contents/{data.path}",
        json=payload,
        headers=gh(token)
    ).json()

# -------- GitBot --------
@app.post("/gitbot")
def gitbot(data: GitBotRequest):
    token = s.loads(data.token)

    # 🔹 user info
    user = get_user_info(token)

    # 🔹 ALL repos (important)
    all_repos = get_all_repos(token)

    # 🔹 selected repo info
    repo_info = get_repo_info(token, data.owner, data.repo)

    # 🔹 files list (GitHub API returns objects like {name, path, type, ...})
    raw_files = get_repo_files(token, data.owner, data.repo)
    file_paths = [f.get("path") or f.get("name") for f in raw_files if isinstance(f, dict)]
    file_paths = [f for f in file_paths if f]

    # 🔹 important files
    important_files = [f for f in file_paths if any(x in f.lower() for x in [
        "readme", "requirements", "dockerfile", "package.json"
    ])][:3]

    contents = ""
    for f in important_files:
        contents += f"\n--- {f} ---\n"
        contents += get_file_content(token, data.owner, data.repo, f)

   
    context = f"""
USER INFO:
- Username: {user.get('login')}
- Bio: {user.get('bio')}

ALL REPOSITORIES:
{", ".join(all_repos)}

CURRENT REPOSITORY:
- Name: {repo_info.get('name')}
- Owner: {repo_info.get('owner', {}).get('login')}
- Description: {repo_info.get('description')}

FILES IN CURRENT REPO:
{chr(10).join(file_paths[:20])}

IMPORTANT FILE CONTENTS:
{contents}
"""

    # 🔥 STRONG PROMPT
    ans = ai(f"""
You are GitBot, an expert GitHub assistant.

STRICT RULES:
- Answer ONLY using the provided context
- DO NOT make assumptions
- DO NOT hallucinate missing data
- If something is not in context, say: "Not found in repository data"
- If user asks about repositories, ALWAYS refer to "ALL REPOSITORIES"

BEHAVIOR:
- Be precise
- Be technical when needed
- Be concise

CONTEXT:
{context}

USER QUESTION:
{data.question}

FINAL ANSWER:
""")

    return {"answer": ans}


def get_repo_info(token, owner, repo):
    return requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}",
        headers=gh(token)
    ).json()

def get_repo_files(token, owner, repo):
    res = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/contents",
        headers=gh(token)
    ).json()

    return res if isinstance(res, list) else []

def get_file_content(token, owner, repo, path, max_chars=800):
    r = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/contents/{path}",
        headers=gh(token)
    ).json()

    if "content" in r:
        try:
            return base64.b64decode(r["content"]).decode(errors="ignore")[:max_chars]
        except:
            return ""
    return ""
    return ""

def get_all_repos(token):
    res = requests.get(
        f"{GITHUB_API}/user/repos",
        headers=gh(token)
    ).json()

    if not isinstance(res, list):
        return []

    return [r["name"] for r in res if isinstance(r, dict) and "name" in r][:20]

@app.post("/scan-repo")
def scan_repo(data: ScanRequest):
    """Improved AI scanning - Real fixes, not bullshit"""
    token = s.loads(data.token)

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE github_token = ?", (token,))
    user_result = c.fetchone()
    conn.close()
    real_user_id = user_result["id"] if user_result else None

    files = get_repo_tree(token, data.owner, data.repo)
    file_paths = [f["path"] for f in files]
    
    # Smart file selection
    important_files = []
    
    patterns = {
        "security": ["config.py", "settings.py", ".env", "secrets", "keys"],
        "performance": ["requirements.txt", "package.json", "docker", "index.js"],
        "errors": ["error", "exception", "handler"],
        "structure": ["__init__.py", "app.py", "main.py", "server.js", "index.js"],
        "deployment": ["procfile", "dockerfile", "render.yaml", "vercel.json"]
    }
    
    for f in file_paths:
        f_lower = f.lower()
        for category, keywords in patterns.items():
            if any(kw in f_lower for kw in keywords):
                important_files.append(f)
                break
    
    important_files = list(dict.fromkeys(important_files))[:10]
    
    # Collect file contents — give the model real context instead of a
    # near-useless 800-char snippet (that limit still applies to GitBot,
    # which only needs a peek, but a scan needs to actually read the code)
    contents = ""
    for f in important_files:
        try:
            content = get_file_content(token, data.owner, data.repo, f, max_chars=4000)
            contents += f"\n\n=== FILE: {f} ===\n{content}\n"
        except Exception as e:
            print(f"⚠️ Could not read {f} for scan: {e}")
            continue
    
    # IMPROVED AI PROMPT - Real analysis
    result = ai(f"""
You are a senior software engineer doing CODE REVIEW for production deployment.

TASK: Find REAL, CRITICAL issues that will cause deployment to FAIL or the app to
misbehave in production. Base every issue on the ACTUAL file contents given below —
never invent a problem you can't point to in the code.

CRITICAL FOCUS AREAS:
1. Hardcoded values (localhost, fixed ports, API keys, secrets committed in code)
2. Missing dependencies (imports without a matching entry in requirements.txt/package.json)
3. Framework mismatches (e.g. render.yaml/Procfile pointing at a start command or
   entrypoint that doesn't exist or doesn't match the actual code)
4. Port/host binding issues (not reading $PORT, binding to 127.0.0.1 instead of 0.0.0.0
   where a public deploy needs it)
5. Missing or overly broad error handling (bare except, unhandled exceptions on
   the main request path)
6. Environment variable issues (used but never documented/set, no fallback, crashes if missing)
7. Async/await problems (blocking calls inside async functions, missing awaits)
8. Database connection issues (no error handling, connection leaks, missing indexes/constraints)
9. Security issues (SQL built via string concatenation, missing auth checks on
   sensitive endpoints, secrets logged in plaintext)

RULES:
- Only report issues that are actually present in the file contents below — quote
  the relevant snippet in "line_context" so it's verifiable.
- For each issue, provide a COMPLETE working fix, not generic advice.
- Prioritize the most deployment-breaking issues first.
- Return JSON array with 3-6 REAL issues max. If the code is genuinely clean,
  return fewer issues rather than inventing filler ones.

Return ONLY JSON (no markdown):
[
  {{
    "severity": "critical|warning",
    "category": "framework|dependencies|config|security|error-handling|performance",
    "issue": "Exact problem description",
    "file": "filename.ext",
    "line_context": "the actual problematic code snippet from the file",
    "fix": "COMPLETE working solution to replace with"
  }}
]

Repository files:
{chr(10).join(file_paths[:30])}

File contents:
{contents}
""")
    
    try:
        cleaned = result.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("```")[1]
            if cleaned.startswith("json"):
                cleaned = cleaned[4:]
        
        issues = json.loads(cleaned)
        
        # Store scan result
        conn = get_db()
        c = conn.cursor()
        scan_id = f"scan_{uuid.uuid4().hex[:12]}"
        
        c.execute('''INSERT INTO scan_results (id, user_id, repo_name, scan_type, issues, created_at)
                     VALUES (?, ?, ?, ?, ?, ?)''',
                  (scan_id, real_user_id, data.repo, "initial", json.dumps(issues), datetime.now()))
        
        conn.commit()
        conn.close()

        if real_user_id:
            log_activity(real_user_id, "scan", {"repo": data.repo, "scan_id": scan_id, "issue_count": len(issues)})
        
        return {"fixes": issues, "scan_id": scan_id}
    except Exception as e:
        print("❌ SCAN PARSE ERROR:", str(e))
        print("❌ RAW AI RESPONSE WAS:", result[:1000] if result else "(empty)")
        return {"fixes": [], "error": "Scan failed — AI response could not be parsed. Check server logs for details."}

@app.post("/apply-fix")
def apply_fix(data: ApplyFixRequest):
    try:
        token = s.loads(data.token)
    except Exception:
        return {"error": "Invalid or expired token"}

    if not data.fixes:
        return {"error": "No fixes to apply"}

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE github_token = ?", (token,))
    user_result = c.fetchone()
    conn.close()
    real_user_id = user_result["id"] if user_result else None

    try:
        # 🔹 get default branch
        repo_data = requests.get(
            f"{GITHUB_API}/repos/{data.owner}/{data.repo}",
            headers=gh(token)
        ).json()

        if "default_branch" not in repo_data:
            return {"error": f"Could not read repo (check owner/repo name and access): {repo_data.get('message', 'unknown error')}"}

        base_branch = repo_data.get("default_branch", "main")

        # 🔹 get latest commit SHA
        ref = requests.get(
            f"{GITHUB_API}/repos/{data.owner}/{data.repo}/git/ref/heads/{base_branch}",
            headers=gh(token)
        ).json()

        if "object" not in ref:
            return {"error": f"Could not read base branch '{base_branch}': {ref.get('message', 'unknown error')}"}

        base_sha = ref["object"]["sha"]

        # 🔹 create new branch
        branch_name = f"ai-fix-{int(time.time())}"

        branch_res = requests.post(
            f"{GITHUB_API}/repos/{data.owner}/{data.repo}/git/refs",
            headers=gh(token),
            json={
                "ref": f"refs/heads/{branch_name}",
                "sha": base_sha
            }
        )

        if branch_res.status_code not in (200, 201):
            return {"error": f"Could not create branch: {branch_res.json().get('message', branch_res.text)}"}

        # 🔹 apply fixes
        applied = 0
        skipped = []
        path = None
        for fix in data.fixes:
            try:
                path = fix.get("file")
                content = fix.get("fix")

                if not path or not content:
                    continue

                # 🔥 invalid path check — reject actual path traversal / absolute
                # paths, but don't reject legitimate dotted directory names
                # (e.g. "config.d/settings.py" or ".github/workflows/x.yml")
                if ".." in path or path.startswith("/") or path.startswith("\\"):
                    print("⚠️ Skipping unsafe path:", path)
                    skipped.append(path)
                    continue

                encoded = base64.b64encode(content.encode()).decode()

                # 🔹 check existing file
                old = requests.get(
                    f"{GITHUB_API}/repos/{data.owner}/{data.repo}/contents/{path}",
                    headers=gh(token)
                ).json()

                file_sha = None
                if isinstance(old, dict):
                    file_sha = old.get("sha")

                payload = {
                    "message": f"AI fix: {path}",
                    "content": encoded,
                    "branch": branch_name
                }

                if file_sha:
                    payload["sha"] = file_sha

                res = requests.put(
                    f"{GITHUB_API}/repos/{data.owner}/{data.repo}/contents/{path}",
                    headers=gh(token),
                    json=payload
                )

                print("UPLOAD:", path, res.status_code)
                if res.status_code in (200, 201):
                    applied += 1
                else:
                    skipped.append(path)

            except Exception as e:
                print("❌ Error fixing file:", path, e)
                if path:
                    skipped.append(path)

        if applied == 0:
            return {"error": "None of the fixes could be applied (see server logs for per-file errors)", "skipped": skipped}

        # 🔹 create PR
        pr_res = requests.post(
            f"{GITHUB_API}/repos/{data.owner}/{data.repo}/pulls",
            headers=gh(token),
            json={
                "title": "AI Fixes",
                "head": branch_name,
                "base": base_branch,
                "body": "Automated fixes by AI"
            }
        )
        pr = pr_res.json()

        if not pr.get("html_url"):
            return {"error": f"Branch '{branch_name}' was created with {applied} fix(es), but PR creation failed: {pr.get('message', 'unknown error')}"}

        if real_user_id:
            log_activity(real_user_id, "fix_applied", {
                "repo": data.repo, "pr_url": pr["html_url"], "files_fixed": applied
            })

        return {"pr_url": pr["html_url"], "files_fixed": applied, "skipped": skipped}

    except Exception as e:
        print("❌ APPLY FIX ERROR:", str(e))
        return {"error": f"Unexpected error while applying fixes: {str(e)}"}


def get_repo_tree(token, owner, repo):
    # get default branch
    repo_data = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}",
        headers=gh(token)
    ).json()

    branch = repo_data.get("default_branch", "main")

    res = requests.get(
        f"{GITHUB_API}/repos/{owner}/{repo}/git/trees/{branch}?recursive=1",
        headers=gh(token)
    ).json()

    return res.get("tree", [])

@app.post("/deploy-own-server")
def deploy_own_server(data: OwnServerDeployRequest):
    """Deploy a GitHub repo directly on this machine (mini-PaaS), and expose
    it publicly via a cloudflared quick tunnel if available."""
    try:
        try:
            github_token = s.loads(data.token)
        except Exception:
            return {"error": "Invalid or expired token"}

        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT id FROM users WHERE github_token = ?", (github_token,))
        user_result = c.fetchone()
        conn.close()

        if not user_result:
            return {"error": "User not found. Please login again."}

        real_user_id = user_result["id"]

        project_id, info = own_server.deploy_repo(
            github_token, data.owner, data.repo, real_user_id
        )

        log_activity(real_user_id, "own_server_deploy", {
            "repo": data.repo, "project_id": project_id, "type": info["type"]
        })

        return {
            "success": True,
            "project_id": project_id,
            "type": info["type"],
            "entry": info["entry"],
            "local_url": f"http://localhost:{info['port']}",
            "live_url": info.get("tunnel_url"),
            "note": info.get("tunnel_note")
        }

    except Exception as e:
        print("❌ OWN SERVER DEPLOY ERROR:", str(e))
        return {"error": str(e)}


@app.get("/own-server-projects")
def own_server_projects(user_id: str, token: str):
    if not verify_owner(token, user_id):
        return {"error": "Not authorized to view these projects"}
    try:
        return own_server.list_projects_for_user(user_id)
    except Exception as e:
        return {"error": str(e)}


@app.post("/own-server-stop/{project_id}")
def own_server_stop(project_id: str, data: OwnServerStopRequest):
    if not verify_owner(data.token, data.user_id):
        return {"error": "Not authorized to stop this project"}
    try:
        own_server.stop_project(project_id, data.user_id)
        return {"stopped": project_id}
    except KeyError:
        return {"error": "No such project"}
    except PermissionError:
        return {"error": "You don't own this deployment"}
    except Exception as e:
        return {"error": str(e)}


class WorkspaceCreate(BaseModel):
    name: str
    user_id: str
    token: str

def get_db():
    conn = sqlite3.connect("app.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist yet. Safe to call every startup —
    every statement is IF NOT EXISTS, so this never touches an existing DB."""
    conn = get_db()
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        github_id TEXT,
        username TEXT,
        email TEXT,
        github_token TEXT,
        created_at TIMESTAMP,
        updated_at TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS workspaces (
        id TEXT PRIMARY KEY,
        name TEXT,
        owner_id TEXT,
        created_at TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS workspace_members (
        id TEXT PRIMARY KEY,
        workspace_id TEXT,
        user_id TEXT,
        role TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS deployments (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        workspace_id TEXT,
        repo_name TEXT,
        repo_url TEXT,
        service_id TEXT,
        status TEXT,
        live_url TEXT,
        created_at TIMESTAMP,
        updated_at TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS activity_logs (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        workspace_id TEXT,
        action TEXT,
        details TEXT,
        created_at TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS api_keys (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        platform TEXT,
        encrypted_key TEXT,
        platform_account_name TEXT,
        created_at TIMESTAMP,
        UNIQUE(user_id, platform)
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS scan_results (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        repo_name TEXT,
        scan_type TEXT,
        issues TEXT,
        created_at TIMESTAMP
    )''')

    conn.commit()
    conn.close()


def _migrate_fix_apikeys():
    """Self-healing migration (was the standalone migrate_fix_apikeys.py
    script). Makes sure api_keys has UNIQUE(user_id, platform), which
    store_render_key/store_vercel_key rely on for ON CONFLICT to work.
    Runs on every startup, no-ops instantly if already fixed — safe to
    leave in permanently, no need to run anything by hand anymore."""
    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='api_keys'")
    row = c.fetchone()
    if not row or "UNIQUE" in row[0].upper():
        conn.close()
        return  # doesn't exist yet (init_db will create it correctly) or already fixed

    print("⚠️  Migrating api_keys table to add UNIQUE(user_id, platform)...")

    c.execute("ALTER TABLE api_keys RENAME TO api_keys_old")
    c.execute('''CREATE TABLE api_keys (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        platform TEXT,
        encrypted_key TEXT,
        platform_account_name TEXT,
        created_at TIMESTAMP,
        UNIQUE(user_id, platform)
    )''')

    # Copy old data over, de-duplicating by (user_id, platform) — keep latest
    c.execute('''
        INSERT OR IGNORE INTO api_keys (id, user_id, platform, encrypted_key, platform_account_name, created_at)
        SELECT
            COALESCE(id, lower(hex(randomblob(8)))),
            user_id, platform, encrypted_key, platform_account_name, created_at
        FROM api_keys_old
        GROUP BY user_id, platform
        HAVING created_at = MAX(created_at)
    ''')

    c.execute("DROP TABLE api_keys_old")
    conn.commit()
    conn.close()
    print("✅ api_keys migration complete.")


@app.on_event("startup")
def _on_startup():
    init_db()
    _migrate_fix_apikeys()

def create_user(github_id, username, email, github_token):
    """Create user after OAuth"""
    conn = get_db()
    c = conn.cursor()
    
    user_id = f"user_{uuid.uuid4().hex[:12]}"
    
    try:
        c.execute('''INSERT INTO users (id, github_id, username, email, github_token, created_at, updated_at)
                     VALUES (?, ?, ?, ?, ?, ?, ?)''',
                  (user_id, github_id, username, email, github_token, datetime.now(), datetime.now()))
        
        # Create default workspace for user
        workspace_id = f"ws_{uuid.uuid4().hex[:12]}"
        c.execute('''INSERT INTO workspaces (id, name, owner_id, created_at)
                     VALUES (?, ?, ?, ?)''',
                  (workspace_id, f"{username}'s Workspace", user_id, datetime.now()))
        
        # Add user as admin to their workspace
        c.execute('''INSERT INTO workspace_members (id, workspace_id, user_id, role)
                     VALUES (?, ?, ?, ?)''',
                  (f"wm_{uuid.uuid4().hex[:12]}", workspace_id, user_id, "admin"))
        
        conn.commit()
        return {"success": True, "user_id": user_id, "workspace_id": workspace_id}
    except sqlite3.IntegrityError:
        # User already exists — update their github_token since GitHub
        # may issue a new one on each login. Without this, /user-from-token
        # keeps looking up the OLD token and never finds the user again.
        conn.rollback()
        c.execute(
            "UPDATE users SET github_id = ?, github_token = ?, updated_at = ? WHERE email = ?",
            (github_id, github_token, datetime.now(), email)
        )
        conn.commit()

        c.execute("SELECT id FROM users WHERE email = ?", (email,))
        result = c.fetchone()
        return {"success": True, "user_id": result[0]}
    finally:
        conn.close()

def log_activity(user_id: str, action: str, details: dict, workspace_id: str = None):
    """Log user activity"""
    conn = get_db()
    c = conn.cursor()
    
    log_id = f"log_{uuid.uuid4().hex[:12]}"
    
    c.execute('''INSERT INTO activity_logs (id, user_id, workspace_id, action, details, created_at)
                 VALUES (?, ?, ?, ?, ?, ?)''',
              (log_id, user_id, workspace_id, action, json.dumps(details), datetime.now()))
    
    conn.commit()
    conn.close()

# Store Render API Key (encrypted)
@app.get("/deployments/{user_id}")
def get_deployments(user_id: str, token: str):
    if not verify_owner(token, user_id):
        return {"error": "Not authorized", "deployments": []}
    conn = get_db()
    c = conn.cursor()
    
    c.execute('''SELECT id, repo_name, status, live_url, created_at, updated_at 
                 FROM deployments WHERE user_id = ? ORDER BY created_at DESC LIMIT 20''',
              (user_id,))
    
    deployments = [dict(row) for row in c.fetchall()]
    conn.close()
    
    return {"deployments": deployments}

# Get user activity (dashboard)
@app.get("/activity/{user_id}")
def get_user_activity(user_id: str, token: str, limit: int = 50):
    if not verify_owner(token, user_id):
        return {"error": "Not authorized", "activities": []}
    conn = get_db()
    c = conn.cursor()
    
    c.execute('''SELECT action, details, created_at FROM activity_logs 
                 WHERE user_id = ? ORDER BY created_at DESC LIMIT ?''',
              (user_id, limit))
    
    activities = [dict(row) for row in c.fetchall()]
    conn.close()
    
    return {"activities": activities}

# Create workspace
@app.post("/workspace")
def create_workspace(data: WorkspaceCreate):
    if not verify_owner(data.token, data.user_id):
        return {"error": "Not authorized"}
    conn = get_db()
    c = conn.cursor()
    
    workspace_id = f"ws_{uuid.uuid4().hex[:12]}"
    
    c.execute('''INSERT INTO workspaces (id, name, owner_id, created_at)
                 VALUES (?, ?, ?, ?)''',
              (workspace_id, data.name, data.user_id, datetime.now()))
    
    # Add creator as admin
    c.execute('''INSERT INTO workspace_members (id, workspace_id, user_id, role)
                 VALUES (?, ?, ?, ?)''',
              (f"wm_{uuid.uuid4().hex[:12]}", workspace_id, data.user_id, "admin"))
    
    conn.commit()
    conn.close()
    
    log_activity(data.user_id, "workspace_created", {"workspace_id": workspace_id})
    
    return {"success": True, "workspace_id": workspace_id}

# Get user workspaces
@app.get("/workspaces/{user_id}")
def get_user_workspaces(user_id: str, token: str):
    if not verify_owner(token, user_id):
        return {"error": "Not authorized", "workspaces": []}
    conn = get_db()
    c = conn.cursor()
    
    c.execute('''SELECT w.id, w.name, w.owner_id FROM workspaces w
                 JOIN workspace_members wm ON w.id = wm.workspace_id
                 WHERE wm.user_id = ?''', (user_id,))
    
    workspaces = [dict(row) for row in c.fetchall()]
    conn.close()
    
    return {"workspaces": workspaces}


@app.get("/workspace/{workspace_id}/members")
def get_workspace_members(workspace_id: str, user_id: str, token: str):
    if not verify_owner(token, user_id):
        return {"error": "Not authorized", "members": []}

    conn = get_db()
    c = conn.cursor()

    # only members of this workspace can view its member list
    c.execute("SELECT 1 FROM workspace_members WHERE workspace_id = ? AND user_id = ?", (workspace_id, user_id))
    if not c.fetchone():
        conn.close()
        return {"error": "Not a member of this workspace", "members": []}

    c.execute('''SELECT u.username, u.email, wm.role FROM workspace_members wm
                 JOIN users u ON u.id = wm.user_id
                 WHERE wm.workspace_id = ?''', (workspace_id,))
    members = [dict(row) for row in c.fetchall()]
    conn.close()

    return {"members": members}


class WorkspaceInvite(BaseModel):
    token: str
    user_id: str          # the inviter (must already be a member)
    workspace_id: str
    invite_email: str
    role: str = "developer"  # "admin" | "developer" | "viewer"


@app.post("/workspace/invite")
def invite_to_workspace(data: WorkspaceInvite):
    if not verify_owner(data.token, data.user_id):
        return {"error": "Not authorized"}

    conn = get_db()
    c = conn.cursor()

    # inviter must actually belong to this workspace
    c.execute("SELECT 1 FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
              (data.workspace_id, data.user_id))
    if not c.fetchone():
        conn.close()
        return {"error": "You're not a member of this workspace"}

    c.execute("SELECT id, username FROM users WHERE email = ?", (data.invite_email,))
    invitee = c.fetchone()

    if not invitee:
        conn.close()
        return {"error": "No GitSetLive account found for that email yet — ask them to sign in with GitHub first, then invite them again."}

    c.execute("SELECT 1 FROM workspace_members WHERE workspace_id = ? AND user_id = ?",
              (data.workspace_id, invitee["id"]))
    if c.fetchone():
        conn.close()
        return {"error": "That person is already a member of this workspace"}

    c.execute('''INSERT INTO workspace_members (id, workspace_id, user_id, role)
                 VALUES (?, ?, ?, ?)''',
              (f"wm_{uuid.uuid4().hex[:12]}", data.workspace_id, invitee["id"], data.role))

    c.execute("SELECT name FROM workspaces WHERE id = ?", (data.workspace_id,))
    ws = c.fetchone()
    ws_name = ws["name"] if ws else "a workspace"

    conn.commit()
    conn.close()

    log_activity(data.user_id, "workspace_invite_sent", {"workspace_id": data.workspace_id, "invitee": data.invite_email})

    if SMTP_EMAIL and SMTP_PASSWORD:
        try:
            send_email(
                data.invite_email,
                f"You've been added to {ws_name} on GitSetLive",
                f"Hi {invitee['username']},\n\nYou've been added as a {data.role} to the workspace '{ws_name}' on GitSetLive."
            )
        except Exception as e:
            print(f"⚠️ Invite email failed (member was still added): {e}")

    return {"success": True}


from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib

SMTP_EMAIL = os.getenv("SMTP_EMAIL")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

def send_email(to_email: str, subject: str, body: str):
    """Send email notification"""
    try:
        msg = MIMEMultipart()
        msg['From'] = SMTP_EMAIL
        msg['To'] = to_email
        msg['Subject'] = subject
        
        msg.attach(MIMEText(body, 'html'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(SMTP_EMAIL, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        
        return True
    except Exception as e:
        print(f"Email failed: {e}")
        return False


@app.get("/user-from-token")
def user_from_token(token: str):
    """Get user info from encrypted token"""
    try:
        token_data = s.loads(token)
        
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT id, username, email FROM users WHERE github_token = ? LIMIT 1", (token_data,))
        user = c.fetchone()
        conn.close()
        
        if user:
            return {"user_id": user['id'], "username": user['username'], "email": user['email']}
        
        return {"error": "User not found"}
    except:
        return {"error": "Invalid token"}
import { screen, waitFor, within, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { BASE, mockFetch, renderPage, signedIn } from "./helpers";
import { mockRouter } from "./stubs/router";
import { api, session } from "../lib/api";
import { Markdown } from "../components/ui";
import { render } from "@testing-library/react";

import Dashboard from "../pages/dashboard";
import Scan from "../pages/scan";
import GitBot from "../pages/gitbot";
import AIBuilder from "../pages/upload-code";
import Deploy from "../pages/deploy";
import Callback from "../pages/callback";
import Login from "../pages/login";
import Workspaces from "../pages/workspaces";

beforeEach(() => { localStorage.clear(); sessionStorage.clear(); mockRouter.replace.mockClear(); mockRouter.query = {}; });

test("api sends the Bearer session and logs out on 401", async () => {
  session.set("gsl_abc");
  const calls = mockFetch({ "GET /x": { __status: 401, detail: { message: "expired", code: "unauthenticated" } } });
  const onLogout = vi.fn(); window.addEventListener("gsl:logout", onLogout);
  await expect(api.get("/x")).rejects.toThrow("expired");
  expect(calls[0].headers.Authorization).toBe("Bearer gsl_abc");
  expect(session.get()).toBeNull(); expect(onLogout).toHaveBeenCalled();
});

test("api turns FastAPI validation errors into readable text", async () => {
  mockFetch({ "POST /v": { __status: 422, detail: [{ loc: ["body", "name"], msg: "String should match pattern" }] } });
  await expect(api.post("/v", {})).rejects.toThrow(/name.*String should match/);
});

test("callback stores the token from the URL fragment and scrubs it", async () => {
  mockFetch(BASE);
  window.history.replaceState(null, "", "/callback#token=gsl_frag123");
  renderPage(Callback);
  await waitFor(() => expect(mockRouter.replace).toHaveBeenCalledWith("/dashboard"));
  expect(session.get()).toBe("gsl_frag123");
  expect(window.location.hash).toBe("");
});

test("login shows server errors and a warning when GitHub login isn't configured", async () => {
  mockFetch({ "GET /config": { login_configured: false } });
  mockRouter.query = { error: "Your login attempt expired" };
  renderPage(Login);
  expect(screen.getByRole("alert")).toHaveTextContent("expired");
  await waitFor(() => expect(screen.getByText(/isn't configured/i)).toBeInTheDocument());
  expect(screen.getByRole("button", { name: /continue with github/i })).toBeDisabled();
});

test("dashboard lists repos with health score, filters and searches", async () => {
  signedIn();
  mockFetch({ ...BASE, "GET /stats": { deployments: { live: 1, total: 2, failed: 0 }, success_rate: 100, scan_count: 3, latest_scores: { "alice/shop": { score: 72 } } },
    "GET /activity": { activities: [{ action: "scan", details: { repo: "shop" }, created_at: "2026-11-01T10:00:00Z" }] }, "GET /deployments": { deployments: [] } });
  renderPage(Dashboard);
  await screen.findByText("shop");
  expect(screen.getByText("blog")).toBeInTheDocument();
  expect(screen.getByText("72")).toBeInTheDocument();
  expect(screen.getByText("Scanned shop")).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Search repositories"), "blo");
  expect(screen.queryByText("shop")).not.toBeInTheDocument();
  await userEvent.clear(screen.getByLabelText("Search repositories"));
  await userEvent.click(screen.getByRole("button", { name: "Private" }));
  expect(screen.queryByText("blog")).not.toBeInTheDocument();
});

test("dashboard: deleting asks for the exact name and offers the extra permission when missing", async () => {
  signedIn();
  mockFetch({ ...BASE, "GET /stats": { deployments: {}, latest_scores: {} }, "GET /activity": { activities: [] }, "GET /deployments": { deployments: [] } });
  renderPage(Dashboard);
  await screen.findByText("shop");
  await userEvent.click(screen.getByRole("button", { name: "Delete shop" }));
  expect(await screen.findByText(/extra GitHub permission/i)).toBeInTheDocument();
  expect(screen.getByRole("link", { name: /grant delete permission/i }).getAttribute("href")).toMatch(/\/login\?extra=delete_repo$/);
});

const FINDINGS = [
  { id: "f1", severity: "critical", category: "security", title: "Groq API key committed", file: "app.py", line: 3, line_context: 'KEY = "gsk_…"', detail: "Rotate it.", source: "static", fixable: false, diff: null },
  { id: "f2", severity: "warning", category: "deployment", title: "Server only listens on localhost", file: "main.py", line: 9, line_context: "host='127.0.0.1'", detail: "d", source: "static", fixable: true, diff: "--- a/main.py\n+++ b/main.py\n@@ -1 +1 @@\n-host='127.0.0.1'\n+host='0.0.0.0'" },
  { id: "f3", severity: "warning", category: "logic", title: "AI found a thing", file: "main.py", line: 4, line_context: "x", detail: "d", source: "ai", fixable: true, diff: "+x" },
];

test("scan: run, review, deselect one fix and open a PR with exactly the selected fixes", async () => {
  signedIn("alice/shop");
  const calls = mockFetch({ ...BASE, "GET /scans": [],
    "POST /scan": { scan_id: "scan_1", score: 64, grade: "C", counts: { critical: 1, warning: 2, info: 0 }, findings: FINDINGS, ai: { ok: true }, files_scanned: 12, truncated: false },
    "POST /scan/apply": { pr_url: "https://github.com/alice/shop/pull/7", files_changed: 1, applied: ["f2"], skipped: [] } });
  renderPage(Scan);
  await userEvent.click(await screen.findByRole("button", { name: /run scan/i }));
  await screen.findByText("Groq API key committed");
  expect(screen.getByLabelText("Health score 64 out of 100")).toBeInTheDocument();
  expect(screen.getByText(/AI · verified/)).toBeInTheDocument();
  expect(screen.getByText((_, el) => el.tagName === "SPAN" && el.textContent.startsWith("2 fixes selected"))).toBeInTheDocument();
  await userEvent.click(screen.getByLabelText("Include fix: AI found a thing"));
  await userEvent.click(screen.getByRole("button", { name: /create pull request/i }));
  const link = await screen.findByRole("link", { name: /pull\/7/ });
  expect(link).toHaveAttribute("href", "https://github.com/alice/shop/pull/7");
  const apply = calls.find((c) => c.key === "POST /scan/apply");
  expect(apply.body).toEqual({ owner: "alice", repo: "shop", scan_id: "scan_1", finding_ids: ["f2"] });
});

test("scan: expanding a finding shows its diff", async () => {
  signedIn("alice/shop");
  mockFetch({ ...BASE, "GET /scans": [], "POST /scan": { scan_id: "s", score: 90, grade: "A", counts: { critical: 0, warning: 1, info: 0 }, findings: [FINDINGS[1]], ai: { ok: false, note: "AI down" }, files_scanned: 1 } });
  renderPage(Scan);
  await userEvent.click(await screen.findByRole("button", { name: /run scan/i }));
  expect(await screen.findByText(/AI review unavailable/)).toBeInTheDocument();
  await userEvent.click(screen.getByText("Server only listens on localhost"));
  expect(await screen.findByText("+host='0.0.0.0'")).toBeInTheDocument();
});

test("gitbot: sends history, renders markdown answer safely with sources", async () => {
  signedIn("alice/shop");
  const calls = mockFetch({ ...BASE, "POST /ai/chat": (c) => ({ answer: "It's a **shop**.\n\n```py\nprint(1)\n```\n<img src=x onerror=alert(1)>", files_used: ["README.md"] }) });
  renderPage(GitBot);
  await userEvent.click(await screen.findByRole("button", { name: /explain it simply/i }));
  expect(await screen.findByText("shop", { selector: "strong" })).toBeInTheDocument();
  expect(screen.getByText("README.md")).toBeInTheDocument();
  expect(document.querySelector("img[src='x']")).toBeNull();            // raw HTML stays text
  expect(screen.getByText(/<img src=x onerror=alert\(1\)>/)).toBeInTheDocument();
  await userEvent.type(screen.getByLabelText("Your question"), "and the db?{enter}");
  await waitFor(() => expect(calls.filter((c) => c.key === "POST /ai/chat")).toHaveLength(2));
  expect(calls.filter((c) => c.key === "POST /ai/chat")[1].body.history).toHaveLength(2);
});

test("markdown never renders javascript: links", () => {
  render(<Markdown text={"[click](javascript:alert(1)) and [ok](https://example.com)"} />);
  expect(screen.queryByRole("link", { name: "click" })).toBeNull();
  expect(screen.getByRole("link", { name: "ok" })).toHaveAttribute("rel", expect.stringContaining("noopener"));
});

test("AI builder: propose → review diff → commit as PR (sensitive files start unchecked)", async () => {
  signedIn("alice/shop");
  const calls = mockFetch({ ...BASE,
    "POST /ai/propose": { summary: "Adds health", warnings: ["Skipped x"], changes: [
      { path: "main.py", action: "modify", content: "NEW", diff: "+NEW", reason: "r", sensitive: false },
      { path: ".github/workflows/ci.yml", action: "create", content: "ci", diff: "+ci", reason: "", sensitive: true }] },
    "POST /ai/commit": { pr_url: "https://github.com/alice/shop/pull/9", branch: "b" } });
  renderPage(AIBuilder);
  await userEvent.click(await screen.findByRole("button", { name: /add a \/health endpoint/i }));
  await userEvent.click(screen.getByRole("button", { name: /generate changes/i }));
  await screen.findByText(/Adds health/);
  expect(screen.getByText(/Some suggestions were dropped/)).toBeInTheDocument();
  expect(screen.getByLabelText(".github/workflows/ci.yml")).not.toBeChecked();
  await userEvent.click(screen.getByRole("button", { name: /create pull request \(1 file\)/i }));
  expect(await screen.findByRole("link", { name: /open it on github/i })).toHaveAttribute("href", "https://github.com/alice/shop/pull/9");
  const body = calls.find((c) => c.key === "POST /ai/commit").body;
  expect(body.mode).toBe("pr"); expect(body.changes).toEqual([{ path: "main.py", content: "NEW" }]);
});

const ANALYSIS = { score: 70, grade: "C", counts: {}, apps: [
  { root: "backend", type: "python", framework: "fastapi", env_vars: [{ name: "GROQ_API_KEY" }], recommend: { render: { service: "Web Service", runtime: "Python 3", root_dir: "backend", build_command: "pip install -r requirements.txt", start_command: "uvicorn main:app --host 0.0.0.0 --port $PORT" }, vercel: null, own_server: true, notes: ["Vercel isn't a good fit"] },
    readiness: [{ id: "deps", label: "Dependencies are declared", ok: true, detail: "d", level: "required" }, { id: "bind", label: "Listens on 0.0.0.0", ok: false, detail: "d", level: "required" }] },
  { root: "frontend", type: "node", framework: "next", env_vars: [], recommend: { render: null, vercel: { framework: "Next", root_dir: "frontend", build_command: "npm run build" }, own_server: true, notes: [] }, readiness: [] }] };

test("deploy: monorepo detection, blockers, exact Render values, Vercel fallback and recording a deploy", async () => {
  signedIn("alice/shop");
  const calls = mockFetch({ ...BASE, "GET /analyze": ANALYSIS, "GET /deployments": { deployments: [] }, "POST /deployments": { id: "d1" }, "GET /deploy/own": { enabled: false, projects: [] } });
  renderPage(Deploy);
  expect(await screen.findByText(/contains 2 apps/)).toBeInTheDocument();
  expect(screen.getByText(/1 thing will stop this deploy/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Render" }));
  expect(screen.getByText("uvicorn main:app --host 0.0.0.0 --port $PORT")).toBeInTheDocument();
  expect(screen.getByText("GROQ_API_KEY")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Vercel" }));
  expect(screen.getByText(/isn't a good fit/i)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /frontend · next/ }));
  expect(screen.getByRole("link", { name: /open vercel/i })).toHaveAttribute("href", "https://vercel.com/new");
  await userEvent.type(screen.getByLabelText("Live URL"), "https://shop.vercel.app");
  await userEvent.click(screen.getByRole("button", { name: /save/i }));
  await waitFor(() => expect(calls.find((c) => c.key === "POST /deployments")?.body).toEqual({ repo_name: "shop", provider: "vercel", live_url: "https://shop.vercel.app", status: "live" }));
  await userEvent.click(screen.getByRole("button", { name: "Our Servers" }));
  expect(await screen.findByText(/turned off on this server/i)).toBeInTheDocument();
});

test("deploy: Our Servers shows a building deployment with its message and a failed one with the error", async () => {
  signedIn("alice/shop");
  mockFetch({ ...BASE, "GET /analyze": { ...ANALYSIS, apps: [ANALYSIS.apps[0]] }, "GET /deployments": { deployments: [] }, "GET /env": { vars: [] },
    "GET /deploy/own": { enabled: true, projects: [
      { id: "p1", name: "shop", owner: "alice", repo: "shop", root: "backend", framework: "fastapi", status: "building", message: "Installing dependencies…", created_at: 1 },
      { id: "p2", name: "shop", owner: "alice", repo: "shop", status: "failed", message: "Failed", error: "pip install failed", created_at: 0 }] } });
  renderPage(Deploy);
  await userEvent.click(await screen.findByRole("button", { name: "Our Servers" }));
  expect(await screen.findByText("Installing dependencies…")).toBeInTheDocument();
  expect(screen.getByText("pip install failed")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /stop/i })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /remove/i })).toBeInTheDocument();
});

test("workspaces: viewers get no admin controls", async () => {
  signedIn();
  mockFetch({ ...BASE, "GET /workspaces": { workspaces: [{ id: "w1", name: "Team", role: "viewer", member_count: 2 }] },
    "GET /workspaces/w1/members": { members: [{ user_id: "u1", username: "alice", email: null, role: "viewer" }, { user_id: "u2", username: "bob", email: "b@x.com", role: "admin" }] }, "GET /deployments": { deployments: [] } });
  renderPage(Workspaces);
  await screen.findByText("bob");
  expect(screen.queryByText("Invite someone")).toBeNull();
  expect(screen.queryByLabelText("Role for bob")).toBeNull();
  expect(screen.getByRole("button", { name: "Leave" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Remove" })).toBeNull();
});

import SavedKeys from "../pages/keys";

test("saved keys: list shows only hints; reveal fetches on demand and auto-hides; delete asks first", async () => {
  signedIn();
  const calls = mockFetch({ ...BASE,
    "GET /keys": { keys: [{ id: "k1", name: "GROQ_API_KEY", note: "main", hint: "••••7890", saved_at: "2026-11-01T10:00:00Z" }] },
    "POST /keys/k1/reveal": { value: "gsk_the_real_value_7890" }, "DELETE /keys/k1": { ok: true }, "PUT /keys": { id: "k2", created: true } });
  renderPage(SavedKeys);
  expect(await screen.findByText("GROQ_API_KEY", { selector: ".keyname" })).toBeInTheDocument();
  expect(screen.getByText("••••7890")).toBeInTheDocument();
  expect(screen.queryByText(/gsk_the_real_value/)).toBeNull();                 // never shown until asked
  expect(calls.some((c) => c.key === "POST /keys/k1/reveal")).toBe(false);

  await userEvent.click(screen.getByRole("button", { name: "Reveal GROQ_API_KEY" }));
  expect(await screen.findByText("gsk_the_real_value_7890")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Hide GROQ_API_KEY" }));
  expect(screen.queryByText("gsk_the_real_value_7890")).toBeNull();

  // saving a new key sends exactly what was typed (name trimmed) and clears the form
  await userEvent.click(screen.getByRole("button", { name: "VERCEL_TOKEN" }));
  await userEvent.type(screen.getByPlaceholderText("paste the key here"), "vercel-secret-1");
  await userEvent.click(screen.getByRole("button", { name: /save key/i }));
  await waitFor(() => expect(calls.find((c) => c.key === "PUT /keys")?.body).toEqual({ name: "VERCEL_TOKEN", value: "vercel-secret-1", note: null }));

  await userEvent.click(screen.getByRole("button", { name: "Delete GROQ_API_KEY" }));
  expect(await screen.findByText(/does not revoke the key at its provider/)).toBeInTheDocument();
  expect(calls.some((c) => c.key === "DELETE /keys/k1")).toBe(false);          // nothing deleted until confirmed
  await userEvent.click(screen.getByRole("button", { name: /delete key/i }));
  await waitFor(() => expect(calls.some((c) => c.key === "DELETE /keys/k1")).toBe(true));
});

test("saved keys: typing an existing name switches the form to 'replace'", async () => {
  signedIn();
  mockFetch({ ...BASE, "GET /keys": { keys: [{ id: "k1", name: "Render", note: null, hint: "••••", saved_at: "2026-11-01T10:00:00Z" }] } });
  renderPage(SavedKeys);
  await screen.findByText("Render", { selector: ".keyname" });
  await userEvent.type(screen.getByPlaceholderText("e.g. GROQ_API_KEY"), "render");
  expect(screen.getByText(/already exists/)).toBeInTheDocument();
});

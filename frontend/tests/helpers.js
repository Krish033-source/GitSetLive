import React from "react";
import { render } from "@testing-library/react";
import { AuthProvider } from "../lib/auth";
import { ToastProvider } from "../lib/toast";

export const REPOS = [
  { id: 1, name: "shop", full_name: "alice/shop", owner: { login: "alice" }, private: true, language: "Python", updated_at: "2026-11-01T10:00:00Z", default_branch: "main", html_url: "https://github.com/alice/shop", description: "A shop", permissions: { push: true } },
  { id: 2, name: "blog", full_name: "alice/blog", owner: { login: "alice" }, private: false, language: "JavaScript", updated_at: "2026-10-01T10:00:00Z", default_branch: "main", html_url: "https://github.com/alice/blog", description: null, permissions: { push: true } },
];

// handlers: { "GET /path": data | (call) => data | {__status, ...} }
export function mockFetch(handlers) {
  const calls = [];
  global.fetch = vi.fn(async (url, opts = {}) => {
    const u = new URL(url);
    const key = `${opts.method || "GET"} ${u.pathname}`;
    const call = { key, body: opts.body ? JSON.parse(opts.body) : null, params: Object.fromEntries(u.searchParams), headers: opts.headers || {} };
    calls.push(call);
    let h = handlers[key];
    if (h === undefined) return { ok: false, status: 404, json: async () => ({ detail: `no mock for ${key}` }) };
    if (typeof h === "function") h = h(call);
    const status = h && h.__status ? h.__status : 200;
    return { ok: status < 400, status, json: async () => (h && h.__status ? { detail: h.detail } : h) };
  });
  return calls;
}

export const BASE = { "GET /me": { id: "u1", username: "alice", scopes: ["repo"], can_delete_repos: false, avatar_url: null }, "GET /repos": REPOS };

export function renderPage(Page) {
  return render(<AuthProvider><ToastProvider><Page /></ToastProvider></AuthProvider>);
}

export function signedIn(repo) {
  localStorage.setItem("gsl_session", "gsl_testtoken");
  if (repo) sessionStorage.setItem("gsl_repo", repo);
}

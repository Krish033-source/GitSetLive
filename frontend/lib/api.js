// One place for every backend call: auth header, JSON, timeouts, consistent errors.
export const API = (process.env.NEXT_PUBLIC_API || "http://localhost:5000").replace(/\/$/, "");
const KEY = "gsl_session";

export const session = {
  get() { try { return localStorage.getItem(KEY); } catch { return null; } },
  set(t) { try { localStorage.setItem(KEY, t); } catch {} },
  clear() { try { localStorage.removeItem(KEY); } catch {} },
};

export class ApiError extends Error {
  constructor(message, { status = 0, code = "error", data = null } = {}) {
    super(message);
    this.status = status; this.code = code; this.data = data;
  }
}

function explain(status, body) {
  const d = body && body.detail;
  if (typeof d === "string") return { message: d, code: "error" };
  if (Array.isArray(d)) { // FastAPI validation error
    const first = d[0] || {};
    const field = Array.isArray(first.loc) ? first.loc[first.loc.length - 1] : "";
    return { message: `Invalid input${field ? ` (${field})` : ""}: ${first.msg || "please check the value"}`, code: "validation" };
  }
  if (d && typeof d === "object") return { message: d.message || "Request failed", code: d.code || "error", data: d };
  return { message: `Request failed (${status})`, code: "error" };
}

async function request(method, path, { body, params, timeout = 60000 } = {}) {
  const url = new URL(API + path);
  Object.entries(params || {}).forEach(([k, v]) => { if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v); });

  const headers = {};
  const token = session.get();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body !== undefined) headers["Content-Type"] = "application/json";

  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  let res;
  try {
    res = await fetch(url, { method, headers, signal: ctrl.signal, body: body !== undefined ? JSON.stringify(body) : undefined });
  } catch (e) {
    if (e.name === "AbortError") throw new ApiError("This is taking longer than expected. Please try again.", { code: "timeout" });
    throw new ApiError("Can't reach the server. Check your connection (or that the backend is running).", { code: "network" });
  } finally { clearTimeout(timer); }

  let data = null;
  try { data = await res.json(); } catch {}
  if (!res.ok) {
    const { message, code, data: extra } = explain(res.status, data);
    if (res.status === 401 && (code === "unauthenticated" || code === "github_auth") && typeof window !== "undefined") {
      session.clear();
      window.dispatchEvent(new Event("gsl:logout"));
    }
    throw new ApiError(message, { status: res.status, code, data: extra || data });
  }
  return data;
}

export const api = {
  get: (p, o) => request("GET", p, o),
  post: (p, body, o) => request("POST", p, { ...o, body: body ?? {} }),
  put: (p, body, o) => request("PUT", p, { ...o, body }),
  patch: (p, body, o) => request("PATCH", p, { ...o, body }),
  del: (p, o) => request("DELETE", p, o),
};

// "Is it reachable?" without any backend involvement (no SSRF surface): a no-cors request
// succeeds (opaque) if the host answers at all and throws if it can't be reached.
export async function checkReachable(url, ms = 8000) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), ms);
  try { await fetch(url, { mode: "no-cors", cache: "no-store", signal: ctrl.signal }); return true; }
  catch { return false; } finally { clearTimeout(t); }
}

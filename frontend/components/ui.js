import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/router";
import { api } from "../lib/api";
import { gradeColor, timeAgo } from "../lib/format";
import { useToast } from "../lib/toast";

/* ------------------------------------------------------------------ icons */
const PATHS = {
  home: "M3 11l9-8 9 8M5 10v10h5v-6h4v6h5V10",
  scan: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3zM9 12l2 2 4-4",
  bot: "M12 3v3M5 8h14a2 2 0 012 2v7a2 2 0 01-2 2H5a2 2 0 01-2-2v-7a2 2 0 012-2zM8.5 13h.01M15.5 13h.01M9 17h6",
  sparkle: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8L12 3zM19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8L19 16z",
  file: "M14 3H7a2 2 0 00-2 2v14a2 2 0 002 2h10a2 2 0 002-2V8l-5-5zM14 3v5h5M9 13h6M9 17h6",
  rocket: "M5 15c-1.5 1.3-2 5-2 5s3.7-.5 5-2c.7-.8.7-2-.1-2.8S5.8 14.3 5 15zM12 15l-3-3a22 22 0 012-4 12.9 12.9 0 0111-5c0 2.7-.8 7.5-5 11a22 22 0 01-4 2zM9 12H4s.6-3 2-4c1.6-1.1 5 0 5 0M12 15v5s3-.6 4-2c1.1-1.6 0-5 0-5",
  users: "M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2M9 11a4 4 0 100-8 4 4 0 000 8zM23 21v-2a4 4 0 00-3-3.9M16 3.1a4 4 0 010 7.8",
  help: "M12 22a10 10 0 100-20 10 10 0 000 20zM9.1 9a3 3 0 015.8 1c0 2-3 3-3 3M12 17h.01",
  logout: "M9 21H5a2 2 0 01-2-2V5a2 2 0 012-2h4M16 17l5-5-5-5M21 12H9",
  github: "M9 19c-5 1.5-5-2.5-7-3m14 6v-3.9a3.4 3.4 0 00-.9-2.6c3.1-.3 6.4-1.5 6.4-7A5.4 5.4 0 0020 4.8 5 5 0 0019.9 1S18.7.7 16 2.5a13.4 13.4 0 00-7 0C6.3.7 5.1 1 5.1 1A5 5 0 005 4.8a5.4 5.4 0 00-1.5 3.8c0 5.4 3.3 6.6 6.4 7a3.4 3.4 0 00-.9 2.6V22",
  plus: "M12 5v14M5 12h14", trash: "M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2M19 6l-1 14a2 2 0 01-2 2H8a2 2 0 01-2-2L5 6M10 11v6M14 11v6",
  external: "M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6M15 3h6v6M10 14L21 3",
  check: "M20 6L9 17l-5-5", x: "M18 6L6 18M6 6l12 12", alert: "M12 9v4M12 17h.01M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z",
  copy: "M9 9h11v11H9zM5 15H4a1 1 0 01-1-1V4a1 1 0 011-1h10a1 1 0 011 1v1", refresh: "M23 4v6h-6M1 20v-6h6M3.5 9a9 9 0 0114.9-3.4L23 10M1 14l4.6 4.4A9 9 0 0020.5 15",
  lock: "M7 11V7a5 5 0 0110 0v4M5 11h14a1 1 0 011 1v8a1 1 0 01-1 1H5a1 1 0 01-1-1v-8a1 1 0 011-1z", menu: "M3 6h18M3 12h18M3 18h18",
  terminal: "M4 17l6-6-6-6M12 19h8", search: "M21 21l-4.3-4.3M11 18a7 7 0 100-14 7 7 0 000 14z", send: "M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z",
  star: "M12 2l3.1 6.3 6.9 1-5 4.9 1.2 6.8L12 17.8 5.8 21l1.2-6.8-5-4.9 6.9-1L12 2z", sun: "M12 17a5 5 0 100-10 5 5 0 000 10zM12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4",
  moon: "M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z", branch: "M6 3v12M18 9a3 3 0 100-6 3 3 0 000 6zM6 21a3 3 0 100-6 3 3 0 000 6zM18 9a9 9 0 01-9 9",
  key: "M21 2l-2 2m-7.61 7.61a5.5 5.5 0 11-7.778 7.778 5.5 5.5 0 017.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4",
  eye: "M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8zM12 15a3 3 0 100-6 3 3 0 000 6z",
  eyeoff: "M17.94 17.94A10.07 10.07 0 0112 20c-7 0-11-8-11-8a18.45 18.45 0 015.06-5.94M9.9 4.24A9.12 9.12 0 0112 4c7 0 11 8 11 8a18.5 18.5 0 01-2.16 3.19m-6.72-1.07a3 3 0 11-4.24-4.24M1 1l22 22",
  chevron: "M9 18l6-6-6-6", stop: "M6 6h12v12H6z", shield: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z",
};
export function Icon({ name, size = 18, className = "", style }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"
      strokeLinejoin="round" className={className} style={{ flex: "none", ...style }} aria-hidden="true">
      <path d={PATHS[name] || PATHS.help} />
    </svg>
  );
}

/* ------------------------------------------------------------------ logo */
export function Logo({ size = 32 }) {
  return <img src="/logo.svg" width={size} height={size} alt="" style={{ display: "block", borderRadius: Math.round(size * 0.24), flex: "none" }} />;
}

/* ----------------------------------------------------------- small pieces */
export const Spinner = ({ lg }) => <span className={`spinner${lg ? " lg" : ""}`} role="progressbar" aria-label="Loading" />;
export const Badge = ({ kind = "", children, title }) => <span className={`badge ${kind}`} title={title}>{children}</span>;
export const Skeleton = ({ h = 18, w = "100%", style }) => <div className="skeleton" style={{ height: h, width: w, ...style }} />;

export function EmptyState({ icon = "sparkle", title, children, action }) {
  return (
    <div className="empty">
      <div className="big"><Icon name={icon} size={34} /></div>
      <h3 style={{ color: "var(--text)", marginBottom: 6 }}>{title}</h3>
      <p style={{ maxWidth: 420, margin: "0 auto 16px" }}>{children}</p>
      {action}
    </div>
  );
}

export function CopyButton({ text, label = "Copy", small = true }) {
  const toast = useToast();
  const [done, setDone] = useState(false);
  return (
    <button className={`btn ${small ? "sm" : ""} ghost`} type="button" onClick={async () => {
      try { await navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1500); }
      catch { toast.error("Couldn't copy — select the text and copy it manually."); }
    }}>
      <Icon name={done ? "check" : "copy"} size={14} /> {done ? "Copied" : label}
    </button>
  );
}

export function Modal({ title, onClose, children, footer, wide }) {
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? "wide" : ""}`} role="dialog" aria-modal="true" aria-label={title}>
        <div className="modal-head"><h2>{title}</h2><button className="btn ghost icon" onClick={onClose} aria-label="Close"><Icon name="x" /></button></div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

export function ScoreRing({ score, grade }) {
  const r = 56, c = 2 * Math.PI * r, color = gradeColor(score);
  return (
    <div className="score" aria-label={`Health score ${score} out of 100`}>
      <svg width="132" height="132" viewBox="0 0 132 132">
        <circle cx="66" cy="66" r={r} fill="none" stroke="var(--border)" strokeWidth="10" />
        <circle cx="66" cy="66" r={r} fill="none" stroke={color} strokeWidth="10" strokeLinecap="round"
          strokeDasharray={c} strokeDashoffset={c * (1 - score / 100)} style={{ transition: "stroke-dashoffset .8s ease" }} />
      </svg>
      <div className="num"><b style={{ color }}>{score}</b><span>Grade {grade}</span></div>
    </div>
  );
}

export function DiffView({ diff }) {
  if (!diff) return null;
  return (
    <div className="diff" role="region" aria-label="Changes">
      {diff.split("\n").map((l, i) => {
        const cls = l.startsWith("+++") || l.startsWith("---") ? "meta" : l.startsWith("@@") ? "hunk" : l.startsWith("+") ? "add" : l.startsWith("-") ? "del" : "";
        return <div key={i} className={cls}>{l || " "}</div>;
      })}
    </div>
  );
}

export function CodeBlock({ code, copy = true }) {
  return (
    <div style={{ position: "relative" }}>
      <pre className="code">{code}</pre>
      {copy && <div style={{ position: "absolute", top: 6, right: 6 }}><CopyButton text={code} /></div>}
    </div>
  );
}

/* --------------------------------------- safe Markdown (no innerHTML, http(s) links only) */
function inline(text, keyBase) {
  return text.split(/(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\(https?:\/\/[^)\s]+\))/g).map((p, i) => {
    const k = `${keyBase}-${i}`;
    if (/^`[^`]+`$/.test(p)) return <code key={k}>{p.slice(1, -1)}</code>;
    if (/^\*\*[^*]+\*\*$/.test(p)) return <strong key={k}>{p.slice(2, -2)}</strong>;
    const m = p.match(/^\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)$/);
    if (m) return <a key={k} href={m[2]} target="_blank" rel="noopener noreferrer">{m[1]}</a>;
    return <Fragment key={k}>{p}</Fragment>;
  });
}

export function Markdown({ text }) {
  const blocks = useMemo(() => {
    const out = []; const lines = (text || "").split("\n"); let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (line.trim().startsWith("```")) {
        const buf = []; i++;
        while (i < lines.length && !lines[i].trim().startsWith("```")) buf.push(lines[i++]);
        i++; out.push({ t: "code", v: buf.join("\n") }); continue;
      }
      if (/^\s*([-*]|\d+\.)\s+/.test(line)) {
        const ordered = /^\s*\d+\./.test(line); const items = [];
        while (i < lines.length && /^\s*([-*]|\d+\.)\s+/.test(lines[i])) items.push(lines[i++].replace(/^\s*([-*]|\d+\.)\s+/, ""));
        out.push({ t: ordered ? "ol" : "ul", v: items }); continue;
      }
      const h = line.match(/^#{1,4}\s+(.*)/);
      if (h) { out.push({ t: "h", v: h[1] }); i++; continue; }
      if (!line.trim()) { i++; continue; }
      const buf = [];
      while (i < lines.length && lines[i].trim() && !/^\s*([-*]|\d+\.)\s+/.test(lines[i]) && !lines[i].trim().startsWith("```") && !/^#{1,4}\s/.test(lines[i])) buf.push(lines[i++]);
      out.push({ t: "p", v: buf.join(" ") });
    }
    return out;
  }, [text]);

  return (
    <div className="md">
      {blocks.map((b, i) => {
        if (b.t === "code") return <CodeBlock key={i} code={b.v} />;
        if (b.t === "h") return <h4 key={i}>{inline(b.v, i)}</h4>;
        if (b.t === "p") return <p key={i}>{inline(b.v, i)}</p>;
        const L = b.t === "ol" ? "ol" : "ul";
        return <L key={i}>{b.v.map((x, j) => <li key={j}>{inline(x, `${i}-${j}`)}</li>)}</L>;
      })}
    </div>
  );
}

/* ----------------------------------------------------------------- repos */
let repoCache = { data: null, at: 0 };

export function useRepos() {
  const [repos, setRepos] = useState(repoCache.data || []);
  const [loading, setLoading] = useState(!repoCache.data);
  const [error, setError] = useState("");

  const load = useCallback(async (force = false) => {
    if (!force && repoCache.data && Date.now() - repoCache.at < 60000) { setRepos(repoCache.data); setLoading(false); return; }
    setLoading(true); setError("");
    try {
      const data = await api.get("/repos", { params: force ? { refresh: 1 } : {} });
      repoCache = { data, at: Date.now() }; setRepos(data);
    } catch (e) { setError(e.message); } finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); }, [load]);
  return { repos, loading, error, reload: () => load(true) };
}

export function useSelectedRepo(repos) {
  const router = useRouter();
  const [selected, setSelected] = useState(null);

  useEffect(() => {
    if (!repos.length || selected || !router.isReady) return;
    let want = router.query.repo;
    if (!want) { try { want = sessionStorage.getItem("gsl_repo"); } catch {} }
    const found = repos.find((r) => r.full_name === want);
    if (found) setSelected(found);
  }, [repos, router.isReady, router.query.repo, selected]);

  const choose = (r) => {
    setSelected(r);
    try { r ? sessionStorage.setItem("gsl_repo", r.full_name) : sessionStorage.removeItem("gsl_repo"); } catch {}
  };
  return [selected, choose];
}

export function RepoPicker({ repos, loading, value, onChange, error, onReload }) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const box = useRef(null);

  useEffect(() => {
    const close = (e) => box.current && !box.current.contains(e.target) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const list = useMemo(() => {
    const s = q.trim().toLowerCase();
    return (s ? repos.filter((r) => r.full_name.toLowerCase().includes(s)) : repos).slice(0, 60);
  }, [repos, q]);

  return (
    <div ref={box} style={{ position: "relative", minWidth: 280, flex: 1, maxWidth: 520 }}>
      <button type="button" className="input" onClick={() => setOpen((o) => !o)} aria-haspopup="listbox" aria-expanded={open}
        style={{ display: "flex", alignItems: "center", gap: 10, textAlign: "left", cursor: "pointer" }}>
        <Icon name="github" size={16} />
        <span className="grow truncate">{loading ? "Loading repositories…" : value ? value.full_name : "Choose a repository"}</span>
        {value?.private && <Icon name="lock" size={14} style={{ color: "var(--muted)" }} />}
        <Icon name="chevron" size={14} style={{ transform: open ? "rotate(90deg)" : "none", color: "var(--muted)" }} />
      </button>
      {error && <div className="tiny" style={{ color: "var(--bad)", marginTop: 6 }}>{error} {onReload && <a href="#" onClick={(e) => { e.preventDefault(); onReload(); }}>Retry</a>}</div>}
      {open && (
        <div className="card flush" style={{ position: "absolute", zIndex: 40, left: 0, right: 0, top: "calc(100% + 6px)", boxShadow: "var(--shadow)" }}>
          <div style={{ padding: 10, borderBottom: "1px solid var(--border)" }}>
            <input autoFocus className="input" placeholder="Search your repositories…" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <div role="listbox" style={{ maxHeight: 320, overflow: "auto" }}>
            {list.length === 0 && <div className="muted small" style={{ padding: 16 }}>{repos.length ? "No match." : "No repositories yet."}</div>}
            {list.map((r) => (
              <button key={r.id} role="option" aria-selected={value?.id === r.id} className="btn ghost" type="button"
                onClick={() => { onChange(r); setOpen(false); setQ(""); }}
                style={{ width: "100%", justifyContent: "space-between", borderRadius: 0, padding: "10px 14px", fontWeight: 500 }}>
                <span className="truncate">{r.full_name}</span>
                <span className="row tiny muted" style={{ gap: 8, flexShrink: 0 }}>
                  {r.private && <Icon name="lock" size={12} />}{r.language || ""}<span>{timeAgo(r.updated_at)}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

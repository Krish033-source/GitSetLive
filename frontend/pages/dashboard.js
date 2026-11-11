import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { API, api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import { describeActivity, gradeColor, timeAgo } from "../lib/format";
import { Badge, EmptyState, Icon, Modal, Skeleton, Spinner, useRepos } from "../components/ui";

const FILTERS = [["all", "All"], ["private", "Private"], ["public", "Public"], ["scanned", "Scanned"], ["unscanned", "Not scanned"]];

function Stat({ icon, label, value, sub, loading }) {
  return (
    <div className="card stat">
      <div className="label"><Icon name={icon} size={15} /> {label}</div>
      {loading ? <Skeleton h={34} w={80} style={{ marginTop: 8 }} /> : <div className="value">{value}</div>}
      {sub && <div className="sub">{sub}</div>}
    </div>
  );
}

function CreateRepoModal({ onClose, onCreated }) {
  const toast = useToast();
  const [name, setName] = useState(""); const [desc, setDesc] = useState(""); const [priv, setPriv] = useState(true); const [busy, setBusy] = useState(false);
  const valid = /^[A-Za-z0-9_.-]{1,100}$/.test(name);
  const submit = async () => {
    setBusy(true);
    try { await api.post("/repos", { name, description: desc || null, private: priv }); toast.success(`Created ${name}`); onCreated(); onClose(); }
    catch (e) { toast.error(e.message); setBusy(false); }
  };
  return (
    <Modal title="New repository" onClose={onClose} footer={<><button className="btn" onClick={onClose}>Cancel</button><button className="btn primary" disabled={!valid || busy} onClick={submit}>{busy ? <Spinner /> : <Icon name="plus" size={16} />} Create</button></>}>
      <div className="col">
        <label className="field">Name<input className="input" autoFocus value={name} onChange={(e) => setName(e.target.value.replace(/\s/g, "-"))} placeholder="my-awesome-app" />
          <span className="hint">Letters, numbers, dashes, dots and underscores.</span></label>
        <label className="field">Description (optional)<input className="input" value={desc} maxLength={350} onChange={(e) => setDesc(e.target.value)} /></label>
        <label className="switch"><input type="checkbox" checked={priv} onChange={(e) => setPriv(e.target.checked)} /> Private repository <span className="muted small">(only you and people you invite can see it)</span></label>
        <p className="tiny faint">We add a README so the repo isn't empty and every tool works right away.</p>
      </div>
    </Modal>
  );
}

function DeleteRepoModal({ repo, canDelete, onClose, onDeleted }) {
  const toast = useToast();
  const [confirm, setConfirm] = useState(""); const [busy, setBusy] = useState(false); const [needScope, setNeedScope] = useState(!canDelete);
  const submit = async () => {
    setBusy(true);
    try { await api.post(`/repos/${repo.owner.login}/${repo.name}/delete`, { confirm }); toast.success(`Deleted ${repo.name}`); onDeleted(); onClose(); }
    catch (e) { if (e.code === "needs_scope") setNeedScope(true); else toast.error(e.message); setBusy(false); }
  };
  return (
    <Modal title={`Delete ${repo.name}?`} onClose={onClose} footer={needScope ? <button className="btn" onClick={onClose}>Close</button> : <><button className="btn" onClick={onClose}>Cancel</button><button className="btn danger" disabled={confirm !== repo.name || busy} onClick={submit}>{busy ? <Spinner /> : <Icon name="trash" size={16} />} Delete forever</button></>}>
      {needScope ? (
        <div className="col">
          <div className="callout warn"><Icon name="shield" /><span>Deleting repositories needs an extra GitHub permission. We only ask for it when you actually need it.</span></div>
          <a className="btn primary" href={`${API}/login?extra=delete_repo`}><Icon name="github" size={16} /> Grant delete permission</a>
        </div>
      ) : (
        <div className="col">
          <div className="callout bad"><Icon name="alert" /><span>This permanently deletes <b>{repo.full_name}</b> with all its code, issues and pull requests. It can't be undone.</span></div>
          <label className="field">Type <code>{repo.name}</code> to confirm<input className="input" value={confirm} onChange={(e) => setConfirm(e.target.value)} autoFocus /></label>
        </div>
      )}
    </Modal>
  );
}

export default function Dashboard() {
  const { user } = useAuth();
  const { repos, loading, error, reload } = useRepos();
  const [stats, setStats] = useState(null);
  const [activity, setActivity] = useState(null);
  const [deps, setDeps] = useState(null);
  const [q, setQ] = useState(""); const [filter, setFilter] = useState("all");
  const [creating, setCreating] = useState(false); const [deleting, setDeleting] = useState(null);

  const loadSide = useCallback(() => {
    api.get("/stats").then(setStats).catch(() => setStats({ deployments: {}, latest_scores: {}, scan_count: 0 }));
    api.get("/activity", { params: { limit: 8 } }).then((d) => setActivity(d.activities)).catch(() => setActivity([]));
    api.get("/deployments").then((d) => setDeps(d.deployments.slice(0, 5))).catch(() => setDeps([]));
  }, []);
  useEffect(loadSide, [loadSide]);

  const scores = stats?.latest_scores || {};
  const shown = useMemo(() => {
    const s = q.trim().toLowerCase();
    return repos.filter((r) => {
      if (s && !r.full_name.toLowerCase().includes(s) && !(r.description || "").toLowerCase().includes(s)) return false;
      const has = !!scores[r.full_name.toLowerCase()];
      return filter === "private" ? r.private : filter === "public" ? !r.private : filter === "scanned" ? has : filter === "unscanned" ? !has : true;
    });
  }, [repos, q, filter, scores]);

  return (
    <>
      <div className="page-header">
        <div><h1>Welcome back, {user?.username} 👋</h1><p>Pick a repository to scan, fix, chat with or deploy.</p></div>
        <div className="row"><button className="btn" onClick={reload}><Icon name="refresh" size={16} /> Refresh</button><button className="btn primary" onClick={() => setCreating(true)}><Icon name="plus" size={16} /> New repository</button></div>
      </div>

      <div className="grid stats">
        <Stat icon="github" label="Repositories" value={repos.length} loading={loading} sub={`${repos.filter((r) => r.private).length} private`} />
        <Stat icon="rocket" label="Live deployments" value={stats?.deployments?.live ?? 0} loading={!stats} sub={`${stats?.deployments?.total ?? 0} total`} />
        <Stat icon="check" label="Deploy success rate" value={stats?.success_rate != null ? `${stats.success_rate}%` : "—"} loading={!stats} sub="live vs failed" />
        <Stat icon="scan" label="Scans run" value={stats?.scan_count ?? 0} loading={!stats} sub={`${Object.keys(scores).length} repos checked`} />
      </div>

      <div className="card flush" style={{ marginTop: 22 }}>
        <div className="card-head">
          <h2>Your repositories</h2>
          <div className="row">
            <div style={{ position: "relative" }}><Icon name="search" size={15} style={{ position: "absolute", left: 11, top: 12, color: "var(--faint)" }} />
              <input className="input" style={{ paddingLeft: 34, width: 230 }} placeholder="Search…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search repositories" /></div>
          </div>
        </div>
        <div className="chips" style={{ padding: "12px 20px", borderBottom: "1px solid var(--border)" }}>
          {FILTERS.map(([k, label]) => <button key={k} className={`chip ${filter === k ? "on" : ""}`} onClick={() => setFilter(k)}>{label}</button>)}
        </div>

        {error && <div className="callout bad" style={{ margin: 16 }}><Icon name="alert" /> {error}</div>}
        {loading && !repos.length ? <div style={{ padding: 20 }} className="col">{[0, 1, 2, 3].map((i) => <Skeleton key={i} h={44} />)}</div>
          : !shown.length ? <EmptyState icon="github" title={repos.length ? "No repositories match" : "No repositories yet"} action={!repos.length && <button className="btn primary" onClick={() => setCreating(true)}>Create your first repository</button>}>{repos.length ? "Try another search or filter." : "Create one here or on GitHub and it will show up."}</EmptyState>
          : (
            <div className="scroll-x"><table className="table">
              <thead><tr><th>Repository</th><th>Health</th><th>Updated</th><th style={{ textAlign: "right" }}>Actions</th></tr></thead>
              <tbody>{shown.slice(0, 100).map((r) => {
                const sc = scores[r.full_name.toLowerCase()]; const qs = `?repo=${encodeURIComponent(r.full_name)}`;
                return (
                  <tr key={r.id}>
                    <td style={{ maxWidth: 340 }}>
                      <div className="row" style={{ gap: 8, flexWrap: "nowrap" }}>
                        <a href={r.html_url} target="_blank" rel="noopener noreferrer" className="truncate" style={{ fontWeight: 600 }}>{r.name}</a>
                        {r.private && <Badge><Icon name="lock" size={11} /> private</Badge>}{r.fork && <Badge>fork</Badge>}{r.archived && <Badge kind="warn">archived</Badge>}
                      </div>
                      <div className="tiny muted truncate">{r.description || r.language || "—"}</div>
                    </td>
                    <td>{sc?.score != null ? <span style={{ color: gradeColor(sc.score), fontWeight: 700 }}>{sc.score}<span className="faint tiny">/100</span></span> : <span className="faint tiny">not scanned</span>}</td>
                    <td className="muted small" style={{ whiteSpace: "nowrap" }}>{timeAgo(r.updated_at)}</td>
                    <td><div className="row" style={{ justifyContent: "flex-end", gap: 6, flexWrap: "nowrap" }}>
                      <Link className="btn sm" href={`/scan${qs}`}><Icon name="scan" size={14} /> Scan</Link>
                      <Link className="btn sm" href={`/gitbot${qs}`}><Icon name="bot" size={14} /> Ask</Link>
                      <Link className="btn sm" href={`/deploy${qs}`}><Icon name="rocket" size={14} /> Deploy</Link>
                      <button className="btn sm ghost" title="Delete repository" aria-label={`Delete ${r.name}`} onClick={() => setDeleting(r)}><Icon name="trash" size={14} /></button>
                    </div></td>
                  </tr>
                );
              })}</tbody>
            </table></div>
          )}
        {shown.length > 100 && <div className="muted small" style={{ padding: 14, textAlign: "center" }}>Showing 100 of {shown.length} — use search to narrow down.</div>}
      </div>

      <div className="grid two" style={{ marginTop: 22 }}>
        <div className="card flush">
          <div className="card-head"><h2>Recent deployments</h2><Link href="/deploy" className="small">Deploy →</Link></div>
          {!deps ? <div style={{ padding: 20 }}><Skeleton h={40} /></div> : !deps.length ? <EmptyState icon="rocket" title="Nothing deployed yet">Your deployments will appear here.</EmptyState> : (
            <div className="list">{deps.map((d) => (
              <div key={d.id} className="row between" style={{ flexWrap: "nowrap" }}>
                <div className="grow"><b className="truncate" style={{ display: "block" }}>{d.repo_name}</b><span className="tiny muted">{d.provider || "—"} · {timeAgo(d.created_at)}</span></div>
                <Badge kind={d.status === "live" ? "good" : d.status === "failed" ? "bad" : d.status === "deploying" ? "info" : ""}>{d.status}</Badge>
                {d.live_url && <a href={d.live_url} target="_blank" rel="noopener noreferrer" className="btn sm icon" aria-label="Open live site"><Icon name="external" size={14} /></a>}
              </div>))}</div>)}
        </div>
        <div className="card flush">
          <div className="card-head"><h2>Recent activity</h2></div>
          {!activity ? <div style={{ padding: 20 }}><Skeleton h={40} /></div> : !activity.length ? <EmptyState icon="sparkle" title="No activity yet">Scans, fixes and deploys will be listed here.</EmptyState> : (
            <div className="list">{activity.map((a, i) => <div key={i} className="row between" style={{ flexWrap: "nowrap" }}><span className="small">{describeActivity(a)}</span><span className="tiny faint" style={{ whiteSpace: "nowrap" }}>{timeAgo(a.created_at)}</span></div>)}</div>)}
        </div>
      </div>

      {creating && <CreateRepoModal onClose={() => setCreating(false)} onCreated={() => { reload(); loadSide(); }} />}
      {deleting && <DeleteRepoModal repo={deleting} canDelete={!!user?.can_delete_repos} onClose={() => setDeleting(null)} onDeleted={() => { reload(); loadSide(); }} />}
    </>
  );
}
Dashboard.title = "Dashboard";

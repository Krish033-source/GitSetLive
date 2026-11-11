import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, checkReachable } from "../lib/api";
import { useToast } from "../lib/toast";
import { timeAgo, timeLeft } from "../lib/format";
import { Badge, CopyButton, EmptyState, Icon, Modal, RepoPicker, Skeleton, Spinner, useRepos, useSelectedRepo } from "../components/ui";

const FIELD_LABELS = { service: "Service type", runtime: "Runtime / Language", framework: "Framework preset", root_dir: "Root directory", build_command: "Build command", start_command: "Start command", publish_dir: "Publish directory", output_dir: "Output directory", install_command: "Install command" };

function SettingsTable({ values }) {
  const rows = Object.entries(values).filter(([, v]) => v !== undefined && v !== null);
  return (
    <div className="kv card" style={{ background: "var(--bg-2)" }}>
      {rows.map(([k, v]) => (
        <div key={k} style={{ display: "contents" }}>
          <span className="k">{FIELD_LABELS[k] || k}</span><code>{v === "" ? "(leave empty)" : String(v)}</code>
          {v !== "" && !String(v).startsWith("(") ? <CopyButton text={String(v)} /> : <span />}
        </div>
      ))}
    </div>
  );
}

function EnvList({ app }) {
  if (!app?.env_vars?.length) return null;
  return (
    <div className="col" style={{ gap: 8 }}>
      <h3>Environment variables to add on the host</h3>
      <p className="small muted">Your code reads these. Set real values in the host's dashboard — never commit them.</p>
      <div className="chips">{app.env_vars.map((e) => <Badge key={e.name}><span className="mono">{e.name}</span></Badge>)}</div>
    </div>
  );
}

function RecordDeployment({ repo, provider, onSaved }) {
  const toast = useToast();
  const [url, setUrl] = useState(""); const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try { await api.post("/deployments", { repo_name: repo.name, provider, live_url: url || null, status: "live" }); toast.success("Saved to your deployment history"); setUrl(""); onSaved(); }
    catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };
  return (
    <div className="card col">
      <h3>Finished deploying?</h3>
      <p className="small muted">Paste the live URL to keep it in your history and dashboard stats.</p>
      <div className="row"><input className="input grow" placeholder="https://your-app.onrender.com" value={url} onChange={(e) => setUrl(e.target.value)} aria-label="Live URL" />
        <button className="btn primary" disabled={busy || !/^https?:\/\//i.test(url)} onClick={save}>{busy ? <Spinner /> : <Icon name="check" size={16} />} Save</button></div>
    </div>
  );
}

function PlatformTab({ app, repo, provider, onSaved }) {
  const rec = app.recommend[provider];
  const repoUrl = repo.html_url;
  if (!rec) return (
    <div className="callout warn"><Icon name="alert" /><span>{provider === "vercel" ? "Vercel isn't a good fit for this app." : "This app type isn't supported here."} {app.recommend.notes?.[0]}</span></div>
  );
  return (
    <div className="col" style={{ gap: 18 }}>
      <div className="card col">
        <h2>{provider === "render" ? "Deploy on Render" : "Deploy on Vercel"}</h2>
        <ol className="muted" style={{ lineHeight: 1.9, margin: 0, paddingLeft: 20 }}>
          {provider === "render" ? <>
            <li>Click <b>Open Render</b> and sign in (GitHub login is fine).</li>
            <li>Choose <b>{repo.full_name}</b> when asked for a repository.</li>
            <li>Paste the settings below, add your environment variables, and press <b>Create</b>.</li>
          </> : <>
            <li>Click <b>Open Vercel</b>, then <b>Import Git Repository</b>.</li>
            <li>Pick <b>{repo.full_name}</b> (install the Vercel GitHub app if it asks).</li>
            <li>Set the Root Directory and settings below, add your environment variables, and press <b>Deploy</b>.</li>
          </>}
        </ol>
        <SettingsTable values={rec} />
        <EnvList app={app} />
        <div className="row">
          {provider === "render"
            ? <a className="btn primary" target="_blank" rel="noopener noreferrer" href={`https://dashboard.render.com/create?type=web&repo=${encodeURIComponent(repoUrl)}`}><Icon name="external" size={16} /> Open Render</a>
            : <a className="btn primary" target="_blank" rel="noopener noreferrer" href="https://vercel.com/new"><Icon name="external" size={16} /> Open Vercel</a>}
          <CopyButton text={repoUrl} label="Copy repo URL" small={false} />
        </div>
        {provider === "vercel" && <p className="tiny faint">Tip: the “Deploy a copy” links you may see elsewhere clone the repo into a new one. Use Import to deploy this exact repository.</p>}
        {provider === "render" && <p className="tiny faint">Free Render web services go to sleep when idle and wake on the next visit (the first load is slow). Data written to local files or SQLite is lost on redeploy unless you attach a persistent disk or a database.</p>}
      </div>
      <RecordDeployment repo={repo} provider={provider} onSaved={onSaved} />
    </div>
  );
}

function EnvEditor({ repo, app }) {
  const toast = useToast();
  const [rows, setRows] = useState(null); const [busy, setBusy] = useState(false); const [vault, setVault] = useState([]);
  useEffect(() => { api.get("/keys").then((d) => setVault(d.keys)).catch(() => {}); }, []);
  const fillFromVault = async (i, id) => {
    if (!id) return;
    try { const r = await api.post(`/keys/${id}/reveal`); set(i, { value: r.value }); toast.success("Filled from Saved Keys"); }
    catch (e) { toast.error(e.message); }
  };
  useEffect(() => {
    setRows(null);
    api.get("/env", { params: { owner: repo.owner.login, repo: repo.name } }).then((d) => setRows(d.vars.map((v) => ({ key: v.key, value: "", saved: true })))).catch(() => setRows([]));
  }, [repo.full_name]); // eslint-disable-line
  if (!rows) return <Skeleton h={60} />;

  const suggestions = (app?.env_vars || []).map((e) => e.name).filter((n) => !rows.some((r) => r.key === n));
  const set = (i, patch) => setRows((r) => r.map((x, j) => (j === i ? { ...x, ...patch } : x)));
  const save = async () => {
    setBusy(true);
    try {
      const vars = rows.filter((r) => r.key).map((r) => ({ key: r.key, value: r.value === "" && r.saved ? null : r.value }));
      await api.put("/env", { owner: repo.owner.login, repo: repo.name, vars });
      setRows((r) => r.filter((x) => x.key).map((x) => ({ key: x.key, value: "", saved: true }))); toast.success("Environment variables saved (encrypted)");
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };
  return (
    <div className="col" style={{ gap: 10 }}>
      <h3>Environment variables</h3>
      <p className="small muted">Stored encrypted and passed only to this repo's “Our Servers” deployments. Saved values are never shown again — leave a field empty to keep it.</p>
      {rows.map((r, i) => (
        <div key={i} className="row" style={{ flexWrap: "nowrap" }}>
          <input className="input mono" style={{ maxWidth: 240 }} placeholder="NAME" value={r.key} disabled={r.saved} onChange={(e) => set(i, { key: e.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, "") })} aria-label="Variable name" />
          <input className="input grow" type="password" autoComplete="off" placeholder={r.saved ? "•••••••• (saved)" : "value"} value={r.value} onChange={(e) => set(i, { value: e.target.value })} aria-label={`Value for ${r.key || "new variable"}`} />
          {!r.saved && vault.length > 0 && (
            <select className="select" style={{ width: 150 }} value="" onChange={(e) => fillFromVault(i, e.target.value)} aria-label="Fill from a saved key">
              <option value="">From vault…</option>{vault.map((k) => <option key={k.id} value={k.id}>{k.name}</option>)}
            </select>)}
          <button className="btn ghost icon" onClick={() => setRows((l) => l.filter((_, j) => j !== i))} aria-label="Remove variable"><Icon name="trash" size={15} /></button>
        </div>
      ))}
      <div className="row">
        <button className="btn sm" onClick={() => setRows((r) => [...r, { key: "", value: "", saved: false }])}><Icon name="plus" size={14} /> Add variable</button>
        {suggestions.slice(0, 6).map((n) => <button key={n} className="chip" onClick={() => setRows((r) => [...r, { key: n, value: "", saved: false }])}>+ {n}</button>)}
        <span className="grow" /><button className="btn primary sm" disabled={busy} onClick={save}>{busy ? <Spinner /> : null} Save</button>
      </div>
    </div>
  );
}

function LogModal({ project, onClose }) {
  const [log, setLog] = useState("Loading…"); const box = useRef(null);
  useEffect(() => {
    let live = true;
    const load = () => api.get(`/deploy/own/${project.id}/logs`).then((d) => { if (live) setLog(d.log); }).catch((e) => live && setLog(e.message));
    load(); const t = setInterval(load, 2500);
    return () => { live = false; clearInterval(t); };
  }, [project.id]);
  useEffect(() => { if (box.current) box.current.scrollTop = box.current.scrollHeight; }, [log]);
  return <Modal wide title={`Logs · ${project.name}`} onClose={onClose}><pre ref={box} className="code" style={{ maxHeight: "60vh" }}>{log}</pre></Modal>;
}

function OwnServers({ repo, app, apps, onSaved }) {
  const toast = useToast();
  const [data, setData] = useState(null); const [root, setRoot] = useState(app?.root ?? ""); const [busy, setBusy] = useState(false); const [logFor, setLogFor] = useState(null);
  useEffect(() => { setRoot(app?.root ?? ""); }, [app?.root]);

  const load = useCallback(() => api.get("/deploy/own").then(setData).catch(() => {}), []);
  useEffect(() => { load(); }, [load]);
  const anyBuilding = data?.projects?.some((p) => p.status === "building");
  useEffect(() => {
    const t = setInterval(load, anyBuilding ? 2500 : 12000);
    return () => clearInterval(t);
  }, [load, anyBuilding]);

  if (!data) return <Skeleton h={120} />;
  if (!data.enabled) return <div className="callout warn"><Icon name="alert" /><span><b>“Our Servers” is turned off on this server.</b> Use Render or Vercel above — or self-host GitSetLive with <code>OWN_SERVER_ENABLED=true</code> (see the README).</span></div>;

  const deploy = async () => {
    setBusy(true);
    try { await api.post("/deploy/own", { owner: repo.owner.login, repo: repo.name, root }); toast.info("Deployment started"); await load(); onSaved(); }
    catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };
  const stop = async (p, remove) => { try { await api.post(`/deploy/own/${p.id}/stop`, {}, { params: remove ? { remove: 1 } : {} }); load(); onSaved(); } catch (e) { toast.error(e.message); } };

  const mine = data.projects.filter((p) => p.owner === repo.owner.login && p.repo === repo.name);
  return (
    <div className="col" style={{ gap: 18 }}>
      <div className="callout warn"><Icon name="shield" /><span>Your code runs on this server's machine with a clean environment (our secrets are not passed to it). Deployments are temporary and stop automatically after a time limit. Only deploy code you trust.</span></div>
      <div className="card col">
        <h2>Deploy on Our Servers</h2>
        {apps.length > 1 && <label className="field">Which app?<select className="select" value={root} onChange={(e) => setRoot(e.target.value)}>{apps.map((a) => <option key={a.root} value={a.root}>{a.root || "(repository root)"} — {a.framework}</option>)}</select></label>}
        <EnvEditor repo={repo} app={app} />
        <div><button className="btn primary" disabled={busy || !app?.recommend?.own_server} onClick={deploy}>{busy ? <Spinner /> : <Icon name="rocket" size={16} />} Deploy now</button>
          {!app?.recommend?.own_server && <span className="small muted" style={{ marginLeft: 10 }}>This app type can't run here.</span>}</div>
      </div>

      <div className="card flush"><div className="card-head"><h2>Your running deployments</h2><button className="btn sm ghost" onClick={load}><Icon name="refresh" size={14} /></button></div>
        {!data.projects.length ? <EmptyState icon="rocket" title="Nothing running">Press “Deploy now” to start one.</EmptyState> : (
          <div className="list">{(mine.length ? mine : data.projects).map((p) => {
            const active = p.status === "building" || p.status === "running";
            return (
              <div key={p.id} className="col" style={{ gap: 8 }}>
                <div className="row between"><div className="row"><b>{p.name}</b>{p.root && <Badge>{p.root}</Badge>}{p.framework && <Badge>{p.framework}</Badge>}
                  <Badge kind={p.status === "running" ? "good" : p.status === "building" ? "info" : p.status === "failed" ? "bad" : ""}>{p.status === "building" && <Spinner />} {p.status}</Badge></div>
                  <div className="row">
                    <button className="btn sm" onClick={() => setLogFor(p)}><Icon name="terminal" size={14} /> Logs</button>
                    {active ? <button className="btn sm danger" onClick={() => stop(p, false)}><Icon name="stop" size={14} /> Stop</button> : <button className="btn sm" onClick={() => stop(p, true)}><Icon name="trash" size={14} /> Remove</button>}
                  </div></div>
                <div className="small muted">{p.message}{p.status === "running" && p.expires_at ? ` · ${timeLeft(p.expires_at)}` : ""}</div>
                {p.error && <pre className="code" style={{ maxHeight: 150, color: "#fca5a5" }}>{p.error}</pre>}
                {p.tunnel_url && <div className="row"><a href={p.tunnel_url} target="_blank" rel="noopener noreferrer" className="mono small">{p.tunnel_url}</a><CopyButton text={p.tunnel_url} /></div>}
                {p.tunnel_note && <div className="tiny faint">{p.tunnel_note}</div>}
                {p.status === "running" && p.local_url && <div className="tiny faint">Local: <span className="mono">{p.local_url}</span></div>}
              </div>);
          })}</div>)}
      </div>
      {logFor && <LogModal project={logFor} onClose={() => setLogFor(null)} />}
    </div>
  );
}

function History({ items, reload }) {
  const toast = useToast(); const [reach, setReach] = useState({});
  const check = async (d) => { setReach((r) => ({ ...r, [d.id]: "…" })); const ok = await checkReachable(d.live_url); setReach((r) => ({ ...r, [d.id]: ok ? "up" : "down" })); };
  const remove = async (id) => { try { await api.del(`/deployments/${id}`); reload(); } catch (e) { toast.error(e.message); } };
  if (!items) return <Skeleton h={80} />;
  if (!items.length) return <EmptyState icon="rocket" title="No deployments recorded yet">Deploys you make here or record after using Render/Vercel will be listed.</EmptyState>;
  return (
    <div className="list">{items.map((d) => (
      <div key={d.id} className="row between" style={{ flexWrap: "nowrap" }}>
        <div className="grow"><b>{d.repo_name}</b> <Badge>{d.provider || "—"}</Badge> <Badge kind={d.status === "live" ? "good" : d.status === "failed" ? "bad" : d.status === "deploying" ? "info" : ""}>{d.status}</Badge>
          <div className="tiny muted">{timeAgo(d.created_at)}{d.live_url && <> · <a href={d.live_url} target="_blank" rel="noopener noreferrer">{d.live_url}</a></>}</div></div>
        {d.live_url && d.provider !== "own" && <button className="btn sm" onClick={() => check(d)}>{reach[d.id] === "up" ? <><span className="dot good" /> Reachable</> : reach[d.id] === "down" ? <><span className="dot bad" /> Not reachable</> : reach[d.id] ? <Spinner /> : "Check"}</button>}
        <button className="btn sm ghost" onClick={() => remove(d.id)} aria-label="Remove from history"><Icon name="trash" size={14} /></button>
      </div>))}</div>
  );
}

export default function Deploy() {
  const toast = useToast();
  const { repos, loading, error, reload } = useRepos();
  const [repo, setRepo] = useSelectedRepo(repos);
  const [analysis, setAnalysis] = useState(null); const [analyzing, setAnalyzing] = useState(false); const [aErr, setAErr] = useState("");
  const [appIdx, setAppIdx] = useState(0); const [tab, setTab] = useState("render");
  const [history, setHistory] = useState(null);

  const loadHistory = useCallback(() => api.get("/deployments").then((d) => setHistory(d.deployments)).catch(() => setHistory([])), []);
  useEffect(() => { loadHistory(); }, [loadHistory]);

  useEffect(() => {
    if (!repo) return;
    let live = true;
    setAnalysis(null); setAErr(""); setAnalyzing(true); setAppIdx(0);
    api.get("/analyze", { params: { owner: repo.owner.login, repo: repo.name }, timeout: 120000 })
      .then((a) => live && setAnalysis(a)).catch((e) => live && setAErr(e.message)).finally(() => live && setAnalyzing(false));
    return () => { live = false; };
  }, [repo?.full_name]); // eslint-disable-line

  const app = analysis?.apps?.[appIdx];
  const blockers = app?.readiness?.filter((r) => !r.ok && r.level === "required") || [];

  return (
    <>
      <div className="page-header"><div><h1>Deploy</h1><p>Check that your repo is ready, then get the exact settings for Render or Vercel — or run it on our servers for a quick shareable link.</p></div></div>
      <div className="card"><RepoPicker repos={repos} loading={loading} error={error} onReload={reload} value={repo} onChange={setRepo} /></div>

      {!repo && <EmptyState icon="rocket" title="Choose a repository to deploy">We'll detect your stack and tell you exactly what to do.</EmptyState>}
      {repo && analyzing && <div className="card row" style={{ marginTop: 18 }}><Spinner /> <span className="muted">Analysing {repo.name}…</span></div>}
      {aErr && <div className="callout bad" style={{ marginTop: 18 }}><Icon name="alert" /> {aErr}</div>}

      {analysis && !analyzing && (
        <div className="col" style={{ marginTop: 18, gap: 18 }}>
          {!analysis.apps.length ? <div className="callout warn"><Icon name="alert" /><span>We couldn't find anything deployable (no <code>package.json</code>, <code>requirements.txt</code> or <code>index.html</code>). Add one, or use AI Builder to scaffold the project.</span></div> : (
            <>
              {analysis.apps.length > 1 && (
                <div className="callout info"><Icon name="branch" /><div className="grow"><b>This repository contains {analysis.apps.length} apps.</b> Choose the one you want to deploy:
                  <div className="chips" style={{ marginTop: 8 }}>{analysis.apps.map((a, i) => <button key={a.root} className={`chip ${i === appIdx ? "on" : ""}`} onClick={() => setAppIdx(i)}>{a.root || "root"} · {a.framework}</button>)}</div></div></div>
              )}
              <div className="card">
                <div className="row between" style={{ marginBottom: 6 }}><h2>Pre-flight check <span className="muted small">· {app.type} / {app.framework}</span></h2>
                  <Link className="btn sm" href={`/scan?repo=${encodeURIComponent(repo.full_name)}`}><Icon name="scan" size={14} /> Scan & fix</Link></div>
                {blockers.length > 0 ? <div className="callout bad" style={{ margin: "10px 0" }}><Icon name="alert" /><span><b>{blockers.length} thing{blockers.length > 1 ? "s" : ""} will stop this deploy.</b> Fix them with Scan & Fix first.</span></div>
                  : <div className="callout good" style={{ margin: "10px 0" }}><Icon name="check" /><span>No blockers found — you're ready to deploy.</span></div>}
                {app.readiness.map((r) => (
                  <div key={r.id} className={`check ${r.ok ? "" : "no"} ${r.level === "recommended" ? "rec" : ""}`}>
                    <span className="mark"><Icon name={r.ok ? "check" : r.level === "recommended" ? "alert" : "x"} size={13} /></span>
                    <div><b className="small">{r.label}</b>{r.level === "recommended" && <span className="tiny faint"> · recommended</span>}<div className="tiny muted">{r.detail}</div></div>
                  </div>))}
              </div>

              <div>
                <div className="tabs">{[["render", "Render"], ["vercel", "Vercel"], ["own", "Our Servers"]].map(([k, l]) => <button key={k} className={`tab ${tab === k ? "on" : ""}`} onClick={() => setTab(k)}>{l}</button>)}</div>
                {tab === "own" ? <OwnServers repo={repo} app={app} apps={analysis.apps} onSaved={loadHistory} /> : <PlatformTab key={tab + appIdx} app={app} repo={repo} provider={tab} onSaved={loadHistory} />}
              </div>
            </>
          )}
        </div>
      )}

      <div className="card flush" style={{ marginTop: 24 }}><div className="card-head"><h2>Deployment history</h2></div><History items={history} reload={loadHistory} /></div>
    </>
  );
}
Deploy.title = "Deploy";

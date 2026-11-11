import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../lib/api";
import { useToast } from "../lib/toast";
import { timeAgo, gradeColor } from "../lib/format";
import { Badge, DiffView, EmptyState, Icon, RepoPicker, ScoreRing, Spinner, useRepos, useSelectedRepo } from "../components/ui";

const SEV = { critical: ["bad", "Critical"], warning: ["warn", "Warning"], info: ["info", "Tip"] };

function Finding({ f, open, toggleOpen, checked, onCheck }) {
  const [kind, label] = SEV[f.severity] || SEV.info;
  return (
    <div className={`finding ${f.severity}`}>
      <div className="finding-head" onClick={toggleOpen} role="button" tabIndex={0} aria-expanded={open}
        onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), toggleOpen())}>
        {f.fixable ? <input type="checkbox" checked={checked} onClick={(e) => e.stopPropagation()} onChange={(e) => onCheck(e.target.checked)} aria-label={`Include fix: ${f.title}`} style={{ marginTop: 4, width: 17, height: 17, accentColor: "var(--brand)" }} />
          : <span style={{ width: 17 }} />}
        <div className="grow">
          <div className="row" style={{ gap: 8, marginBottom: 4 }}>
            <Badge kind={kind}>{label}</Badge><Badge>{f.category}</Badge>
            {f.source === "ai" && <Badge kind="info" title="Suggested by AI and verified against your real file"><Icon name="sparkle" size={11} /> AI · verified</Badge>}
            {f.fixable ? <Badge kind="good"><Icon name="check" size={11} /> Auto-fix</Badge> : <Badge title="Needs a manual change">Manual</Badge>}
          </div>
          <b>{f.title}</b>
          {f.file && <div className="tiny muted mono truncate">{f.file}{f.line ? `:${f.line}` : ""}</div>}
        </div>
        <Icon name="chevron" size={16} style={{ transform: open ? "rotate(90deg)" : "none", color: "var(--muted)", marginTop: 4 }} />
      </div>
      {open && (
        <div className="finding-body">
          {f.detail && <p className="muted small">{f.detail}</p>}
          {f.line_context && <pre className="code" style={{ maxHeight: 120 }}>{f.line_context}</pre>}
          {f.diff && <><div className="tiny muted">Proposed change</div><DiffView diff={f.diff} /></>}
        </div>
      )}
    </div>
  );
}

export default function Scan() {
  const toast = useToast();
  const { repos, loading: reposLoading, error, reload } = useRepos();
  const [repo, setRepo] = useState(null);
  const [selectedRepo, chooseRepo] = useSelectedRepo(repos);
  const [running, setRunning] = useState(false); const [elapsed, setElapsed] = useState(0);
  const [result, setResult] = useState(null); const [history, setHistory] = useState([]);
  const [checked, setChecked] = useState(new Set()); const [openIds, setOpenIds] = useState(new Set());
  const [sev, setSev] = useState("all"); const [applying, setApplying] = useState(false); const [applied, setApplied] = useState(null);

  const current = selectedRepo || repo;
  const owner = current?.owner.login, name = current?.name;

  const loadHistory = useCallback(() => {
    if (!current) return;
    api.get("/scans", { params: { owner, repo: name } }).then(setHistory).catch(() => setHistory([]));
  }, [current, owner, name]);
  useEffect(() => { setResult(null); setApplied(null); loadHistory(); }, [current?.full_name]); // eslint-disable-line

  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(t);
  }, [running]);

  const show = (res) => {
    setResult(res); setApplied(null);
    setChecked(new Set(res.findings.filter((f) => f.fixable && f.severity !== "info").map((f) => f.id)));
    setOpenIds(new Set(res.findings.filter((f) => f.severity === "critical").slice(0, 3).map((f) => f.id)));
  };

  const run = async () => {
    setRunning(true); setElapsed(0); setResult(null); setApplied(null);
    try { show(await api.post("/scan", { owner, repo: name }, { timeout: 180000 })); loadHistory(); }
    catch (e) { toast.error(e.message); } finally { setRunning(false); }
  };

  const openOld = async (id) => {
    try { show(await api.get(`/scans/${id}`)); } catch (e) { toast.error(e.message); }
  };

  const apply = async () => {
    setApplying(true);
    try {
      const r = await api.post("/scan/apply", { owner, repo: name, scan_id: result.scan_id, finding_ids: [...checked] }, { timeout: 120000 });
      setApplied(r); toast.success("Pull request created");
    } catch (e) { toast.error(e.message); } finally { setApplying(false); }
  };

  const findings = useMemo(() => (result?.findings || []).filter((f) => sev === "all" || f.severity === sev), [result, sev]);
  const fixableCount = (result?.findings || []).filter((f) => f.fixable).length;

  return (
    <>
      <div className="page-header"><div><h1>Scan & Fix</h1><p>Finds leaked secrets, crashes, bad server settings and missing packages. Every issue is checked against your real code, and fixes arrive as a pull request you review.</p></div></div>

      <div className="card">
        <div className="row">
          <RepoPicker repos={repos} loading={reposLoading} error={error} onReload={reload} value={current} onChange={(r) => { chooseRepo(r); setRepo(r); }} />
          <button className="btn primary" disabled={!current || running} onClick={run}>{running ? <Spinner /> : <Icon name="scan" size={16} />} {running ? "Scanning…" : "Run scan"}</button>
        </div>
        {running && <p className="small muted" style={{ marginTop: 14 }}>Downloading your code, running checks and asking the AI reviewer… usually 10–40 seconds. <span className="faint">({elapsed}s)</span></p>}
      </div>

      {!result && !running && history.length > 0 && (
        <div className="card flush" style={{ marginTop: 18 }}>
          <div className="card-head"><h2>Previous scans</h2></div>
          <div className="list">{history.map((h) => (
            <div key={h.id} className="row between"><span><b style={{ color: gradeColor(h.score) }}>{h.score}</b> <span className="muted small">· grade {h.grade} · {h.counts.critical || 0} critical, {h.counts.warning || 0} warnings</span></span>
              <span className="row"><span className="tiny faint">{timeAgo(h.created_at)}</span><button className="btn sm" onClick={() => openOld(h.id)}>Open</button></span></div>))}</div>
        </div>
      )}

      {!current && !running && <EmptyState icon="scan" title="Choose a repository to begin">Pick one above, then press “Run scan”. Nothing is changed until you approve a pull request.</EmptyState>}

      {result && (
        <div style={{ marginTop: 20 }}>
          <div className="card row" style={{ gap: 28, alignItems: "center" }}>
            <ScoreRing score={result.score} grade={result.grade} />
            <div className="grow col" style={{ gap: 10 }}>
              <h2>{result.score >= 90 ? "Looking great" : result.score >= 60 ? "A few things to fix" : "Needs attention before you deploy"}</h2>
              <div className="chips">
                {[["all", `All (${result.findings.length})`], ["critical", `Critical (${result.counts.critical || 0})`], ["warning", `Warnings (${result.counts.warning || 0})`], ["info", `Tips (${result.counts.info || 0})`]].map(([k, l]) =>
                  <button key={k} className={`chip ${sev === k ? "on" : ""}`} onClick={() => setSev(k)}>{l}</button>)}
              </div>
              <p className="tiny muted">{result.files_scanned} files analysed{result.truncated ? " (large repo — some files skipped)" : ""} · {fixableCount} can be fixed automatically</p>
            </div>
          </div>
          {!result.ai.ok && <div className="callout warn" style={{ marginTop: 14 }}><Icon name="alert" /><span><b>AI review unavailable</b> — showing automated checks only. {result.ai.note}</span></div>}

          {applied && (
            <div className="callout good" style={{ marginTop: 14 }}><Icon name="check" /><div>
              <b>{applied.files_changed} file(s) fixed.</b> {applied.pr_url ? <>Review and merge: <a href={applied.pr_url} target="_blank" rel="noopener noreferrer">{applied.pr_url}</a></> : "Committed."}
              {applied.skipped?.length > 0 && <div className="small muted" style={{ marginTop: 6 }}>Skipped: {applied.skipped.map((s) => `${s.file} (${s.reason})`).join("; ")}</div>}
              <div className="small muted" style={{ marginTop: 6 }}>After merging, run the scan again to see your new score.</div></div></div>
          )}

          <div className="col" style={{ marginTop: 16 }}>
            {!findings.length && <EmptyState icon="check" title="Nothing here">No findings in this category.</EmptyState>}
            {findings.map((f) => (
              <Finding key={f.id} f={f} open={openIds.has(f.id)} checked={checked.has(f.id)}
                toggleOpen={() => setOpenIds((s) => { const n = new Set(s); n.has(f.id) ? n.delete(f.id) : n.add(f.id); return n; })}
                onCheck={(on) => setChecked((s) => { const n = new Set(s); on ? n.add(f.id) : n.delete(f.id); return n; })} />
            ))}
          </div>

          {fixableCount > 0 && !applied && (
            <div className="stickybar">
              <span className="small"><b>{checked.size}</b> fix{checked.size === 1 ? "" : "es"} selected · will open a pull request on a new branch</span>
              <div className="row">
                <button className="btn sm" onClick={() => setChecked(new Set(result.findings.filter((f) => f.fixable).map((f) => f.id)))}>Select all</button>
                <button className="btn sm" onClick={() => setChecked(new Set())}>None</button>
                <button className="btn primary" disabled={!checked.size || applying} onClick={apply}>{applying ? <Spinner /> : <Icon name="branch" size={16} />} Create pull request</button>
              </div>
            </div>
          )}
        </div>
      )}
    </>
  );
}
Scan.title = "Scan & Fix";

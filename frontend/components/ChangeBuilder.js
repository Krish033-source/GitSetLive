import { useState } from "react";
import { api } from "../lib/api";
import { useToast } from "../lib/toast";
import { Badge, DiffView, EmptyState, Icon, RepoPicker, Spinner, useRepos, useSelectedRepo } from "./ui";

function ChangeCard({ c, included, onToggle, onEdit }) {
  const [view, setView] = useState("diff");
  return (
    <div className="card flush">
      <div className="card-head" style={{ gap: 10 }}>
        <label className="switch grow" style={{ minWidth: 0 }}>
          <input type="checkbox" checked={included} onChange={onToggle} />
          <span className="mono truncate">{c.path}</span>
        </label>
        <Badge kind={c.action === "create" ? "good" : "info"}>{c.action === "create" ? "new file" : "modified"}</Badge>
        {c.sensitive && <Badge kind="warn" title="Touches CI or environment files — review carefully"><Icon name="shield" size={11} /> sensitive</Badge>}
      </div>
      <div style={{ padding: 16 }} className="col">
        {c.reason && <p className="small muted">{c.reason}</p>}
        <div className="tabs" style={{ marginBottom: 0 }}>
          <button className={`tab ${view === "diff" ? "on" : ""}`} onClick={() => setView("diff")}>Changes</button>
          <button className={`tab ${view === "edit" ? "on" : ""}`} onClick={() => setView("edit")}>Edit full file</button>
        </div>
        {view === "diff" ? <DiffView diff={c.diff} /> : <textarea className="textarea code" spellCheck={false} value={c.content} onChange={(e) => onEdit(e.target.value)} aria-label={`Contents of ${c.path}`} />}
      </div>
    </div>
  );
}

// Shared by "AI Builder" and "File Templates": prompt -> reviewed diff -> pull request.
export default function ChangeBuilder({ presets, placeholder, intro }) {
  const toast = useToast();
  const { repos, loading, error, reload } = useRepos();
  const [repo, setRepo] = useSelectedRepo(repos);
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false); const [plan, setPlan] = useState(null);
  const [inc, setInc] = useState({}); const [edits, setEdits] = useState({});
  const [message, setMessage] = useState(""); const [mode, setMode] = useState("pr");
  const [committing, setCommitting] = useState(false); const [done, setDone] = useState(null);

  const propose = async () => {
    setBusy(true); setPlan(null); setDone(null);
    try {
      const p = await api.post("/ai/propose", { owner: repo.owner.login, repo: repo.name, prompt }, { timeout: 180000 });
      setPlan(p); setEdits({}); setInc(Object.fromEntries(p.changes.map((c) => [c.path, !c.sensitive])));
      setMessage(`AI: ${prompt.replace(/\s+/g, " ").slice(0, 70)}`);
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };

  const chosen = plan ? plan.changes.filter((c) => inc[c.path]) : [];
  const commit = async () => {
    setCommitting(true);
    try {
      const r = await api.post("/ai/commit", {
        owner: repo.owner.login, repo: repo.name, mode, message: message.trim() || "AI changes", body: plan.summary,
        changes: chosen.map((c) => ({ path: c.path, content: edits[c.path] ?? c.content })),
      }, { timeout: 120000 });
      setDone(r); toast.success(mode === "pr" ? "Pull request created" : "Committed");
    } catch (e) { toast.error(e.message); } finally { setCommitting(false); }
  };

  return (
    <>
      <div className="card col">
        {intro}
        <RepoPicker repos={repos} loading={loading} error={error} onReload={reload} value={repo} onChange={(r) => { setRepo(r); setPlan(null); setDone(null); }} />
        <div className="chips">{presets.map((p) => <button key={p.label} className="chip" onClick={() => setPrompt(p.prompt)}>{p.label}</button>)}</div>
        <label className="field">What should change?
          <textarea className="textarea" value={prompt} maxLength={4000} onChange={(e) => setPrompt(e.target.value)} placeholder={placeholder} />
          <span className="hint">The AI reads your repository first, so it can match your stack and style. {prompt.length}/4000</span></label>
        <div className="row"><button className="btn primary" disabled={!repo || prompt.trim().length < 3 || busy} onClick={propose}>{busy ? <Spinner /> : <Icon name="sparkle" size={16} />} {busy ? "Working on it…" : "Generate changes"}</button>
          {busy && <span className="small muted">Reading your code and writing changes — up to a minute.</span>}</div>
      </div>

      {!plan && !busy && !done && <EmptyState icon="sparkle" title="Nothing generated yet">Describe the change above. You'll review every line before anything is sent to GitHub.</EmptyState>}

      {plan && !done && (
        <div className="col" style={{ marginTop: 20 }}>
          <div className="callout info"><Icon name="sparkle" /><span><b>Summary:</b> {plan.summary || "Proposed changes below."}</span></div>
          {plan.warnings?.length > 0 && <div className="callout warn"><Icon name="alert" /><div><b>Some suggestions were dropped</b> because they didn't match your files:<ul style={{ margin: "6px 0 0", paddingLeft: 18 }}>{plan.warnings.map((w, i) => <li key={i} className="small">{w}</li>)}</ul></div></div>}
          {plan.changes.map((c) => <ChangeCard key={c.path} c={{ ...c, content: edits[c.path] ?? c.content }} included={!!inc[c.path]}
            onToggle={() => setInc((s) => ({ ...s, [c.path]: !s[c.path] }))} onEdit={(v) => setEdits((s) => ({ ...s, [c.path]: v }))} />)}

          <div className="card col">
            <h3>Send to GitHub</h3>
            <label className="field">Title / commit message<input className="input" value={message} maxLength={200} onChange={(e) => setMessage(e.target.value)} /></label>
            <div className="col" style={{ gap: 8 }}>
              <label className="switch"><input type="radio" name="mode" checked={mode === "pr"} onChange={() => setMode("pr")} /> <span><b>Open a pull request</b> <span className="muted small">(recommended — you review and merge on GitHub)</span></span></label>
              <label className="switch"><input type="radio" name="mode" checked={mode === "direct"} onChange={() => setMode("direct")} /> <span><b>Commit straight to {repo.default_branch}</b> <span className="muted small">(goes live immediately)</span></span></label>
            </div>
            {mode === "direct" && <div className="callout warn"><Icon name="alert" /><span>This changes your main branch right away. If this repo auto-deploys, the site will update too.</span></div>}
            <div><button className="btn primary" disabled={!chosen.length || committing || message.trim().length < 3} onClick={commit}>{committing ? <Spinner /> : <Icon name="branch" size={16} />} {mode === "pr" ? "Create pull request" : "Commit"} ({chosen.length} file{chosen.length === 1 ? "" : "s"})</button></div>
          </div>
        </div>
      )}

      {done && (
        <div className="callout good" style={{ marginTop: 20 }}><Icon name="check" /><div>
          {done.pr_url ? <><b>Pull request ready.</b> <a href={done.pr_url} target="_blank" rel="noopener noreferrer">Open it on GitHub →</a></>
            : <><b>Committed.</b> <a href={done.commit_url} target="_blank" rel="noopener noreferrer">View commit →</a></>}
          <div className="small muted" style={{ marginTop: 6 }}><button className="btn sm" onClick={() => { setPlan(null); setDone(null); setPrompt(""); }}>Make another change</button></div></div></div>
      )}
    </>
  );
}

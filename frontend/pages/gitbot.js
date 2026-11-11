import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { useToast } from "../lib/toast";
import { Badge, EmptyState, Icon, Markdown, RepoPicker, useRepos, useSelectedRepo } from "../components/ui";

const SUGGESTIONS = [
  "What does this project do? Explain it simply.",
  "How do I run this project locally?",
  "Which environment variables does it need?",
  "Where is the login / authentication code?",
  "What are the biggest risks before deploying this?",
];

export default function GitBot() {
  const toast = useToast();
  const { repos, loading, error, reload } = useRepos();
  const [repo, setRepo] = useSelectedRepo(repos);
  const [msgs, setMsgs] = useState([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef(null);

  useEffect(() => { setMsgs([]); }, [repo?.full_name]);
  useEffect(() => { end.current?.scrollIntoView?.({ behavior: "smooth", block: "end" }); }, [msgs, busy]);

  const send = async (text) => {
    const q = (text ?? input).trim();
    if (!q || busy || !repo) return;
    const history = msgs.map((m) => ({ role: m.role, content: m.content }));
    setMsgs((m) => [...m, { role: "user", content: q }]); setInput(""); setBusy(true);
    try {
      const r = await api.post("/ai/chat", { owner: repo.owner.login, repo: repo.name, question: q, history }, { timeout: 120000 });
      setMsgs((m) => [...m, { role: "assistant", content: r.answer, files: r.files_used }]);
    } catch (e) {
      toast.error(e.message);
      setMsgs((m) => [...m, { role: "assistant", content: `⚠️ ${e.message}`, error: true }]);
    } finally { setBusy(false); }
  };

  return (
    <>
      <div className="page-header"><div><h1>GitBot</h1><p>Ask anything about a repository in plain language. Answers come only from your actual code, and GitBot shows which files it used.</p></div>
        {msgs.length > 0 && <button className="btn" onClick={() => setMsgs([])}>Clear chat</button>}</div>

      <div className="card"><RepoPicker repos={repos} loading={loading} error={error} onReload={reload} value={repo} onChange={setRepo} /></div>

      {!repo ? <EmptyState icon="bot" title="Choose a repository">GitBot reads the repo you pick and answers questions about it.</EmptyState> : (
        <>
          <div className="chat" style={{ margin: "22px 0 110px" }}>
            {!msgs.length && (
              <div className="card"><h3 style={{ marginBottom: 12 }}>Try asking</h3>
                <div className="chips">{SUGGESTIONS.map((s) => <button key={s} className="chip" onClick={() => send(s)}>{s}</button>)}</div></div>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={`msg ${m.role}`}>
                {m.role === "assistant" && <span className="ava"><img src="/logo.svg" alt="" /></span>}
                <div className="bubble" style={m.error ? { borderColor: "var(--bad)" } : undefined}>
                  {m.role === "assistant" ? <Markdown text={m.content} /> : <p style={{ whiteSpace: "pre-wrap" }}>{m.content}</p>}
                  {m.files?.length > 0 && <div className="row" style={{ marginTop: 10, gap: 6 }}><span className="tiny faint">Sources:</span>{m.files.map((f) => <Badge key={f}><span className="mono">{f}</span></Badge>)}</div>}
                </div>
              </div>
            ))}
            {busy && <div className="msg"><span className="ava"><img src="/logo.svg" alt="" /></span><div className="bubble typing" aria-label="GitBot is typing"><span /><span /><span /></div></div>}
            <div ref={end} />
          </div>

          <div className="stickybar" style={{ bottom: 18 }}>
            <textarea className="textarea grow" style={{ minHeight: 48, maxHeight: 160, resize: "none" }} rows={1} value={input} placeholder={`Ask about ${repo.name}…  (Enter to send, Shift+Enter for a new line)`}
              maxLength={2000} onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); } }} aria-label="Your question" />
            <button className="btn primary" disabled={busy || !input.trim()} onClick={() => send()}><Icon name="send" size={16} /> Send</button>
          </div>
        </>
      )}
    </>
  );
}
GitBot.title = "GitBot";

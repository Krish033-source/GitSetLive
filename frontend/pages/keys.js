import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { useToast } from "../lib/toast";
import { timeAgo } from "../lib/format";
import { Badge, CopyButton, EmptyState, Icon, Modal, Skeleton, Spinner } from "../components/ui";

const PRESETS = ["GROQ_API_KEY", "RENDER_API_KEY", "VERCEL_TOKEN", "GITHUB_TOKEN", "OPENAI_API_KEY", "NETLIFY_TOKEN", "DATABASE_URL"];

function KeyRow({ k, onDelete, onEdit }) {
  const toast = useToast();
  const [value, setValue] = useState(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef(null);

  useEffect(() => () => clearTimeout(timer.current), []);
  const hide = () => { clearTimeout(timer.current); setValue(null); };

  const fetchValue = async () => { const r = await api.post(`/keys/${k.id}/reveal`); return r.value; };
  const reveal = async () => {
    setBusy(true);
    try { setValue(await fetchValue()); timer.current = setTimeout(() => setValue(null), 15000); }
    catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };
  const copy = async () => {
    setBusy(true);
    try { await navigator.clipboard.writeText(await fetchValue()); toast.success(`${k.name} copied`); }
    catch (e) { toast.error(e.message || "Couldn't copy"); } finally { setBusy(false); }
  };

  return (
    <div className="col" style={{ gap: 8 }}>
      <div className="row between" style={{ flexWrap: "nowrap" }}>
        <div className="grow">
          <div className="row" style={{ gap: 8 }}><Icon name="key" size={15} style={{ color: "var(--brand)" }} /><span className="keyname truncate">{k.name}</span><Badge><span className="mono">{k.hint}</span></Badge></div>
          <div className="tiny muted" style={{ marginTop: 3 }}>{k.note ? `${k.note} · ` : ""}saved {timeAgo(k.saved_at)}</div>
        </div>
        <div className="row" style={{ gap: 6, flexWrap: "nowrap" }}>
          <button className="btn sm" disabled={busy} onClick={value ? hide : reveal} aria-label={value ? `Hide ${k.name}` : `Reveal ${k.name}`}>
            {busy ? <Spinner /> : <Icon name={value ? "eyeoff" : "eye"} size={14} />} {value ? "Hide" : "Reveal"}</button>
          <button className="btn sm" disabled={busy} onClick={copy} aria-label={`Copy ${k.name}`}><Icon name="copy" size={14} /> Copy</button>
          <button className="btn sm ghost" onClick={() => onEdit(k)} aria-label={`Replace ${k.name}`}><Icon name="refresh" size={14} /></button>
          <button className="btn sm ghost" onClick={() => onDelete(k)} aria-label={`Delete ${k.name}`}><Icon name="trash" size={14} /></button>
        </div>
      </div>
      {value && (
        <div className="row" style={{ gap: 8 }}>
          <pre className="code grow" style={{ margin: 0, padding: "9px 12px", maxHeight: 120, whiteSpace: "pre-wrap", wordBreak: "break-all" }}>{value}</pre>
          <CopyButton text={value} /><span className="tiny faint">hides in 15s</span>
        </div>
      )}
    </div>
  );
}

export default function SavedKeys() {
  const toast = useToast();
  const [keys, setKeys] = useState(null);
  const [name, setName] = useState(""); const [value, setValue] = useState(""); const [note, setNote] = useState("");
  const [show, setShow] = useState(false); const [busy, setBusy] = useState(false); const [del, setDel] = useState(null);
  const formRef = useRef(null);

  const load = useCallback(() => api.get("/keys").then((d) => setKeys(d.keys)).catch((e) => { toast.error(e.message); setKeys([]); }), [toast]);
  useEffect(() => { load(); }, []); // eslint-disable-line

  const exists = keys?.some((k) => k.name.toLowerCase() === name.trim().toLowerCase());
  const valid = /^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,59}$/.test(name.trim()) && value.trim().length > 0;

  const save = async () => {
    setBusy(true);
    try {
      const r = await api.put("/keys", { name: name.trim(), value, note: note.trim() || null });
      toast.success(r.created ? "Key saved" : "Key updated");
      setName(""); setValue(""); setNote(""); setShow(false); load();
    } catch (e) { toast.error(e.message); } finally { setBusy(false); }
  };
  const remove = async () => {
    try { await api.del(`/keys/${del.id}`); toast.success(`Deleted ${del.name}`); setDel(null); load(); }
    catch (e) { toast.error(e.message); }
  };
  const edit = (k) => { setName(k.name); setNote(k.note || ""); setValue(""); formRef.current?.scrollIntoView?.({ behavior: "smooth" }); };

  return (
    <>
      <div className="page-header"><div><span className="eyebrow">Vault</span><h1 style={{ marginTop: 8 }}>Saved Keys</h1>
        <p>Keep your API keys and tokens in one place. Copy them when you need them, or drop them into a deployment's environment variables.</p></div></div>

      <div className="callout info" style={{ marginBottom: 18 }}><Icon name="shield" />
        <span>Keys are <b>encrypted</b> before they are stored, and the list only ever shows the last 4 characters. A key is shown only when you press <b>Reveal</b> or <b>Copy</b>. The server can decrypt them (that is what makes reuse possible), so keep only keys you can rotate, and never paste keys for accounts you can't afford to lose.</span></div>

      <div className="card col" ref={formRef}>
        <h2>{exists ? "Replace a key" : "Add a key"}</h2>
        <div className="chips">{PRESETS.map((p) => <button key={p} type="button" className={`chip ${name === p ? "on" : ""}`} onClick={() => setName(p)}>{p}</button>)}</div>
        <div className="grid two" style={{ gap: 12 }}>
          <label className="field">Name<input className="input mono" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} placeholder="e.g. GROQ_API_KEY" autoComplete="off" /></label>
          <label className="field">Note (optional)<input className="input" value={note} maxLength={120} onChange={(e) => setNote(e.target.value)} placeholder="e.g. personal account" autoComplete="off" /></label>
        </div>
        <label className="field">Value
          <div className="row" style={{ flexWrap: "nowrap" }}>
            <input className="input mono grow" type={show ? "text" : "password"} value={value} maxLength={4000} onChange={(e) => setValue(e.target.value)} placeholder="paste the key here" autoComplete="off" spellCheck={false} />
            <button type="button" className="btn icon" onClick={() => setShow((s) => !s)} aria-label={show ? "Hide value" : "Show value"}><Icon name={show ? "eyeoff" : "eye"} size={16} /></button>
          </div></label>
        <div className="row">
          <button className="btn primary" disabled={!valid || busy} onClick={save}>{busy ? <Spinner /> : <Icon name="key" size={16} />} {exists ? "Replace key" : "Save key"}</button>
          {exists && <span className="small muted">A key named “{name.trim()}” already exists. Saving will replace its value.</span>}
        </div>
      </div>

      <div className="card flush" style={{ marginTop: 20 }}>
        <div className="card-head"><h2>Your keys</h2>{keys && <span className="small muted">{keys.length} saved</span>}</div>
        {!keys ? <div style={{ padding: 20 }}><Skeleton h={44} /></div>
          : !keys.length ? <EmptyState icon="key" title="No keys saved yet">Add your first key above. Handy ones: your Groq key, Render API key and Vercel token.</EmptyState>
          : <div className="list">{keys.map((k) => <KeyRow key={k.id} k={k} onDelete={setDel} onEdit={edit} />)}</div>}
      </div>

      {del && (
        <Modal title={`Delete ${del.name}?`} onClose={() => setDel(null)} footer={<><button className="btn" onClick={() => setDel(null)}>Cancel</button><button className="btn danger" onClick={remove}><Icon name="trash" size={16} /> Delete key</button></>}>
          <p className="muted">This removes the saved copy from GitSetLive. It does not revoke the key at its provider; do that there if the key was exposed.</p>
        </Modal>
      )}
    </>
  );
}
SavedKeys.title = "Saved Keys";

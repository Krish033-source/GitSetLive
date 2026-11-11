import { useCallback, useEffect, useState } from "react";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import { timeAgo } from "../lib/format";
import { Badge, EmptyState, Icon, Skeleton, Spinner } from "../components/ui";

const ROLE_HELP = { admin: "Manage members and everything else", developer: "Create and manage deployments", viewer: "Read-only access" };

export default function Workspaces() {
  const { user, logout } = useAuth();
  const toast = useToast();
  const [list, setList] = useState(null); const [sel, setSel] = useState(null);
  const [members, setMembers] = useState(null); const [deps, setDeps] = useState(null);
  const [name, setName] = useState(""); const [ident, setIdent] = useState(""); const [role, setRole] = useState("developer"); const [busy, setBusy] = useState(false);

  const loadList = useCallback(async (keep) => {
    try { const { workspaces } = await api.get("/workspaces"); setList(workspaces); setSel((s) => keep && s && workspaces.find((w) => w.id === s) ? s : workspaces[0]?.id || null); }
    catch (e) { toast.error(e.message); setList([]); }
  }, [toast]);
  useEffect(() => { loadList(false); }, []); // eslint-disable-line

  const loadWs = useCallback(() => {
    if (!sel) return;
    setMembers(null); setDeps(null);
    api.get(`/workspaces/${sel}/members`).then((d) => setMembers(d.members)).catch((e) => { toast.error(e.message); setMembers([]); });
    api.get("/deployments", { params: { workspace_id: sel } }).then((d) => setDeps(d.deployments)).catch(() => setDeps([]));
  }, [sel, toast]);
  useEffect(loadWs, [loadWs]);

  const current = list?.find((w) => w.id === sel);
  const isAdmin = current?.role === "admin";
  const run = async (fn, ok) => { setBusy(true); try { await fn(); if (ok) toast.success(ok); } catch (e) { toast.error(e.message); } finally { setBusy(false); } };

  return (
    <>
      <div className="page-header"><div><h1>Workspaces</h1><p>Share projects with teammates. Admins manage people, developers manage deployments, viewers can look but not touch.</p></div></div>

      <div className="grid" style={{ gridTemplateColumns: "minmax(240px, 300px) 1fr", alignItems: "start" }}>
        <div className="col">
          <div className="card flush">
            <div className="card-head"><h3>Your workspaces</h3></div>
            {!list ? <div style={{ padding: 16 }}><Skeleton h={40} /></div> : (
              <div className="list">{list.map((w) => (
                <div key={w.id} onClick={() => setSel(w.id)} role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && setSel(w.id)}
                  style={{ cursor: "pointer", background: w.id === sel ? "var(--panel-2)" : "transparent" }}>
                  <b>{w.name}</b><div className="tiny muted">{w.member_count} member{w.member_count > 1 ? "s" : ""} · you: {w.role}</div></div>))}</div>)}
          </div>
          <div className="card col">
            <h3>New workspace</h3>
            <input className="input" placeholder="Team name" maxLength={60} value={name} onChange={(e) => setName(e.target.value)} aria-label="Workspace name" />
            <button className="btn primary" disabled={!name.trim() || busy} onClick={() => run(async () => { const r = await api.post("/workspaces", { name }); setName(""); await loadList(false); setSel(r.id); }, "Workspace created")}><Icon name="plus" size={16} /> Create</button>
          </div>
        </div>

        <div className="col">
          {!current ? <EmptyState icon="users" title="No workspace selected">Create one to start collaborating.</EmptyState> : (
            <>
              <div className="card flush">
                <div className="card-head"><h2>{current.name}</h2><Badge kind={isAdmin ? "good" : ""}>you are {current.role}</Badge></div>
                {!members ? <div style={{ padding: 16 }}><Skeleton h={50} /></div> : (
                  <div className="scroll-x"><table className="table"><thead><tr><th>Member</th><th>Role</th><th /></tr></thead><tbody>
                    {members.map((m) => (
                      <tr key={m.user_id}>
                        <td><div className="row" style={{ flexWrap: "nowrap" }}>{m.avatar_url ? <img className="avatar" src={m.avatar_url} alt="" /> : <span className="avatar" />}<div><b>{m.username}</b>{m.user_id === user.id && <span className="tiny faint"> (you)</span>}<div className="tiny muted">{m.email || "email hidden"}</div></div></div></td>
                        <td>{isAdmin ? <select className="select" style={{ width: 140 }} value={m.role} disabled={busy} aria-label={`Role for ${m.username}`}
                          onChange={(e) => run(async () => { await api.patch(`/workspaces/${sel}/members/${m.user_id}`, { role: e.target.value }); loadWs(); }, "Role updated")}>
                          {Object.keys(ROLE_HELP).map((r) => <option key={r}>{r}</option>)}</select> : <Badge>{m.role}</Badge>}</td>
                        <td style={{ textAlign: "right" }}>{(isAdmin || m.user_id === user.id) && <button className="btn sm ghost" disabled={busy}
                          onClick={() => confirm(m.user_id === user.id ? "Leave this workspace?" : `Remove ${m.username}?`) && run(async () => { await api.del(`/workspaces/${sel}/members/${m.user_id}`); m.user_id === user.id ? await loadList(false) : loadWs(); }, "Done")}>
                          {m.user_id === user.id ? "Leave" : "Remove"}</button>}</td>
                      </tr>))}
                  </tbody></table></div>)}
              </div>

              {isAdmin && (
                <div className="card col">
                  <h3>Invite someone</h3>
                  <p className="small muted">They need to have signed in to GitSetLive once. Use their GitHub username (works even if their email is private) or their email.</p>
                  <div className="row"><input className="input grow" placeholder="github-username or email" value={ident} onChange={(e) => setIdent(e.target.value)} aria-label="GitHub username or email" />
                    <select className="select" style={{ width: 150 }} value={role} onChange={(e) => setRole(e.target.value)} aria-label="Role">{Object.keys(ROLE_HELP).map((r) => <option key={r}>{r}</option>)}</select>
                    <button className="btn primary" disabled={busy || ident.trim().length < 2} onClick={() => run(async () => { await api.post(`/workspaces/${sel}/invite`, { identifier: ident, role }); setIdent(""); loadWs(); loadList(true); }, "Added to the workspace")}>{busy ? <Spinner /> : <Icon name="plus" size={16} />} Add</button></div>
                  <p className="tiny faint">{role}: {ROLE_HELP[role]}</p>
                </div>)}

              <div className="card flush"><div className="card-head"><h3>Workspace deployments</h3></div>
                {!deps ? <div style={{ padding: 16 }}><Skeleton h={40} /></div> : !deps.length ? <EmptyState icon="rocket" title="None yet">Deployments recorded in this workspace appear here.</EmptyState> :
                  <div className="list">{deps.map((d) => <div key={d.id} className="row between"><span><b>{d.repo_name}</b> <Badge>{d.status}</Badge></span><span className="tiny faint">{timeAgo(d.created_at)}</span></div>)}</div>}</div>
            </>
          )}

          <div className="card col">
            <h3>Account security</h3>
            <p className="small muted">Used a shared computer? End every active session of your account, on every device.</p>
            <div><button className="btn danger" onClick={() => confirm("Sign out of all devices?") && api.post("/logout-all").then(() => logout()).catch((e) => toast.error(e.message))}><Icon name="logout" size={16} /> Sign out everywhere</button></div>
          </div>
        </div>
      </div>
    </>
  );
}
Workspaces.title = "Workspaces";

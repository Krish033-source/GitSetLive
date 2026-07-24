import { useEffect, useState } from "react";
import { useRouter } from "next/router";
import Link from "next/link";

const API = process.env.NEXT_PUBLIC_API || "http://localhost:5000";

export default function Dashboard() {
  const router = useRouter();
  const [mounted, setMounted] = useState(false);
  const [token, setToken] = useState(null);
  const [userId, setUserId] = useState(null);
  const [username, setUsername] = useState("");

  const [repos, setRepos] = useState([]);
  const [deployments, setDeployments] = useState([]);
  const [activities, setActivities] = useState([]);
  const [loading, setLoading] = useState(true);

  const [stats, setStats] = useState({
    totalDeploys: 0,
    successRate: 0,
    liveApps: 0
  });

  const [showCreateRepo, setShowCreateRepo] = useState(false);
  const [newRepoName, setNewRepoName] = useState("");
  const [creatingRepo, setCreatingRepo] = useState(false);
  const [createRepoError, setCreateRepoError] = useState("");

  const [showDeleteRepo, setShowDeleteRepo] = useState(false);
  const [deleteRepoTarget, setDeleteRepoTarget] = useState("");
  const [deletingRepo, setDeletingRepo] = useState(false);
  const [deleteRepoError, setDeleteRepoError] = useState("");

  const [showHowTo, setShowHowTo] = useState(false);

  const [workspaces, setWorkspaces] = useState([]);
  const [showCreateWorkspace, setShowCreateWorkspace] = useState(false);
  const [newWorkspaceName, setNewWorkspaceName] = useState("");
  const [creatingWorkspace, setCreatingWorkspace] = useState(false);
  const [workspaceError, setWorkspaceError] = useState("");
  const [selectedWorkspace, setSelectedWorkspace] = useState(null);
  const [workspaceMembers, setWorkspaceMembers] = useState([]);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("developer");
  const [invitingMember, setInvitingMember] = useState(false);
  const [inviteError, setInviteError] = useState("");
  const [inviteSuccess, setInviteSuccess] = useState("");

  useEffect(() => {
    setMounted(true);
    const t = localStorage.getItem("token");
    const uid = localStorage.getItem("user_id");
    const uname = localStorage.getItem("username");

    if (!t) {
      router.push("/login");
      return;
    }

    setToken(t);
    setUserId(uid);
    setUsername(uname || "User");
  }, [router]);

  useEffect(() => {
  if (!mounted) return;

  if (!token || !userId) {
    setLoading(false);
    return;
  }

  loadData();
  loadWorkspaces();
}, [token, userId, mounted]);

  const loadData = async () => {
    setLoading(true);

    try {
      const [repoRes, depRes, actRes] = await Promise.allSettled([
        fetch(`${API}/repos?token=${token}`),
        fetch(`${API}/deployments/${userId}?token=${token}`),
        fetch(`${API}/activity/${userId}?token=${token}`)
      ]);

      const repoData =
  repoRes.status === "fulfilled"
    ? await repoRes.value.json()
    : [];

const depData =
  depRes.status === "fulfilled"
    ? await depRes.value.json()
    : {};

const actData =
  actRes.status === "fulfilled"
    ? await actRes.value.json()
    : {};

      const repoList = Array.isArray(repoData) ? repoData : (repoData.repos || []);
      const deploymentList = depData.deployments || [];
      const activityList = actData.activities || [];

      setRepos(repoList);
      setDeployments(deploymentList);
      setActivities(activityList);

      const successful = deploymentList.filter(d => d.status === "live").length;
      const total = deploymentList.length;

      setStats({
        totalDeploys: total,
        successRate: total > 0 ? ((successful / total) * 100).toFixed(1) : 0,
        liveApps: successful
      });
    } catch (err) {
      console.error("Load error:", err);
    } finally {
      setLoading(false);
    }
  };

  const createRepo = async () => {
    const name = newRepoName.trim();

    if (!name) {
      setCreateRepoError("Repo name daalo pehle");
      return;
    }

    setCreatingRepo(true);
    setCreateRepoError("");

    try {
      const res = await fetch(`${API}/create-repo`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, name })
      });

      const data = await res.json();

      if (data.success) {
        setNewRepoName("");
        setShowCreateRepo(false);
        await loadData();
      } else {
        setCreateRepoError(data.error || "Repo create nahi ho paya");
      }
    } catch (err) {
      console.error("Create repo error:", err);
      setCreateRepoError("Server se contact nahi ho paya");
    } finally {
      setCreatingRepo(false);
    }
  };

  const deleteRepo = async () => {
    if (!deleteRepoTarget) {
      setDeleteRepoError("Pehle repo select karo");
      return;
    }

    const repoObj = repos.find(r => r.full_name === deleteRepoTarget);
    if (!repoObj) {
      setDeleteRepoError("Repo nahi mila");
      return;
    }

    if (!window.confirm(`Pakka delete karna hai "${repoObj.full_name}"? Ye undo nahi ho sakta.`)) {
      return;
    }

    setDeletingRepo(true);
    setDeleteRepoError("");

    try {
      const res = await fetch(`${API}/delete-repo`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          token,
          owner: repoObj.owner.login,
          name: repoObj.name
        })
      });

      const data = await res.json();

      if (data.success) {
        setDeleteRepoTarget("");
        setShowDeleteRepo(false);
        await loadData();
      } else {
        setDeleteRepoError(data.error || "Delete nahi ho paya");
      }
    } catch (err) {
      console.error("Delete repo error:", err);
      setDeleteRepoError("Server se contact nahi ho paya");
    } finally {
      setDeletingRepo(false);
    }
  };

  const loadWorkspaces = async () => {
    if (!token || !userId) return;
    try {
      const res = await fetch(`${API}/workspaces/${userId}?token=${token}`);
      const data = await res.json();
      setWorkspaces(data.workspaces || []);
    } catch (err) {
      console.error("Load workspaces error:", err);
    }
  };

  const createWorkspace = async () => {
    const name = newWorkspaceName.trim();
    if (!name) {
      setWorkspaceError("Workspace ka naam daalo");
      return;
    }

    setCreatingWorkspace(true);
    setWorkspaceError("");

    try {
      const res = await fetch(`${API}/workspace`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, user_id: userId, name })
      });

      const data = await res.json();

      if (data.success) {
        setNewWorkspaceName("");
        setShowCreateWorkspace(false);
        await loadWorkspaces();
      } else {
        setWorkspaceError(data.error || "Workspace nahi ban paya");
      }
    } catch (err) {
      setWorkspaceError("Server se contact nahi ho paya");
    } finally {
      setCreatingWorkspace(false);
    }
  };

  const viewWorkspaceMembers = async (ws) => {
    setSelectedWorkspace(ws);
    setInviteError("");
    setInviteSuccess("");
    try {
      const res = await fetch(`${API}/workspace/${ws.id}/members?user_id=${userId}&token=${token}`);
      const data = await res.json();
      setWorkspaceMembers(data.members || []);
    } catch (err) {
      console.error("Load members error:", err);
    }
  };

  const inviteMember = async () => {
    const email = inviteEmail.trim();
    if (!email) {
      setInviteError("Email daalo pehle");
      return;
    }

    setInvitingMember(true);
    setInviteError("");
    setInviteSuccess("");

    try {
      const res = await fetch(`${API}/workspace/invite`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          token,
          user_id: userId,
          workspace_id: selectedWorkspace.id,
          invite_email: email,
          role: inviteRole
        })
      });

      const data = await res.json();

      if (data.success) {
        setInviteEmail("");
        setInviteSuccess("Add ho gaye workspace mein!");
        await viewWorkspaceMembers(selectedWorkspace);
      } else {
        setInviteError(data.error || "Invite nahi ho paya");
      }
    } catch (err) {
      setInviteError("Server se contact nahi ho paya");
    } finally {
      setInvitingMember(false);
    }
  };

  const logout = () => {
    localStorage.clear();
    sessionStorage.clear();
    router.push("/login");
  };

  if (!mounted || loading) {
    return (
      <div style={{
        height: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: "system-ui"
      }}>
        <h2>Loading...</h2>
      </div>
    );
  }

  return (
    <div style={{ padding: 20, maxWidth: 1200, margin: "0 auto", fontFamily: "system-ui" }}>
      {/* HEADER */}
      <div style={{
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center",
        marginBottom: 30,
        paddingBottom: 20,
        borderBottom: "1px solid #ddd"
      }}>
        <h1 style={{ margin: 0 }}>Dashboard</h1>
        <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
          <div style={{ textAlign: "right", marginRight: 20 }}>
            <p style={{ margin: 0, fontSize: 14, fontWeight: "bold" }}>{username}</p>
          </div>
          <button
            onClick={() => setShowHowTo(true)}
            style={{
              padding: "10px 20px",
              background: "#fff",
              color: "#0070f3",
              border: "2px solid #0070f3",
              borderRadius: 5,
              cursor: "pointer",
              fontWeight: "bold"
            }}
          >
            ❓ How to Use
          </button>
          <button
            onClick={() => window.open(`https://github.com/${username}`, "_blank")}
            style={{
              padding: "10px 20px",
              background: "#333",
              color: "white",
              border: "none",
              borderRadius: 5,
              cursor: "pointer",
              fontWeight: "bold"
            }}
          >
            View GitHub
          </button>
          <Link href="/deploy">
            <button style={{
              padding: "10px 20px",
              background: "#0070f3",
              color: "white",
              border: "none",
              borderRadius: 5,
              cursor: "pointer",
              fontWeight: "bold"
            }}>
              Deploy
            </button>
          </Link>
          <button
            onClick={logout}
            style={{
              padding: "10px 20px",
              background: "#f44336",
              color: "white",
              border: "none",
              borderRadius: 5,
              cursor: "pointer",
              fontWeight: "bold"
            }}
          >
            Logout
          </button>
        </div>
      </div>

      {/* STATS */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
        gap: 20,
        marginBottom: 30
      }}>
        <StatCard label="Total Deployments" value={stats.totalDeploys} />
        <StatCard label="Success Rate" value={stats.successRate + "%"} />
        <StatCard label="Live Apps" value={stats.liveApps} />
      </div>

      {/* REPOS */}
      <Section title="Repositories">
        {repos.length === 0 ? (
          <p style={{ color: "#999" }}>No repositories found</p>
        ) : (
          <div>
            {repos.map(r => (
              <div key={r.id} style={{
                padding: 10,
                borderBottom: "1px solid #eee",
                fontSize: 14
              }}>
                {r.full_name}
              </div>
            ))}
          </div>
        )}

        <div style={{ display: "flex", gap: 10, marginTop: 10 }}>
          <button
            onClick={loadData}
            style={{
              padding: "8px 15px",
              background: "#0070f3",
              color: "white",
              border: "none",
              borderRadius: 5,
              cursor: "pointer",
              fontSize: 13
            }}
          >
            Refresh
          </button>

          <button
            onClick={() => {
              setShowCreateRepo(!showCreateRepo);
              setCreateRepoError("");
            }}
            style={{
              padding: "8px 15px",
              background: "#4caf50",
              color: "white",
              border: "none",
              borderRadius: 5,
              cursor: "pointer",
              fontSize: 13,
              fontWeight: "bold"
            }}
          >
            + New Repo
          </button>

          <button
            onClick={() => {
              setShowDeleteRepo(!showDeleteRepo);
              setDeleteRepoError("");
            }}
            style={{
              padding: "8px 15px",
              background: "#f44336",
              color: "white",
              border: "none",
              borderRadius: 5,
              cursor: "pointer",
              fontSize: 13,
              fontWeight: "bold"
            }}
          >
            🗑 Delete Repo
          </button>
        </div>

        {showDeleteRepo && (
          <div style={{
            marginTop: 15,
            padding: 15,
            background: "#fff3f0",
            borderRadius: 8,
            border: "1px solid #f44336"
          }}>
            <select
              value={deleteRepoTarget}
              onChange={(e) => setDeleteRepoTarget(e.target.value)}
              style={{
                padding: 10,
                width: "100%",
                maxWidth: 300,
                fontSize: 14,
                borderRadius: 5,
                border: "1px solid #ccc",
                marginBottom: 10,
                boxSizing: "border-box"
              }}
            >
              <option value="">-- Select repo to delete --</option>
              {repos.map(r => (
                <option key={r.id} value={r.full_name}>{r.full_name}</option>
              ))}
            </select>
            <br />
            <button
              onClick={deleteRepo}
              disabled={deletingRepo}
              style={{
                padding: "8px 20px",
                background: deletingRepo ? "#999" : "#f44336",
                color: "white",
                border: "none",
                borderRadius: 5,
                cursor: deletingRepo ? "not-allowed" : "pointer",
                fontSize: 13,
                fontWeight: "bold"
              }}
            >
              {deletingRepo ? "Deleting..." : "Permanently Delete"}
            </button>

            {deleteRepoError && (
              <p style={{ color: "#c62828", fontSize: 13, marginTop: 8 }}>
                {deleteRepoError}
              </p>
            )}
          </div>
        )}

        {showCreateRepo && (
          <div style={{
            marginTop: 15,
            padding: 15,
            background: "#f5f5f5",
            borderRadius: 8,
            border: "1px solid #ddd"
          }}>
            <input
              placeholder="repo-name (e.g. my-new-app)"
              value={newRepoName}
              onChange={(e) => setNewRepoName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") createRepo();
              }}
              style={{
                padding: 10,
                width: "100%",
                maxWidth: 300,
                fontSize: 14,
                borderRadius: 5,
                border: "1px solid #ccc",
                marginBottom: 10,
                boxSizing: "border-box"
              }}
            />
            <br />
            <button
              onClick={createRepo}
              disabled={creatingRepo}
              style={{
                padding: "8px 20px",
                background: creatingRepo ? "#999" : "#0070f3",
                color: "white",
                border: "none",
                borderRadius: 5,
                cursor: creatingRepo ? "not-allowed" : "pointer",
                fontSize: 13,
                fontWeight: "bold"
              }}
            >
              {creatingRepo ? "Creating..." : "Create Repository"}
            </button>

            {createRepoError && (
              <p style={{ color: "#c62828", fontSize: 13, marginTop: 8 }}>
                {createRepoError}
              </p>
            )}
          </div>
        )}
      </Section>

      {/* DEPLOYMENTS */}
      <Section title="Recent Deployments">
        {deployments.length === 0 ? (
          <p style={{ color: "#999" }}>No deployments yet</p>
        ) : (
          <div>
            {deployments.slice(0, 10).map(dep => (
              <div key={dep.id} style={{
                padding: 12,
                borderBottom: "1px solid #eee",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center"
              }}>
                <div>
                  <strong>{dep.repo_name}</strong>
                  <span style={{
                    marginLeft: 10,
                    padding: "4px 8px",
                    background: getStatusColor(dep.status),
                    color: "white",
                    borderRadius: 3,
                    fontSize: 12
                  }}>
                    {dep.status}
                  </span>
                </div>
                {dep.live_url && (
                  <a
                    href={dep.live_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    style={{
                      color: "#0070f3",
                      textDecoration: "none",
                      fontSize: 13
                    }}
                  >
                    Open
                  </a>
                )}
              </div>
            ))}
          </div>
        )}
      </Section>

      {/* ACTIVITY */}
      <Section title="Recent Activity">
        {activities.length === 0 ? (
          <p style={{ color: "#999" }}>No activity yet</p>
        ) : (
          <div>
            {activities.slice(0, 10).map((a, i) => (
              <div key={i} style={{
                padding: 10,
                borderBottom: "1px solid #eee",
                fontSize: 14,
                color: "#333"
              }}>
                {formatAction(a.action)} - {formatDate(a.created_at)}
              </div>
            ))}
          </div>
        )}
      </Section>
      {/* TOOLS */}
<Section title="AI Tools">
  <div style={{
    display: "flex",
    gap: 15,
    flexWrap: "wrap"
  }}>

    <Link href="/upload-file">
      <button style={toolBtn}>
         Upload File
      </button>
    </Link>

    <Link href="/upload-code">
      <button style={toolBtn}>
         Upload Code
      </button>
    </Link>

    <Link href="/scan">
      <button style={toolBtn}>
         Scan AI
      </button>
    </Link>

    <Link href="/gitbot">
      <button style={toolBtn}>
         GitBot
      </button>
    </Link>

  </div>
</Section>

      {/* WORKSPACES */}
      <Section title="Workspaces">
        {workspaces.length === 0 ? (
          <p style={{ color: "#999" }}>Koi workspace nahi hai abhi — team ke saath deployments share karne ke liye ek banao</p>
        ) : (
          <div>
            {workspaces.map(ws => (
              <div key={ws.id} style={{
                padding: 10,
                borderBottom: "1px solid #eee",
                fontSize: 14,
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center"
              }}>
                <span>{ws.name}</span>
                <button
                  onClick={() => viewWorkspaceMembers(ws)}
                  style={{
                    padding: "5px 12px",
                    background: "#0070f3",
                    color: "white",
                    border: "none",
                    borderRadius: 5,
                    cursor: "pointer",
                    fontSize: 12
                  }}
                >
                  View Members
                </button>
              </div>
            ))}
          </div>
        )}

        <button
          onClick={() => {
            setShowCreateWorkspace(!showCreateWorkspace);
            setWorkspaceError("");
          }}
          style={{
            marginTop: 10,
            padding: "8px 15px",
            background: "#4caf50",
            color: "white",
            border: "none",
            borderRadius: 5,
            cursor: "pointer",
            fontSize: 13,
            fontWeight: "bold"
          }}
        >
          + New Workspace
        </button>

        {showCreateWorkspace && (
          <div style={{ marginTop: 15, padding: 15, background: "#f5f5f5", borderRadius: 8, border: "1px solid #ddd" }}>
            <input
              placeholder="Workspace naam (e.g. My Team)"
              value={newWorkspaceName}
              onChange={(e) => setNewWorkspaceName(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") createWorkspace(); }}
              style={{
                padding: 10, width: "100%", maxWidth: 300, fontSize: 14,
                borderRadius: 5, border: "1px solid #ccc", marginBottom: 10, boxSizing: "border-box"
              }}
            />
            <br />
            <button
              onClick={createWorkspace}
              disabled={creatingWorkspace}
              style={{
                padding: "8px 20px",
                background: creatingWorkspace ? "#999" : "#0070f3",
                color: "white", border: "none", borderRadius: 5,
                cursor: creatingWorkspace ? "not-allowed" : "pointer",
                fontSize: 13, fontWeight: "bold"
              }}
            >
              {creatingWorkspace ? "Creating..." : "Create Workspace"}
            </button>
            {workspaceError && <p style={{ color: "#c62828", fontSize: 13, marginTop: 8 }}>{workspaceError}</p>}
          </div>
        )}

        {selectedWorkspace && (
          <div style={{ marginTop: 20, padding: 15, background: "#f5f5f5", borderRadius: 8, border: "1px solid #ddd" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <h4 style={{ margin: 0 }}>{selectedWorkspace.name} — Members</h4>
              <button onClick={() => setSelectedWorkspace(null)} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 18 }}>✕</button>
            </div>

            <table style={{ width: "100%", borderCollapse: "collapse", marginTop: 10, fontSize: 14 }}>
              <thead>
                <tr>
                  <th style={{ textAlign: "left", padding: 6, borderBottom: "1px solid #ddd" }}>Username</th>
                  <th style={{ textAlign: "left", padding: 6, borderBottom: "1px solid #ddd" }}>Email</th>
                  <th style={{ textAlign: "left", padding: 6, borderBottom: "1px solid #ddd" }}>Role</th>
                </tr>
              </thead>
              <tbody>
                {workspaceMembers.map((m, i) => (
                  <tr key={i}>
                    <td style={{ padding: 6, borderBottom: "1px solid #eee" }}>{m.username}</td>
                    <td style={{ padding: 6, borderBottom: "1px solid #eee" }}>{m.email}</td>
                    <td style={{ padding: 6, borderBottom: "1px solid #eee" }}>{m.role}</td>
                  </tr>
                ))}
              </tbody>
            </table>

            <div style={{ marginTop: 15 }}>
              <label style={{ fontSize: 13, color: "#666", display: "block", marginBottom: 5 }}>
                Naye member ko invite karo (unka GitSetLive account already hona chahiye)
              </label>
              <div style={{ display: "flex", gap: 8 }}>
                <input
                  placeholder="unka@email.com"
                  value={inviteEmail}
                  onChange={(e) => setInviteEmail(e.target.value)}
                  style={{ flex: 1, padding: 8, borderRadius: 5, border: "1px solid #ccc", fontSize: 13 }}
                />
                <select
                  value={inviteRole}
                  onChange={(e) => setInviteRole(e.target.value)}
                  style={{ padding: 8, borderRadius: 5, border: "1px solid #ccc", fontSize: 13 }}
                >
                  <option value="admin">Admin</option>
                  <option value="developer">Developer</option>
                  <option value="viewer">Viewer</option>
                </select>
                <button
                  onClick={inviteMember}
                  disabled={invitingMember}
                  style={{
                    padding: "8px 16px",
                    background: invitingMember ? "#999" : "#0070f3",
                    color: "white", border: "none", borderRadius: 5,
                    cursor: invitingMember ? "not-allowed" : "pointer", fontSize: 13, fontWeight: "bold"
                  }}
                >
                  {invitingMember ? "..." : "Invite"}
                </button>
              </div>
              {inviteError && <p style={{ color: "#c62828", fontSize: 13, marginTop: 8 }}>{inviteError}</p>}
              {inviteSuccess && <p style={{ color: "#2e7d32", fontSize: 13, marginTop: 8 }}>{inviteSuccess}</p>}
            </div>
          </div>
        )}
      </Section>

      {/* HOW TO USE MODAL */}
      {showHowTo && (
        <div
          onClick={() => setShowHowTo(false)}
          style={{
            position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
            background: "rgba(0,0,0,0.5)", display: "flex", alignItems: "center",
            justifyContent: "center", zIndex: 1000, padding: 20
          }}
        >
          <div
            onClick={(e) => e.stopPropagation()}
            style={{
              background: "white", borderRadius: 12, padding: 30,
              maxWidth: 600, maxHeight: "85vh", overflowY: "auto",
              fontFamily: "system-ui"
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 15 }}>
              <h2 style={{ margin: 0 }}>How to use GetSetLive: </h2>
              <button onClick={() => setShowHowTo(false)} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 22 }}>✕</button>
            </div>

            <p style={{ color: "#666", fontSize: 14 }}>
              Don't know coding?? Never a big deal!! Follow the steps and get your needs.. we will take care of the codes..
            </p>

            <HowToStep num="1" title="Browse Your Repositories">
  In the "Repositories" section, you'll see all of your GitHub projects.
  To create a new project, click "+ New Repo", enter a name, and you're ready to go.
</HowToStep>

<HowToStep num="2" title="Generate Code with AI">
  Click "Upload Code" or "Upload File", choose your repository, then describe what
  you want (for example, "Create a login form"). Click "Generate" and the AI will
  write the code for you. When you're satisfied, click "Upload to GitHub" to push
  it directly to your repository.
</HowToStep>

<HowToStep num="3" title="Scan Your Code for Issues">
  Click the "Scan AI" button, select a repository, then click "Scan Repo". The AI
  will analyze your code and highlight bugs, security issues, and possible
  improvements. If you're happy with the suggested fixes, click "Apply Fix & Create PR"
  to automatically create a Pull Request with the changes.
</HowToStep>

<HowToStep num="4" title="Review and Merge Pull Requests">
  Once the Pull Request is created, open it on GitHub using the "View GitHub"
  button. Review the changes, and if everything looks good, click "Merge".
</HowToStep>

<HowToStep num="5" title="Deploy Your Project">
  Click the "Deploy" button. You'll see three deployment options:
  <ul style={{ marginTop: 6, marginBottom: 0 }}>
    <li><strong>Render</strong> — Free hosting, ideal for backend services and full-stack applications.</li>
    <li><strong>Vercel</strong> — Free hosting, perfect for frontend projects and websites.</li>
    <li><strong>Our Servers</strong> — Instantly deploy to our own servers without creating an account, great for demos and testing.</li>
  </ul>
  Select your preferred option, choose a repository, and click Deploy. Within
  seconds, you'll receive a live URL that you can share with anyone.
</HowToStep>

<HowToStep num="6" title="Ask GitBot Anything">
  Not sure what's inside a repository? Click the "GitBot" button, select a
  repository, and ask questions like "What does this project do?" or "Explain the
  project structure." GitBot will answer instantly.
</HowToStep>

<HowToStep num="7" title="Collaborate with Your Team">
  Open the "Workspaces" section to create a new workspace. Then click
  "View Members" and invite teammates by entering their email addresses.
  (They'll need a GitSetLive account to join your workspace.)
</HowToStep>
          </div>
        </div>
      )}
    </div>
  );
}

function HowToStep({ num, title, children }) {
  return (
    <div style={{ display: "flex", gap: 12, marginBottom: 18 }}>
      <div style={{
        minWidth: 28, height: 28, borderRadius: "50%", background: "#0070f3",
        color: "white", display: "flex", alignItems: "center", justifyContent: "center",
        fontWeight: "bold", fontSize: 13
      }}>
        {num}
      </div>
      <div>
        <p style={{ margin: "0 0 4px 0", fontWeight: "bold", fontSize: 14 }}>{title}</p>
        <p style={{ margin: 0, fontSize: 13, color: "#555", lineHeight: 1.5 }}>{children}</p>
      </div>
    </div>
  );
}

const toolBtn = {
  padding: "12px 20px",
  background: "#0070f3",
  color: "white",
  border: "none",
  borderRadius: 6,
  cursor: "pointer",
  fontWeight: "bold"
};

function StatCard({ label, value }) {
  return (
    <div style={{
      padding: 20,
      background: "#f5f5f5",
      borderRadius: 8,
      border: "1px solid #ddd"
    }}>
      <p style={{ margin: "0 0 10px 0", fontSize: 12, color: "#666" }}>
        {label}
      </p>
      <p style={{ margin: 0, fontSize: 24, fontWeight: "bold", color: "#0070f3" }}>
        {value}
      </p>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div style={{ marginBottom: 30 }}>
      <h2 style={{ marginTop: 0, marginBottom: 15 }}>{title}</h2>
      <div style={{
        background: "white",
        border: "1px solid #ddd",
        borderRadius: 8,
        padding: 15
      }}>
        {children}
      </div>
    </div>
  );
}

function getStatusColor(status) {
  const colors = {
    live: "#4caf50",
    deploying: "#ff9800",
    failed: "#f44336",
    pending: "#2196f3"
  };
  return colors[status] || "#999";
}

function formatAction(action) {
  return action
    .split("_")
    .map(w => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function formatDate(dateStr) {
  if (!dateStr) return "Unknown";
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now - date;
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;

  return date.toLocaleDateString();
}
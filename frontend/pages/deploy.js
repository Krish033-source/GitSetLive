import { useEffect, useState } from "react";
import { useRouter } from "next/router";

const API = process.env.NEXT_PUBLIC_API || "http://localhost:5000";

export default function Deploy() {
  const router = useRouter();

  const [token, setToken] = useState(null);
  const [userId, setUserId] = useState(null);

  const [repos, setRepos] = useState([]);
  const [selected, setSelected] = useState(null);

  const [tab, setTab] = useState("render"); // "render" | "vercel" | "own"

  // Own-server state
  const [ownDeploying, setOwnDeploying] = useState(false);
  const [ownError, setOwnError] = useState("");
  const [ownResult, setOwnResult] = useState(null);
  const [ownProjects, setOwnProjects] = useState({});

  useEffect(() => {
    const t = localStorage.getItem("token");
    const uid = localStorage.getItem("user_id");
    if (!t) {
      router.push("/login");
      return;
    }
    setToken(t);
    setUserId(uid);
  }, [router]);

  useEffect(() => {
    if (!token) return;
    fetch(`${API}/repos?token=${token}`)
      .then((r) => r.json())
      .then((data) => setRepos(Array.isArray(data) ? data : []))
      .catch((err) => console.error("Repo load error:", err));
  }, [token]);

  const refreshOwnProjects = () => {
    const uid = userId || localStorage.getItem("user_id");
    const tok = token || localStorage.getItem("token");
    if (!uid || !tok) return;
    fetch(`${API}/own-server-projects?user_id=${uid}&token=${tok}`)
      .then((r) => r.json())
      .then((data) => setOwnProjects(data && !data.error ? data : {}))
      .catch((err) => console.error("Own-server list error:", err));
  };

  useEffect(() => {
    if (tab === "own") refreshOwnProjects();
  }, [tab, userId]);

  const githubRepoUrl = () =>
    selected ? `https://github.com/${selected.owner.login}/${selected.name}` : null;

  const deployToOwnServer = async () => {
    if (!selected) {
      alert("Select a repository first");
      return;
    }
    const freshToken = token || localStorage.getItem("token");
    const freshUserId = userId || localStorage.getItem("user_id");
    if (!freshToken || !freshUserId) {
      alert("Session not fully loaded yet. Please refresh the page and try again.");
      return;
    }

    setOwnDeploying(true);
    setOwnError("");
    setOwnResult(null);

    try {
      const res = await fetch(`${API}/deploy-own-server`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          token: freshToken,
          owner: selected.owner.login,
          repo: selected.name,
          user_id: freshUserId
        })
      });

      const data = await res.json();

      if (data.error) {
        setOwnError(data.error);
      } else {
        setOwnResult(data);
        refreshOwnProjects();
      }
    } catch (err) {
      setOwnError(err.message);
    } finally {
      setOwnDeploying(false);
    }
  };

  const stopOwnProject = async (projectId) => {
    const freshUserId = userId || localStorage.getItem("user_id");
    const freshToken = token || localStorage.getItem("token");
    try {
      await fetch(`${API}/own-server-stop/${projectId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: freshUserId, token: freshToken })
      });
      refreshOwnProjects();
    } catch (err) {
      alert("Failed to stop: " + err.message);
    }
  };

  return (
    <div style={{ padding: 20, maxWidth: 800, margin: "0 auto", fontFamily: "system-ui" }}>
      <h1 style={{ marginBottom: 4 }}>Deploy</h1>
      <p style={{ color: "#666", marginTop: 0 }}>Pick a repo, then choose where to deploy it.</p>

      {/* REPO SELECT */}
      <div style={{ marginBottom: 20 }}>
        <label style={{ fontWeight: "bold", display: "block", marginBottom: 6, fontSize: 14 }}>
          Repository
        </label>
        <select
          onChange={(e) => setSelected(e.target.value ? JSON.parse(e.target.value) : null)}
          style={{
            padding: 10, width: "100%", fontSize: 14, borderRadius: 6, border: "1px solid #ccc"
          }}
        >
          <option value="">-- Select repository --</option>
          {repos.map((r) => (
            <option key={r.id} value={JSON.stringify(r)}>{r.full_name}</option>
          ))}
        </select>
      </div>

      {/* TABS */}
      <div style={{ display: "flex", gap: 8, marginBottom: 25, borderBottom: "1px solid #ddd" }}>
        {[
          { id: "render", label: "Deploy to Render" },
          { id: "vercel", label: "▲ Deploy to Vercel" },
          { id: "own", label: "Deploy to Our Servers" }
        ].map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{
              padding: "10px 18px",
              background: "none",
              border: "none",
              borderBottom: tab === t.id ? "3px solid #0070f3" : "3px solid transparent",
              color: tab === t.id ? "#0070f3" : "#666",
              fontWeight: tab === t.id ? "bold" : "normal",
              cursor: "pointer",
              fontSize: 14
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* RENDER TAB */}
      {tab === "render" && (
        <div>
          <h3 style={{ marginTop: 0 }}>How Render deployment works</h3>
          <p style={{ color: "#555", fontSize: 14 }}>
            Render reads your repo and asks you to fill a short form for a <strong>Web Service</strong>.
            Here's what each section means and what to put, based on your project type:
          </p>

          <div style={{ background: "#f5f5f5", borderRadius: 8, padding: 16, marginBottom: 20, fontSize: 14 }}>
            <p><strong>Name</strong> — anything, e.g. your repo name.</p>
            <p><strong>Region</strong> — pick the one closest to your users (any is fine to start).</p>
            <p><strong>Branch</strong> — usually <code>main</code>.</p>
            <p><strong>Root Directory</strong> — leave blank unless your app lives in a subfolder.</p>
            <p><strong>Build Command</strong> — depends on your stack:</p>
            <ul style={{ marginTop: 4 }}>
              <li>Python: <code>pip install -r requirements.txt</code></li>
              <li>Node: <code>npm install &amp;&amp; npm run build</code> (or just <code>npm install</code> if no build step)</li>
            </ul>
            <p><strong>Start Command</strong>:</p>
            <ul style={{ marginTop: 4 }}>
              <li>Flask: <code>gunicorn app:app</code></li>
              <li>FastAPI: <code>uvicorn main:app --host 0.0.0.0 --port $PORT</code></li>
              <li>Node: <code>npm start</code> or <code>node index.js</code></li>
            </ul>
            <p><strong>Instance Type</strong> — Free is fine for testing/demos.</p>
            <p style={{ marginBottom: 0 }}><strong>Environment Variables</strong> — add any secrets/config your app needs (API keys, DB URLs, etc).</p>
          </div>

          <button
            disabled={!selected}
            onClick={() => window.open(`https://dashboard.render.com/create?type=web&repo=${githubRepoUrl()}`, "_blank")}
            style={{
              padding: "14px 28px",
              background: selected ? "#0070f3" : "#999",
              color: "white",
              border: "none",
              borderRadius: 8,
              cursor: selected ? "pointer" : "not-allowed",
              fontSize: 16,
              fontWeight: "bold"
            }}
          >
            Open in Render →
          </button>
          {!selected && <p style={{ color: "#999", fontSize: 13, marginTop: 8 }}>Select a repo above first</p>}
        </div>
      )}

      {/* VERCEL TAB */}
      {tab === "vercel" && (
        <div>
          <h3 style={{ marginTop: 0 }}>How Vercel deployment works</h3>
          <p style={{ color: "#555", fontSize: 14 }}>
            Vercel imports your repo and shows a "New Project" form. Here's what to check:
          </p>

          <div style={{ background: "#f5f5f5", borderRadius: 8, padding: 16, marginBottom: 20, fontSize: 14 }}>
            <p><strong>Project Name</strong> — anything, defaults to your repo name.</p>
            <p><strong>Framework Preset</strong> — Vercel auto-detects this (Next.js, React, etc). Only change it if it's wrong.</p>
            <p><strong>Root Directory</strong> — leave blank unless your app lives in a subfolder.</p>
            <p><strong>Build Command</strong> — usually auto-filled, e.g. <code>next build</code> or <code>npm run build</code>.</p>
            <p><strong>Output Directory</strong> — usually auto-filled (e.g. <code>.next</code>, <code>dist</code>, <code>build</code>).</p>
            <p><strong>Install Command</strong> — usually <code>npm install</code> (auto-filled).</p>
            <p style={{ marginBottom: 0 }}><strong>Environment Variables</strong> — add any secrets/config your app needs.</p>
          </div>

          <p style={{ fontSize: 13, color: "#999", marginBottom: 15 }}>
            Note: Vercel is built for frontend/Next.js/static apps. Plain Flask/FastAPI backends generally
            don't run well on Vercel — use Render or "Our Servers" for those instead.
          </p>

          <button
            disabled={!selected}
            onClick={() => window.open(`https://vercel.com/new/clone?repository-url=${githubRepoUrl()}`, "_blank")}
            style={{
              padding: "14px 28px",
              background: selected ? "#000" : "#999",
              color: "white",
              border: "none",
              borderRadius: 8,
              cursor: selected ? "pointer" : "not-allowed",
              fontSize: 16,
              fontWeight: "bold"
            }}
          >
            ▲ Open in Vercel →
          </button>
          {!selected && <p style={{ color: "#999", fontSize: 13, marginTop: 8 }}>Select a repo above first</p>}
        </div>
      )}

      {/* OWN SERVERS TAB */}
      {tab === "own" && (
        <div>
          <h3 style={{ marginTop: 0 }}>Deploy to Our Servers</h3>
          <p style={{ color: "#555", fontSize: 14 }}>
            We'll pull your repo, auto-detect if it's static / Flask / Node, install dependencies,
            run it right here, and give you a public link — no Render/Vercel account needed.
          </p>
          <p style={{ fontSize: 13, color: "#c76b00", background: "#fff3e0", padding: 10, borderRadius: 6 }}>
            ⚠️ Prototype-grade hosting: good for demos, not for production traffic — no sandboxing,
            no auto-scaling, and deployments may be stopped if the server restarts.
          </p>

          <button
            disabled={!selected || ownDeploying}
            onClick={deployToOwnServer}
            style={{
              padding: "14px 28px",
              background: ownDeploying ? "#999" : "#4caf50",
              color: "white",
              border: "none",
              borderRadius: 8,
              cursor: ownDeploying || !selected ? "not-allowed" : "pointer",
              fontSize: 16,
              fontWeight: "bold",
              marginBottom: 20
            }}
          >
            {ownDeploying ? "Deploying..." : "Deploy to Our Servers"}
          </button>
          {!selected && <p style={{ color: "#999", fontSize: 13 }}>Select a repo above first</p>}

          {ownError && (
            <div style={{
              padding: 15, background: "#ffebee", border: "1px solid #ef5350",
              borderRadius: 8, marginBottom: 20, color: "#c62828", fontSize: 14, whiteSpace: "pre-wrap"
            }}>
              {ownError}
            </div>
          )}

          {ownResult && (
            <div style={{
              padding: 15, background: "#e8f5e9", border: "1px solid #4caf50",
              borderRadius: 8, marginBottom: 20, fontSize: 14
            }}>
              <p><strong>Detected type:</strong> {ownResult.type} (entry: {ownResult.entry})</p>
              {ownResult.live_url ? (
                <p>
                  <strong>Live URL:</strong>{" "}
                  <a href={ownResult.live_url} target="_blank" rel="noopener noreferrer">{ownResult.live_url}</a>
                </p>
              ) : (
                <p style={{ color: "#c76b00" }}>{ownResult.note || "No public URL yet"}</p>
              )}
              <p><strong>Local URL:</strong> {ownResult.local_url}</p>
            </div>
          )}

          <h4>Your running deployments</h4>
          {Object.keys(ownProjects).length === 0 ? (
            <p style={{ color: "#999", fontSize: 14 }}>Nothing running right now</p>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 14 }}>
              <thead>
                <tr>
                  <th style={{ textAlign: "left", borderBottom: "1px solid #ddd", padding: 8 }}>Repo</th>
                  <th style={{ textAlign: "left", borderBottom: "1px solid #ddd", padding: 8 }}>Type</th>
                  <th style={{ textAlign: "left", borderBottom: "1px solid #ddd", padding: 8 }}>Live URL</th>
                  <th style={{ textAlign: "left", borderBottom: "1px solid #ddd", padding: 8 }}>Status</th>
                  <th style={{ borderBottom: "1px solid #ddd", padding: 8 }}></th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(ownProjects).map(([pid, info]) => (
                  <tr key={pid}>
                    <td style={{ padding: 8, borderBottom: "1px solid #eee" }}>{info.repo}</td>
                    <td style={{ padding: 8, borderBottom: "1px solid #eee" }}>{info.type}</td>
                    <td style={{ padding: 8, borderBottom: "1px solid #eee" }}>
                      {info.tunnel_url ? (
                        <a href={info.tunnel_url} target="_blank" rel="noopener noreferrer">{info.tunnel_url}</a>
                      ) : (
                        <span style={{ color: "#999" }}>{info.tunnel_note || "no link"}</span>
                      )}
                    </td>
                    <td style={{ padding: 8, borderBottom: "1px solid #eee" }}>{info.alive ? "🟢 running" : "🔴 stopped"}</td>
                    <td style={{ padding: 8, borderBottom: "1px solid #eee" }}>
                      <button onClick={() => stopOwnProject(pid)} style={{
                        padding: "6px 12px", background: "#f44336", color: "white",
                        border: "none", borderRadius: 5, cursor: "pointer", fontSize: 12
                      }}>
                        Stop
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}
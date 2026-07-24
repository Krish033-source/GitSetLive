import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API || "http://localhost:5000";

export default function GitBot() {
  const [repos, setRepos] = useState([]);
  const [selected, setSelected] = useState(null);
  const [q, setQ] = useState("");
  const [a, setA] = useState("");
  const [loading, setLoading] = useState(false);

  const token =
    typeof window !== "undefined" ? localStorage.getItem("token") : null;

  useEffect(() => {
    if (!token) return;

    fetch(`${API}/repos?token=${token}`)
      .then((res) => res.json())
      .then((data) => setRepos(Array.isArray(data) ? data : []))
      .catch((err) => {
        console.error("Repo load error:", err);
        setRepos([]);
      });
  }, [token]);

  const ask = async () => {
    if (!selected) {
      alert("Select a repo first");
      return;
    }
    if (!q.trim()) {
      alert("Type a question first");
      return;
    }

    setLoading(true);
    setA("");

    try {
      const res = await fetch(`${API}/gitbot`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          token,
          owner: selected.owner.login,
          repo: selected.name,
          question: q,
        }),
      });

      const data = await res.json();
      setA(data.answer || "No answer returned");
    } catch (err) {
      console.error("GitBot error:", err);
      setA("❌ Failed to reach GitBot. Is the backend running?");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{ padding: 20, maxWidth: 700, margin: "0 auto", fontFamily: "system-ui" }}>
      <h2>GitBot</h2>
      <p style={{ color: "#666", fontSize: 14 }}>
        Ask questions about a repository's code, structure, or setup.
      </p>

      <select
        onChange={(e) => setSelected(e.target.value ? JSON.parse(e.target.value) : null)}
        style={{
          padding: 10,
          width: "100%",
          maxWidth: 400,
          fontSize: 14,
          borderRadius: 5,
          border: "1px solid #ccc",
          marginBottom: 15
        }}
      >
        <option value="">-- Select repository --</option>
        {repos.map((r) => (
          <option key={r.id} value={JSON.stringify(r)}>
            {r.full_name}
          </option>
        ))}
      </select>

      <br />

      <input
        placeholder="Ask about your repo..."
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") ask();
        }}
        style={{
          padding: 10,
          width: "100%",
          maxWidth: 400,
          fontSize: 14,
          borderRadius: 5,
          border: "1px solid #ccc",
          marginBottom: 10,
          boxSizing: "border-box"
        }}
      />

      <br />

      <button
        onClick={ask}
        disabled={loading}
        style={{
          padding: "10px 20px",
          background: loading ? "#999" : "#0070f3",
          color: "white",
          border: "none",
          borderRadius: 5,
          cursor: loading ? "not-allowed" : "pointer",
          fontWeight: "bold"
        }}
      >
        {loading ? "Thinking..." : "Ask"}
      </button>

      {a && (
        <pre style={{
          whiteSpace: "pre-wrap",
          marginTop: 20,
          background: "#f5f5f5",
          padding: 15,
          borderRadius: 8,
          border: "1px solid #ddd",
          fontSize: 14
        }}>
          {a}
        </pre>
      )}
    </div>
  );
}

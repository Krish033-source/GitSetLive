import { useEffect, useState } from "react";

export default function ScanRepo() {
  const [repos, setRepos] = useState([]);
  const [selected, setSelected] = useState(null);
  const [fixes, setFixes] = useState([]);
  const [loading, setLoading] = useState(false);

  const token =
    typeof window !== "undefined" ? localStorage.getItem("token") : null;

  // 🔹 load repos
  useEffect(() => {
    if (!token) return;

    fetch(`${process.env.NEXT_PUBLIC_API}/repos?token=${token}`)
      .then((res) => res.json())
      .then((data) => setRepos(Array.isArray(data) ? data : []))
      .catch((err) => {
        console.error(err);
        alert("Failed to load repos ❌");
      });
  }, [token]);

  // 🔹 scan repo
  const scan = async () => {
  if (!selected) return alert("Select repo first");

  setLoading(true);

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);

    const res = await fetch(
      process.env.NEXT_PUBLIC_API + "/scan-repo",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          token,
          owner: selected.owner.login,
          repo: selected.name,
        }),
        signal: controller.signal,
      }
    );

    clearTimeout(timeout);

    const data = await res.json();

    let parsed = data.fixes;
    if (typeof parsed === "string") {
      parsed = JSON.parse(parsed);
    }

    setFixes(parsed);
  } catch (err) {
    console.error("SCAN ERROR:", err);

    if (err.name === "AbortError") {
      alert("Request timeout ⏳");
    } else {
      alert("Backend not reachable ❌");
    }
  }

  setLoading(false);
};

  // 🔹 apply fixes
  const applyFix = async () => {
    if (!fixes || fixes.length === 0)
      return alert("No fixes to apply");

    try {
      const res = await fetch(
        process.env.NEXT_PUBLIC_API + "/apply-fix",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            token,
            owner: selected.owner.login,
            repo: selected.name,
            fixes,
          }),
        }
      );

      const data = await res.json();

      console.log("PR RESPONSE:", data);

      if (data.pr_url) {
        window.location.href = data.pr_url;
      } else {
        alert("PR create failed ❌ " + (data.error || ""));
      }
    } catch (err) {
      console.error(err);
      alert("Apply fix failed ❌");
    }
  };

  return (
    <div style={{ padding: 20 }}>
      <h2>AI Repo Scanner</h2>

      {/* Repo Select */}
      <select
        onChange={(e) => setSelected(JSON.parse(e.target.value))}
      >
        <option>Select Repo</option>
        {repos.map((r) => (
          <option key={r.id} value={JSON.stringify(r)}>
            {r.name}
          </option>
        ))}
      </select>

      <br /><br />

      {/* Scan */}
      <button onClick={scan}>
        {loading ? "Scanning..." : "Scan Repo 🔍"}
      </button>

      {/* Results */}
      <pre style={{ whiteSpace: "pre-wrap", marginTop: 20 }}>
        {JSON.stringify(fixes, null, 2)}
      </pre>

      {/* Apply */}
      {fixes && fixes.length > 0 && (
        <button onClick={applyFix}>
          Apply Fix & Create PR 🚀
        </button>
      )}
    </div>
  );
}

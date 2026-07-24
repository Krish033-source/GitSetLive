import { useEffect, useState } from "react";

export default function UploadCode() {
  const [repos, setRepos] = useState([]);
  const [selectedRepo, setSelectedRepo] = useState(null);
  const [path, setPath] = useState("");
  const [prompt, setPrompt] = useState("");
  const [code, setCode] = useState("");

  const token =
    typeof window !== "undefined" ? localStorage.getItem("token") : null;

  // 🔹 Load repos
  useEffect(() => {
    if (!token) return;

    fetch(`${process.env.NEXT_PUBLIC_API}/repos?token=${token}`)
      .then((res) => res.json())
      .then((data) => setRepos(Array.isArray(data) ? data : []))
      .catch((err) => console.error("Repo load error:", err));
  }, [token]);

  // 🔹 Generate code
  const generate = async () => {
    if (!selectedRepo) return alert("Select repo first");
    if (!prompt) return alert("Enter prompt");

    const res = await fetch(process.env.NEXT_PUBLIC_API + "/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        token,
        owner: selectedRepo.owner.login,
        repo: selectedRepo.name,
        prompt,
      }),
    });

    const data = await res.json();
    setCode(data.final || "");
  };

  // 🔹 Upload to GitHub
  const upload = async () => {
    if (!selectedRepo) return alert("Select repo first");
    if (!code) return alert("Generate code first");
    if (!path) return alert("Enter file path (e.g. src/app.py)");

    await fetch(process.env.NEXT_PUBLIC_API + "/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        token,
        owner: selectedRepo.owner.login,
        repo: selectedRepo.name,
        path: path, // 🔥 dynamic path
        content: code,
      }),
    });

    alert("Code uploaded 🚀");
  };

  return (
    <div style={{ padding: 20 }}>
      <h2>Upload Code</h2>

      {/* 🔹 Repo Select */}
      <select
        onChange={(e) =>
          setSelectedRepo(JSON.parse(e.target.value))
        }
      >
        <option>Select Repo</option>
        {repos.map((r) => (
          <option key={r.id} value={JSON.stringify(r)}>
            {r.name}
          </option>
        ))}
      </select>

      <br /><br />

      {/* 🔹 File Path */}
      <input
        placeholder="Enter file path (e.g. src/app.py or frontend/index.html)"
        value={path}
        onChange={(e) => setPath(e.target.value)}
        style={{ width: "300px" }}
      />

      <br /><br />

      {/* 🔹 Prompt */}
      <textarea
        placeholder="What code do you want?"
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        style={{ width: "400px", height: "100px" }}
      />

      <br /><br />

      <button onClick={generate}>Generate Code</button>

      <pre style={{ background: "#111", color: "#0f0", padding: 10 }}>
        {code}
      </pre>

      <button onClick={upload}>Upload to GitHub</button>
    </div>
  );
}

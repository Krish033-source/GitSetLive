import { useEffect, useState } from "react";

export default function UploadFile() {
  const [repos, setRepos] = useState([]);
  const [selectedRepo, setSelectedRepo] = useState(null);
  const [fileType, setFileType] = useState("README.md");
  const [prompt, setPrompt] = useState("");
  const [output, setOutput] = useState("");

  const token =
    typeof window !== "undefined" ? localStorage.getItem("token") : null;

  // Load repos
  useEffect(() => {
    if (!token) return;
    fetch(`${process.env.NEXT_PUBLIC_API}/repos?token=${token}`)
      .then((res) => res.json())
      .then((data) => setRepos(Array.isArray(data) ? data : []))
      .catch((err) => console.error("Repo load error:", err));
  }, [token]);

  // Generate file content
  const generate = async () => {
    if (!selectedRepo) return alert("Select repo first");

    const res = await fetch(process.env.NEXT_PUBLIC_API + "/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        token,
        owner: selectedRepo.owner.login,
        repo: selectedRepo.name,
        prompt: `Create ${fileType}. ${prompt}`,
      }),
    });

    const data = await res.json();
    setOutput(data.final);
  };

  // Upload to GitHub
  const upload = async () => {
    if (!output) return alert("Generate first");

    await fetch(process.env.NEXT_PUBLIC_API + "/upload", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        token,
        owner: selectedRepo.owner.login,
        repo: selectedRepo.name,
        path: fileType,
        content: output,
      }),
    });

    alert("File uploaded 🚀");
  };

  return (
    <div style={{ padding: 20 }}>
      <h2>Upload Non-Code Files</h2>

      {/* Repo Select */}
      <select onChange={(e) => setSelectedRepo(JSON.parse(e.target.value))}>
        <option>Select Repo</option>
        {repos.map((r) => (
          <option key={r.id} value={JSON.stringify(r)}>
            {r.name}
          </option>
        ))}
      </select>

      {/* File Type */}
      <select onChange={(e) => setFileType(e.target.value)}>
        <option>README.md</option>
        <option>Dockerfile</option>
        <option>Procfile</option>
        <option>requirements.txt</option>
        <option>.env.example</option>
      </select>

      {/* Prompt */}
      <textarea
        placeholder="Describe what you want..."
        onChange={(e) => setPrompt(e.target.value)}
      />

      <br />

      <button onClick={generate}>Generate</button>

      <pre>{output}</pre>

      <button onClick={upload}>Upload to GitHub</button>
    </div>
  );
}

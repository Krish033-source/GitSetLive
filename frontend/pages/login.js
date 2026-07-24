import { useEffect } from "react";
import { useRouter } from "next/router";

const API = process.env.NEXT_PUBLIC_API || "http://localhost:5000";

export default function Login() {
  const router = useRouter();
  const error = router.query.error;

  useEffect(() => {
    const token = localStorage.getItem("token");
    if (token) {
      router.push("/dashboard");
    }
  }, [router]);

  const handleGitHubLogin = () => {
    fetch(`${API}/login`)
      .then(r => r.json())
      .then(data => {
        if (data.url) {
          window.location.href = data.url;
        }
      })
      .catch(err => {
        console.error("Login error:", err);
        alert("Failed to initiate login");
      });
  };

  return (
    <div style={{
      height: "100vh",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
      fontFamily: "system-ui"
    }}>
      <div style={{
        background: "white",
        padding: 40,
        borderRadius: 10,
        boxShadow: "0 10px 25px rgba(0,0,0,0.2)",
        maxWidth: 400,
        width: "100%"
      }}>
        <h1 style={{ textAlign: "center", marginBottom: 10, fontSize: 28 }}>
          Smart Deploy
        </h1>
        <p style={{ textAlign: "center", color: "#666", marginBottom: 30 }}>
          Deploy with AI-powered fixes
        </p>

        {error && (
          <div style={{
            padding: 15,
            background: "#ffebee",
            border: "1px solid #ef5350",
            borderRadius: 5,
            marginBottom: 20,
            color: "#c62828",
            fontSize: 14
          }}>
            {error}
          </div>
        )}

        <button
          onClick={handleGitHubLogin}
          style={{
            width: "100%",
            padding: 15,
            background: "#333",
            color: "white",
            border: "none",
            borderRadius: 5,
            fontSize: 16,
            fontWeight: "bold",
            cursor: "pointer"
          }}
        >
          Login with GitHub
        </button>

        <p style={{
          textAlign: "center",
          marginTop: 20,
          fontSize: 12,
          color: "#999"
        }}>
          We will never post to your GitHub without permission
        </p>
      </div>
    </div>
  );
}

import { useEffect } from "react";
import { useRouter } from "next/router";

const API = process.env.NEXT_PUBLIC_API || "http://localhost:5000";

export default function Callback() {
  const router = useRouter();

  useEffect(() => {
    if (!router.isReady) return;

    const token = new URLSearchParams(window.location.search).get("token");

    if (!token) {
      router.replace("/login?error=No token");
      return;
    }

    if (sessionStorage.getItem("auth_done")) return;
    sessionStorage.setItem("auth_done", "true");

    localStorage.setItem("token", token);

    fetch(`${API}/user-from-token?token=${token}`)
      .then(r => r.json())
      .then(data => {
        if (data.user_id) {
          localStorage.setItem("user_id", data.user_id);
          localStorage.setItem("username", data.username || "User");
          localStorage.setItem("email", data.email || "");
          router.replace("/dashboard");
        } else {
          router.replace("/login?error=User not found");
        }
      })
      .catch((err) => {
        console.error("Auth error:", err);
        router.replace("/login?error=Authentication failed");
      });

  }, [router.isReady, router]);

  return (
    <div style={{
      height: "100vh",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontFamily: "system-ui"
    }}>
      <div style={{ textAlign: "center" }}>
        <h2>Authenticating...</h2>
        <p style={{ color: "#666" }}>Please wait while we set up your account.</p>
      </div>
    </div>
  );
}

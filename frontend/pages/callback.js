import { useEffect, useRef } from "react";
import { useRouter } from "next/router";
import { session } from "../lib/api";
import { useAuth } from "../lib/auth";
import { Spinner } from "../components/ui";

// The backend redirects here with  #token=...  (a URL fragment is never sent to any server).
export default function Callback() {
  const router = useRouter();
  const { refresh } = useAuth();
  const ran = useRef(false);

  useEffect(() => {
    if (ran.current) return;
    ran.current = true;
    const token = new URLSearchParams(window.location.hash.slice(1)).get("token");
    window.history.replaceState(null, "", window.location.pathname); // scrub the token from the address bar
    if (!token) { router.replace("/login?error=" + encodeURIComponent("Login didn't complete. Please try again.")); return; }
    session.set(token);
    refresh().then((me) => router.replace(me ? "/dashboard" : "/login?error=" + encodeURIComponent("Couldn't verify your login. Please try again.")));
  }, [router, refresh]);

  return <div className="center-screen"><div className="col" style={{ alignItems: "center" }}><Spinner lg /><p className="muted">Signing you in…</p></div></div>;
}

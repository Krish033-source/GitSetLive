import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useRouter } from "next/router";
import { api, session } from "./api";

const AuthCtx = createContext(null);
export const useAuth = () => useContext(AuthCtx);

export function AuthProvider({ children }) {
  const router = useRouter();
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    if (!session.get()) { setUser(null); setLoading(false); return null; }
    try { const me = await api.get("/me"); setUser(me); return me; }
    catch (e) { if (e.status === 401) setUser(null); return null; }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);

  useEffect(() => {
    const onLogout = () => { setUser(null); router.replace("/login"); };
    window.addEventListener("gsl:logout", onLogout);
    return () => window.removeEventListener("gsl:logout", onLogout);
  }, [router]);

  const logout = useCallback(async () => {
    try { await api.post("/logout"); } catch {}
    session.clear();
    try { sessionStorage.clear(); } catch {}
    setUser(null);
    router.replace("/login");
  }, [router]);

  return <AuthCtx.Provider value={{ user, loading, refresh, logout }}>{children}</AuthCtx.Provider>;
}

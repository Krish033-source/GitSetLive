import Head from "next/head";
import Link from "next/link";
import { useRouter } from "next/router";
import { useEffect, useState } from "react";
import { useAuth } from "../lib/auth";
import { Icon, Logo, Spinner } from "./ui";

const NAV = [
  { href: "/dashboard", label: "Dashboard", icon: "home" },
  { href: "/scan", label: "Scan & Fix", icon: "scan" },
  { href: "/gitbot", label: "GitBot", icon: "bot" },
  { href: "/upload-code", label: "AI Builder", icon: "sparkle" },
  { href: "/upload-file", label: "File Templates", icon: "file" },
  { href: "/deploy", label: "Deploy", icon: "rocket" },
  { href: "/keys", label: "Saved Keys", icon: "key" },
  { sep: true },
  { href: "/workspaces", label: "Workspaces", icon: "users" },
  { href: "/help", label: "How it works", icon: "help" },
];

export default function Layout({ title, children }) {
  const { user, loading, logout } = useAuth();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [theme, setTheme] = useState("light");

  useEffect(() => { setTheme(document.documentElement.dataset.theme || "light"); }, []);
  useEffect(() => { if (!loading && !user) router.replace("/login"); }, [loading, user, router]);
  useEffect(() => { setOpen(false); }, [router.pathname]);

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("gsl_theme", next); } catch {}
    setTheme(next);
  };

  if (loading || !user) return <div className="center-screen"><Spinner lg /></div>;

  return (
    <>
      <Head><title>{title ? `${title} · GitSetLive` : "GitSetLive"}</title></Head>
      <div className="app">
        <aside className={`sidebar ${open ? "open" : ""}`}>
          <div className="brand"><Logo size={34} />GitSetLive</div>
          <nav className="nav" aria-label="Main">
            {NAV.map((n, i) => n.sep ? <div key={i} className="sep" /> : (
              <Link key={n.href} href={n.href} className={router.pathname === n.href ? "active" : ""} aria-current={router.pathname === n.href ? "page" : undefined}>
                <Icon name={n.icon} /> {n.label}
              </Link>
            ))}
          </nav>
          <div className="spacer" />
          <button className="btn ghost sm" onClick={toggleTheme} style={{ justifyContent: "flex-start" }}>
            <Icon name={theme === "dark" ? "sun" : "moon"} size={15} /> {theme === "dark" ? "Light" : "Dark"} theme
          </button>
          <div className="usercard">
            {user.avatar_url ? <img src={user.avatar_url} alt="" /> : <span className="avatar" />}
            <div className="who"><b>{user.username}</b><span>Signed in with GitHub</span></div>
            <button className="btn ghost icon" onClick={logout} title="Sign out" aria-label="Sign out"><Icon name="logout" size={16} /></button>
          </div>
        </aside>
        <div className="main">
          <div className="topbar">
            <button className="btn ghost icon" onClick={() => setOpen((o) => !o)} aria-label="Menu"><Icon name="menu" /></button>
            <Logo size={26} /><b>GitSetLive</b>
          </div>
          <main className="page">{children}</main>
        </div>
        {open && <div className="overlay" style={{ zIndex: 75 }} onClick={() => setOpen(false)} />}
      </div>
    </>
  );
}

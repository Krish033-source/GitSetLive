import Head from "next/head";
import { useEffect, useState } from "react";
import { useRouter } from "next/router";
import { API, api, session } from "../lib/api";
import { Icon, Logo } from "../components/ui";

const FEATURES = [
  ["scan", "Find it", "Leaked keys, crashes, wrong server settings, missing packages. Every finding is checked against your real code."],
  ["branch", "Fix it", "Review the exact diff, then we open a pull request. Nothing touches your main branch without you."],
  ["rocket", "Ship it", "A pre-flight checklist and the exact build and start values for Render, Vercel or our servers."],
  ["key", "Keep your keys", "Save API keys once, encrypted, and copy them when you need them."],
];

export default function Login() {
  const router = useRouter();
  const [cfg, setCfg] = useState(null);

  useEffect(() => { if (session.get()) router.replace("/dashboard"); }, [router]);
  useEffect(() => { api.get("/config", { timeout: 8000 }).then(setCfg).catch(() => setCfg({ unreachable: true })); }, []);

  const error = router.query.error;
  const blocked = cfg && (cfg.unreachable || cfg.login_configured === false);

  return (
    <>
      <Head><title>GitSetLive: scan it, fix it, ship it live</title></Head>
      <div className="glow" />
      <div style={{ position: "relative", maxWidth: 1080, margin: "0 auto", padding: "0 24px 60px" }}>
        <div className="row between" style={{ padding: "22px 0" }}>
          <div className="brand" style={{ padding: 0 }}><Logo size={38} />GitSetLive</div>
          <a className="btn sm" href="https://github.com/Krish033-source/GitSetLive" target="_blank" rel="noopener noreferrer"><Icon name="github" size={15} /> GitHub</a>
        </div>

        <section className="hero grid" style={{ gridTemplateColumns: "repeat(auto-fit, minmax(320px, 1fr))", alignItems: "center", gap: 36 }}>
          <div>
            <span className="eyebrow">Free for your repos · AI-assisted · you approve everything</span>
            <h1 style={{ margin: "16px 0 18px" }}>Scan it. Fix it.<br /><span className="grad">Ship it live.</span></h1>
            <p className="muted" style={{ fontSize: 18, maxWidth: 520, marginBottom: 26 }}>
              Connect GitHub and GitSetLive finds what would break in production, proposes the fix as a pull request, and walks you through deploying. No DevOps degree needed.
            </p>

            {error && <div className="callout bad" role="alert" style={{ maxWidth: 520, marginBottom: 16 }}><Icon name="alert" /> <span>{error}</span></div>}
            {blocked && <div className="callout warn" style={{ maxWidth: 520, marginBottom: 16 }}><Icon name="alert" /><span>{cfg.unreachable ? <>Can't reach the API at <code>{API}</code>. Is the backend running?</> : "GitHub login isn't configured on the server yet (see the README, step “GitHub OAuth”)."}</span></div>}

            <button className="btn primary lg" disabled={blocked} onClick={() => { window.location.href = `${API}/login`; }}>
              <Icon name="github" size={20} /> Continue with GitHub
            </button>
            <p className="tiny faint" style={{ marginTop: 12, maxWidth: 480 }}>
              We ask for repository access to read code and open pull requests. Revoke it any time in your GitHub settings.
            </p>
          </div>

          <div className="term" aria-label="Example scan output">
            <div className="term-bar"><i /><i /><i /><span style={{ marginLeft: 6 }}>scan.log</span></div>
            <div className="term-body">
<span className="dim">$ gitsetlive scan alice/shop</span>{"\n"}
<span className="ok">OK  </span> 41 files downloaded · 0.8s{"\n"}
<span className="bad">FAIL</span> app.py:12 Groq API key committed{"\n"}
<span className="warn">WARN</span> main.py:9 server listens on localhost{"\n"}
<span className="warn">WARN</span> requirements.txt missing: requests{"\n"}
<span className="ok">OK  </span> 3 fixes ready · health score 64{"\n"}
<span className="dim">… opening pull request #7 …</span>{"\n"}
<span className="ok">OK  </span> review and merge on GitHub{"\n"}
<span className="dim">$ <span style={{ opacity: .7 }}>▍</span></span>
            </div>
          </div>
        </section>
        <p className="tiny faint" style={{ marginTop: -6 }}>Example output. Your own repositories show up on your dashboard.</p>

        <section className="grid stats" style={{ marginTop: 34 }}>
          {FEATURES.map(([icon, title, text]) => (
            <div key={title} className="card">
              <div className="row" style={{ marginBottom: 8 }}><Icon name={icon} size={18} style={{ color: "var(--brand)" }} /><h3>{title}</h3></div>
              <p className="muted small">{text}</p>
            </div>
          ))}
        </section>
      </div>
    </>
  );
}

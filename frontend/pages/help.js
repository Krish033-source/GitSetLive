import Link from "next/link";
import { Icon } from "../components/ui";

const STEPS = [
  ["home", "1. Pick a repository", "Everything starts from a GitHub repository. Create a new one on the Dashboard or choose an existing one.", "/dashboard", "Open dashboard"],
  ["scan", "2. Scan & Fix", "We download your code and check it for leaked passwords, crashes, wrong server settings and missing packages. Every issue shows the exact change we'd make. Tick the ones you want and we open a pull request — you review and merge it on GitHub.", "/scan", "Scan a repo"],
  ["bot", "3. Ask GitBot", "Not sure what a file does or where a setting lives? Ask in plain words. GitBot answers only from your actual code and tells you which files it used.", "/gitbot", "Ask GitBot"],
  ["sparkle", "4. Build with AI", "Describe a change (“add a contact form”, “add login rate limiting”). The AI proposes edits to your real files; you read the diff, edit if you like, and send it as a pull request.", "/upload-code", "Open AI Builder"],
  ["file", "5. Generate project files", "One click for a README, Dockerfile, .env.example, .gitignore or a CI workflow — written from your real code, not a generic template.", "/upload-file", "Open templates"],
  ["rocket", "6. Deploy", "The pre-flight check tells you if the repo is deploy-ready and gives the exact values to paste into Render or Vercel. On servers where it's enabled you can also run it on Our Servers with a temporary public link.", "/deploy", "Go to deploy"],
];

export default function Help() {
  return (
    <>
      <div className="page-header"><div><h1>How GitSetLive works</h1><p>A six-step flow from “it works on my laptop” to a live website. Nothing is ever merged or pushed to your main branch without your approval.</p></div></div>
      <div className="col" style={{ gap: 14 }}>
        {STEPS.map(([icon, title, text, href, cta]) => (
          <div key={title} className="card row" style={{ alignItems: "flex-start", gap: 16, flexWrap: "nowrap" }}>
            <span className="badge info" style={{ padding: 10 }}><Icon name={icon} size={20} /></span>
            <div className="grow"><h2>{title}</h2><p className="muted" style={{ marginTop: 6 }}>{text}</p></div>
            <Link className="btn sm" href={href}>{cta}</Link>
          </div>
        ))}
      </div>
      <div className="card" style={{ marginTop: 18 }}>
        <h2>Good to know</h2>
        <ul className="muted" style={{ lineHeight: 1.9 }}>
          <li><b>Pull requests, not surprises.</b> Fixes and AI changes go to a new branch and a PR by default.</li>
          <li><b>Secrets.</b> If a scan finds a leaked key, rotate it at the provider first — deleting it from the code doesn't remove it from git history.</li>
          <li><b>Deleting repositories</b> needs an extra GitHub permission that we only request when you try it.</li>
          <li><b>Sign out everywhere</b> is available from the Workspaces page if you used a shared computer.</li>
        </ul>
      </div>
    </>
  );
}
Help.title = "How it works";

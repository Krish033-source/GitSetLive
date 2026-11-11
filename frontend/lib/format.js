// The backend sends ISO timestamps ending in "Z"; very old rows are "YYYY-MM-DD HH:MM:SS" (treated as UTC).
export function parseDate(v) {
  if (!v) return null;
  if (typeof v === "number") return new Date(v * 1000);
  const s = /[zZ]|[+-]\d\d:?\d\d$/.test(v) ? v : v.replace(" ", "T") + "Z";
  const d = new Date(s);
  return isNaN(d) ? null : d;
}

export function timeAgo(v) {
  const d = parseDate(v);
  if (!d) return "";
  const sec = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
  if (sec < 45) return "just now";
  const units = [["year", 31536000], ["month", 2592000], ["day", 86400], ["hour", 3600], ["minute", 60]];
  for (const [name, n] of units) if (sec >= n) { const c = Math.floor(sec / n); return `${c} ${name}${c > 1 ? "s" : ""} ago`; }
  return "just now";
}

export function timeLeft(epochSeconds) {
  const sec = Math.floor(epochSeconds - Date.now() / 1000);
  if (sec <= 0) return "expired";
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  return h ? `${h}h ${m}m left` : `${m}m left`;
}

const LABELS = {
  login: "Signed in", repo_created: "Created repository", repo_deleted: "Deleted repository", scan: "Scanned",
  fix_applied: "Opened a fix pull request for", ai_commit: "Committed AI changes to", gitbot: "Asked GitBot about",
  own_server_deploy: "Deployed on Our Servers:", deployment_recorded: "Recorded a deployment of",
  key_saved: "Saved a key:", key_revealed: "Revealed a key:", key_deleted: "Deleted a key:",
  workspace_created: "Created a workspace", workspace_invite: "Invited to a workspace:",
};
export function describeActivity(a) {
  const d = a.details || {};
  const what = d.repo || d.invitee || d.name || "";
  return `${LABELS[a.action] || a.action.replace(/_/g, " ")}${what ? " " + what : ""}`;
}

export const gradeColor = (score) => (score >= 75 ? "var(--good)" : score >= 50 ? "var(--warn)" : "var(--bad)");

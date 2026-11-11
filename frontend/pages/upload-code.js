import ChangeBuilder from "../components/ChangeBuilder";

const PRESETS = [
  { label: "Add a /health endpoint", prompt: "Add a /health endpoint that returns {\"status\":\"ok\"} so hosting platforms and uptime monitors can check the app is alive." },
  { label: "Add input validation", prompt: "Review the request handlers and add proper input validation with clear error messages. Keep the existing behaviour for valid input." },
  { label: "Add rate limiting", prompt: "Add simple per-IP rate limiting to the public/auth endpoints, configurable through environment variables." },
  { label: "Write tests", prompt: "Add a small, runnable automated test suite covering the most important functions or endpoints, plus the command to run it in the README." },
  { label: "Improve error handling", prompt: "Find places where errors are swallowed or can crash the app and add proper error handling and useful log messages." },
];

export default function AIBuilder() {
  return (
    <>
      <div className="page-header"><div><h1>AI Builder</h1><p>Describe a change in plain words. The AI edits your real files, you review every line, then it goes to GitHub as a pull request.</p></div></div>
      <ChangeBuilder presets={PRESETS} placeholder="e.g. Add a contact form page that emails me the message, and validate the email field." />
    </>
  );
}
AIBuilder.title = "AI Builder";

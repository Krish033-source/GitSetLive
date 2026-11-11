import ChangeBuilder from "../components/ChangeBuilder";

const PRESETS = [
  { label: "README.md", prompt: "Create a professional README.md written from this project's actual code: what it does, features, tech stack, setup steps, required environment variables, how to run and how to deploy. Do not invent features that aren't in the code." },
  { label: ".env.example", prompt: "Create a .env.example listing every environment variable the code reads, with a short comment explaining each. Never include real values." },
  { label: ".gitignore", prompt: "Create or complete the .gitignore for this project's stack so secrets, dependencies, build output and local databases are never committed." },
  { label: "Dockerfile", prompt: "Create a production-ready Dockerfile (and .dockerignore) for this project: small base image, non-root user, dependency caching, reads PORT from the environment." },
  { label: "GitHub Actions CI", prompt: "Create a GitHub Actions workflow in .github/workflows/ci.yml that installs dependencies and runs the build and tests (if any) on every push and pull request." },
  { label: "render.yaml", prompt: "Create a render.yaml Blueprint for deploying this project on Render with the correct build and start commands, a health check path and the environment variables it needs (secrets marked sync: false)." },
  { label: "LICENSE (MIT)", prompt: "Add an MIT LICENSE file with the current year and the repository owner as the copyright holder." },
];

export default function FileTemplates() {
  return (
    <>
      <div className="page-header"><div><h1>File Templates</h1><p>Generate the files every real project needs — written from your actual code, not a generic template. Review the result, then send it as a pull request.</p></div></div>
      <ChangeBuilder presets={PRESETS} placeholder="Pick a file type above, or describe the file you need." />
    </>
  );
}
FileTemplates.title = "File Templates";

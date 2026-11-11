import patching
import analyzer


# ---------------------------------------------------------------- patching
def test_replace_exact_and_indentation_tolerant():
    src = "def f():\n    x = 1\n    return x\n"
    out = patching.apply_fix(src, {"op": "replace", "search": "x = 1", "replace": "x = 2"})
    assert "x = 2" in out and out.count("\n") == src.count("\n")
    # model forgot the indentation -> still matches uniquely
    out = patching.apply_fix(src, {"op": "replace", "search": "return x", "replace": "return x + 1"})
    assert "    return x + 1" in out


def test_replace_ambiguous_and_missing_are_refused():
    src = "a = 1\na = 1\n"
    for fix in ({"op": "replace", "search": "a = 1", "replace": "a = 2"},
                {"op": "replace", "search": "nope", "replace": "x"}):
        try:
            patching.apply_fix(src, fix)
            assert False, "should have raised"
        except patching.PatchError:
            pass


def test_snippet_fix_never_wipes_the_file():
    """Regression: the old apply-fix overwrote the whole file with the AI's snippet."""
    big = "\n".join(f"line_{i} = {i}" for i in range(200)) + "\n"
    new = patching.apply_fix(big, {"op": "replace", "search": "line_5 = 5", "replace": "line_5 = 55"})
    assert len(new) >= len(big) and "line_199 = 199" in new
    try:
        patching.validate("x.py", big, "x = 1\n")
        assert False
    except patching.PatchError:
        pass


def test_syntax_and_json_guards_and_append_idempotent():
    try:
        patching.validate("a.py", "x = 1\n", "def (:\n")
        assert False
    except patching.PatchError:
        pass
    try:
        patching.validate("a.json", "{}", "{oops")
        assert False
    except patching.PatchError:
        pass
    out = patching.apply_fix("node_modules\n", {"op": "append", "content": ".env\n"})
    assert out == "node_modules\n.env\n"
    try:
        patching.apply_fix(out, {"op": "append", "content": ".env\n"})
        assert False
    except patching.PatchError:
        pass


def test_apply_all_skips_bad_fix_but_keeps_good_ones():
    originals = {"a.py": "x = 1\n", "b.py": "y = 2\n"}
    fixes = [{"id": "1", "file": "a.py", "op": "replace", "search": "x = 1", "replace": "x = 3"},
             {"id": "2", "file": "b.py", "op": "replace", "search": "missing", "replace": "z"},
             {"id": "3", "file": "a.py", "op": "replace", "search": "x = 3", "replace": "x = ("}]  # syntax error
    changed, applied, skipped = patching.apply_all(originals, fixes)
    assert changed == {"a.py": "x = 3\n"} and applied == ["1"] and {s["id"] for s in skipped} == {"2", "3"}


# ---------------------------------------------------------------- analyzer
def run(files):
    return analyzer.analyze(sorted(files), files)


def rules(res):
    return {f["rule"] for f in res["findings"]}


def test_secrets_are_found_and_never_echoed():
    key = "gsk_" + "a1B2c3D4e5F6g7H8i9J0k1L2"
    res = run({"app.py": f'API = "{key}"\n', ".gitignore": ".env\n"})
    hit = next(f for f in res["findings"] if f["rule"] == "secret-known")
    assert hit["severity"] == "critical" and key not in (hit["line_context"] or "") and "gsk_…" in hit["line_context"]


def test_placeholders_and_env_reads_are_not_flagged():
    res = run({"app.py": 'KEY = os.getenv("API_KEY")\nPASSWORD = "your_password_here"\nTOKEN = "changeme123456"\n'})
    assert not {"secret-generic", "secret-known"} & rules(res)


def test_localhost_bind_debug_and_port_have_working_fixes():
    src = 'import os\nfrom flask import Flask\napp = Flask(__name__)\nif __name__ == "__main__":\n    app.run(host="127.0.0.1", port=5000, debug=True)\n'
    res = run({"app.py": src, "requirements.txt": "flask\ngunicorn\n"})
    r = rules(res)
    assert {"py-localhost", "py-debug"} <= r
    fixed = src
    for f in res["findings"]:
        if f["rule"] in ("py-localhost", "py-debug", "py-port") and f["fix"]:
            fixed = patching.apply_fix(fixed, f["fix"])
    assert "0.0.0.0" in fixed and "debug=False" in fixed


def test_missing_dependencies_and_implied_ones():
    files = {"main.py": "from fastapi import FastAPI\nimport requests, pydantic\napp = FastAPI()\n",
             "requirements.txt": "fastapi\nuvicorn\n"}
    res = run(files)
    miss = next(f for f in res["findings"] if f["rule"] == "py-missing-deps")
    assert "requests" in miss["title"] and "pydantic" not in miss["title"]   # pydantic ships with fastapi
    assert miss["fix"]["op"] == "append"


def test_no_requirements_creates_one():
    res = run({"app.py": "import flask, requests\napp = flask.Flask(__name__)\n"})
    f = next(f for f in res["findings"] if f["rule"] == "py-no-requirements")
    assert f["fix"]["op"] == "create" and "flask" in f["fix"]["content"] and "requests" in f["fix"]["content"]


def test_node_missing_dep_and_aliases_ignored():
    files = {"package.json": '{"name":"x","dependencies":{"express":"4"},"scripts":{}}',
             "index.js": "const e=require('express');const a=require('axios');const l=require('./lib');const f=require('fs');"}
    res = run(files)
    f = next(f for f in res["findings"] if f["rule"] == "js-missing-deps")
    assert "axios" in f["title"] and "express" not in f["title"] and "fs" not in f["title"]


def test_monorepo_detection_and_recommendations():
    files = {"backend/main.py": "from fastapi import FastAPI\napp = FastAPI()\n", "backend/requirements.txt": "fastapi\nuvicorn\n",
             "frontend/package.json": '{"dependencies":{"next":"15"},"scripts":{"dev":"next dev"}}'}
    apps = {a["root"]: a for a in run(files)["apps"]}
    assert apps["backend"]["start_command"] == "uvicorn main:app --host 0.0.0.0 --port $PORT"
    assert apps["frontend"]["framework"] == "next" and apps["frontend"]["recommend"]["vercel"]["root_dir"] == "frontend"
    assert apps["backend"]["recommend"]["vercel"] is None


def test_committed_env_and_gitignore():
    files = {".env": "SECRET_KEY=abcdef123456\n", "app.py": "x=1\n"}
    r = rules(run(files))
    assert "env-committed" in r and "no-gitignore" in r


def test_clean_repo_scores_high():
    files = {"README.md": "# x", "LICENSE": "MIT", ".gitignore": ".env\n__pycache__/\n*.log\n.env.local\n*.db\n*.pyc\n.venv/\nvenv/\n*.sqlite3\n.DS_Store\n",
             "main.py": 'print("hi")\n'}
    assert run(files)["score"] >= 90


def test_patterns_inside_strings_and_nosec_lines_are_not_flagged():
    src = ('PATTERN = "debug=True"\nRULE = re.compile(r"verify=False")\n'
           'conn.execute(f"UPDATE {table} SET x=1")  # nosec - constant\n'
           'API = "gsk_' + "a1B2c3D4e5F6g7H8i9J0k1L2" + '"  # nosec\n')
    r = rules(run({"x.py": src, ".gitignore": ".env\n"}))
    assert not {"py-debug", "py-tls", "py-sqli", "secret-known"} & r

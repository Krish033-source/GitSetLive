"""Applying structured fixes to REAL file contents.

The old "Apply Fix" wrote the AI's `fix` string over the *entire* file, so a
fix that was just a snippet silently destroyed the rest of the file. Fixes are
now precise edits:

  {"file": "app.py", "op": "replace", "search": "<exact old code>", "replace": "<new code>"}
  {"file": ".gitignore", "op": "append", "content": ".env\\n"}
  {"file": "requirements.txt", "op": "create", "content": "fastapi\\n"}

`search` must match the current file (exactly, or ignoring indentation) and be
unambiguous; results are sanity-checked (Python must still parse, JSON must
still load, a file can't be gutted) before anything is committed.
"""

import ast
import difflib
import json
import textwrap
from typing import Dict, List, Optional, Tuple


class PatchError(Exception):
    pass


def _fuzzy_find(work: str, search: str) -> Optional[Tuple[int, int, str]]:
    """Find `search` ignoring per-line indentation/trailing whitespace. Returns (start, end, indent)."""
    want = [ln.strip() for ln in search.strip("\n").split("\n")]
    while want and not want[0]:
        want.pop(0)
    while want and not want[-1]:
        want.pop()
    if not want:
        return None

    lines = work.split("\n")
    stripped = [ln.strip() for ln in lines]
    hits = [i for i in range(len(lines) - len(want) + 1) if stripped[i:i + len(want)] == want]
    if len(hits) != 1:
        if len(hits) > 1:
            raise PatchError("the code to change appears more than once — ambiguous")
        return None

    i = hits[0]
    start = sum(len(l) + 1 for l in lines[:i])
    end = start + sum(len(l) + 1 for l in lines[i:i + len(want)]) - 1
    indent = lines[i][: len(lines[i]) - len(lines[i].lstrip())]
    return start, end, indent


def apply_fix(original: Optional[str], fix: dict) -> str:
    op = fix.get("op")

    if op == "create":
        content = fix.get("content")
        if original is not None:
            raise PatchError("file already exists")
        if not isinstance(content, str) or not content.strip():
            raise PatchError("nothing to create")
        return content if content.endswith("\n") else content + "\n"

    if original is None:
        raise PatchError("file not found in the repository")

    if op == "append":
        text = fix.get("content")
        if not isinstance(text, str) or not text.strip():
            raise PatchError("nothing to append")
        if text.strip() in original:
            raise PatchError("already present — nothing to do")
        sep = "" if (not original or original.endswith("\n")) else "\n"
        return original + sep + (text if text.endswith("\n") else text + "\n")

    if op == "replace":
        search, replace = fix.get("search"), fix.get("replace")
        if not isinstance(search, str) or not search.strip() or not isinstance(replace, str):
            raise PatchError("invalid replace instruction")

        crlf = "\r\n" in original
        work = original.replace("\r\n", "\n")
        s = search.replace("\r\n", "\n")
        r = replace.replace("\r\n", "\n")

        count = work.count(s)
        if count == 1:
            start = work.index(s)
            new = work[:start] + r + work[start + len(s):]
        elif count > 1:
            raise PatchError("the code to change appears more than once — ambiguous")
        else:
            found = _fuzzy_find(work, s)
            if not found:
                raise PatchError("the code to change was not found (the file may have changed)")
            start, end, indent = found
            block = textwrap.indent(textwrap.dedent(r).strip("\n"), indent)
            new = work[:start] + block + work[end:]

        if new == work:
            raise PatchError("no change")
        return new.replace("\n", "\r\n") if crlf else new

    raise PatchError(f"unsupported fix type: {op!r}")


def validate(path: str, original: Optional[str], new: str) -> None:
    """Refuse results that are obviously broken."""
    if original and len(original) > 500 and len(new) < len(original) * 0.5:
        raise PatchError("would remove more than half of the file")
    low = path.lower()
    if low.endswith(".py"):
        try:
            ast.parse(new)
        except SyntaxError as e:
            raise PatchError(f"would introduce a Python syntax error (line {e.lineno})")
    elif low.endswith(".json"):
        try:
            json.loads(new)
        except ValueError:
            raise PatchError("would make the JSON file invalid")


def apply_all(originals: Dict[str, Optional[str]], fixes: List[dict]):
    """Apply fixes in order, file by file.

    originals: {path: current text or None if the file doesn't exist}
    fixes:     [{"id", "file", "op", ...}]
    Returns (new_texts: {path: str}, applied_ids: [str], skipped: [{"id", "file", "reason"}])
    """
    current = dict(originals)
    changed: Dict[str, str] = {}
    applied, skipped = [], []

    for fx in fixes:
        path = fx.get("file")
        fid = fx.get("id")
        try:
            if path not in current:
                raise PatchError("file not available")
            before = current[path]
            after = apply_fix(before, fx)
            validate(path, before, after)
            current[path] = after
            changed[path] = after
            applied.append(fid)
        except PatchError as e:
            skipped.append({"id": fid, "file": path, "reason": str(e)})

    return changed, applied, skipped


def unified_diff(old: Optional[str], new: Optional[str], path: str) -> str:
    a = (old or "").splitlines(keepends=True)
    b = (new or "").splitlines(keepends=True)
    diff = difflib.unified_diff(
        a, b,
        fromfile=f"a/{path}" if old is not None else "/dev/null",
        tofile=f"b/{path}" if new is not None else "/dev/null",
        n=3,
    )
    out = "".join(diff)
    return out[:60_000]

"""Saved Keys: a small per-user vault for API keys / tokens.

* Values are Fernet-encrypted at rest (ENCRYPTION_KEY) in the existing `api_keys` table.
* The list endpoint NEVER returns values — only a name, an optional note and the last 4 characters.
* A value is returned only by an explicit, rate-limited "reveal" call, which is written to the activity log.
* This is server-side encryption, not zero-knowledge: the server can decrypt (that is what lets you
  reuse a key in a deploy). Don't store anything you couldn't rotate.
"""

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

import db
import encryption
import security
from routers.common import fail

router = APIRouter(tags=["keys"])
NAME_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9 _.\-]{0,59}$"
MAX_KEYS = 50


def _hint(value: Optional[str]) -> str:
    if not value:
        return "unreadable"
    return "••••" + value[-4:] if len(value) >= 12 else "••••"


@router.get("/keys")
def list_keys(user: dict = Depends(security.current_user)):
    with db.db() as conn:
        rows = conn.execute(
            "SELECT id, platform, platform_account_name, encrypted_key, created_at FROM api_keys "
            "WHERE user_id=? ORDER BY lower(platform)", (user["id"],)).fetchall()
    return {"keys": [{"id": r["id"], "name": r["platform"], "note": r["platform_account_name"],
                      "hint": _hint(encryption.decrypt(r["encrypted_key"])), "saved_at": r["created_at"]} for r in rows]}


class KeyIn(BaseModel):
    name: str = Field(pattern=NAME_PATTERN)
    value: str = Field(min_length=1, max_length=4000)
    note: Optional[str] = Field(default=None, max_length=120)


@router.put("/keys")
def save_key(body: KeyIn, user: dict = Depends(security.current_user)):
    """Create a key, or overwrite the one with the same name (case-insensitive)."""
    value = body.value.strip()
    if not value:
        fail(400, "The key value can't be empty.", "empty")
    name = body.name.strip()
    enc = encryption.encrypt(value)
    with db.db() as conn:
        row = conn.execute("SELECT id FROM api_keys WHERE user_id=? AND lower(platform)=lower(?)",
                           (user["id"], name)).fetchone()
        if row:
            conn.execute("UPDATE api_keys SET platform=?, encrypted_key=?, platform_account_name=?, created_at=? WHERE id=?",
                         (name, enc, (body.note or "").strip() or None, db.now(), row["id"]))
            key_id, created = row["id"], False
        else:
            if conn.execute("SELECT COUNT(*) n FROM api_keys WHERE user_id=?", (user["id"],)).fetchone()["n"] >= MAX_KEYS:
                fail(409, f"You can save up to {MAX_KEYS} keys. Delete one first.", "limit")
            key_id, created = db.new_id("key"), True
            conn.execute("INSERT INTO api_keys (id, user_id, platform, encrypted_key, platform_account_name, created_at) "
                         "VALUES (?,?,?,?,?,?)", (key_id, user["id"], name, enc, (body.note or "").strip() or None, db.now()))
    db.log_activity(user["id"], "key_saved", {"name": name})
    return {"id": key_id, "created": created, "hint": _hint(value)}


@router.post("/keys/{key_id}/reveal")
def reveal_key(key_id: str, user: dict = Depends(security.current_user),
               _rl=Depends(security.rate_limit("reveal", 30, 600))):
    with db.db() as conn:
        row = conn.execute("SELECT platform, encrypted_key FROM api_keys WHERE id=? AND user_id=?",
                           (key_id, user["id"])).fetchone()
    if not row:
        fail(404, "Key not found.", "not_found")
    value = encryption.decrypt(row["encrypted_key"])
    if value is None:
        fail(410, "This key can't be decrypted any more (the server's ENCRYPTION_KEY changed). Save it again.", "unreadable")
    db.log_activity(user["id"], "key_revealed", {"name": row["platform"]})
    return {"value": value}


@router.delete("/keys/{key_id}")
def delete_key(key_id: str, user: dict = Depends(security.current_user)):
    with db.db() as conn:
        row = conn.execute("SELECT platform FROM api_keys WHERE id=? AND user_id=?", (key_id, user["id"])).fetchone()
        if not row:
            fail(404, "Key not found.", "not_found")
        conn.execute("DELETE FROM api_keys WHERE id=?", (key_id,))
    db.log_activity(user["id"], "key_deleted", {"name": row["platform"]})
    return {"ok": True}

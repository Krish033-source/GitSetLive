import json

import db
from conftest import make_user


def test_keys_are_encrypted_masked_and_revealed_only_on_request(client):
    u = make_user()
    secret = "gsk_SuperSecretValue1234567890"
    r = client.put("/keys", json={"name": "GROQ_API_KEY", "value": f"  {secret}  ", "note": "main account"}, headers=u["headers"])
    assert r.status_code == 200 and r.json()["created"] is True

    with db.db() as c:   # encrypted at rest
        stored = c.execute("SELECT encrypted_key FROM api_keys").fetchone()[0]
    assert secret not in stored

    listing = client.get("/keys", headers=u["headers"]).json()["keys"]
    assert listing[0]["name"] == "GROQ_API_KEY" and listing[0]["hint"] == "••••7890" and listing[0]["note"] == "main account"
    assert secret not in json.dumps(listing)                       # never in the list

    kid = listing[0]["id"]
    assert client.post(f"/keys/{kid}/reveal", headers=u["headers"]).json()["value"] == secret   # whitespace trimmed
    acts = client.get("/activity", headers=u["headers"]).json()["activities"]
    assert any(a["action"] == "key_revealed" and a["details"]["name"] == "GROQ_API_KEY" for a in acts)
    assert secret not in json.dumps(acts)                          # the log records the name, never the value


def test_same_name_overwrites_case_insensitively_and_short_values_are_fully_masked(client):
    u = make_user()
    client.put("/keys", json={"name": "Render", "value": "abcdef"}, headers=u["headers"])
    r = client.put("/keys", json={"name": "RENDER", "value": "new-value-123456"}, headers=u["headers"])
    assert r.json()["created"] is False
    keys = client.get("/keys", headers=u["headers"]).json()["keys"]
    assert len(keys) == 1 and keys[0]["name"] == "RENDER" and keys[0]["hint"] == "••••3456"
    client.put("/keys", json={"name": "short", "value": "abc"}, headers=u["headers"])
    assert [k["hint"] for k in client.get("/keys", headers=u["headers"]).json()["keys"] if k["name"] == "short"] == ["••••"]


def test_users_cannot_read_or_delete_each_others_keys(client):
    a, b = make_user("a", "1"), make_user("b", "2")
    kid = client.put("/keys", json={"name": "mine", "value": "topsecretvalue99"}, headers=a["headers"]).json()["id"]
    assert client.get("/keys", headers=b["headers"]).json()["keys"] == []
    assert client.post(f"/keys/{kid}/reveal", headers=b["headers"]).status_code == 404
    assert client.delete(f"/keys/{kid}", headers=b["headers"]).status_code == 404
    assert client.delete(f"/keys/{kid}", headers=a["headers"]).status_code == 200
    assert client.get("/keys", headers=a["headers"]).json()["keys"] == []


def test_validation_limits_and_auth(client):
    u = make_user()
    assert client.get("/keys").status_code == 401
    assert client.put("/keys", json={"name": "bad/name", "value": "x"}, headers=u["headers"]).status_code == 422
    assert client.put("/keys", json={"name": "ok", "value": "   "}, headers=u["headers"]).status_code == 400
    assert client.put("/keys", json={"name": "ok", "value": "x" * 5000}, headers=u["headers"]).status_code == 422
    for i in range(50):
        assert client.put("/keys", json={"name": f"k{i}", "value": "value-value-1"}, headers=u["headers"]).status_code == 200
    assert client.put("/keys", json={"name": "one-too-many", "value": "v"}, headers=u["headers"]).status_code == 409
    assert client.put("/keys", json={"name": "k3", "value": "updated-value-1"}, headers=u["headers"]).status_code == 200  # overwrite still allowed


def test_reveal_is_rate_limited(client):
    u = make_user()
    kid = client.put("/keys", json={"name": "k", "value": "value-value-1"}, headers=u["headers"]).json()["id"]
    codes = [client.post(f"/keys/{kid}/reveal", headers=u["headers"]).status_code for _ in range(32)]
    assert codes[0] == 200 and codes[-1] == 429

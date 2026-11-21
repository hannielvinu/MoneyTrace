"""JWT authentication and role guard."""
from moneytrace.auth import create_access_token, decode_access_token


def test_token_roundtrip():
    tok = create_access_token("u1", "a@b.c", "USER")
    payload = decode_access_token(tok)
    assert payload["sub"] == "u1" and payload["role"] == "USER"


def test_tampered_token_rejected():
    tok = create_access_token("u1", "a@b.c", "USER")
    assert decode_access_token(tok[:-2] + "xx") is None


def test_login_bad_password(client):
    r = client.post("/api/auth/login", json={"email": "victim@moneytrace.in", "password": "nope"})
    assert r.status_code == 401


def test_me_requires_token(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_returns_user(client, victim_headers):
    r = client.get("/api/auth/me", headers=victim_headers)
    assert r.status_code == 200 and r.json()["role"] == "USER"


def test_victim_blocked_from_operator_routes(client, victim_headers):
    for path in ("/api/dashboard", "/api/incidents"):
        assert client.get(path, headers=victim_headers).status_code == 403


def test_operator_allowed(client, operator_headers):
    r = client.get("/api/dashboard", headers=operator_headers)
    assert r.status_code == 200
    assert "metrics" in r.json()

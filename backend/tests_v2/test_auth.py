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


def test_deployed_service_never_seeds_public_demo_passwords(monkeypatch):
    from sqlalchemy import select
    from moneytrace.db import database as db, models as m
    monkeypatch.setenv("K_SERVICE", "moneytrace")
    monkeypatch.delenv("SEED_DEMO_USERS", raising=False)
    with db.get_engine().begin() as conn:
        conn.execute(m.users.delete().where(m.users.c.email == "operator@moneytrace.in"))
        db.seed_users(conn)
        assert conn.execute(select(m.users).where(m.users.c.email == "operator@moneytrace.in")).first() is None
    monkeypatch.setenv("SEED_DEMO_USERS", "1")
    monkeypatch.setenv("DEMO_OPERATOR_PASSWORD", "a-long-private-password")
    with db.get_engine().begin() as conn:
        db.seed_users(conn)
    u = db.get_user_by_email("operator@moneytrace.in")
    assert u["password_hash"] == db.hash_password("a-long-private-password")
    assert u["password_hash"] != db.hash_password("operator123")
    monkeypatch.delenv("K_SERVICE")
    monkeypatch.delenv("DEMO_OPERATOR_PASSWORD")
    monkeypatch.delenv("SEED_DEMO_USERS")
    with db.get_engine().begin() as conn:  # restore dev account for the other tests
        db.seed_users(conn)


def test_event_stream_requires_token(client):
    assert client.get("/api/events").status_code == 401
    assert client.get("/api/events?token=garbage").status_code == 401


def test_event_filtering_per_role():
    from moneytrace.main import _visible_event
    ev = {"event_type": "RELATED_INCIDENTS_FOUND", "user_id": "u1",
          "payload": {"related_count": 3, "shared_entities": ["UPI: x@ybl"]}}
    assert _visible_event(ev, {"id": "u2", "role": "USER"}) is None
    mine = _visible_event(ev, {"id": "u1", "role": "USER"})
    assert "shared_entities" not in mine["payload"] and mine["payload"]["related_count"] == 3
    assert _visible_event(ev, {"id": "op", "role": "FRAUD_OPERATOR"})["payload"]["shared_entities"]

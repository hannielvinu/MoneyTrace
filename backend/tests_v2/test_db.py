"""Database helper behaviour that must survive the storage migration."""
from moneytrace.db import database as db


def test_seeded_users_and_ledger(app):
    assert db.get_user_by_email("operator@moneytrace.in")["role"] == "FRAUD_OPERATOR"
    assert db.get_transaction("TXN784219") is not None


def test_audit_and_update(app):
    inc = db.get_user_incidents("usr_demo_victim_1")[0]
    db.add_audit_log(inc["id"], "unit-test", "detail")
    db.update_incident_record(inc["id"], {"status": "UNIT_TEST"})
    full = db.get_incident(inc["id"])
    assert full["status"] == "UNIT_TEST"
    assert any(a["action"] == "unit-test" for a in full["audit_trail"])


def test_migration_url_uses_direct_endpoint_of_same_database(monkeypatch):
    from moneytrace.db import database as db
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@ep-a-pooler.c-4.ap-southeast-1.aws.neon.tech/neondb?sslmode=require")
    monkeypatch.delenv("DATABASE_URL_UNPOOLED", raising=False)
    assert "@ep-a.c-4.ap-southeast-1.aws.neon.tech/neondb" in db.migration_database_url()
    # an unpooled URL for a different database must never redirect migrations away from the app's database
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@localhost/local")
    monkeypatch.setenv("DATABASE_URL_UNPOOLED", "postgresql://u:p@ep-a.c-4.ap-southeast-1.aws.neon.tech/neondb")
    assert db.migration_database_url().endswith("@localhost/local")

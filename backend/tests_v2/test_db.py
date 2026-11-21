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

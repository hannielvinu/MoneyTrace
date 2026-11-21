"""Help-desk mode: consent gate, disclaimer endpoint, usage logging without personal data, operator accounts."""
from tests_v2.test_pipeline import REPORT


def test_report_without_consent_is_rejected(client, victim_headers):
    body = dict(REPORT)
    body.pop("consent")
    r = client.post("/api/portal/reports", json=body, headers=victim_headers)
    assert r.status_code == 400 and "Consent" in r.json()["detail"]


def test_helpdesk_info_has_official_channels(client):
    d = client.get("/api/helpdesk/info").json()
    assert d["official_channels"]["helpline"] == "1930" and "cybercrime.gov.in" in d["official_channels"]["portal"]
    assert "not an official" in d["disclaimer"]


def test_usage_summary_counts_and_contains_no_pii(client, victim_headers, operator_headers):
    r = client.post("/api/portal/reports", json=REPORT, headers=victim_headers)
    inc = r.json()["incident_id"]
    client.post(f"/api/incidents/{inc}/review", json={"action": "APPROVED"}, headers=operator_headers)
    u = client.get("/api/helpdesk/usage", headers=operator_headers).json()
    assert u["totals"]["reports_received"] >= 1 and u["totals"]["guidance_delivered"] >= 1
    assert u["totals"]["operator_signoffs"] >= 1
    blob = str(u)
    assert "kyc-update.pay@ybl" not in blob and "TXN784219" not in blob and "victim@" not in blob
    assert client.get("/api/helpdesk/usage", headers=victim_headers).status_code == 403


def test_create_operator_account(app, client):
    import importlib.util, os
    spec = importlib.util.spec_from_file_location("create_operator", os.path.join(os.path.dirname(__file__), "..", "scripts", "create_operator.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    uid, pw, existed = mod.create("whitehats.member@example.org", "Club Member")
    r = client.post("/api/auth/login", json={"email": "whitehats.member@example.org", "password": pw})
    assert r.status_code == 200 and r.json()["user"]["role"] == "FRAUD_OPERATOR"


def test_retention_purge_removes_old_reports_but_keeps_counts(app):
    from datetime import datetime, timedelta, timezone
    from moneytrace.db import database as db
    old = db.create_incident({"user_id": "usr_demo_victim_1", "narrative": "old report 9876543210", "language": "en",
                              "created_ts": datetime.now(timezone.utc) - timedelta(days=200)})
    db.add_audit_log(old, "x", "y")
    db.record_usage_event("report_received", old, None, "en")
    assert db.purge_reports_older_than(90, dry_run=True)["incidents"] >= 1
    db.purge_reports_older_than(90)
    assert db.get_incident(old) is None
    assert db.get_usage_summary(400)["totals"]["reports_received"] >= 1

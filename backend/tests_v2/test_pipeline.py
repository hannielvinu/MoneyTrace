"""End-to-end 12-milestone pipeline through the public API (no external services)."""

EXPECTED_MILESTONES = [
    "INCIDENT_CREATED",
    "INVESTIGATION_STARTED",
    "TRANSACTION_FOUND",
    "SIGNALS_ANALYZED",
    "RELATED_INCIDENTS_FOUND",
    "GRAPH_READY",
    "EVIDENCE_PREPARED",
    "N8N_WORKFLOW_STARTED",
    "N8N_WORKFLOW_COMPLETED",
    "HUMAN_REVIEW_REQUIRED",
    "INCIDENT_COMPLETED",
    "USER_NOTIFICATION_CREATED",
]

REPORT = {
    "narrative": "Received a call claiming to be HDFC bank KYC department. They asked me to transfer "
                 "money to kyc-update.pay@ybl or my account will freeze. Transferred ₹18,500.",
    "language": "en",
    "transaction_id": "TXN784219",
    "amount": 18500.0,
    "consent": True,
}


def _submit(client, headers, payload=None):
    r = client.post("/api/portal/reports", json=payload or REPORT, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["incident_id"]


def test_pipeline_emits_all_milestones_in_order(client, victim_headers, operator_headers):
    inc_id = _submit(client, victim_headers)
    events = client.get(f"/api/incidents/{inc_id}/events", headers=operator_headers).json()["events"]
    types = [e["event_type"] for e in events]
    # Every milestone present, in canonical order (other informational events may be interleaved)
    positions = [types.index(m) for m in EXPECTED_MILESTONES]
    assert positions == sorted(positions), types

    inc = client.get(f"/api/incidents/{inc_id}", headers=operator_headers).json()
    assert inc["investigation_stage"] == "COMPLETE"
    assert inc["evidence_package"] is not None
    assert inc["evidence_package"]["transaction_id"] == "TXN784219"


def test_victim_data_isolation(client, victim_headers, victim2_headers):
    inc_id = _submit(client, victim_headers)
    mine = client.get("/api/portal/my-reports", headers=victim_headers).json()["reports"]
    theirs = client.get("/api/portal/my-reports", headers=victim2_headers).json()["reports"]
    assert any(r["id"] == inc_id for r in mine)
    assert not any(r["id"] == inc_id for r in theirs)


def test_notification_created(client, victim_headers):
    _submit(client, victim_headers)
    notifs = client.get("/api/portal/notifications", headers=victim_headers).json()["notifications"]
    assert notifs and notifs[0]["guidance"]


def test_operator_signoff(client, victim_headers, operator_headers):
    inc_id = _submit(client, victim_headers)
    r = client.post(f"/api/incidents/{inc_id}/review", json={"action": "APPROVED"}, headers=operator_headers)
    assert r.status_code == 200
    inc = client.get(f"/api/incidents/{inc_id}", headers=operator_headers).json()
    assert inc["status"] == "OPERATOR_CONFIRMED"

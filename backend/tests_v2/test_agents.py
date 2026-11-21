"""ADK agent layer: redaction, ordered milestones, ReAct tools, grounding check and safe fallback (no network)."""
import asyncio

import pytest

from moneytrace.agents import guidance as G
from moneytrace.agents.milestones import MilestoneEmitter, ORDER
from moneytrace.agents.redact import redact, resolve


def test_redaction_hides_pii_but_keeps_upi_and_amount():
    t = "Called from +91-98765-43210, acct 009214481029, paid ₹18,500 to kyc-update.pay@ybl"
    red, mapping = redact(t)
    assert "98765" not in red and "009214481029" not in red
    assert "kyc-update.pay@ybl" in red and "18,500" in red
    assert resolve("[PHONE_1]", t) == "+91-98765-43210"


def test_milestones_are_emitted_in_canonical_order(monkeypatch):
    sent = []

    async def fake_emit(event_type, **kw):
        sent.append(event_type)

    monkeypatch.setattr("moneytrace.agents.milestones.emit_event", fake_emit)
    em = MilestoneEmitter("MT-T", "u")

    async def run():
        # agent calls tools out of order: related search before ledger lookup
        await em.emit("RELATED_INCIDENTS_FOUND", "x", "s", {})
        await em.emit("GRAPH_READY", "x", "s", {})
        assert sent == []  # buffered: earlier milestones missing
        await em.emit("INVESTIGATION_STARTED", "x", "s", {})
        await em.emit("TRANSACTION_FOUND", "x", "s", {})
        await em.emit("SIGNALS_ANALYZED", "x", "s", {})
        await em.emit("SIGNALS_ANALYZED", "x", "s", {})  # duplicate ignored
    asyncio.run(run())
    assert sent == ORDER[1:6]


def test_parse_steps_accepts_fenced_json():
    raw = 'Here you go:\n```json\n{"steps": [{"text": "Call 1930", "citations": ["a#1"]}, {"text": " "}]}\n```'
    assert G.parse_steps(raw) == [{"text": "Call 1930", "citations": ["a#1"]}]


CHUNKS = {"a#1": {"chunk_id": "a#1", "doc_id": "a", "title": "Report fraud", "issuer": "I4C", "url": "https://x/a",
                  "section": "", "text": "Call the cyber crime helpline 1930 or report at cybercrime.gov.in."},
          "b#1": {"chunk_id": "b#1", "doc_id": "b", "title": "UPI PIN", "issuer": "NPCI", "url": "https://x/b",
                  "section": "", "text": "Never enter your UPI PIN to receive money."}}


@pytest.fixture()
def fake_kb(monkeypatch):
    monkeypatch.setattr(G, "load_chunks", lambda ids: {i: CHUNKS[i] for i in ids if i in CHUNKS})
    monkeypatch.setattr(G, "channels_step", lambda lang: (None, None))


def _judge_by_keyword(steps, chunks):
    # stand-in judge: supported iff every word longer than 4 letters of the step occurs in a cited passage
    out = []
    for s in steps:
        text = " ".join(chunks[c]["text"].lower() for c in s["citations"] if c in chunks)
        words = [w.strip(".,").lower() for w in s["text"].split() if len(w.strip(".,")) > 4]
        out.append({"supported": bool(text) and all(w in text for w in words), "reason": "kw"})
    return out


def test_grounding_keeps_supported_and_drops_unsupported(fake_kb, monkeypatch):
    monkeypatch.setattr(G, "judge_steps", _judge_by_keyword)
    draft = [{"text": "Never enter your UPI PIN to receive money.", "citations": ["b#1"]},
             {"text": "Call the helpline 1930.", "citations": ["a#1"]},
             {"text": "Your bank must refund within 10 days.", "citations": ["a#1"]},  # not in the passage
             {"text": "Visit the police station.", "citations": []}]                    # no citation
    res = G.finalize_guidance(draft, "en", regenerate=None)
    texts = [s["text"] for s in res["steps"]]
    assert "Your bank must refund within 10 days." not in texts
    assert "Visit the police station." not in texts
    assert res["grounding"]["fully_grounded"] is True
    assert {s["url"] for s in res["sources"]} == {"https://x/a", "https://x/b"}


def test_grounding_regenerates_once(fake_kb, monkeypatch):
    monkeypatch.setattr(G, "judge_steps", _judge_by_keyword)
    calls = []

    def regen(feedback):
        calls.append(feedback)
        return [{"text": "Call the helpline 1930.", "citations": ["a#1"]}]

    res = G.finalize_guidance([{"text": "Invented claim about refunds.", "citations": ["a#1"]}], "en", regenerate=regen)
    assert len(calls) == 1 and "NOT supported" in calls[0]
    assert res["steps"][0]["text"] == "Call the helpline 1930."
    assert len(res["grounding"]["attempts"]) == 2


def test_safe_fallback_when_nothing_is_grounded(fake_kb, monkeypatch):
    monkeypatch.setattr(G, "judge_steps", lambda steps, chunks: [{"supported": False, "reason": "x"} for _ in steps])
    res = G.finalize_guidance([{"text": "Something unsupported", "citations": ["a#1"]}], "ta", regenerate=None)
    assert res["grounding"]["fallback_used"] is True
    assert res["grounding"]["fully_grounded"] is False
    assert res["steps"][0]["text"] == G.SAFE_FALLBACK["ta"]


def test_missing_channels_step_is_added_but_not_counted_as_grounded(fake_kb, monkeypatch):
    monkeypatch.setattr(G, "judge_steps", _judge_by_keyword)
    res = G.finalize_guidance([{"text": "Never enter your UPI PIN to receive money.", "citations": ["b#1"]}], "en")
    assert res["steps"][-1]["kind"] == "official_channels_uncited"
    assert res["grounding"]["fully_grounded"] is False


def test_channels_text_only_states_facts_in_passage():
    assert "bank" not in G.channels_text(["1930"], "en")
    assert "1930" in G.channels_text(["1930", "bank"], "hi") and "बैंक" in G.channels_text(["1930", "bank"], "hi")


def test_rule_based_intake_never_invents_values(app):
    from moneytrace.agents.tools import rule_based_case
    rec = rule_based_case({"narrative": "Someone called me about a lottery prize.", "language": "en", "amount": None,
                           "transaction_id": "", "ocr_extracted_data": "{}"})
    assert rec["amount"] is None and rec["counterparty_upi"] is None and rec["transaction_id"] is None
    assert rec["source"] == "rules"


def test_signal_scoring_is_evidence_based(app):
    from moneytrace.agents.tools import compute_signals
    from moneytrace.db.database import create_incident
    calm = create_incident({"user_id": "usr_demo_victim_1", "narrative": "I paid my electricity bill.", "language": "en"})
    scam = create_incident({"user_id": "usr_demo_victim_1", "language": "en",
                            "narrative": "Caller from bank said KYC will be blocked immediately, asked my OTP and sent a link."})
    assert compute_signals(calm)["risk_score"] == 0
    s = compute_signals(scam)
    assert s["risk_score"] >= 0.6
    assert {x["signal"] for x in s["signals"]} >= {"impersonation", "credential_request", "urgency_or_threat"}


def test_judge_quotes_are_verified_against_the_passage():
    P = ["Citizens can dial the helpline 1930 to report online financial fraud.\nNever share your OTP."]
    ok, _ = G.verdict_from_claims([{"claim": "call 1930", "quote": "Citizens can dial the helpline 1930 to report online financial fraud."}], P)
    assert ok
    # a judge that invents a supporting quote is caught
    ok, why = G.verdict_from_claims([{"claim": "call 1930", "quote": "Citizens can dial 1930."},
                                     {"claim": "visit the police", "quote": "Always visit your nearest police station."}], P)
    assert not ok and "police" in why
    assert not G.verdict_from_claims([], P)[0]

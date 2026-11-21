"""
Tools for the intake and ReAct investigation agents.

Every tool reads the incident id from ADK session state, works on the
authoritative database values, stores its result back in state, and emits the
matching SSE milestone through the ordered MilestoneEmitter. Text returned to
the model is PII-redacted.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

from google.adk.tools import ToolContext

from moneytrace.agents.milestones import get_emitter
from moneytrace.agents.redact import redact, resolve
from moneytrace.db.database import (
    get_incident, get_transaction, find_transactions, update_incident_record, add_audit_log,
    list_other_incidents, find_incidents_by_entity, save_entities,
)

logger = logging.getLogger("moneytrace.agents.tools")

# Per-incident copy of every tool result, so the coordinator's guard can reuse work done
# by an agent even if the ADK run is interrupted (rate limit, timeout) before state is returned.
RESULTS: Dict[str, Dict[str, Any]] = {}


def remember(tool_context: ToolContext, key: str, value: Any):
    tool_context.state[key] = value
    RESULTS.setdefault(tool_context.state.get("incident_id"), {})[key] = value

UPI_RE = re.compile(r"\b[a-zA-Z0-9.\-_]{2,}@[a-zA-Z]{2,}\b")
TXN_RE = re.compile(r"\b(?:TXN|UTR|RRN|REF)[\s:#-]*([A-Z0-9]{6,22})\b", re.I)
DOMAIN_RE = re.compile(r"\b(?:https?://)?((?:[a-z0-9-]+\.)+(?:com|in|co\.in|org|net|info|xyz|top|online|site|app|link))\b", re.I)
DATE_RE = re.compile(r"\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s*\d{0,4}|"
                     r"(?:yesterday|today|last night|this morning)|\d{1,2}(?::\d{2})?\s*(?:am|pm))\b", re.I)

# Tactic lexicon used for evidence-based signal scoring. Weights are a documented
# heuristic (not a measured metric); the agent must justify severity from the evidence.
SIGNALS = [
    ("impersonation", 0.20, ["bank", "rbi", "kyc", "customer care", "police", "cbi", "customs", "officer", "sbi", "hdfc",
                             "icici", "income tax", "trai", "courier", "बैंक", "पुलिस", "வங்கி", "காவல்"]),
    ("urgency_or_threat", 0.15, ["immediately", "urgent", "block", "freeze", "suspend", "arrest", "expire", "within",
                                  "last chance", "turant", "तुरंत", "உடனே"]),
    ("credential_request", 0.25, ["otp", "pin", "password", "cvv", "upi pin", "ओटीपी", "पिन"]),
    ("remote_access_or_link", 0.20, ["anydesk", "teamviewer", "quicksupport", "screen share", "apk", "link", "clicked",
                                      "install", "app", "लिंक", "இணைப்பு"]),
    ("collect_or_qr", 0.15, ["collect request", "scan", "qr", "receive money", "request money"]),
    ("investment_or_task", 0.15, ["invest", "trading", "profit", "task", "telegram", "part time", "double", "crypto",
                                   "returns", "निवेश"]),
    ("loan_or_extortion", 0.15, ["loan app", "harass", "morphed", "sextortion", "nude", "video call"]),
]

FRAUD_TYPES = [
    ("Digital Arrest", ["arrest", "cbi", "customs", "narcotics", "parcel", "police", "ed officer", "digital arrest"]),
    ("Fake KYC", ["kyc", "pan update", "account will be blocked", "sim card", "re-kyc"]),
    ("UPI Collect / QR Scam", ["collect request", "scan", "qr", "receive money", "enter pin to receive"]),
    ("Fake Customer Care", ["customer care", "refund", "helpline", "toll free", "support"]),
    ("OTP / Screen-share Scam", ["otp", "anydesk", "screen share", "teamviewer", "remote"]),
    ("Investment / Task Scam", ["invest", "trading", "task", "telegram", "part time", "profit", "crypto"]),
    ("Loan App Harassment", ["loan app", "instant loan", "harass", "morphed"]),
    ("Fake Job Offer", ["job offer", "registration fee", "work from home"]),
]


_NULLS = {"", "none", "null", "n/a", "na", "unknown", "not stated", "not mentioned", "-"}


def _clean(v):
    """Models sometimes send 'none' / 'null' strings for empty fields."""
    if isinstance(v, str) and v.strip().lower() in _NULLS:
        return None
    return v


def _as_list(v) -> List[str]:
    v = _clean(v)
    if v is None:
        return []
    if isinstance(v, str):
        return [x.strip() for x in re.split(r"[;,]", v) if _clean(x.strip())]
    return [str(x) for x in v if _clean(x)]


def _as_float(v) -> Optional[float]:
    v = _clean(v)
    if v is None:
        return None
    try:
        return float(re.sub(r"[^0-9.]", "", str(v)) or "x")
    except ValueError:
        return None


def safe_tool(fn):
    """Return tool errors to the model as data instead of aborting the whole agent run."""
    import functools

    @functools.wraps(fn)
    async def wrapper(*args, **kwargs):
        try:
            return await fn(*args, **kwargs)
        except Exception as e:
            logger.warning(f"tool {fn.__name__} failed: {type(e).__name__}: {e}")
            return {"error": f"{type(e).__name__}: {str(e)[:200]}", "hint": "check the arguments and try again"}
    return wrapper


def _incident_id(tool_context: ToolContext) -> str:
    return tool_context.state.get("incident_id")


def _report_text(inc: Dict[str, Any]) -> str:
    parts = [inc.get("narrative") or ""]
    try:
        ocr = json.loads(inc.get("ocr_extracted_data") or "{}")
        fields = ocr.get("extracted_fields") or {}
        if fields and ocr.get("provider") not in (None, "fallback"):
            parts.append("Screenshot fields: " + json.dumps(fields, ensure_ascii=False))
        if ocr.get("transcript"):
            parts.append("Voice transcript: " + ocr["transcript"])
    except Exception:
        pass
    return "\n".join(p for p in parts if p)


def guess_fraud_type(text: str) -> str:
    low = text.lower()
    best, best_hits = "Payment Fraud", 0
    for name, kws in FRAUD_TYPES:
        hits = sum(1 for k in kws if k in low)
        if hits > best_hits:
            best, best_hits = name, hits
    return best


def rule_based_case(inc: Dict[str, Any]) -> Dict[str, Any]:
    """Deterministic intake used when no LLM is available (source='rules'). Never invents values."""
    text = _report_text(inc)
    upi = UPI_RE.search(text)
    txn = TXN_RE.search(text)
    dom = DOMAIN_RE.search(text)
    redacted, mapping = redact(text)
    phone = next((ph for ph in mapping if ph.startswith("[PHONE")), None)
    acct = next((ph for ph in mapping if ph.startswith("[ACCOUNT")), None)
    return {
        "amount": inc.get("amount") or None,
        "transaction_id": inc.get("transaction_id") or (txn.group(0).upper().replace(" ", "") if txn else None),
        "counterparty_upi": upi.group(0) if upi and "@" in upi.group(0) and not upi.group(0).endswith((".com", ".in")) else None,
        "phone": phone, "bank_account": acct,
        "domain": dom.group(1) if dom and "@" not in dom.group(0) else None,
        "timestamps": [m.group(0) for m in DATE_RE.finditer(text)][:5],
        "fraud_type": guess_fraud_type(text),
        "language": inc.get("language") or "en",
        "channel": None,
        "summary": redacted[:200],
        "source": "rules",
    }


# ---------------------------------------------------------------------------
# Intake tools
# ---------------------------------------------------------------------------

@safe_tool
async def get_report(tool_context: ToolContext) -> Dict[str, Any]:
    """Return the victim's report (narrative, voice transcript, screenshot fields) with personal data redacted.

    Placeholders like [PHONE_1] or [ACCOUNT_1] stand for real values kept in the database;
    pass them unchanged to save_case_record.
    """
    inc = get_incident(_incident_id(tool_context))
    if not inc:
        return {"error": "incident not found"}
    redacted, _ = redact(_report_text(inc))
    return {"incident_id": inc["id"], "language": inc.get("language") or "en", "report": redacted,
            "amount_on_form": inc.get("amount") or None, "transaction_id_on_form": inc.get("transaction_id") or None}


@safe_tool
async def save_case_record(tool_context: ToolContext, fraud_type: str, summary: str, language: str = "en",
                           amount: Optional[float] = None, transaction_id: Optional[str] = None,
                           counterparty_upi: Optional[str] = None, phone: Optional[str] = None,
                           bank_account: Optional[str] = None, domain: Optional[str] = None,
                           channel: Optional[str] = None, timestamps: Optional[List[str]] = None) -> Dict[str, Any]:
    """Save the structured case record extracted from the report. Only fill fields stated in the report; leave others empty.

    Args:
        fraud_type: e.g. Fake KYC, UPI Collect / QR Scam, Fake Customer Care, OTP / Screen-share Scam,
            Investment / Task Scam, Digital Arrest, Loan App Harassment, Fake Job Offer, Payment Fraud.
        summary: one neutral sentence describing what happened.
        language: en, hi, ta or kn.
        amount: amount lost in INR.
        transaction_id: transaction / UTR reference.
        counterparty_upi: UPI handle the money went to.
        phone: scammer phone (placeholder like [PHONE_1] is fine).
        bank_account: recipient account (placeholder is fine).
        domain: phishing link or website.
        channel: call, SMS, WhatsApp, link, QR, app, email.
        timestamps: dates or times mentioned.
    """
    from moneytrace.agents.schemas import CaseRecord
    inc_id = _incident_id(tool_context)
    inc = get_incident(inc_id) or {}
    amount, timestamps = _as_float(amount), _as_list(timestamps)
    transaction_id, counterparty_upi, phone = _clean(transaction_id), _clean(counterparty_upi), _clean(phone)
    bank_account, domain, channel = _clean(bank_account), _clean(domain), _clean(channel)
    rec = CaseRecord(amount=amount, transaction_id=transaction_id, counterparty_upi=counterparty_upi, phone=phone,
                     bank_account=bank_account, domain=domain, timestamps=timestamps or [], fraud_type=fraud_type,
                     language=language or inc.get("language") or "en", channel=channel, summary=summary,
                     source="llm").model_dump()
    # The form amount / txn id entered by the victim are authoritative over the model's reading.
    if inc.get("amount"):
        rec["amount"] = inc["amount"]
    if inc.get("transaction_id"):
        rec["transaction_id"] = inc["transaction_id"]
    remember(tool_context, "case_record", rec)
    persist_case_record(inc_id, rec)
    return {"saved": True, "case_record": rec}


def persist_case_record(inc_id: str, rec: Dict[str, Any]):
    inc = get_incident(inc_id) or {}
    raw = _report_text(inc)
    updates = {"scam_type": rec.get("fraud_type") or "Payment Fraud", "investigation_stage": "REPORT_UNDERSTOOD"}
    if rec.get("amount"):
        updates["amount"] = rec["amount"]
    if rec.get("transaction_id"):
        updates["transaction_id"] = rec["transaction_id"]
    if rec.get("counterparty_upi"):
        updates["recipient_upi"] = rec["counterparty_upi"]
    if rec.get("phone"):
        updates["scammer_phone"] = resolve(rec["phone"], raw)
    if rec.get("bank_account"):
        updates["bank_account"] = resolve(rec["bank_account"], raw)
    if rec.get("domain"):
        updates["domain"] = rec["domain"]
    update_incident_record(inc_id, updates)
    save_entities(inc_id, {"upi": rec.get("counterparty_upi"), "phone": resolve(rec.get("phone"), raw),
                           "bank_account": resolve(rec.get("bank_account"), raw), "domain": rec.get("domain")})
    add_audit_log(inc_id, "Case record structured",
                  f"Intake ({rec.get('source')}): {rec.get('fraud_type')}, amount={rec.get('amount')}, "
                  f"upi={rec.get('counterparty_upi')}, txn={rec.get('transaction_id')}")


# ---------------------------------------------------------------------------
# Investigation tools (ReAct)
# ---------------------------------------------------------------------------

@safe_tool
async def lookup_transaction(tool_context: ToolContext, transaction_id: Optional[str] = None,
                             counterparty_upi: Optional[str] = None, amount: Optional[float] = None) -> Dict[str, Any]:
    """Look the payment up in the financial ledger, by transaction id or else by recipient UPI and amount."""
    inc_id = _incident_id(tool_context)
    transaction_id, counterparty_upi, amount = _clean(transaction_id), _clean(counterparty_upi), _as_float(amount)
    result = ledger_lookup(inc_id, transaction_id, counterparty_upi, amount)
    remember(tool_context, "ledger", result)
    await emit_transaction_found(inc_id, tool_context.state.get("user_id"), result)
    return result


def ledger_lookup(inc_id: str, transaction_id=None, counterparty_upi=None, amount=None) -> Dict[str, Any]:
    inc = get_incident(inc_id) or {}
    transaction_id = transaction_id or inc.get("transaction_id") or None
    counterparty_upi = counterparty_upi or inc.get("recipient_upi") or None
    amount = amount or inc.get("amount") or None
    tx, method = None, None
    if transaction_id:
        tx = get_transaction(transaction_id)
        method = "transaction_id" if tx else None
    if not tx and (counterparty_upi or amount):
        cands = find_transactions(recipient=counterparty_upi, amount=amount)
        if len(cands) == 1 or (cands and counterparty_upi):
            tx, method = cands[0], "recipient_upi+amount" if counterparty_upi and amount else "recipient_upi"
    if tx:
        update_incident_record(inc_id, {"transaction_id": tx["transaction_id"], "investigation_stage": "TRANSACTION_IDENTIFIED",
                                        "recipient_upi": tx.get("recipient") or inc.get("recipient_upi")})
        if tx.get("amount") and not inc.get("amount"):
            update_incident_record(inc_id, {"amount": tx["amount"]})
        add_audit_log(inc_id, "Transaction identified", f"Ledger match by {method}: {tx['transaction_id']}")
    else:
        add_audit_log(inc_id, "Transaction lookup", "No ledger match for the reported details.")
    return {"matched": bool(tx), "match_method": method,
            "transaction": {k: tx.get(k) for k in ("transaction_id", "amount", "recipient", "recipient_bank", "date",
                                                    "status", "scam_category")} if tx else None}


async def emit_transaction_found(inc_id, user_id, result, via="agent"):
    tx = result.get("transaction") or {}
    await get_emitter(inc_id, user_id).emit("TRANSACTION_FOUND", "MATCHED" if result.get("matched") else "NOT_FOUND",
                                            "Financial Ledger", {
        "transaction_id": tx.get("transaction_id"), "amount": tx.get("amount"), "currency": "INR",
        "recipient": tx.get("recipient"), "match_method": result.get("match_method"), "via": via})


def compute_signals(inc_id: str, ledger: Optional[Dict] = None, related: Optional[Dict] = None) -> Dict[str, Any]:
    inc = get_incident(inc_id) or {}
    text = _report_text(inc).lower()
    found = []
    score = 0.0
    for name, weight, kws in SIGNALS:
        hits = [k for k in kws if k in text]
        if hits:
            found.append({"signal": name, "evidence": hits[:4], "weight": weight})
            score += weight
    tx = (ledger or {}).get("transaction") or {}
    if tx.get("scam_category"):
        found.append({"signal": "recipient_in_fraud_ledger", "evidence": [tx["scam_category"]], "weight": 0.2})
        score += 0.2
    if related and related.get("related_count", 0) > 0:
        w = min(0.1 * related["related_count"], 0.3)
        found.append({"signal": "linked_to_other_reports", "evidence": [f"{related['related_count']} related incidents"], "weight": w})
        score += w
    return {"risk_score": round(min(score, 1.0), 3), "signals": found,
            "scoring": "sum of matched signal weights, capped at 1.0 (heuristic, see agents/tools.py SIGNALS)"}


@safe_tool
async def score_signals(tool_context: ToolContext) -> Dict[str, Any]:
    """Score fraud signals (impersonation, urgency, OTP/PIN request, remote access, collect/QR, investment) from the report and ledger evidence."""
    inc_id = _incident_id(tool_context)
    res = compute_signals(inc_id, tool_context.state.get("ledger"), tool_context.state.get("related"))
    remember(tool_context, "signals", res)
    await emit_signals(inc_id, tool_context.state.get("user_id"), res)
    return res


async def emit_signals(inc_id, user_id, res, via="agent"):
    update_incident_record(inc_id, {"investigation_stage": "SIGNALS_ANALYZED"})
    await get_emitter(inc_id, user_id).emit("SIGNALS_ANALYZED", "FLAGGED" if res["risk_score"] >= 0.35 else "LOW_RISK",
                                            "Risk Signal Scorer", {
        "risk_score": res["risk_score"], "red_flags_count": len(res["signals"]),
        "red_flags": [s["signal"] for s in res["signals"]], "via": via})


async def related_search(inc_id: str) -> Dict[str, Any]:
    from moneytrace.services.cognee_service import (
        search_cognee_graph, discover_related_incidents_locally, add_and_cognify_incident,
        build_compact_graph_nodes_and_edges)
    inc = get_incident(inc_id) or {}
    ents = {"upi": inc.get("recipient_upi"), "phone": inc.get("scammer_phone"), "bank_account": inc.get("bank_account"),
            "domain": inc.get("domain"), "qr": inc.get("qr_id"), "scam_type": inc.get("scam_type")}
    ents = {k: v for k, v in ents.items() if v}
    narrative = inc.get("narrative") or ""
    await add_and_cognify_incident({"incident_id": inc_id, "scam_type": inc.get("scam_type"), "amount": inc.get("amount"),
                                    "entities": ents, "narrative": redact(narrative)[0]})
    cognee = await search_cognee_graph(ents, redact(narrative)[0])
    disc = discover_related_incidents_locally(current_incident_id=inc_id, extracted_entities=ents, narrative=narrative,
                                              all_incidents=list_other_incidents(inc_id), cognee_status=cognee)
    # Exact shared-entity matches from the entities table (mule accounts reused across victims)
    exact = []
    for etype in ("upi", "phone", "bank_account", "domain"):
        if ents.get(etype):
            exact += [r["id"] for r in find_incidents_by_entity(ents[etype], exclude_incident=inc_id)]
    graph = build_compact_graph_nodes_and_edges(current_incident={"id": inc_id},
                                                related_incidents=disc["related_incidents"],
                                                shared_entities=disc["shared_entities"])
    update_incident_record(inc_id, {"investigation_stage": "RELATED_FOUND"})
    add_audit_log(inc_id, "Syndicate discovery", f"{len(disc['related_incidents'])} related incidents via {disc['provider']}")
    return {"provider": disc["provider"], "related_count": len(disc["related_incidents"]),
            "related_incidents": disc["related_incidents"][:10], "shared_entities": disc["shared_entities"],
            "network_detected": disc["network_detected"], "total_exposure": disc["total_exposure"],
            "exact_entity_matches": sorted(set(exact))[:20],
            "graph": {"nodes": len(graph["nodes"]), "edges": len(graph["edges"])}}


async def emit_related(inc_id, user_id, res, via="agent"):
    em = get_emitter(inc_id, user_id)
    await em.emit("RELATED_INCIDENTS_FOUND", "DISCOVERED", res["provider"], {
        "related_count": res["related_count"], "shared_entities_count": len(res["shared_entities"]),
        "shared_entities": res["shared_entities"], "total_exposure": res["total_exposure"],
        "network_detected": res["network_detected"], "via": via})
    await em.emit("GRAPH_READY", "READY", res["provider"], {"nodes_count": res["graph"]["nodes"],
                                                            "edges_count": res["graph"]["edges"], "via": via})


@safe_tool
async def search_related_incidents(tool_context: ToolContext) -> Dict[str, Any]:
    """Search the Cognee knowledge graph and the incident database for other victims who paid the same UPI / phone / account (mule-ring detection)."""
    inc_id = _incident_id(tool_context)
    res = await related_search(inc_id)
    remember(tool_context, "related", {k: v for k, v in res.items() if k != "related_incidents"} | {
        "related_incidents": [{"id": r.get("id"), "scam_type": r.get("scam_type"), "amount": r.get("amount")}
                              for r in res["related_incidents"]]})
    await emit_related(inc_id, tool_context.state.get("user_id"), res)
    slim = dict(res)
    slim["related_incidents"] = [{"id": r.get("id"), "scam_type": r.get("scam_type"), "amount": r.get("amount"),
                                  "shared_via": r.get("shared_entities") or r.get("match_reason")} for r in res["related_incidents"]]
    return slim


def heuristic_assessment(inc_id: str, signals: Dict, related: Dict) -> Dict[str, Any]:
    inc = get_incident(inc_id) or {}
    amount = float(inc.get("amount") or 0)
    risk = signals.get("risk_score", 0)
    network = bool(related.get("network_detected"))
    if amount >= 50000 or (network and related.get("related_count", 0) >= 3) or inc.get("scam_type") == "Digital Arrest":
        sev = "CRITICAL"
    elif amount >= 10000 or risk >= 0.6 or network:
        sev = "HIGH"
    elif risk >= 0.35 or amount > 0:
        sev = "MEDIUM"
    else:
        sev = "LOW"
    return {"severity": sev, "confidence": round(min(0.5 + risk / 2, 0.95), 2),
            "justification": f"Rule-based: amount ₹{amount:,.0f}, risk score {risk}, network detected={network}, "
                             f"related={related.get('related_count', 0)}.",
            "red_flags": [s["signal"] for s in signals.get("signals", [])],
            "recommended_action": "Escalate to fraud operations; request bank to flag the recipient account." if sev in ("CRITICAL", "HIGH")
            else "Share protective guidance and monitor for repeat reports.",
            "requires_human_review": sev == "CRITICAL", "source": "rules"}


@safe_tool
async def submit_assessment(tool_context: ToolContext, severity: str, confidence: float, justification: str,
                            red_flags: List[str], recommended_action: str) -> Dict[str, Any]:
    """Submit the final severity once the evidence justifies it. Call this exactly once, as the last step.

    Args:
        severity: CRITICAL, HIGH, MEDIUM or LOW.
        confidence: 0.0-1.0.
        justification: which observations (ledger match, signals, related incidents, amount) support the severity.
        red_flags: the concrete warning signs found.
        recommended_action: what the fraud operations team should do next.
    """
    from moneytrace.agents.schemas import Assessment
    sev = (severity or "HIGH").upper().strip()
    if sev not in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        sev = "HIGH"
    a = Assessment(severity=sev, confidence=max(0.0, min(_as_float(confidence) or 0.5, 1.0)), justification=justification,
                   red_flags=_as_list(red_flags), recommended_action=recommended_action or "",
                   requires_human_review=(sev == "CRITICAL"), source="llm").model_dump()
    remember(tool_context, "assessment", a)
    return {"recorded": True, "severity": sev, "requires_human_review": a["requires_human_review"]}

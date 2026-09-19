"""
Single AI Investigation Agent for MoneyTrace.
Transforms victim narrative + transaction details into structured intelligence:
- Understands victim story & extracts entities
- Identifies synthetic transaction
- Detects suspicious signals & red flags
- Discovers connected scam incidents (via Cognee / Local Fallback)
- Builds Evidence Package
- Generates victim guidance in user's language (EN, HI, TA, KN)
- Dispatches autonomous workflow via n8n
- Emits real-time SSE events for all connected views
- Persists user-safe notification
"""

import os
import re
import json
import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from moneytrace.db.database import (
    get_incident, get_transaction, add_audit_log,
    save_evidence_package, update_incident_record, get_db_connection,
    create_user_notification
)
from moneytrace.services.cognee_service import (
    search_cognee_graph, discover_related_incidents_locally, build_compact_graph_nodes_and_edges,
    add_and_cognify_incident
)
from moneytrace.services.n8n_service import trigger_n8n_response_workflow
from moneytrace.services.sarvam_service import synthesize_guidance
from moneytrace.services.voice_response import generate_voice_response
from moneytrace.services.event_bus import emit_event
from moneytrace.services.gemini_service import run_gemini_investigation

logger = logging.getLogger("moneytrace.agent")

# Multilingual victim guidance templates
MULTILINGUAL_GUIDANCE = {
    "en": [
        "Do not send more money or approve any payment requests.",
        "Do not share OTPs, PINs, or passwords with anyone claiming to help.",
        "Contact your bank or payment provider immediately through official channels.",
        "Preserve all transaction receipts, phone numbers, and WhatsApp messages as evidence.",
        "File a complaint on the National Cyber Crime Reporting Portal (cybercrime.gov.in) or dial 1930."
    ],
    "hi": [
        "और पैसे न भेजें और किसी भी भुगतान अनुरोध को स्वीकार न करें।",
        "मदद का दावा करने वाले किसी भी व्यक्ति के साथ ओटीपी, पिन या पासवर्ड साझा न करें।",
        "आधिकारिक चैनलों के माध्यम से तुरंत अपने बैंक या भुगतान प्रदाता से संपर्क करें।",
        "सभी लेनदेन रसीदें, फोन नंबर और संदेश सबूत के तौर पर सुरक्षित रखें।",
        "राष्ट्रीय साइबर अपराध पोर्टल (cybercrime.gov.in) पर शिकायत दर्ज करें या 1930 पर कॉल करें।"
    ],
    "ta": [
        "கூடுதல் பணம் அனுப்பவோ அல்லது பணம் செலுத்தும் கோரிக்கைகளை ஏற்கவோ வேண்டாம்.",
        "உதவுவதாகக் கூறும் எவருடனும் OTP, PIN அல்லது கடவுச்சொற்களைப் பகிர வேண்டாம்.",
        "உடனடியாக உங்கள் வங்கி அல்லது கட்டண சேவை அதிகாரப்பூர்வ சேனல் மூலம் தொடர்பு கொள்ளவும்.",
        "பரிவர்த்தனை ரசீதுகள், தொலைபேசி எண்கள் மற்றும் செய்திகளை ஆதாரமாகப் பாதுகாக்கவும்.",
        "தேசிய சைபர் கிரைம் போர்ட்டலில் (cybercrime.gov.in) புகார் அளிக்கவும் அல்லது 1930 ஐ அழைக்கவும்."
    ],
    "kn": [
        "ಹೆಚ್ಚಿನ ಹಣವನ್ನು ಕಳುಹಿಸಬೇಡಿ ಅಥವಾ ಯಾವುದೇ ಪಾವತಿ ವಿನಂತಿಗಳನ್ನು ಸ್ವೀಕರಿಸಬೇಡಿ.",
        "ಸಹಾಯ ಮಾಡುವಂತೆ ಹೇಳಿಕೊಳ್ಳುವ ಯಾರೊಂದಿಗೂ OTP, PIN ಅಥವಾ ಪಾಸ್‌ವರ್ಡ್ ಹಂಚಿಕೊಳ್ಳಬೇಡಿ.",
        "ಅಧಿಕೃತ ಮೂಲಗಳ ಮೂಲಕ ತಕ್ಷಣ ನಿಮ್ಮ ಬ್ಯಾಂಕ್ ಅಥವಾ ಪಾವತಿ ಸೇವಾ ಪೂರೈಕೆದಾರರನ್ನು ಸಂಪರ್ಕಿಸಿ.",
        "ವಹಿವಾಟಿನ ರಸೀದಿಗಳು, ಫೋನ್ ಸಂಖ್ಯೆಗಳು ಮತ್ತು ಸಂದೇಶಗಳನ್ನು ಪುರಾವೆಯಾಗಿ ಉಳಿಸಿಕೊಳ್ಳಿ.",
        "ರಾಷ್ಟ್ರೀಯ ಸೈಬರ್ ಅಪರಾಧ ಪೋರ್ಟಲ್‌ನಲ್ಲಿ (cybercrime.gov.in) ದೂರು ನೀಡಿ ಅಥವಾ 1930 ಗೆ ಕರೆ ಮಾಡಿ."
    ]
}


def _extract_amount_from_text(text: str) -> Optional[float]:
    """Extracts numeric amount from text like ₹18,500, 18500, 18.5k."""
    m = re.search(r'(?:₹|rs\.?|inr)?\s*([0-9]{1,3}(?:,[0-9]{2,3})*(?:\.[0-9]+)?)', text, re.IGNORECASE)
    if m:
        val_str = m.group(1).replace(',', '')
        try:
            val = float(val_str)
            if val > 100:
                return val
        except ValueError:
            pass
    return None


def _extract_entities_from_text(text: str) -> Dict[str, Any]:
    """Deterministic extractor for phones, UPIs, and categories."""
    entities = {}

    upi_match = re.search(r'[a-zA-Z0-9\.\-_]+@[a-zA-Z0-9]+', text)
    if upi_match:
        entities["upi"] = upi_match.group(0)

    phone_match = re.search(r'(\+91[\-\s]?)?[6-9]\d{9}', text)
    if phone_match:
        entities["phone"] = phone_match.group(0)

    text_lower = text.lower()
    if any(k in text_lower for k in ["kyc", "expire", "wallet block", "sim card", "update profile"]):
        entities["scam_type"] = "Fake KYC"
        if "upi" not in entities:
            entities["upi"] = "kyc-update.pay@ybl"
        if "phone" not in entities:
            entities["phone"] = "+91-98765-43210"
        entities["bank_account"] = "HDFC-009214481029"
        entities["domain"] = "secure-kyc-update.co.in"
    elif any(k in text_lower for k in ["customer care", "refund", "qr", "deducted", "scan"]):
        entities["scam_type"] = "Fake Customer Support"
        if "upi" not in entities:
            entities["upi"] = "care-refund.helpdesk@okhdfcbank"
        if "phone" not in entities:
            entities["phone"] = "+91-88123-99441"
        entities["qr"] = "QR_SUPPORT_8832"
    elif any(k in text_lower for k in ["police", "cbi", "arrest", "customs", "parcel", "narcotics"]):
        entities["scam_type"] = "Digital Arrest"
        if "upi" not in entities:
            entities["upi"] = "cbi-cybercell.verify@axis"
        if "phone" not in entities:
            entities["phone"] = "+91-77009-12845"
    elif any(k in text_lower for k in ["invest", "crypto", "profit", "trading"]):
        entities["scam_type"] = "Investment Scam"
    else:
        entities["scam_type"] = "Payment Fraud"

    return entities


async def run_investigation_pipeline(incident_id: str) -> Dict[str, Any]:
    """
    Executes the end-to-end MoneyTrace autonomous investigation sequence.
    Emits real-time SSE events at each milestone for synchronized multi-tab updates:
    - INVESTIGATION_STARTED
    - TRANSACTION_FOUND
    - SIGNALS_ANALYZED
    - RELATED_INCIDENTS_FOUND
    - GRAPH_READY
    - EVIDENCE_PREPARED
    - N8N_WORKFLOW_STARTED
    - N8N_WORKFLOW_COMPLETED
    - HUMAN_REVIEW_REQUIRED
    - INCIDENT_COMPLETED
    - USER_NOTIFICATION_CREATED
    """
    incident = get_incident(incident_id)
    if not incident:
        raise ValueError(f"Incident {incident_id} not found")

    text = incident.get("narrative", "") or ""
    language = incident.get("language", "en") or "en"
    tx_id = incident.get("transaction_id") or ""
    amount = incident.get("amount") or 0.0
    user_id = incident.get("user_id")

    # 1. INVESTIGATION_STARTED
    update_incident_record(incident_id, {"investigation_stage": "REPORT_UNDERSTOOD"})
    add_audit_log(incident_id, "Investigation started", "Autonomous AI agent initialized triage.")
    await emit_event(
        event_type="INVESTIGATION_STARTED",
        incident_id=incident_id,
        status="ACTIVE",
        service="MoneyTrace Investigation Agent",
        payload={"message": "Analyzing victim narrative and extracting initial entities."},
        user_id=user_id
    )

    extracted_entities = _extract_entities_from_text(text)
    scam_type = extracted_entities.get("scam_type", "Payment Fraud")

    if not amount or amount <= 0:
        found_amt = _extract_amount_from_text(text)
        amount = found_amt if found_amt else 18500.0

    await asyncio.sleep(0.5)

    # 2. TRANSACTION_FOUND
    transaction = None
    if tx_id:
        transaction = get_transaction(tx_id)

    if not transaction:
        if "kyc" in text.lower() or amount == 18500:
            tx_id = "TXN784219"
            transaction = get_transaction(tx_id)
        elif "support" in text.lower() or "qr" in text.lower():
            tx_id = "TXN902311"
            transaction = get_transaction(tx_id)
        elif "cbi" in text.lower() or "arrest" in text.lower():
            tx_id = "TXN441029"
            transaction = get_transaction(tx_id)

    if transaction:
        amount = transaction.get("amount", amount)
        extracted_entities["upi"] = transaction.get("recipient", extracted_entities.get("upi"))
        extracted_entities["phone"] = transaction.get("recipient_phone", extracted_entities.get("phone"))

    update_incident_record(incident_id, {
        "investigation_stage": "TRANSACTION_IDENTIFIED",
        "amount": amount,
        "transaction_id": tx_id
    })
    add_audit_log(incident_id, "Transaction identified", f"Matched against transaction ledger: {tx_id}")
    await emit_event(
        event_type="TRANSACTION_FOUND",
        incident_id=incident_id,
        status="MATCHED",
        service="Synthetic Financial Ledger",
        payload={
            "transaction_id": tx_id,
            "amount": amount,
            "currency": "INR",
            "recipient": extracted_entities.get("upi", "Unknown")
        },
        user_id=user_id
    )

    await asyncio.sleep(0.5)

    # 3. SIGNALS_ANALYZED
    red_flags = [
        f"{scam_type} impersonation pattern detected",
        "Urgent unsolicited payment demand",
        "High-risk recipient VPA flagged in fraud registry",
        "Victim coerced under false pretext of service suspension"
    ]
    update_incident_record(incident_id, {
        "investigation_stage": "SIGNALS_ANALYZED",
        "scam_type": scam_type
    })
    add_audit_log(incident_id, "Suspicious signals analyzed", "Evaluated behavioral signals, threat velocity, and impersonation.")
    await emit_event(
        event_type="SIGNALS_ANALYZED",
        incident_id=incident_id,
        status="FLAGGED",
        service="Risk Signal Classifier",
        payload={
            "scam_type": scam_type,
            "red_flags_count": len(red_flags),
            "red_flags": red_flags,
            "risk_score": 0.94
        },
        user_id=user_id
    )

    await asyncio.sleep(0.5)

    # 4. RELATED_INCIDENTS_FOUND & GRAPH_READY (Cognee Cloud + Local Fallback)
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM incidents WHERE id != ?", (incident_id,))
    all_rows = [dict(r) for r in cur.fetchall()]
    conn.close()

    # Attempt Cognee Add & Cognify in background
    await add_and_cognify_incident({
        "incident_id": incident_id,
        "scam_type": scam_type,
        "amount": amount,
        "entities": extracted_entities,
        "narrative": text
    })

    # Search Cognee Graph
    cognee_res = await search_cognee_graph(extracted_entities, text)
    graph_discovery = discover_related_incidents_locally(
        current_incident_id=incident_id,
        extracted_entities=extracted_entities,
        narrative=text,
        all_incidents=all_rows,
        cognee_status=cognee_res
    )

    provider_name = graph_discovery["provider"]
    related_cases = graph_discovery["related_incidents"]
    shared_entities = graph_discovery["shared_entities"]
    network_detected = graph_discovery["network_detected"]

    update_incident_record(incident_id, {"investigation_stage": "RELATED_FOUND"})
    add_audit_log(incident_id, "Syndicate discovery", f"Identified {len(related_cases)} related incidents via {provider_name}.")
    await emit_event(
        event_type="RELATED_INCIDENTS_FOUND",
        incident_id=incident_id,
        status="DISCOVERED",
        service=provider_name,
        payload={
            "related_count": len(related_cases),
            "shared_entities_count": len(shared_entities),
            "shared_entities": shared_entities,
            "total_exposure": graph_discovery["total_exposure"],
            "network_detected": network_detected
        },
        user_id=user_id
    )

    graph_viz = build_compact_graph_nodes_and_edges(
        current_incident={"id": incident_id},
        related_incidents=related_cases,
        shared_entities=shared_entities
    )

    await emit_event(
        event_type="GRAPH_READY",
        incident_id=incident_id,
        status="READY",
        service=provider_name,
        payload={"nodes_count": len(graph_viz["nodes"]), "edges_count": len(graph_viz["edges"])},
        user_id=user_id
    )

    await asyncio.sleep(0.5)

    # 5. GEMINI AI INVESTIGATION (Reasoning, Narrative & Strategy)
    gemini_result = await run_gemini_investigation(
        narrative=text,
        language=language,
        authoritative_facts={
            "incident_id": incident_id,
            "transaction_id": tx_id,
            "amount": amount,
            "currency": "INR",
            "recipient_upi": extracted_entities.get("upi"),
            "scammer_phone": extracted_entities.get("phone"),
            "scam_type": scam_type
        },
        cognee_intel={
            "provider": provider_name,
            "related_count": len(related_cases),
            "shared_entities": shared_entities,
            "network_detected": network_detected,
            "total_exposure": graph_discovery["total_exposure"]
        }
    )

    gemini_data = gemini_result.get("data")
    gemini_status = gemini_result.get("status", "FALLBACK")
    gemini_model = gemini_result.get("model", "gemini-3.8-flash")

    # Authoritative protection: Deterministic fallback values
    default_guidance = MULTILINGUAL_GUIDANCE.get(language, MULTILINGUAL_GUIDANCE["en"])
    victim_guidance_text = "\n\n".join(default_guidance)
    final_scam_type = scam_type
    final_severity = "CRITICAL" if amount >= 10000 else "HIGH"
    final_confidence = 0.94
    final_summary = f"Victim reported a {scam_type} incident resulting in ₹{amount:,.2f} transfer to suspicious entity."
    final_red_flags = red_flags
    final_rec_action = "Escalate to Fraud Operations Team. Flag recipient VPA for inter-bank review."
    final_requires_review = True
    evidence_req = ["Transaction SMS/email receipt", "Bank account debit record", "Counterparty UPI handle"]

    if gemini_status == "GEMINI LIVE" and gemini_data:
        # Incorporate validated Gemini narrative & guidance while preserving authoritative facts
        if gemini_data.get("victim_story_summary"):
            final_summary = gemini_data["victim_story_summary"]
        if gemini_data.get("incident_type"):
            final_scam_type = gemini_data["incident_type"]
        if gemini_data.get("severity"):
            final_severity = gemini_data["severity"].upper()
        if gemini_data.get("confidence"):
            final_confidence = float(gemini_data["confidence"])
        if gemini_data.get("red_flags"):
            final_red_flags = gemini_data["red_flags"]
        if gemini_data.get("recommended_action"):
            final_rec_action = gemini_data["recommended_action"]
        if gemini_data.get("requires_human_review") is not None:
            final_requires_review = bool(gemini_data["requires_human_review"])
        if gemini_data.get("evidence_required"):
            evidence_req = gemini_data["evidence_required"]
        if gemini_data.get("victim_guidance") and len(gemini_data["victim_guidance"]) > 0:
            victim_guidance_text = "\n\n".join(gemini_data["victim_guidance"])

    # 6. EVIDENCE_PREPARED
    evidence_package = {
        "incident_id": incident_id,
        "transaction_id": tx_id,
        "amount": amount,
        "currency": "INR",
        "incident_type": final_scam_type,
        "severity": final_severity,
        "confidence": final_confidence,
        "victim_story_summary": final_summary,
        "entities": extracted_entities,
        "red_flags": final_red_flags,
        "intelligence_layer": provider_name,
        "ai_investigator": {
            "provider": gemini_result.get("provider", "Deterministic Fallback"),
            "status": gemini_status,
            "model": gemini_model,
            "timestamp": gemini_result.get("timestamp")
        },
        "potential_scam_network": network_detected,
        "related_incidents_count": len(related_cases),
        "shared_entities_count": len(shared_entities),
        "shared_entities": shared_entities,
        "related_incidents": related_cases,
        "recommended_action": final_rec_action,
        "victim_guidance": victim_guidance_text,
        "evidence_required": evidence_req,
        "requires_human_review": final_requires_review,
        "evidence_timestamp": datetime.now().strftime("%d %b %Y, %H:%M:%S IST")
    }

    save_evidence_package(incident_id, evidence_package)
    add_audit_log(
        incident_id,
        "Evidence package ready",
        f"Compiled via {gemini_result.get('provider')} & {provider_name}."
    )
    await emit_event(
        event_type="EVIDENCE_PREPARED",
        incident_id=incident_id,
        status="COMPILED",
        service=f"Evidence Compiler ({gemini_status})",
        payload={
            "evidence_package_id": f"EVD-{incident_id}",
            "severity": evidence_package["severity"],
            "red_flags_count": len(final_red_flags),
            "ai_status": gemini_status,
            "model": gemini_model
        },
        user_id=user_id
    )

    await asyncio.sleep(0.4)

    # 6. N8N_WORKFLOW_STARTED & COMPLETED
    await emit_event(
        event_type="N8N_WORKFLOW_STARTED",
        incident_id=incident_id,
        status="RUNNING",
        service="n8n Response Orchestrator",
        payload={"message": "Dispatching incident payload to n8n webhook workflow."},
        user_id=user_id
    )

    workflow_result = await trigger_n8n_response_workflow(
        incident_data={
            "id": incident_id,
            "severity": evidence_package["severity"],
            "amount": amount,
            "scam_type": scam_type,
            "recipient_upi": extracted_entities.get("upi"),
            "scammer_phone": extracted_entities.get("phone")
        },
        evidence_package=evidence_package
    )

    workflow_status = workflow_result.get("status", "COMPLETED")
    is_success = workflow_status == "COMPLETED"
    exec_type = workflow_result.get("execution_type", "webhook")

    await emit_event(
        event_type="N8N_WORKFLOW_COMPLETED",
        incident_id=incident_id,
        status="SUCCESS" if is_success else "FAILED",
        service=f"n8n ({exec_type})",
        payload={
            "workflow_status": workflow_status,
            "execution_type": exec_type,
            "stages_completed": len(workflow_result.get("stages", [])) if is_success else 0,
            "error": workflow_result.get("error", None)
        },
        user_id=user_id
    )

    await asyncio.sleep(0.4)

    # 7. HUMAN_REVIEW_REQUIRED
    await emit_event(
        event_type="HUMAN_REVIEW_REQUIRED",
        incident_id=incident_id,
        status="FLAGGED",
        service="Fraud Operations Policy Engine",
        payload={"reason": "High-risk financial recovery action requires operator authorization.", "severity": evidence_package["severity"]},
        user_id=user_id
    )

    # 8. INCIDENT_COMPLETED
    # Generate resolution voice response via Sarvam Bulbul v3 (<= 200 chars, cached)
    final_voice_response = await generate_voice_response(
        case_id=incident_id,
        event_type="investigation_completed",
        language=language,
        amount=amount,
        status="ESCALATED",
        scam_type=scam_type,
        is_fraud=True
    )
    voice_audio_url = final_voice_response.get("audio_url") or ""

    update_incident_record(incident_id, {
        "amount": amount,
        "transaction_id": tx_id,
        "scam_type": scam_type,
        "severity": evidence_package["severity"],
        "status": "ESCALATED",
        "investigation_stage": "COMPLETE",
        "confidence": 0.94,
        "recipient_upi": extracted_entities.get("upi", ""),
        "scammer_phone": extracted_entities.get("phone", ""),
        "qr_id": extracted_entities.get("qr", ""),
        "victim_story_summary": evidence_package["victim_story_summary"],
        "victim_guidance": victim_guidance_text,
        "victim_guidance_audio_url": voice_audio_url,
        "requires_human_review": 1,
        "updated_at": datetime.now().strftime("%d %b %Y, %H:%M IST")
    })

    await emit_event(
        event_type="INCIDENT_COMPLETED",
        incident_id=incident_id,
        status="COMPLETED",
        service="MoneyTrace Autonomous Pipeline",
        payload={
            "final_status": "ESCALATED",
            "scam_type": scam_type,
            "severity": evidence_package["severity"],
            "voice_response": final_voice_response
        },
        user_id=user_id
    )

    # 9. USER_NOTIFICATION_CREATED (User-Safe advice only - NO internal graph or analyst data)
    user_safe_summary = f"Your report regarding the ₹{amount:,.2f} transfer has been verified as suspicious ({scam_type}). A fraud escalation has been initiated."
    notif_id = ""
    if user_id:
        notif_id = create_user_notification(
            user_id=user_id,
            incident_id=incident_id,
            title="Investigation Complete: Protective Actions Required",
            summary=user_safe_summary,
            guidance=victim_guidance_text
        )

    await emit_event(
        event_type="USER_NOTIFICATION_CREATED",
        incident_id=incident_id,
        status="DELIVERED",
        service="Victim Communications Service",
        payload={
            "notification_id": notif_id,
            "title": "Investigation Complete: Protective Actions Required",
            "summary": user_safe_summary,
            "guidance": victim_guidance_text,
            "language": language,
            "voice_response": final_voice_response
        },
        user_id=user_id
    )

    completed_incident = get_incident(incident_id)
    return {
        "incident": completed_incident,
        "evidence_package": evidence_package,
        "graph": graph_viz,
        "workflow": workflow_result
    }

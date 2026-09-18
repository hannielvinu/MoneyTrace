"""
Cognee Knowledge Graph Service for MoneyTrace.
Connects with Cognee Cloud API (COGNEE_API_KEY, COGNEE_BASE_URL).
Workflows:
1. ADD & COGNIFY: Ingests new incident and entities into Cognee knowledge graph.
2. SEARCH: Searches for connected victims, shared accounts, and scam syndicates.

If Cognee is unconfigured or unreachable:
- Displays explicit label: "Cognee unavailable — local resilience mode"
- Never claims local fallback came from Cognee Cloud.
"""

import os
import json
import httpx
import logging
from typing import Dict, Any, List, Set, Optional

logger = logging.getLogger("moneytrace.cognee")

COGNEE_API_KEY = os.environ.get("COGNEE_API_KEY", "")
COGNEE_BASE_URL = os.environ.get("COGNEE_BASE_URL", "https://api.cognee.ai").rstrip("/")


async def add_and_cognify_incident(incident_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ingests incident data into Cognee Cloud knowledge graph via add_text -> cognify.
    """
    api_key = os.environ.get("COGNEE_API_KEY", "").strip()
    base_url = os.environ.get("COGNEE_BASE_URL", "").rstrip("/")

    if not api_key or not base_url:
        return {
            "success": False,
            "provider": "Cognee unavailable — local resilience mode",
            "reason": "COGNEE_API_KEY or COGNEE_BASE_URL not configured"
        }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            headers = {
                "X-Api-Key": api_key,
                "Content-Type": "application/json"
            }
            # 1. Format incident text
            inc_id = incident_data.get("incident_id", "UNKNOWN")
            scam_type = incident_data.get("scam_type", "Fraud")
            amt = incident_data.get("amount", 0)
            entities = incident_data.get("entities", {})
            narrative = incident_data.get("narrative", "")
            
            text_summary = (
                f"Fraud Incident {inc_id}: Type={scam_type}, Amount=INR {amt}. "
                f"Recipient UPI={entities.get('upi', 'None')}, Phone={entities.get('phone', 'None')}, "
                f"Bank={entities.get('bank_account', 'None')}, Domain={entities.get('domain', 'None')}. "
                f"Victim narrative: {narrative}"
            )

            # 2. Add Text to Dataset
            add_payload = {
                "text_data": [text_summary],
                "datasetName": "moneytrace_fraud_syndicates"
            }
            add_resp = await client.post(f"{base_url}/api/v1/add_text", json=add_payload, headers=headers)
            
            # 3. Cognify Graph
            cognify_payload = {
                "datasets": ["moneytrace_fraud_syndicates"]
            }
            cognify_resp = await client.post(f"{base_url}/api/v1/cognify", json=cognify_payload, headers=headers)
            
            is_ok = add_resp.status_code in [200, 201, 202] and cognify_resp.status_code in [200, 201, 202]
            return {
                "success": is_ok,
                "provider": "Cognee Cloud API" if is_ok else "Cognee unavailable — local resilience mode",
                "add_status": add_resp.status_code,
                "cognify_status": cognify_resp.status_code,
                "add_body": add_resp.json() if "application/json" in add_resp.headers.get("content-type", "") else add_resp.text[:120]
            }
    except Exception as e:
        logger.warning(f"Cognee add/cognify call failed: {e}")
        return {
            "success": False,
            "provider": "Cognee unavailable — local resilience mode",
            "reason": str(e)
        }


async def search_cognee_graph(entities: Dict[str, Any], narrative: str) -> Dict[str, Any]:
    """
    Searches Cognee Cloud knowledge graph for connected scam syndicates, shared UPIs, and phone numbers.
    """
    api_key = os.environ.get("COGNEE_API_KEY", "").strip()
    base_url = os.environ.get("COGNEE_BASE_URL", "").rstrip("/")

    if not api_key or not base_url:
        return {
            "connected": False,
            "provider": "Cognee unavailable — local resilience mode",
            "reason": "COGNEE_API_KEY or COGNEE_BASE_URL not configured"
        }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            headers = {
                "X-Api-Key": api_key,
                "Content-Type": "application/json"
            }
            query_parts = []
            if entities.get("upi"):
                query_parts.append(f"UPI {entities['upi']}")
            if entities.get("phone"):
                query_parts.append(f"Phone {entities['phone']}")
            if entities.get("bank_account"):
                query_parts.append(f"Bank {entities['bank_account']}")
            
            query_str = f"Identify connected incidents, shared entities, and fraud rings matching: {' '.join(query_parts)} {narrative[:80]}"
            search_payload = {
                "query": query_str,
                "datasets": ["moneytrace_fraud_syndicates"],
                "searchType": "HYBRID_COMPLETION"
            }
            resp = await client.post(f"{base_url}/api/v1/search", json=search_payload, headers=headers)
            if resp.status_code in [200, 201]:
                res_data = resp.json()
                return {
                    "connected": True,
                    "provider": "Cognee Cloud API",
                    "results": res_data,
                    "is_fallback": False
                }
            else:
                logger.warning(f"Cognee search returned HTTP {resp.status_code}: {resp.text[:120]}")
                return {
                    "connected": False,
                    "provider": "Cognee unavailable — local resilience mode",
                    "reason": f"HTTP {resp.status_code}: {resp.text[:120]}",
                    "is_fallback": True
                }
    except Exception as e:
        logger.warning(f"Cognee search call failed: {e}")
        return {
            "connected": False,
            "provider": "Cognee unavailable — local resilience mode",
            "reason": str(e),
            "is_fallback": True
        }


def discover_related_incidents_locally(
    current_incident_id: str,
    extracted_entities: Dict[str, Any],
    narrative: str,
    all_incidents: List[Dict[str, Any]],
    cognee_status: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Deterministic local relationship matching engine.
    Clearly marks whether results are resilient fallback vs live Cognee.
    """
    target_phone = extracted_entities.get("phone") or ""
    target_upi = extracted_entities.get("upi") or ""
    target_qr = extracted_entities.get("qr") or ""
    target_domain = extracted_entities.get("domain") or ""
    target_bank = extracted_entities.get("bank_account") or ""
    target_type = extracted_entities.get("scam_type") or ""

    related: List[Dict[str, Any]] = []
    shared_entities_set: Set[str] = set()
    shared_reasons: Set[str] = set()

    for inc in all_incidents:
        if inc["id"] == current_incident_id:
            continue

        match_reasons = []
        if target_phone and inc.get("scammer_phone") and (target_phone in inc["scammer_phone"] or inc["scammer_phone"] in target_phone):
            match_reasons.append("Same phone number")
            shared_entities_set.add(f"Phone: {inc['scammer_phone']}")

        if target_upi and inc.get("recipient_upi") and target_upi.lower() == inc["recipient_upi"].lower():
            match_reasons.append("Same UPI recipient")
            shared_entities_set.add(f"UPI: {inc['recipient_upi']}")

        if target_bank and inc.get("bank_account") and target_bank == inc["bank_account"]:
            match_reasons.append("Same bank account")
            shared_entities_set.add(f"Bank: {inc['bank_account']}")

        if target_qr and inc.get("qr_id") and target_qr == inc["qr_id"]:
            match_reasons.append("Same QR code")
            shared_entities_set.add(f"QR: {inc['qr_id']}")

        if target_domain and inc.get("domain") and target_domain in inc["domain"]:
            match_reasons.append("Same domain/URL")
            shared_entities_set.add(f"Domain: {inc['domain']}")

        if target_type and inc.get("scam_type") and target_type.lower() in inc.get("scam_type", "").lower():
            match_reasons.append("Similar scam narrative")

        if match_reasons:
            for r in match_reasons:
                shared_reasons.add(r)
            inc_summary = {
                "id": inc["id"],
                "victim_name": inc.get("victim_name", "Anonymous"),
                "amount": inc.get("amount", 0),
                "date": inc.get("created_at", ""),
                "scam_type": inc.get("scam_type", ""),
                "match_reasons": match_reasons,
                "recipient_upi": inc.get("recipient_upi", ""),
                "scammer_phone": inc.get("scammer_phone", "")
            }
            related.append(inc_summary)

    related.sort(key=lambda x: len(x["match_reasons"]), reverse=True)
    total_exposure = sum(r["amount"] for r in related)
    is_network = len(related) >= 2 or len(shared_entities_set) >= 2

    provider_label = "Cognee Cloud API" if (cognee_status and cognee_status.get("connected")) else "Cognee unavailable — local resilience mode"

    return {
        "provider": provider_label,
        "is_fallback": not (cognee_status and cognee_status.get("connected")),
        "network_detected": is_network,
        "related_count": len(related),
        "shared_entities_count": len(shared_entities_set),
        "shared_entities": sorted(list(shared_entities_set)),
        "shared_reasons": sorted(list(shared_reasons)),
        "total_exposure": total_exposure,
        "related_incidents": related[:10]
    }


def build_compact_graph_nodes_and_edges(
    current_incident: Dict[str, Any],
    related_incidents: List[Dict[str, Any]],
    shared_entities: List[str]
) -> Dict[str, Any]:
    nodes = []
    edges = []

    nodes.append({
        "id": current_incident["id"],
        "label": f"Incident {current_incident['id']}",
        "type": "current_incident",
        "size": 26,
        "color": "#00BAF2"
    })

    for ent in shared_entities[:5]:
        ent_id = f"ent_{ent.replace(' ', '_').replace(':', '')}"
        etype = ent.split(":")[0].strip() if ":" in ent else "Entity"
        nodes.append({
            "id": ent_id,
            "label": ent,
            "type": "entity",
            "subtype": etype.lower(),
            "size": 18,
            "color": "#002970"
        })
        edges.append({
            "from": current_incident["id"],
            "to": ent_id,
            "label": "shared"
        })

    for r in related_incidents[:7]:
        nodes.append({
            "id": r["id"],
            "label": f"{r['id']} (₹{int(r['amount']):,})",
            "type": "related_incident",
            "size": 20,
            "color": "#DC2626" if r.get("amount", 0) > 15000 else "#F59E0B"
        })

        for ent in shared_entities[:5]:
            ent_id = f"ent_{ent.replace(' ', '_').replace(':', '')}"
            ent_val = ent.split(":", 1)[-1].strip() if ":" in ent else ent
            if (r.get("recipient_upi") and ent_val in r["recipient_upi"]) or \
               (r.get("scammer_phone") and ent_val in r["scammer_phone"]):
                edges.append({
                    "from": r["id"],
                    "to": ent_id,
                    "label": "linked"
                })

    return {"nodes": nodes, "edges": edges}

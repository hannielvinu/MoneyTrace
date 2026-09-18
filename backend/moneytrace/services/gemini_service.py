"""
Gemini AI Investigation Engine for MoneyTrace.
Powered by the official Google Gemini Python SDK (`google.genai`).

Performs structured autonomous financial fraud investigation:
- Victim story comprehension & summary
- Red flag & scam tactic detection
- Actionable, non-technical victim protection guidance
- Operational escalation recommendations

CRITICAL CONSTRAINTS:
1. Deterministic database truth is AUTHORITATIVE. Gemini cannot alter incident IDs,
   transaction IDs, amounts, currencies, account numbers, UPI IDs, or Cognee graph links.
2. Structured output is enforced via validated Pydantic models.
3. Transparent error handling distinguishes:
   - GEMINI LIVE
   - GEMINI CONFIGURED BUT FAILED
   - GEMINI NOT CONFIGURED
   - FALLBACK
"""

import os
import json
import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field

logger = logging.getLogger("moneytrace.gemini")

# Try importing google.genai
try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False
    logger.warning("google-genai SDK not installed or importable.")


class ExtractedEntitiesModel(BaseModel):
    upi: Optional[str] = Field(default=None, description="Suspected scammer recipient UPI handle")
    phone: Optional[str] = Field(default=None, description="Suspected scammer contact phone number")
    bank_account: Optional[str] = Field(default=None, description="Suspected recipient bank account number")
    domain: Optional[str] = Field(default=None, description="Phishing or scam domain/URL")
    qr_id: Optional[str] = Field(default=None, description="Malicious QR code identifier")


class GeminiInvestigationOutput(BaseModel):
    incident_type: str = Field(description="Specific category of payment fraud e.g. Fake KYC, Fake Customer Support, Digital Arrest, Investment Scam")
    severity: str = Field(description="Severity level: CRITICAL, HIGH, MEDIUM, or LOW")
    confidence: float = Field(description="Investigation confidence score between 0.0 and 1.0")
    victim_story_summary: str = Field(description="Concise 1-2 sentence executive summary of the scam narrative and victim impact")
    entities: ExtractedEntitiesModel = Field(description="Extracted counterparty entities from narrative")
    red_flags: List[str] = Field(description="List of detected deception tactics, urgency triggers, and behavioral anomalies")
    recommended_action: str = Field(description="Immediate operational instructions for the fraud investigation team")
    victim_guidance: List[str] = Field(description="Safe, clear, non-technical step-by-step protective instructions for the victim")
    evidence_required: List[str] = Field(description="Key legal and transaction artifacts the victim should preserve")
    requires_human_review: bool = Field(description="Whether high-risk financial recovery action requires operator authorization")


async def run_gemini_investigation(
    narrative: str,
    language: str,
    authoritative_facts: Dict[str, Any],
    cognee_intel: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Executes real Gemini API structured analysis.
    Returns:
    {
        "status": "GEMINI LIVE" | "GEMINI CONFIGURED BUT FAILED" | "GEMINI NOT CONFIGURED" | "FALLBACK",
        "provider": str,
        "model": str,
        "timestamp": str,
        "data": Dict[str, Any],
        "error": Optional[str]
    }
    """
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("LLM_API_KEY")
    api_key = api_key.strip() if api_key else ""
    model_name = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash"
    now_ts = datetime.now().strftime("%d %b %Y, %H:%M:%S IST")

    if not api_key:
        logger.info("Gemini API key not configured. Using deterministic fallback.")
        return {
            "status": "GEMINI NOT CONFIGURED",
            "provider": "Gemini Not Configured (Deterministic Fallback)",
            "model": model_name,
            "timestamp": now_ts,
            "data": None,
            "error": "GEMINI_API_KEY or LLM_API_KEY is not set in environment."
        }

    if not HAS_GENAI:
        logger.error("google.genai SDK not available.")
        return {
            "status": "GEMINI CONFIGURED BUT FAILED",
            "provider": "Gemini Error (SDK Missing)",
            "model": model_name,
            "timestamp": now_ts,
            "data": None,
            "error": "google-genai Python SDK is not installed."
        }

    # Format prompt strictly incorporating authoritative facts and verified Cognee intelligence
    prompt = f"""You are the senior autonomous fraud investigation teammate for MoneyTrace.
Analyze this payment fraud emergency report and provide structured intelligence.

=== AUTHORITATIVE FINANCIAL TRUTH (IMMUTABLE) ===
- Incident ID: {authoritative_facts.get('incident_id', 'UNKNOWN')}
- Transaction ID: {authoritative_facts.get('transaction_id', 'UNKNOWN')}
- Transaction Amount: INR {authoritative_facts.get('amount', 0.0):,.2f}
- Counterparty UPI ID: {authoritative_facts.get('recipient_upi') or 'Unknown'}
- Scammer Phone: {authoritative_facts.get('scammer_phone') or 'Unknown'}
- Primary Scam Category: {authoritative_facts.get('scam_type', 'Payment Fraud')}
- Victim Language: {language}

=== VERIFIED COGNEE KNOWLEDGE GRAPH INTELLIGENCE ===
- Intelligence Layer: {cognee_intel.get('provider', 'Local Syndicate Matcher')}
- Related Incidents Connected: {cognee_intel.get('related_count', 0)}
- Shared Entities: {cognee_intel.get('shared_entities', [])}
- Syndicate Network Detected: {cognee_intel.get('network_detected', False)}
- Total Exposure: INR {cognee_intel.get('total_exposure', 0.0):,.2f}

=== VICTIM REPORT NARRATIVE ===
"{narrative}"

=== INSTRUCTIONS ===
1. Analyze the deception mechanism, psychological levers (urgency, fear, greed), and technical attack vector.
2. Formulate 3-5 specific red flags observed in this incident.
3. Formulate clear, empathetic, non-technical protective steps for the victim in {language} language context (e.g. contact bank, file 1930/cybercrime.gov.in, never share OTPs, freeze card/UPI).
4. Do NOT disclose internal graph nodes or syndicate architecture in the victim guidance.
5. All financial and identity fields are strictly authoritative; do not invent new amounts or transaction IDs.
"""

    try:
        client = genai.Client(api_key=api_key)
        
        # Resilient retry against transient 503 / rate limits
        response = None
        last_err = None
        for attempt in range(4):
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        response_mime_type="application/json",
                        response_schema=GeminiInvestigationOutput,
                        temperature=0.1
                    )
                )
                if response and response.text:
                    break
            except Exception as ex:
                last_err = ex
                err_str = str(ex)
                if "503" in err_str or "429" in err_str or "UNAVAILABLE" in err_str:
                    logger.warning(f"Gemini {model_name} transient error (attempt {attempt + 1}/4): {ex}. Retrying in 3s...")
                    await asyncio.sleep(3.0)
                else:
                    raise ex

        if not response or not response.text:
            raise last_err or ValueError("Empty response received from Gemini API.")

        # Strongly validate against Pydantic schema
        validated_output = GeminiInvestigationOutput.model_validate_json(response.text)
        result_dict = validated_output.model_dump()

        logger.info(f"Gemini investigation completed successfully using model {model_name}")
        return {
            "status": "GEMINI LIVE",
            "provider": "Google Gemini Cloud AI",
            "model": model_name,
            "timestamp": now_ts,
            "data": result_dict,
            "error": None
        }

    except Exception as e:
        logger.error(f"Gemini API request failed: {e}")
        return {
            "status": "GEMINI CONFIGURED BUT FAILED",
            "provider": "Gemini Configured But Failed (Resilient Fallback)",
            "model": model_name,
            "timestamp": now_ts,
            "data": None,
            "error": str(e)
        }

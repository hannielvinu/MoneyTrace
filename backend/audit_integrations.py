"""
MoneyTrace External Services Integration Audit Script.
Strictly tests actual live calls to:
1. Sarvam AI (SARVAM_API_KEY)
2. Cognee Cloud (COGNEE_API_KEY, COGNEE_BASE_URL)
3. n8n Pro (N8N_WEBHOOK_URL)
4. End-to-End Incident Pipeline
"""

import os
import io
import wave
import httpx
import asyncio
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY", "").strip()
SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"

COGNEE_API_KEY = os.environ.get("COGNEE_API_KEY", "").strip()
COGNEE_BASE_URL = os.environ.get("COGNEE_BASE_URL", "https://api.cognee.ai").rstrip("/")

N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "").strip()

def generate_valid_wav_bytes() -> bytes:
    """Generates 1.0 second of valid PCM audio in WAV format."""
    buf = io.BytesIO()
    with wave.open(buf, 'wb') as wav_file:
        wav_file.setnchannels(1)       # Mono
        wav_file.setsampwidth(2)      # 16-bit
        wav_file.setframerate(16000)  # 16kHz
        # Write 16000 zero samples (silence)
        wav_file.writeframes(b'\x00\x00' * 16000)
    return buf.getvalue()

SARVAM_STT_MODEL = os.environ.get("SARVAM_STT_MODEL", "saaras:v3").strip() or "saaras:v3"

async def audit_sarvam():
    print("==================================================")
    print("1. SARVAM STT AUDIT")
    print("==================================================")
    print(f"SARVAM_API_KEY present in env: {'YES (' + SARVAM_API_KEY[:4] + '...)' if SARVAM_API_KEY else 'NO (NOT CONFIGURED)'}")
    print(f"SARVAM_STT_MODEL: {SARVAM_STT_MODEL}")
    
    if not SARVAM_API_KEY:
        print("Status: SARVAM NOT CONFIGURED")
        print("Actual HTTP Response: None (Request skipped because API key is absent)")
        return "SARVAM NOT CONFIGURED", "SARVAM_API_KEY not set in environment"

    wav_bytes = generate_valid_wav_bytes()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            files = {"file": ("test_audit.wav", wav_bytes, "audio/wav")}
            data = {"language_code": "hi-IN", "model": SARVAM_STT_MODEL}
            headers = {"api-subscription-key": SARVAM_API_KEY}
            resp = await client.post(SARVAM_STT_URL, files=files, data=data, headers=headers)
            print(f"HTTP Status: {resp.status_code}")
            print(f"HTTP Response Body: {resp.text[:300]}")
            if resp.status_code == 200:
                transcript = resp.json().get("transcript", "")
                print(f"Transcript: '{transcript}'")
                return "SARVAM LIVE", resp.text[:200]
            else:
                return "SARVAM CONFIGURED BUT FAILED", f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        print(f"Exception calling Sarvam: {e}")
        return "SARVAM CONFIGURED BUT FAILED", str(e)

async def audit_cognee():
    print("\n==================================================")
    print("2. COGNEE CLOUD AUDIT")
    print("==================================================")
    print(f"COGNEE_API_KEY present in env: {'YES (' + COGNEE_API_KEY[:4] + '...)' if COGNEE_API_KEY else 'NO (NOT CONFIGURED)'}")
    print(f"COGNEE_BASE_URL: {COGNEE_BASE_URL}")

    base_url = os.environ.get("COGNEE_BASE_URL", "").rstrip("/")
    api_key = os.environ.get("COGNEE_API_KEY", "").strip()

    if not api_key or not base_url:
        print("Status: COGNEE NOT CONFIGURED")
        print("Actual HTTP Response: None (Request skipped because COGNEE_API_KEY or COGNEE_BASE_URL is absent)")
        return "COGNEE NOT CONFIGURED", "COGNEE_API_KEY or COGNEE_BASE_URL not set in environment"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {
                "X-Api-Key": api_key,
                "Content-Type": "application/json"
            }
            # Test Search Endpoint with OpenAPI-compliant schema
            search_payload = {
                "query": "KYC fraud kyc-update.pay@ybl",
                "datasets": ["moneytrace_fraud_syndicates"],
                "searchType": "HYBRID_COMPLETION"
            }
            resp = await client.post(f"{base_url}/api/v1/search", json=search_payload, headers=headers)
            print(f"Search HTTP Status: {resp.status_code}")
            print(f"Search Response Body: {resp.text[:300]}")
            if resp.status_code in [200, 201]:
                return "COGNEE LIVE", resp.text[:200]
            else:
                return "COGNEE CONFIGURED BUT FAILED", f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        err_msg = f"{type(e).__name__}: {str(e)}"
        print(f"Exception calling Cognee Cloud: {err_msg}")
        return "COGNEE CONFIGURED BUT FAILED", err_msg

async def audit_n8n():
    print("\n==================================================")
    print("3. N8N PRO AUDIT")
    print("==================================================")
    print(f"N8N_WEBHOOK_URL present in env: {'YES (' + N8N_WEBHOOK_URL + ')' if N8N_WEBHOOK_URL else 'NO (NOT CONFIGURED)'}")

    if not N8N_WEBHOOK_URL:
        print("Status: N8N NOT CONFIGURED")
        print("Actual HTTP Response: None (Request skipped because N8N_WEBHOOK_URL is absent)")
        return "N8N NOT CONFIGURED", "N8N_WEBHOOK_URL not set in environment"

    payload = {
        "event": "moneytrace_incident_created",
        "incident_id": "AUDIT-TEST-001",
        "severity": "CRITICAL",
        "amount": 18500.0,
        "scam_type": "Fake KYC",
        "recipient_upi": "kyc-update.pay@ybl",
        "timestamp": datetime.now().isoformat()
    }
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(N8N_WEBHOOK_URL, json=payload)
            print(f"n8n Webhook HTTP Status: {resp.status_code}")
            print(f"n8n Webhook Response Body: {resp.text[:300]}")
            if resp.status_code in [200, 201, 202]:
                return "N8N LIVE", resp.text[:200]
            else:
                return "N8N CONFIGURED BUT FAILED", f"HTTP {resp.status_code}: {resp.text[:200]}"
    except Exception as e:
        print(f"Exception calling n8n webhook: {e}")
        return "N8N CONFIGURED BUT FAILED", str(e)

async def audit_gemini():
    print("\n==================================================")
    print("4. GOOGLE GEMINI AUDIT")
    print("==================================================")
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("LLM_API_KEY")
    model_name = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash").strip() or "gemini-3.8-flash"
    
    print(f"GEMINI_API_KEY present in env: {'YES' if api_key else 'NO (NOT CONFIGURED)'}")
    print(f"GEMINI_MODEL: {model_name}")

    if not api_key:
        print("Status: GEMINI NOT CONFIGURED")
        return "GEMINI NOT CONFIGURED", "GEMINI_API_KEY or LLM_API_KEY not set"

    try:
        from moneytrace.services.gemini_service import run_gemini_investigation
        res = await run_gemini_investigation(
            narrative="Victim reported Fake KYC call requesting Rs 18500 transfer to kyc-update.pay@ybl.",
            language="en",
            authoritative_facts={
                "incident_id": "AUDIT-GEMINI-01",
                "transaction_id": "TXN784219",
                "amount": 18500.0,
                "recipient_upi": "kyc-update.pay@ybl",
                "scammer_phone": "+91-98765-43210",
                "scam_type": "Fake KYC"
            },
            cognee_intel={
                "provider": "Cognee Cloud API",
                "related_count": 1,
                "shared_entities": ["UPI: kyc-update.pay@ybl"],
                "network_detected": True,
                "total_exposure": 18500.0
            }
        )
        print(f"Gemini Status: {res.get('status')}")
        if res.get("status") == "GEMINI LIVE":
            summary = res.get("data", {}).get("victim_story_summary", "")[:120]
            print(f"Gemini Structured Summary: {summary}")
            return "GEMINI LIVE", f"Model '{model_name}': {summary}"
        else:
            return res.get("status"), res.get("error", "Unknown failure")
    except Exception as e:
        print(f"Exception auditing Gemini: {e}")
        return "GEMINI CONFIGURED BUT FAILED", str(e)


async def main():
    s_status, s_proof = await audit_sarvam()
    c_status, c_proof = await audit_cognee()
    n_status, n_proof = await audit_n8n()
    g_status, g_proof = await audit_gemini()

    print("\n==================================================")
    print("AUDIT SUMMARY MATRIX")
    print("==================================================")
    print(f"{'SERVICE':<14} {'STATUS':<20} {'PROOF / DETAILS'}")
    print(f"{'Sarvam':<14} {s_status:<20} {s_proof}")
    print(f"{'Cognee':<14} {c_status:<20} {c_proof}")
    print(f"{'n8n':<14} {n_status:<20} {n_proof}")
    print(f"{'Gemini':<14} {g_status:<20} {g_proof}")
    print("==================================================")

if __name__ == "__main__":
    asyncio.run(main())

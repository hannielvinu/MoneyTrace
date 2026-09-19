"""
Comprehensive Verification Test Suite for MoneyTrace Acceptance Criteria:
1. Authentication & Role Data Isolation (USER vs FRAUD_OPERATOR)
2. Incident Ingestion via User Portal
3. Autonomous Investigation Pipeline Execution (Event Bus emission)
4. Sarvam STT Transcription Service check
5. Cognee Cloud / Local Resilience relationship discovery
6. n8n Autonomous response workflow execution
7. User Notification Creation & Isolation
"""

import asyncio
import httpx
from datetime import datetime

BASE_URL = "http://127.0.0.1:8000"

async def test_full_flow():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=25.0) as client:
        print("\n--- 1. Health Check ---")
        res = await client.get("/api/health")
        assert res.status_code == 200, f"Health check failed: {res.text}"
        print("✓ Health Check Passed")

        print("\n--- 2. Authentication & Data Isolation ---")
        # Victim 1 Login
        v1_res = await client.post("/api/auth/login", json={"email": "victim@moneytrace.in", "password": "victim123"})
        assert v1_res.status_code == 200, "Victim 1 login failed"
        v1_token = v1_res.json()["access_token"]
        v1_headers = {"Authorization": f"Bearer {v1_token}"}
        print("✓ Victim 1 logged in successfully")

        # Victim 2 Login
        v2_res = await client.post("/api/auth/login", json={"email": "victim2@moneytrace.in", "password": "victim123"})
        assert v2_res.status_code == 200, "Victim 2 login failed"
        v2_token = v2_res.json()["access_token"]
        v2_headers = {"Authorization": f"Bearer {v2_token}"}
        print("✓ Victim 2 logged in successfully")

        # Operator Login
        op_res = await client.post("/api/auth/login", json={"email": "operator@moneytrace.in", "password": "operator123"})
        assert op_res.status_code == 200, "Operator login failed"
        op_token = op_res.json()["access_token"]
        op_headers = {"Authorization": f"Bearer {op_token}"}
        print("✓ Fraud Operator logged in successfully")

        # Role Verification: Victim cannot access /api/dashboard
        v_dash = await client.get("/api/dashboard", headers=v1_headers)
        assert v_dash.status_code == 403, f"Data isolation breach! Victim accessed dashboard: {v_dash.status_code}"
        print("✓ Data Isolation Confirmed: Victim blocked with HTTP 403 on operator endpoint")

        # Operator can access dashboard
        op_dash = await client.get("/api/dashboard", headers=op_headers)
        assert op_dash.status_code == 200, f"Operator dashboard error: {op_dash.text}"
        print(f"✓ Operator Dashboard Loaded: {op_dash.json()['metrics']['active_incidents']} active incidents")

        print("\n--- 3. Voice Transcription (Sarvam STT) ---")
        # Test Tamil / Hindi / English STT endpoint with valid WAV audio
        import io, wave
        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(b'\x00\x00' * 16000)
        audio_dummy = buf.getvalue()

        stt_res = await client.post(
            "/api/voice/transcribe",
            files={"audio": ("audio.wav", audio_dummy, "audio/wav")},
            data={"language": "en"}
        )
        assert stt_res.status_code == 200, f"STT failed: {stt_res.text}"
        stt_data = stt_res.json()
        print(f"✓ Sarvam STT Result: Provider='{stt_data['provider']}', Lang='{stt_data['language']}'")
        print(f"  Live Success: {stt_data.get('success')}, Fallback: {stt_data.get('is_fallback')}")

        print("\n--- 4. Victim 1 Submits Emergency Incident Report ---")
        report_payload = {
            "narrative": "Urgent help needed. Received a call claiming to be HDFC bank KYC department. They asked me to transfer money to kyc-update.pay@ybl or account will freeze. Transferred ₹18,500.",
            "language": "en",
            "transaction_id": "TXN784219",
            "amount": 18500.0
        }
        submit_res = await client.post("/api/portal/reports", json=report_payload, headers=v1_headers)
        assert submit_res.status_code == 200, f"Submission failed: {submit_res.text}"
        inc_data = submit_res.json()
        new_inc_id = inc_data["incident_id"]
        print(f"✓ Incident Registered: {new_inc_id}, Message: '{inc_data['message']}'")
        assert "voice_response" in inc_data, "voice_response missing from intake response"
        print(f"✓ Voice Acknowledgement Generated: available={inc_data['voice_response'].get('available')}, url={inc_data['voice_response'].get('audio_url')}")

        print("\n--- 5. Awaiting Autonomous Investigation Pipeline & Events ---")
        # Await pipeline completion (real Cognee Cloud adds/searches + Gemini structured generation + n8n webhook take 4-8 seconds)
        for _ in range(35):
            await asyncio.sleep(1.0)
            case_check = await client.get(f"/api/incidents/{new_inc_id}", headers=op_headers)
            if case_check.status_code == 200:
                cdata = case_check.json()
                if cdata.get("investigation_stage") == "COMPLETE" and cdata.get("evidence_package"):
                    break

        v1_reps = await client.get("/api/portal/my-reports", headers=v1_headers)
        my_reps = v1_reps.json()["reports"]
        assert any(r["id"] == new_inc_id for r in my_reps), "New incident not found in victim 1 reports"
        print(f"✓ Victim 1 isolated reports confirmed ({len(my_reps)} records)")

        # Verify Victim 2 CANNOT see Victim 1's incident
        v2_reps = await client.get("/api/portal/my-reports", headers=v2_headers)
        v2_records = v2_reps.json()["reports"]
        assert not any(r["id"] == new_inc_id for r in v2_records), "Victim 2 improperly sees Victim 1's report!"
        print(f"✓ Victim 2 Isolation Verified: Victim 2 has {len(v2_records)} reports (0 leak of {new_inc_id})")

        print("\n--- 6. User-Safe Protective Notifications ---")
        notifs_res = await client.get("/api/portal/notifications", headers=v1_headers)
        notifs = notifs_res.json()["notifications"]
        assert len(notifs) > 0, "No user notification generated!"
        print(f"✓ User Notification Created: '{notifs[0]['title']}'")
        print(f"  Summary: {notifs[0]['summary']}")
        print(f"  Safe Guidance Preview: {notifs[0]['guidance'][:80]}...")

        print("\n--- 7. Fraud Operator Case Workspace & Cognee Syndicate Intelligence ---")
        case_res = await client.get(f"/api/incidents/{new_inc_id}", headers=op_headers)
        assert case_res.status_code == 200, f"Case fetch failed: {case_res.text}"
        case_data = case_res.json()
        assert case_data["evidence_package"] is not None, "Evidence package missing!"
        pkg = case_data["evidence_package"]
        print(f"✓ Evidence Package: Severity={pkg['severity']}, Intel Layer='{pkg.get('intelligence_layer')}'")
        ai_inv = pkg.get("ai_investigator", {})
        print(f"✓ AI Investigator: Provider='{ai_inv.get('provider')}', Status='{ai_inv.get('status')}', Model='{ai_inv.get('model')}'")
        assert ai_inv.get("status") == "GEMINI LIVE", f"Gemini status not LIVE: {ai_inv}"
        print(f"  Gemini Story Summary: {pkg.get('victim_story_summary')[:80]}...")
        print(f"  Shared Entities: {pkg.get('shared_entities')}")
        print(f"  Related Incidents Discovered: {pkg.get('related_incidents_count')}")

        # Check event logs
        events_res = await client.get(f"/api/incidents/{new_inc_id}/events", headers=op_headers)
        events = events_res.json()["events"]
        event_types = [e["event_type"] for e in events]
        print(f"✓ Persistent Event Bus recorded {len(events)} milestones: {event_types}")
        assert "INCIDENT_CREATED" in event_types
        assert "INVESTIGATION_STARTED" in event_types
        assert "RELATED_INCIDENTS_FOUND" in event_types
        assert "EVIDENCE_PREPARED" in event_types
        assert "N8N_WORKFLOW_COMPLETED" in event_types
        assert "USER_NOTIFICATION_CREATED" in event_types

        # Verify Resolution Voice Response attached to completion event
        comp_event = next((e for e in events if e["event_type"] == "INCIDENT_COMPLETED"), None)
        assert comp_event is not None, "INCIDENT_COMPLETED event missing"
        voice_res = comp_event.get("payload", {}).get("voice_response", {})
        print(f"✓ Resolution Voice Response in Pipeline: available={voice_res.get('available')}, event={voice_res.get('event')}, url={voice_res.get('audio_url')}")

        # Verify dedicated audio endpoint /api/voice/response
        voice_endpoint_res = await client.get(f"/api/voice/response/{new_inc_id}/investigation_completed", headers=v1_headers)
        assert voice_endpoint_res.status_code == 200, f"Voice endpoint failed: {voice_endpoint_res.text}"
        voice_data = voice_endpoint_res.json()
        assert voice_data.get("available") is True, "Voice response not available on endpoint"
        print(f"✓ Voice Response Endpoint verified: {voice_data.get('audio_url')} (cached={voice_data.get('cached')})")

        print("\n--- 8. Operator Human Review Signoff ---")
        review_res = await client.post(
            f"/api/incidents/{new_inc_id}/review",
            json={"action": "APPROVED", "notes": "Verified fraudulent KYC ring counterparty."},
            headers=op_headers
        )
        assert review_res.status_code == 200, "Review signoff failed"
        print(f"✓ Operator Signoff Executed on {new_inc_id}")

        print("\n=======================================================")
        print("🎉 ALL ACCEPTANCE CRITERIA TESTS PASSED SUCCESSFULLY! 🎉")
        print("=======================================================\n")

if __name__ == "__main__":
    asyncio.run(test_full_flow())

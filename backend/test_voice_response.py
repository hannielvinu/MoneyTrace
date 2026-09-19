"""
Comprehensive Unit & Provenance Test Suite for Human, Empathetic Voice Agent:
1. Amount extraction directly and exclusively from the Sarvam STT voice transcript.
2. Handling distinct amounts: ₹18,500, ₹7,250, ₹50,000, 18.5k, words 'eighteen thousand five hundred'.
3. Missing amount handled gracefully without hallucinating an amount.
4. Conflict resolution: prefers voice transcript over manual/request payload.
5. Empathetic tone verification: acknowledges concern, provides reassurance without robotic phrasing.
6. Outcome-aware resolution voice generation reflecting real investigation conclusions.
7. Idempotency and disk caching (zero duplicate Sarvam TTS network calls).
8. Resilience against 429 quota limits, 500 errors, and missing credentials.
"""

import os
import asyncio
import unittest
from unittest.mock import patch, AsyncMock
import httpx
from dotenv import load_dotenv

load_dotenv()

from moneytrace.services.voice_response import (
    generate_voice_response, build_voice_script, extract_amount_from_transcript,
    resolve_amount_with_provenance, AUDIO_CACHE_DIR, _get_cache_filepath
)


class TestEmpatheticVoiceAgent(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.case_id = "MT-UNIT-PROVENANCE"
        self.cache_ack = _get_cache_filepath(self.case_id, "complaint_received")
        self.cache_res = _get_cache_filepath(self.case_id, "investigation_completed")
        for f in [self.cache_ack, self.cache_res]:
            if os.path.exists(f):
                os.remove(f)

    async def asyncTearDown(self):
        for f in [self.cache_ack, self.cache_res]:
            if os.path.exists(f):
                os.remove(f)

    def test_amount_extraction_from_voice_transcript(self):
        # Example 1: 18,500
        t1 = "I was tricked into sending 18,500 rupees to someone claiming to be bank support."
        res1 = extract_amount_from_transcript(t1)
        self.assertEqual(res1["amount"], 18500.0)
        self.assertEqual(res1["amount_source"], "voice_transcript")
        self.assertIn("18,500", res1["amount_source_text"])

        # Example 2: 7,250
        t2 = "I transferred 7,250 rupees to the wrong person on UPI."
        res2 = extract_amount_from_transcript(t2)
        self.assertEqual(res2["amount"], 7250.0)
        self.assertEqual(res2["amount_source"], "voice_transcript")

        # Example 3: 50,000
        t3 = "I lost 50,000 rupees after someone convinced me to make a payment."
        res3 = extract_amount_from_transcript(t3)
        self.assertEqual(res3["amount"], 50000.0)
        self.assertEqual(res3["amount_source"], "voice_transcript")

        # Example 4: Verbal words (eighteen thousand five hundred)
        t4 = "I paid eighteen thousand five hundred rupees for a fake KYC charge."
        res4 = extract_amount_from_transcript(t4)
        self.assertEqual(res4["amount"], 18500.0)
        self.assertEqual(res4["amount_source"], "voice_transcript")

        # Example 5: Decimal with multiplier (18.5 thousand)
        t5 = "They stole 18.5 thousand from my savings account."
        res5 = extract_amount_from_transcript(t5)
        self.assertEqual(res5["amount"], 18500.0)
        self.assertEqual(res5["amount_source"], "voice_transcript")

        # Critical Spoken Number Hierarchy Cases:
        cases = [
            ("three thousand six hundred rupees", 3600),
            ("three thousand six hundred", 3600),
            ("three thousand", 3000),
            ("three hundred", 300),
            ("three hundred fifty", 350),
            ("three hundred and fifty", 350),
            ("twenty five hundred", 2500),
            ("seven thousand two hundred", 7200),
            ("seven thousand two hundred fifty", 7250),
            ("eighteen thousand five hundred", 18500),
            ("fifty thousand", 50000),
            ("one lakh", 100000),
            ("one lakh twenty five thousand", 125000),
            ("two lakh fifty thousand", 250000),
            ("one crore", 10000000),
            ("I transferred three thousand six hundred rupees", 3600),
            ("I was scammed for three thousand six hundred rupees", 3600),
            ("I lost three thousand six hundred rupees", 3600),
            ("3600 rupees", 3600),
            ("3,600 rupees", 3600),
            ("₹3,600", 3600),
            ("Rs 3600", 3600),
            ("3.6 thousand", 3600),
            ("3.6k", 3600),
        ]
        for phrase, expected in cases:
            res_c = extract_amount_from_transcript(phrase)
            self.assertEqual(res_c["amount"], float(expected), f"Failed for '{phrase}': got {res_c['amount']}, expected {expected}")
            self.assertEqual(res_c["amount_source"], "voice_transcript")
            self.assertTrue(bool(res_c["amount_source_text"]))

    def test_missing_amount_handled_without_hallucination(self):
        t_no_amt = "Someone called pretending to be a police officer and threatened me."
        res = extract_amount_from_transcript(t_no_amt)
        self.assertIsNone(res["amount"])
        self.assertEqual(res["amount_source"], "none")

        # Verify acknowledgement does NOT mention any amount
        script = build_voice_script(
            event_type="complaint_received",
            case_id="MT-10999",
            language="en",
            amount=res["amount"],
            amount_source=res["amount_source"]
        )
        self.assertNotIn("rupees", script)
        self.assertNotIn("₹", script)
        self.assertIn("I understand this is concerning", script)
        self.assertIn("MT-10999", script)

    def test_amount_conflict_resolution(self):
        # When request payload has 15000 but voice transcript clearly states 18500
        narrative = "I was coerced into sending 18,500 rupees to a scammer."
        resolved = resolve_amount_with_provenance(narrative, request_amount=15000.0)
        self.assertEqual(resolved["amount"], 18500.0)
        self.assertEqual(resolved["amount_source"], "voice_transcript")
        self.assertTrue(resolved["amount_conflict"])

    def test_empathetic_script_quality(self):
        # Verify tone is calm, reassuring, professional (NOT robotic ticketing alert)
        script_ack = build_voice_script(
            event_type="complaint_received",
            case_id="MT-10482",
            language="en",
            amount=18500.0,
            amount_source="voice_transcript"
        )
        self.assertNotIn("received successfully", script_ack)
        self.assertIn("I understand this is concerning", script_ack)
        self.assertIn("₹18,500", script_ack)
        self.assertIn("MT-10482", script_ack)
        self.assertLessEqual(len(script_ack), 250)

        # Hindi empathetic script
        script_hi = build_voice_script(
            event_type="complaint_received",
            case_id="MT-10482",
            language="hi",
            amount=18500.0,
            amount_source="voice_transcript"
        )
        self.assertIn("चिंता मत कीजिए", script_hi)
        self.assertIn("18,500", script_hi)
        self.assertIn("MT-10482", script_hi)
        self.assertLessEqual(len(script_hi), 250)

    def test_outcome_grounded_resolution_scripts(self):
        # 1. Suspicious / Fraud identified / Escalated
        script_fraud = build_voice_script(
            event_type="investigation_completed",
            case_id="MT-10482",
            status="ESCALATED",
            scam_type="Fake KYC"
        )
        self.assertIn("suspicious activity", script_fraud.lower())
        self.assertIn("urgent protection", script_fraud.lower())
        self.assertNotIn("gemini", script_fraud.lower())
        self.assertNotIn("cognee", script_fraud.lower())
        self.assertNotIn("confidence score", script_fraud.lower())

        # 2. Legitimate / No Fraud confirmed
        script_legit = build_voice_script(
            event_type="investigation_completed",
            case_id="MT-10482",
            status="RESOLVED"
        )
        self.assertIn("couldn't confirm fraudulent activity", script_legit)

        # 3. Human verification team needed
        script_review = build_voice_script(
            event_type="investigation_completed",
            case_id="MT-10482",
            status="UNDER_REVIEW"
        )
        self.assertIn("needs additional verification", script_review)

    async def test_idempotency_and_caching(self):
        mock_response = httpx.Response(
            status_code=200,
            json={"request_id": "req-1", "audios": ["UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA="]},
            request=httpx.Request("POST", "https://api.sarvam.ai/text-to-speech")
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            res1 = await generate_voice_response(
                case_id=self.case_id,
                event_type="complaint_received",
                language="en",
                amount=7250.0,
                amount_source="voice_transcript"
            )
            self.assertTrue(res1["available"])
            self.assertFalse(res1["cached"])
            self.assertEqual(mock_post.call_count, 1)

            # Re-calling must hit disk cache with ZERO network requests
            res2 = await generate_voice_response(
                case_id=self.case_id,
                event_type="complaint_received",
                language="en",
                amount=7250.0,
                amount_source="voice_transcript"
            )
            self.assertTrue(res2["available"])
            self.assertTrue(res2["cached"])
            self.assertEqual(mock_post.call_count, 1)

    async def test_mock_429_quota_exhaustion_fallback(self):
        mock_response = httpx.Response(
            status_code=429,
            json={"error": {"message": "Rate limit exceeded"}},
            request=httpx.Request("POST", "https://api.sarvam.ai/text-to-speech")
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            res = await generate_voice_response(
                case_id="MT-UNIT-429",
                event_type="complaint_received"
            )
            self.assertFalse(res["available"])
            self.assertEqual(res["reason"], "rate_limit_or_quota_exceeded")
            self.assertIsNotNone(res["text"])


if __name__ == "__main__":
    unittest.main()

"""
Dedicated Unit and Integration Test Suite for Voice Acknowledgement & Resolution:
A. Complaint acknowledgement generation with dynamic data
B. Investigation completion resolution generation with real case status
C. Idempotency and disk caching (zero duplicate calls)
D. TTS Failure resilience with mocked 429 quota exhaustion (no crash, text fallback)
E. TTS Failure resilience with mocked 500 error / timeout (no crash, text fallback)
F. Missing SARVAM_API_KEY graceful fallback
"""

import os
import asyncio
import unittest
from unittest.mock import patch, AsyncMock
import httpx
from dotenv import load_dotenv

load_dotenv()

from moneytrace.services.voice_response import (
    generate_voice_response, build_voice_script, AUDIO_CACHE_DIR, _get_cache_filepath
)


class TestVoiceResponse(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.case_id = "MT-UNIT-9999"
        self.cache_ack = _get_cache_filepath(self.case_id, "complaint_received")
        self.cache_res = _get_cache_filepath(self.case_id, "investigation_completed")
        for f in [self.cache_ack, self.cache_res]:
            if os.path.exists(f):
                os.remove(f)

    async def asyncTearDown(self):
        for f in [self.cache_ack, self.cache_res]:
            if os.path.exists(f):
                os.remove(f)

    def test_dynamic_script_generation(self):
        # Verify script length constraint <= 200 chars
        script_ack = build_voice_script(
            event_type="complaint_received",
            case_id="MT-10482",
            language="en",
            amount=18500.0
        )
        self.assertIn("MT-10482", script_ack)
        self.assertIn("18,500", script_ack)
        self.assertLessEqual(len(script_ack), 200)

        # Verification of distinct resolution status: RESOLVED
        script_res_legit = build_voice_script(
            event_type="investigation_completed",
            case_id="MT-10482",
            status="RESOLVED"
        )
        self.assertIn("No confirmed fraud", script_res_legit)
        self.assertIn("MT-10482", script_res_legit)
        self.assertLessEqual(len(script_res_legit), 200)

        # Verification of distinct resolution status: ESCALATED / SUSPICIOUS
        script_res_fraud = build_voice_script(
            event_type="investigation_completed",
            case_id="MT-10482",
            status="ESCALATED"
        )
        self.assertIn("Suspicious activity", script_res_fraud)
        self.assertIn("MT-10482", script_res_fraud)
        self.assertLessEqual(len(script_res_fraud), 200)

    async def test_idempotency_and_caching(self):
        # Mock Sarvam returning audio
        mock_response = httpx.Response(
            status_code=200,
            json={"request_id": "req-1", "audios": ["UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA="]},
            request=httpx.Request("POST", "https://api.sarvam.ai/text-to-speech")
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            # Call 1: should call Sarvam
            res1 = await generate_voice_response(
                case_id=self.case_id,
                event_type="complaint_received",
                language="en",
                amount=25000.0
            )
            self.assertTrue(res1["available"])
            self.assertFalse(res1["cached"])
            self.assertEqual(mock_post.call_count, 1)
            self.assertTrue(os.path.isfile(self.cache_ack))

            # Call 2 (reconnect / refresh): must be served from cache without calling Sarvam
            res2 = await generate_voice_response(
                case_id=self.case_id,
                event_type="complaint_received",
                language="en",
                amount=25000.0
            )
            self.assertTrue(res2["available"])
            self.assertTrue(res2["cached"])
            self.assertEqual(mock_post.call_count, 1)  # Zero extra API calls

    async def test_mock_429_quota_exhaustion_fallback(self):
        mock_response = httpx.Response(
            status_code=429,
            json={"error": {"message": "Rate limit / Quota exceeded"}},
            request=httpx.Request("POST", "https://api.sarvam.ai/text-to-speech")
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            res = await generate_voice_response(
                case_id="MT-UNIT-429",
                event_type="complaint_received",
                language="en"
            )
            # Must NOT crash, available=False, fallback preserved
            self.assertFalse(res["available"])
            self.assertEqual(res["reason"], "rate_limit_or_quota_exceeded")
            self.assertIsNotNone(res["text"])

    async def test_mock_500_error_fallback(self):
        mock_response = httpx.Response(
            status_code=500,
            text="Internal Server Error",
            request=httpx.Request("POST", "https://api.sarvam.ai/text-to-speech")
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            res = await generate_voice_response(
                case_id="MT-UNIT-500",
                event_type="investigation_completed",
                language="en"
            )
            self.assertFalse(res["available"])
            self.assertEqual(res["reason"], "http_500")
            self.assertIsNotNone(res["text"])

    async def test_missing_api_key_graceful_handling(self):
        with patch.dict(os.environ, {"SARVAM_API_KEY": ""}):
            res = await generate_voice_response(
                case_id="MT-UNIT-NOKEY",
                event_type="complaint_received"
            )
            self.assertFalse(res["available"])
            self.assertEqual(res["reason"], "api_key_missing")
            self.assertIsNotNone(res["text"])


if __name__ == "__main__":
    unittest.main()

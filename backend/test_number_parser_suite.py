import unittest
from moneytrace.services.voice_response import (
    extract_amount_from_transcript,
    build_voice_script,
    resolve_amount_with_provenance
)

class TestSpokenNumberParser(unittest.TestCase):

    def test_all_spoken_amount_cases(self):
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
            with self.subTest(phrase=phrase, expected=expected):
                res = extract_amount_from_transcript(phrase)
                self.assertEqual(res["amount"], float(expected), f"Failed for '{phrase}': got {res['amount']}, expected {expected}")
                self.assertEqual(res["amount_source"], "voice_transcript")
                self.assertIsNotNone(res["amount_source_text"])

    def test_voice_acknowledgement_does_not_say_360(self):
        narrative = "I was tricked into sending three thousand six hundred rupees."
        res = extract_amount_from_transcript(narrative)
        self.assertEqual(res["amount"], 3600.0)
        self.assertEqual(res["amount_source"], "voice_transcript")

        script = build_voice_script(
            event_type="complaint_received",
            case_id="MT-10888",
            language="en",
            amount=res["amount"],
            amount_source=res["amount_source"],
            complaint_narrative=narrative
        )
        print("Generated acknowledgement script:\n", script)
        self.assertIn("₹3,600", script)
        self.assertNotIn("₹360 ", script)
        self.assertNotIn("360 rupees", script)

if __name__ == "__main__":
    unittest.main()

"""Intake parsing: amounts and entities from free text."""
import pytest

from moneytrace.services.voice_response import extract_amount_from_transcript, resolve_amount_with_provenance
from moneytrace.services.investigation_agent import _extract_entities_from_text


@pytest.mark.parametrize("text,expected", [
    ("I transferred ₹18,500 to them", 18500),
    ("lost eighteen thousand five hundred rupees", 18500),
    ("they took 7250 rupees", 7250),
    ("one lakh twenty five thousand", 125000),
])
def test_amount_extraction(text, expected):
    assert extract_amount_from_transcript(text)["amount"] == expected


def test_no_amount_is_not_invented():
    assert extract_amount_from_transcript("someone called me about my account")["amount"] in (None, 0, 0.0)


def test_voice_amount_preferred_over_manual():
    res = resolve_amount_with_provenance("I sent ₹7,250 to the caller", 9999.0)
    assert res["amount"] == 7250
    assert res["amount_source"] == "voice_transcript"


def test_entity_regexes():
    ents = _extract_entities_from_text("paid scammer.pay@okaxis, he called from 9876501234 about refund")
    assert ents["upi"] == "scammer.pay@okaxis"
    assert ents["phone"] == "9876501234"

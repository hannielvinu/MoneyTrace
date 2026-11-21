"""
Payment-screenshot reading (intake: unstructured image -> structured fields).

Uses a vision model (Gemini in production; an NVIDIA VL model in development).
If no model is available, or it fails, the response says so honestly
(provider "fallback", empty fields, is_uncertain=True) instead of inventing values.
"""
import json
import logging
import re
from typing import Any, Dict

logger = logging.getLogger("moneytrace.screenshot")

PROMPT = """This image should be a UPI / bank payment screenshot from India. Extract ONLY what is visible.
Return JSON: {"is_payment_screenshot": bool, "transaction_id": str|null, "utr": str|null, "amount": number|null,
"recipient_vpa": str|null, "recipient_name": str|null, "date": str|null, "app": str|null, "status": str|null,
"confidence": number between 0 and 1}. Use null for anything not clearly visible. Do not guess."""


def _fallback(reason: str) -> Dict[str, Any]:
    return {"detected_type": "Screenshot received (automatic reading unavailable)", "confidence": 0.0,
            "extracted_fields": {"transaction_id": None, "amount": None, "recipient_vpa": None, "date": None},
            "is_uncertain": True, "provider": "fallback", "reason": reason,
            "note": "We could not read the screenshot automatically. Please type the transaction ID and amount."}


def extract_payment_fields(image_bytes: bytes, mime: str = "image/png") -> Dict[str, Any]:
    from moneytrace.llm import generate_text, llm_available
    if not llm_available():
        return _fallback("no vision model configured")
    try:
        res = generate_text(PROMPT, agent="screenshot_reader", json_mode=True, image_bytes=image_bytes,
                            image_mime=mime, tier="vision", max_tokens=2000)
        m = re.search(r"\{.*\}", res.text, re.S)
        data = json.loads(m.group(0)) if m else {}
    except Exception as e:
        logger.warning(f"screenshot extraction failed: {e}")
        return _fallback(f"vision model error: {type(e).__name__}")
    amount = data.get("amount")
    try:
        amount = float(str(amount).replace(",", "")) if amount not in (None, "") else None
    except ValueError:
        amount = None
    conf = float(data.get("confidence") or 0.0)
    return {"detected_type": "UPI Payment Receipt" if data.get("is_payment_screenshot") else "Unrecognised image",
            "confidence": round(conf, 2),
            "extracted_fields": {"transaction_id": data.get("transaction_id") or data.get("utr"), "amount": amount,
                                 "recipient_vpa": data.get("recipient_vpa"), "recipient_name": data.get("recipient_name"),
                                 "date": data.get("date"), "app": data.get("app"), "status": data.get("status")},
            "is_uncertain": conf < 0.7 or not data.get("is_payment_screenshot"), "provider": res.model,
            "note": "Values read from your screenshot. Please check and correct them before submitting."}

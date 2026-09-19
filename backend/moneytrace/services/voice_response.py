"""
MoneyTrace Voice Response Service via Sarvam AI TTS (Bulbul v3).
Supports multilingual spoken acknowledgements and resolution audio:
- Event 'complaint_received': Short intake confirmation with dynamic case_id and amount.
- Event 'investigation_completed': Short resolution outcome with actual case status/fraud assessment.

Free-tier & Quota Controls:
- Target message length <= 200 characters.
- Backend disk caching & idempotency based on (case_id, event_type).
- Returns dict with {"available": True/False, "event": ..., "audio_url": ...}.
- Never raises uncaught exceptions; falls back transparently.
"""

import os
import base64
import logging
import httpx
from typing import Dict, Any, Optional

logger = logging.getLogger("moneytrace.tts")

SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY", "").strip()
SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"
SARVAM_TTS_MODEL = os.environ.get("SARVAM_TTS_MODEL", "bulbul:v3").strip() or "bulbul:v3"

# Supported Sarvam languages & speakers
SARVAM_LANG_MAP = {
    "en": "en-IN",
    "hi": "hi-IN",
    "ta": "ta-IN",
    "kn": "kn-IN"
}

DEFAULT_SPEAKER = "priya"  # Verified valid Bulbul v3 speaker

# Directory for storing and caching generated audio files
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIO_CACHE_DIR = os.path.join(BASE_DIR, "static", "uploads", "voice_cache")
os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)


def _get_cache_filepath(case_id: str, event_type: str) -> str:
    safe_case = case_id.replace("/", "_").replace("\\", "_")
    filename = f"case_{safe_case}_{event_type}.wav"
    return os.path.join(AUDIO_CACHE_DIR, filename)


def _get_audio_url(case_id: str, event_type: str) -> str:
    safe_case = case_id.replace("/", "_").replace("\\", "_")
    return f"/static/uploads/voice_cache/case_{safe_case}_{event_type}.wav"


def build_voice_script(
    event_type: str,
    case_id: str,
    language: str = "en",
    amount: Optional[float] = None,
    status: Optional[str] = None,
    scam_type: Optional[str] = None,
    is_fraud: bool = True
) -> str:
    """
    Constructs a concise (<= 200 chars) dynamically-grounded voice response text.
    Uses actual case details without hardcoding.
    """
    lang = language.lower() if language else "en"
    if lang not in SARVAM_LANG_MAP:
        lang = "en"

    amt_str = f" of {int(amount):,} rupees" if amount and amount > 0 else ""
    amt_hi = f" {int(amount):,} रुपये का" if amount and amount > 0 else ""

    if event_type == "complaint_received":
        if lang == "hi":
            script = f"आपकी शिकायत दर्ज कर ली गई है। संदर्भ संख्या {case_id} है। जांच शुरू कर दी गई है।"
        elif lang == "ta":
            script = f"உங்கள் புகார் பெறப்பட்டது. குறிப்பு எண் {case_id}. விசாரணை தொடங்கப்பட்டுள்ளது."
        elif lang == "kn":
            script = f"ನಿಮ್ಮ ದೂರನ್ನು ಸ್ವೀಕರಿಸಲಾಗಿದೆ. ಉಲ್ಲೇಖ ಸಂಖ್ಯೆ {case_id}. ತನಿಖೆ ಪ್ರಾರಂಭವಾಗಿದೆ."
        else:
            script = f"Your complaint has been received. We have started investigating your reported transaction{amt_str}. Case reference is {case_id}."

    elif event_type == "investigation_completed":
        st_upper = (status or "").upper()
        if st_upper in ["RESOLVED", "LEGITIMATE", "NO_FRAUD"]:
            if lang == "hi":
                script = f"जांच पूरी हो गई है। कोई धोखाधड़ी नहीं पाई गई। संदर्भ संख्या {case_id} है।"
            elif lang == "ta":
                script = f"விசாரணை முடிந்தது. மோசடி எதுவும் கண்டறியப்படவில்லை. குறிப்பு எண் {case_id}."
            elif lang == "kn":
                script = f"ತನಿಖೆ ಪೂರ್ಣಗೊಂಡಿದೆ. ಯಾವುದೇ ವಂಚನೆ ಕಂಡುಬಂದಿಲ್ಲ. ಉಲ್ಲೇಖ {case_id}."
            else:
                script = f"Your investigation is complete. No confirmed fraud was identified. Your case reference is {case_id}."
        elif st_upper in ["FAILED", "ERROR"]:
            if lang == "hi":
                script = f"स्वचालित जांच पूरी नहीं हो सकी। आपका केस समीक्षा के लिए भेजा गया है। संदर्भ {case_id}।"
            else:
                script = f"We could not complete the investigation automatically. Your case has been sent for review. Reference is {case_id}."
        elif st_upper in ["UNDER_REVIEW", "VERIFICATION"]:
            if lang == "hi":
                script = f"आपकी शिकायत की समीक्षा की गई है। केस को आगे सत्यापन के लिए भेजा गया है। संदर्भ {case_id}।"
            else:
                script = f"Your complaint has been reviewed and requires further verification. Your case reference is {case_id}."
        else:
            # Suspicious / Fraud identified / Escalated default
            if lang == "hi":
                script = f"जांच पूरी हो गई है। संदिग्ध गतिविधि पाई गई और केस समीक्षा के लिए आगे भेजा गया है। संदर्भ {case_id}।"
            elif lang == "ta":
                script = f"விசாரணை முடிந்தது. சந்தேகத்திற்கிடமான பரிவர்த்தனை அடையாளம் காணப்பட்டது. குறிப்பு {case_id}."
            elif lang == "kn":
                script = f"ತನಿಖೆ ಪೂರ್ಣಗೊಂಡಿದೆ. ಶಂಕಾಸ್ಪದ ವಹಿವಾಟು ಪತ್ತೆಯಾಗಿದೆ. ಉಲ್ಲೇಖ {case_id}."
            else:
                script = f"Your investigation is complete. Suspicious activity was identified and your case has been escalated. Reference is {case_id}."
    else:
        script = f"Update for case reference {case_id}."

    # Free-tier safety truncation: keep strictly <= 200 characters
    return script[:200].strip()


async def generate_voice_response(
    case_id: str,
    event_type: str,
    language: str = "en",
    text_override: Optional[str] = None,
    amount: Optional[float] = None,
    status: Optional[str] = None,
    scam_type: Optional[str] = None,
    is_fraud: bool = True
) -> Dict[str, Any]:
    """
    Idempotently generates or serves cached voice response for a case milestone.
    Returns:
    {
        "available": bool,
        "event": str,
        "audio_url": str | None,
        "text": str,
        "cached": bool,
        "reason": str (if not available)
    }
    """
    cache_path = _get_cache_filepath(case_id, event_type)
    audio_url = _get_audio_url(case_id, event_type)

    script_text = text_override or build_voice_script(
        event_type=event_type,
        case_id=case_id,
        language=language,
        amount=amount,
        status=status,
        scam_type=scam_type,
        is_fraud=is_fraud
    )

    # 1. Check idempotency / disk cache
    if os.path.isfile(cache_path) and os.path.getsize(cache_path) > 0:
        logger.info(f"[TTS] Cache hit for {case_id} / {event_type}")
        return {
            "available": True,
            "event": event_type,
            "case_id": case_id,
            "audio_url": audio_url,
            "text": script_text,
            "cached": True
        }

    # 2. Check API key configuration
    api_key = os.environ.get("SARVAM_API_KEY", "").strip()
    if not api_key:
        logger.warning(f"[TTS] SARVAM_API_KEY not set. Voice response unavailable for {case_id}")
        return {
            "available": False,
            "event": event_type,
            "case_id": case_id,
            "audio_url": None,
            "text": script_text,
            "cached": False,
            "reason": "api_key_missing"
        }

    # 3. Call Sarvam Bulbul v3 TTS
    target_lang = SARVAM_LANG_MAP.get(language, "en-IN")
    logger.info(f"[TTS] Generating {event_type} voice response for {case_id} in {target_lang}")

    try:
        async with httpx.AsyncClient(timeout=14.0) as client:
            headers = {
                "api-subscription-key": api_key,
                "Content-Type": "application/json"
            }
            payload = {
                "inputs": [script_text],
                "target_language_code": target_lang,
                "speaker": DEFAULT_SPEAKER,
                "pitch": 0,
                "pace": 1.0,
                "loudness": 1.5,
                "speech_sample_rate": 16000,
                "enable_preprocessing": True,
                "model": SARVAM_TTS_MODEL
            }

            resp = await client.post(SARVAM_TTS_URL, json=payload, headers=headers)

            if resp.status_code == 200:
                res_data = resp.json()
                audios = res_data.get("audios", [])
                if audios and len(audios[0]) > 0:
                    audio_bytes = base64.b64decode(audios[0])
                    # Write to stable cache file
                    with open(cache_path, "wb") as f:
                        f.write(audio_bytes)

                    logger.info(f"[TTS] Generated successfully for {case_id} ({len(audio_bytes)} bytes)")
                    return {
                        "available": True,
                        "event": event_type,
                        "case_id": case_id,
                        "audio_url": audio_url,
                        "text": script_text,
                        "cached": False
                    }
                else:
                    logger.warning(f"[TTS] Sarvam returned empty audios array for {case_id}")
                    return {
                        "available": False,
                        "event": event_type,
                        "case_id": case_id,
                        "audio_url": None,
                        "text": script_text,
                        "cached": False,
                        "reason": "empty_audio_response"
                    }
            elif resp.status_code == 429:
                logger.warning(f"[TTS] Quota/rate limit encountered for {case_id}: HTTP 429")
                return {
                    "available": False,
                    "event": event_type,
                    "case_id": case_id,
                    "audio_url": None,
                    "text": script_text,
                    "cached": False,
                    "reason": "rate_limit_or_quota_exceeded"
                }
            else:
                logger.warning(f"[TTS] Failed with HTTP {resp.status_code} for {case_id}: {resp.text[:120]}")
                return {
                    "available": False,
                    "event": event_type,
                    "case_id": case_id,
                    "audio_url": None,
                    "text": script_text,
                    "cached": False,
                    "reason": f"http_{resp.status_code}"
                }

    except httpx.TimeoutException:
        logger.warning(f"[TTS] Timeout contacting Sarvam for {case_id}")
        return {
            "available": False,
            "event": event_type,
            "case_id": case_id,
            "audio_url": None,
            "text": script_text,
            "cached": False,
            "reason": "timeout"
        }
    except Exception as e:
        logger.error(f"[TTS] Failed, continuing with text fallback for {case_id}: {e}")
        return {
            "available": False,
            "event": event_type,
            "case_id": case_id,
            "audio_url": None,
            "text": script_text,
            "cached": False,
            "reason": "exception"
        }

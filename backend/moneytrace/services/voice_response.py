"""
MoneyTrace Voice Response Service via Sarvam AI TTS (Bulbul v3).

Features:
- Context-Aware, Empathetic Spoken Voice Scripts for financial fraud victims:
  * Empathetic acknowledgement on report intake (complaint_received):
    Reassuring, calm, professional tone; confirms case reference and incorporates
    the extracted transaction amount ONLY if sourced from the voice transcript.
  * Meaningful spoken resolution upon investigation completion (investigation_completed):
    Dynamic, human-facing response reflecting real investigation outcome (fraud escalated,
    no confirmed fraud, verification needed, or manual review required) without exposing internal AI telemetry.
- Natural Voice Delivery via Sarvam Bulbul v3 with 'priya' speaker (warm, reassuring pace).
- Robust Amount Extraction with provenance tracking (voice_transcript vs request vs none).
- Free-Tier & Quota Safety:
  * Strict character length target (~1-3 natural sentences, <= 250 characters).
  * Disk-based idempotency caching based on (case_id, event_type).
  * Graceful fallback on 429 quota exhaustion, 500 server error, timeouts, or unconfigured keys.
  * Never crashes the incident intake or investigation pipeline.
"""

import os
import re
import base64
import logging
import httpx
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger("moneytrace.tts")

SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY", "").strip()
SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"
SARVAM_TTS_MODEL = os.environ.get("SARVAM_TTS_MODEL", "bulbul:v3").strip() or "bulbul:v3"

# Supported Sarvam language codes
SARVAM_LANG_MAP = {
    "en": "en-IN",
    "hi": "hi-IN",
    "ta": "ta-IN",
    "kn": "kn-IN"
}

DEFAULT_SPEAKER = "priya"  # Calm, natural, verified Bulbul v3 speaker

# Directory for storing and caching generated audio files
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AUDIO_CACHE_DIR = os.path.join(BASE_DIR, "static", "uploads", "voice_cache")
os.makedirs(AUDIO_CACHE_DIR, exist_ok=True)

# Word-to-number mapping for conversational Indian financial statements
WORD_NUMS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90
}
SCALES = {
    "hundred": 100,
    "thousand": 1000,
    "k": 1000,
    "lakh": 100000,
    "lac": 100000,
    "crore": 10000000
}


def parse_words_number(text: str) -> Optional[float]:
    """
    Parses verbal number sequences like 'eighteen thousand five hundred',
    'three thousand six hundred', 'one lakh twenty five thousand', 'one crore' into numeric float.
    Uses hierarchical number composition:
      - small scale: hundred (multiplies current)
      - large scale: thousand, lakh, crore (multiplies current and accumulates into total)
    """
    tokens = [t.lower() for t in re.findall(r'[a-zA-Z]+', text)]
    total = 0
    current = 0
    has_number = False

    for t in tokens:
        if t in WORD_NUMS:
            current += WORD_NUMS[t]
            has_number = True
        elif t == "hundred":
            if current == 0:
                current = 1
            current *= 100
            has_number = True
        elif t in SCALES:
            scale = SCALES[t]
            if current == 0:
                current = 1
            total += current * scale
            current = 0
            has_number = True
        elif t == "and":
            continue

    total += current
    return float(total) if has_number and total > 0 else None


def extract_amount_from_transcript(transcript: Optional[str]) -> Dict[str, Any]:
    """
    Extracts transaction amount directly and exclusively from the spoken victim narrative.
    Returns:
    {
        "amount": float or None,
        "currency": "INR",
        "amount_source": "voice_transcript" | "none",
        "amount_source_text": str or None
    }
    """
    if not transcript or not transcript.strip():
        return {"amount": None, "currency": "INR", "amount_source": "none", "amount_source_text": None}

    text = transcript.strip()

    # 1. Decimal with multiplier: e.g. 18.5k, 18.5 thousand, 1.5 lakh
    m_dec = re.search(r'(?:(?:₹|rs\.?|inr)\s*)?(\d+(?:\.\d+)?)\s*(k|thousand|lakh|lac|crore)\b', text, re.IGNORECASE)
    if m_dec:
        val = float(m_dec.group(1))
        mult = m_dec.group(2).lower()
        if mult in ["k", "thousand"]:
            val *= 1000
        elif mult in ["lakh", "lac"]:
            val *= 100000
        elif mult in ["crore"]:
            val *= 10000000
        return {
            "amount": float(val),
            "currency": "INR",
            "amount_source": "voice_transcript",
            "amount_source_text": m_dec.group(0).strip()
        }

    # 2. Words like 'three thousand six hundred', 'eighteen thousand five hundred', 'one crore'
    words_seq = r'\b((?:(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|lakh|lac|crore|and)\s*){1,})(?:rupees|rs\.?|inr)?\b'
    m_words = re.search(words_seq, text, re.IGNORECASE)
    if m_words:
        val = parse_words_number(m_words.group(1))
        if val and val >= 50:
            return {
                "amount": val,
                "currency": "INR",
                "amount_source": "voice_transcript",
                "amount_source_text": m_words.group(0).strip()
            }

    # 3. Currency prefix: ₹18,500, Rs. 18500, INR 18,500, Rs 3600
    m_cur = re.search(r'(?:₹|rs\.?|inr)\s*(\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)', text, re.IGNORECASE)
    if m_cur:
        val = float(m_cur.group(1).replace(',', ''))
        if val >= 50:
            return {
                "amount": val,
                "currency": "INR",
                "amount_source": "voice_transcript",
                "amount_source_text": m_cur.group(0).strip()
            }

    # 4. Suffix currency: 18,500 rupees, 18500 inr, 3600 rupees, 7250 rs
    m_suff = re.search(r'(\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(?:rupees|rs\.?|inr|bucks)', text, re.IGNORECASE)
    if m_suff:
        val = float(m_suff.group(1).replace(',', ''))
        if val >= 50:
            return {
                "amount": val,
                "currency": "INR",
                "amount_source": "voice_transcript",
                "amount_source_text": m_suff.group(0).strip()
            }

    # 5. Standalone numbers near transaction verbs (transferred 18500, lost 7250, scammed for 3600)
    m_num = re.search(r'(?:transferred|transfer|sent|paid|debited|lost|scammed|sending|requested|demanded|deposited)\s*(?:for\s*|of\s*)?(?:₹|rs\.?|inr)?\s*(\d{1,3}(?:,\d{2,3})+(?:\.\d+)?|\d+(?:\.\d+)?)', text, re.IGNORECASE)
    if m_num:
        val = float(m_num.group(1).replace(',', ''))
        if val >= 50:
            return {
                "amount": val,
                "currency": "INR",
                "amount_source": "voice_transcript",
                "amount_source_text": m_num.group(0).strip()
            }

    # 6. Fallback standalone 4+ digits
    m_any = re.search(r'\b([1-9]\d{2,6}(?:,\d{2,3})*)\b', text)
    if m_any:
        val = float(m_any.group(1).replace(',', ''))
        if val >= 100:
            return {
                "amount": val,
                "currency": "INR",
                "amount_source": "voice_transcript",
                "amount_source_text": m_any.group(0).strip()
            }

    return {"amount": None, "currency": "INR", "amount_source": "none", "amount_source_text": None}


def resolve_amount_with_provenance(
    narrative: str,
    request_amount: Optional[float] = None
) -> Dict[str, Any]:
    """
    Evaluates amount lineage:
    - If narrative contains a spoken amount, it becomes canonical (source='voice_transcript').
    - If request_amount was provided independently and differs, logs discrepancy (amount_conflict=True).
    - If no amount in narrative, uses request_amount (source='request_payload') or None.
    """
    extracted = extract_amount_from_transcript(narrative)

    if extracted["amount"] is not None:
        conflict = False
        if request_amount is not None and request_amount > 0 and abs(request_amount - extracted["amount"]) > 1.0:
            conflict = True
            logger.info(
                f"[AMOUNT LINEAGE] Conflict detected: voice_amount={extracted['amount']} vs request_amount={request_amount}. "
                f"Preferring canonical voice_transcript."
            )
        return {
            "amount": extracted["amount"],
            "currency": "INR",
            "amount_source": "voice_transcript",
            "amount_source_text": extracted["amount_source_text"],
            "amount_conflict": conflict
        }

    # Fallback to request payload if explicitly given
    if request_amount is not None and request_amount > 0:
        return {
            "amount": request_amount,
            "currency": "INR",
            "amount_source": "request_payload",
            "amount_source_text": None,
            "amount_conflict": False
        }

    return {
        "amount": None,
        "currency": "INR",
        "amount_source": "unknown",
        "amount_source_text": None,
        "amount_conflict": False
    }


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
    amount_source: str = "none",
    status: Optional[str] = None,
    scam_type: Optional[str] = None,
    complaint_narrative: Optional[str] = None,
    investigation_result: Optional[Dict[str, Any]] = None
) -> str:
    """
    Constructs a warm, empathetic, conversational voice script (~1-3 natural sentences, <= 250 chars).
    - Uses amount ONLY if genuinely extracted from the voice transcript (amount_source == 'voice_transcript').
    - Grounds resolution in the real investigation outcome without exposing raw technical telemetry.
    """
    lang = language.lower() if language else "en"
    if lang not in SARVAM_LANG_MAP:
        lang = "en"

    # Only verbalize amount if it came legitimately from the voice complaint
    include_amount = (amount_source == "voice_transcript" and amount is not None and amount > 0)
    amt_formatted = f"₹{int(amount):,}" if amount else ""

    if event_type == "complaint_received":
        if lang == "hi":
            if include_amount:
                script = (
                    f"चिंता मत कीजिए, हमने आपका मामला समझ लिया है। {int(amount):,} रुपये के इस संदिग्ध लेनदेन की "
                    f"जाँच शुरू कर दी गई है। आपका केस संदर्भ {case_id} है।"
                )
            else:
                script = (
                    f"चिंता मत कीजिए, हमने आपकी शिकायत समझ ली है और तुरंत जाँच शुरू कर दी है। "
                    f"हम पूरी सहायता करेंगे। आपका केस संदर्भ {case_id} है।"
                )
        elif lang == "ta":
            if include_amount:
                script = (
                    f"கவலைப்பட வேண்டாம், உங்கள் புகாரைப் புரிந்துகொண்டோம். {int(amount):,} ரூபாய் பரிவர்த்தனை குறித்த விசாரணை "
                    f"தொடங்கப்பட்டுள்ளது. உங்கள் குறிப்பு எண் {case_id}."
                )
            else:
                script = (
                    f"கவலைப்பட வேண்டாம், உங்கள் புகாரைப் பதிவு செய்து விசாரணையைத் தொடங்கிவிட்டோம். "
                    f"உங்கள் குறிப்பு எண் {case_id}."
                )
        elif lang == "kn":
            if include_amount:
                script = (
                    f"ಚಿಂತಿಸಬೇಡಿ, ನಿಮ್ಮ ದೂರನ್ನು ಸ್ವೀಕರಿಸಿದ್ದೇವೆ. {int(amount):,} ರೂಪಾಯಿ ವಹಿವಾಟಿನ ತನಿಖೆ "
                    f"ಪ್ರಾರಂಭವಾಗಿದೆ. ನಿಮ್ಮ ಉಲ್ಲೇಖ ಸಂಖ್ಯೆ {case_id}."
                )
            else:
                script = (
                    f"ಚಿಂತಿಸಬೇಡಿ, ನಿಮ್ಮ ದೂರನ್ನು ಸ್ವೀಕರಿಸಿದ್ದೇವೆ ಮತ್ತು ತಕ್ಷಣವೇ ತನಿಖೆಯನ್ನು ಆರಂಭಿಸಿದ್ದೇವೆ. "
                    f"ನಿಮ್ಮ ಉಲ್ಲೇಖ ಸಂಖ್ಯೆ {case_id}."
                )
        else:
            # English (Empathetic, reassuring, professional)
            if include_amount:
                script = (
                    f"I understand this is concerning, and I'm here to help. We've received your complaint "
                    f"about the {amt_formatted} transaction and started looking into it right away. Your case reference is {case_id}."
                )
            else:
                script = (
                    f"I understand this is concerning, and I'm here to help. We've received your complaint "
                    f"and started looking into what happened right away. Your case reference is {case_id}."
                )

    elif event_type == "investigation_completed":
        st_upper = (status or "").upper()

        if st_upper in ["RESOLVED", "LEGITIMATE", "NO_FRAUD"]:
            if lang == "hi":
                script = (
                    f"हमने जाँच पूरी कर ली है। उपलब्ध जानकारी के अनुसार कोई धोखाधड़ी नहीं पाई गई है। "
                    f"आगे की सुरक्षा के लिए आपका केस संदर्भ {case_id} सुरक्षित रखा गया है।"
                )
            elif lang == "ta":
                script = (
                    f"நாங்கள் விசாரணையை முடித்துவிட்டோம். மோசடி எதுவும் கண்டறியப்படவில்லை. "
                    f"உங்கள் கேஸ் எண் {case_id}."
                )
            else:
                script = (
                    f"We've completed our investigation. We couldn't confirm fraudulent activity from the information available, "
                    f"but we've recorded your complaint under reference {case_id} for review."
                )

        elif st_upper in ["FAILED", "ERROR"]:
            if lang == "hi":
                script = (
                    f"स्वचालित जाँच पूरी नहीं हो सकी, लेकिन आपकी शिकायत सुरक्षित है। "
                    f"केस संदर्भ {case_id} को आगे मानव समीक्षा के लिए भेज दिया गया है।"
                )
            else:
                script = (
                    f"I wasn't able to complete the investigation automatically. Don't worry, your complaint is safe "
                    f"and has been escalated to our team under reference {case_id}."
                )

        elif st_upper in ["UNDER_REVIEW", "VERIFICATION", "OPERATOR_REVIEW"]:
            if lang == "hi":
                script = (
                    f"हमने आपकी रिपोर्ट की जाँच की है। अतिरिक्त पुष्टि के लिए आपका केस "
                    f"वरिष्ठ सुरक्षा टीम को भेज दिया गया है। केस संदर्भ {case_id} है।"
                )
            else:
                script = (
                    f"We've reviewed the information available, and your case needs additional verification. "
                    f"I've sent reference {case_id} to our review team so they can look into it further."
                )

        else:
            # Default: Suspicious / Fraud identified / Escalated
            scam_mention = f" linked to a suspected {scam_type.lower()}" if scam_type and scam_type.lower() != "payment fraud" else ""
            if lang == "hi":
                script = (
                    f"जाँच पूरी हो गई है। संदिग्ध गतिविधि की पहचान की गई है और त्वरित सुरक्षा कार्रवाई के लिए "
                    f"केस को आगे बढ़ा दिया गया है। आपका संदर्भ {case_id} है।"
                )
            elif lang == "ta":
                script = (
                    f"விசாரணை முடிந்தது. சந்தேகத்திற்கிடமான மோசடி அடையாளம் காணப்பட்டு அவசர நடவடிக்கைக்கு "
                    f"அனுப்பப்பட்டுள்ளது. குறிப்பு {case_id}."
                )
            elif lang == "kn":
                script = (
                    f"ತನಿಖೆ ಪೂರ್ಣಗೊಂಡಿದೆ. ಶಂಕಾಸ್ಪದ ವಹಿವಾಟು ಪತ್ತೆಯಾಗಿದ್ದು, ತುರ್ತು ಪರಿಶೀಲನೆಗಾಗಿ "
                    f"ಮುಂದಕ್ಕೆ ಕಳುಹಿಸಲಾಗಿದೆ. ಉಲ್ಲೇಖ {case_id}."
                )
            else:
                script = (
                    f"We've completed our investigation. We found suspicious activity{scam_mention}, "
                    f"and we've escalated your case for urgent protection. Your reference is {case_id}."
                )
    else:
        script = f"Here is an update regarding case reference {case_id}. Our team is monitoring your complaint."

    # Keep strictly <= 250 characters for crisp audio and free-tier safety
    return script[:250].strip()


async def generate_voice_response(
    case_id: str,
    event_type: str,
    language: str = "en",
    text_override: Optional[str] = None,
    amount: Optional[float] = None,
    amount_source: str = "none",
    status: Optional[str] = None,
    scam_type: Optional[str] = None,
    complaint_narrative: Optional[str] = None,
    investigation_result: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Idempotently generates or serves cached voice response for a case milestone.
    Returns:
    {
        "available": bool,
        "event": str,
        "case_id": str,
        "audio_url": str | None,
        "text": str,
        "cached": bool,
        "amount_verbalized": bool,
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
        amount_source=amount_source,
        status=status,
        scam_type=scam_type,
        complaint_narrative=complaint_narrative,
        investigation_result=investigation_result
    )

    amount_verbalized = (amount_source == "voice_transcript" and amount is not None and amount > 0)

    # 1. Check idempotency / disk cache
    if os.path.isfile(cache_path) and os.path.getsize(cache_path) > 0:
        logger.info(f"[TTS] Cache hit for {case_id} / {event_type}")
        return {
            "available": True,
            "event": event_type,
            "case_id": case_id,
            "audio_url": audio_url,
            "text": script_text,
            "cached": True,
            "amount_verbalized": amount_verbalized
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
            "amount_verbalized": amount_verbalized,
            "reason": "api_key_missing"
        }

    # 3. Call Sarvam Bulbul v3 TTS
    target_lang = SARVAM_LANG_MAP.get(language, "en-IN")
    logger.info(f"[TTS] Generating natural {event_type} voice response for {case_id} in {target_lang}")

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
                        "cached": False,
                        "amount_verbalized": amount_verbalized
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
                        "amount_verbalized": amount_verbalized,
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
                    "amount_verbalized": amount_verbalized,
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
                    "amount_verbalized": amount_verbalized,
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
            "amount_verbalized": amount_verbalized,
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
            "amount_verbalized": amount_verbalized,
            "reason": "exception"
        }

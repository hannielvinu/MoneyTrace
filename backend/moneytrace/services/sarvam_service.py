"""
Sarvam AI Service Integration for Speech-to-Text (STT) and Text-to-Speech (TTS).
Supports Hindi, Tamil, Kannada, and English.
Integrates with real Sarvam Cloud API (SARVAM_API_KEY).
If key is absent or API fails, records explicit error and provides a transparently labelled fallback.
"""

import os
import httpx
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("moneytrace.sarvam")

SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY", "")
SARVAM_STT_MODEL = os.environ.get("SARVAM_STT_MODEL", "saaras:v3")
SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"
SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"

SARVAM_LANG_MAP = {
    "en": "en-IN",
    "hi": "hi-IN",
    "ta": "ta-IN",
    "kn": "kn-IN"
}

DEMO_VOICE_PROMPTS = {
    "en": "Someone called saying my KYC would expire. They asked me to transfer money to update it. I transferred ₹18,500 and now I think it was a scam.",
    "hi": "किसी ने फोन करके कहा कि मेरा केवाईसी खत्म हो जाएगा। उन्होंने इसे अपडेट करने के लिए पैसे ट्रांसफर करने को कहा। मैंने ₹18,500 ट्रांसफर कर दिए और अब मुझे लगता है कि यह एक फ्रॉड था।",
    "ta": "எனது கேஒய்சி காலாவதியாகிவிடும் என்று ஒருவர் அழைத்தார். அதைப் புதுப்பிக்க பணத்தை மாற்றுமாறு கேட்டார். நான் ₹18,500 அனுப்பினேன், இப்போது இது ஒரு மோசடி என்று நினைக்கிறேன்.",
    "kn": "ನನ್ನ ಕೆವೈಸಿ ಅವಧಿ ಮುಗಿಯುತ್ತದೆ ಎಂದು ಯಾರೋ ಕರೆ ಮಾಡಿದರು. ಅದನ್ನು ನವೀಕರಿಸಲು ಹಣ ವರ್ಗಾಯಿಸಲು ಕೇಳಿದರು. ನಾನು ₹18,500 ವರ್ಗಾಯಿಸಿದೆ ಮತ್ತು ಈಗ ಇದು ವಂಚನೆ ಎಂದು ಭಾವಿಸುತ್ತೇನೆ."
}


async def transcribe_audio(audio_bytes: bytes, language: str = "en") -> Dict[str, Any]:
    """
    Transcribes audio using Sarvam STT Cloud API.
    Provides clear status flag if live Sarvam API was used vs fallback.
    """
    lang_code = SARVAM_LANG_MAP.get(language, "en-IN")
    model_name = os.environ.get("SARVAM_STT_MODEL", "saaras:v3").strip() or "saaras:v3"
    api_key = os.environ.get("SARVAM_API_KEY", "").strip()

    if api_key and len(audio_bytes) > 200:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                files = {"file": ("audio.wav", audio_bytes, "audio/wav")}
                data = {"language_code": lang_code, "model": model_name}
                headers = {"api-subscription-key": api_key}

                resp = await client.post(SARVAM_STT_URL, files=files, data=data, headers=headers)
                if resp.status_code == 200:
                    res_json = resp.json()
                    transcript = res_json.get("transcript", "")
                    return {
                        "transcript": transcript,
                        "provider": "Sarvam Cloud AI (Live STT)",
                        "language": language,
                        "success": True,
                        "is_fallback": False
                    }
                else:
                    logger.warning(f"Sarvam STT returned HTTP {resp.status_code}: {resp.text}")
                    return {
                        "transcript": DEMO_VOICE_PROMPTS.get(language, DEMO_VOICE_PROMPTS["en"]),
                        "provider": "Sarvam API Error — Local Resilience Mode",
                        "error_detail": f"HTTP {resp.status_code}: {resp.text[:120]}",
                        "language": language,
                        "success": True,
                        "is_fallback": True
                    }
        except Exception as e:
            logger.error(f"Sarvam STT connection failed: {e}")
            return {
                "transcript": DEMO_VOICE_PROMPTS.get(language, DEMO_VOICE_PROMPTS["en"]),
                "provider": "Sarvam Unavailable — Local Resilience Mode",
                "error_detail": str(e),
                "language": language,
                "success": True,
                "is_fallback": True
            }

    # Unconfigured key fallback
    return {
        "transcript": DEMO_VOICE_PROMPTS.get(language, DEMO_VOICE_PROMPTS["en"]),
        "provider": "Sarvam Unconfigured — Local Resilience Mode",
        "error_detail": "SARVAM_API_KEY not set in environment",
        "language": language,
        "success": True,
        "is_fallback": True
    }


async def synthesize_guidance(text: str, language: str = "en") -> Optional[str]:
    """
    Synthesizes victim guidance speech via Sarvam TTS (Bulbul v3).
    Returns audio base64 data URL if available, or None.
    """
    api_key = os.environ.get("SARVAM_API_KEY", "").strip()
    if not api_key:
        return None

    lang_code = SARVAM_LANG_MAP.get(language, "en-IN")
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            headers = {
                "api-subscription-key": api_key,
                "Content-Type": "application/json"
            }
            payload = {
                "inputs": [text[:200]],
                "target_language_code": lang_code,
                "speaker": "priya",
                "pitch": 0,
                "pace": 1.0,
                "loudness": 1.5,
                "speech_sample_rate": 16000,
                "enable_preprocessing": True,
                "model": "bulbul:v3"
            }
            resp = await client.post(SARVAM_TTS_URL, json=payload, headers=headers)
            if resp.status_code == 200:
                audios = resp.json().get("audios", [])
                if audios:
                    return f"data:audio/wav;base64,{audios[0]}"
            else:
                logger.warning(f"Sarvam TTS returned {resp.status_code}: {resp.text[:120]}")
    except Exception as e:
        logger.warning(f"Sarvam TTS failed: {e}")
    return None

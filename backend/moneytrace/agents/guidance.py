"""
Guidance agent support: retrieval-grounded victim guidance with citations and a
self-reflection grounding check.

Flow (driven by the coordinator):
 1. The guidance agent (LlmAgent with the search_advisories tool) drafts steps,
    each citing chunk_ids it retrieved.
 2. check_grounding() asks a judge model, for every step, whether the cited
    chunk text supports it. Unsupported steps are dropped; if any were dropped the
    draft is regenerated ONCE with feedback; anything still unsupported is removed.
 3. If no supported step remains, a safe fallback is returned instead of guessing.
 4. The official reporting channels (1930, cybercrime.gov.in, the victim's bank)
    are always included, cited to a retrieved chunk that states them when one exists.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from moneytrace.telemetry import agent_span

logger = logging.getLogger("moneytrace.agents.guidance")

SAFE_FALLBACK = {
    "en": "Report immediately on the 1930 cyber-fraud helpline or at cybercrime.gov.in, and contact your bank's official helpline to block the account or card.",
    "hi": "तुरंत 1930 साइबर फ्रॉड हेल्पलाइन पर या cybercrime.gov.in पर शिकायत करें, और खाता/कार्ड ब्लॉक करने के लिए अपने बैंक की आधिकारिक हेल्पलाइन से संपर्क करें।",
    "ta": "உடனடியாக 1930 சைபர் மோசடி உதவி எண்ணிலோ cybercrime.gov.in தளத்திலோ புகார் செய்யுங்கள்; கணக்கு/கார்டை முடக்க உங்கள் வங்கியின் அதிகாரப்பூர்வ உதவி எண்ணைத் தொடர்பு கொள்ளுங்கள்.",
    "kn": "ತಕ್ಷಣ 1930 ಸೈಬರ್ ವಂಚನೆ ಸಹಾಯವಾಣಿ ಅಥವಾ cybercrime.gov.in ನಲ್ಲಿ ದೂರು ನೀಡಿ, ಮತ್ತು ಖಾತೆ/ಕಾರ್ಡ್ ನಿರ್ಬಂಧಿಸಲು ನಿಮ್ಮ ಬ್ಯಾಂಕಿನ ಅಧಿಕೃತ ಸಹಾಯವಾಣಿಯನ್ನು ಸಂಪರ್ಕಿಸಿ.",
}
LANG_NAMES = {"en": "English", "hi": "Hindi", "ta": "Tamil", "kn": "Kannada"}
CHANNELS_QUERY = "report cyber financial fraud helpline 1930 cybercrime.gov.in inform bank immediately"

GUIDANCE_INSTRUCTION = """You are the Guidance agent of MoneyTrace, a help desk for UPI / digital-payment fraud victims in India.

Write calm, practical, step-by-step guidance for the victim, using ONLY facts found in official advisories.

Procedure:
1. Read the case in the session state key `case_record` (fraud type, amount, channel, language).
2. Call `search_advisories` with 1-3 focused English queries (e.g. "<fraud type> what to do", "report unauthorised UPI transaction to bank zero liability", "1930 helpline cybercrime.gov.in").
3. Write 4-7 short steps. EVERY step must cite the chunk_id(s) of the passage(s) that support it. Do not add any step
   that no retrieved passage supports. Do not invent phone numbers, websites, deadlines or amounts.
4. Always include a step on reporting through official channels (1930 helpline, cybercrime.gov.in, the bank) if a
   retrieved passage mentions them.
5. Write the step text in {language_name}. Keep chunk_ids exactly as returned.

Reply with ONLY this JSON (no prose): {{"steps": [{{"text": "...", "citations": ["<chunk_id>"]}}]}}"""

JUDGE_PROMPT = """You are a strict fact-checker for victim guidance. For each STEP, decide whether the CITED PASSAGES
explicitly support everything the step says (actions, numbers, websites, deadlines). Paraphrase and translation are fine;
any claim not stated in the cited passages makes the step unsupported. A step with no citations is unsupported.

{items}

Reply with ONLY JSON: {{"verdicts": [{{"step": 1, "supported": true, "reason": "..."}}]}}"""


def parse_steps(raw: Any) -> List[Dict[str, Any]]:
    """Accept the agent's output in any of: dict, JSON string, fenced JSON."""
    if isinstance(raw, dict):
        data = raw
    else:
        txt = str(raw or "")
        m = re.search(r"\{.*\}", txt, re.S)
        if not m:
            return []
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return []
    steps = []
    for s in data.get("steps", []) if isinstance(data, dict) else []:
        if isinstance(s, dict) and str(s.get("text", "")).strip():
            cites = s.get("citations") or []
            if isinstance(cites, str):
                cites = [cites]
            steps.append({"text": str(s["text"]).strip(), "citations": [str(c).strip() for c in cites if str(c).strip()]})
    return steps


def load_chunks(chunk_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    from sqlalchemy import text as sql
    from moneytrace.db.database import get_engine
    ids = sorted(set(chunk_ids))
    if not ids:
        return {}
    out = {}
    with get_engine().connect() as conn:
        for cid in ids:
            r = conn.execute(sql("SELECT id, doc_id, title, issuer, url, section, text FROM advisory_chunks WHERE id = :i"),
                             {"i": cid}).first()
            if r:
                out[cid] = {"chunk_id": r[0], "doc_id": r[1], "title": r[2], "issuer": r[3], "url": r[4],
                            "section": r[5], "text": r[6]}
    return out


def judge_steps(steps: List[Dict[str, Any]], chunks: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One judge call for all steps. Returns per-step {'supported': bool, 'reason': str}."""
    from moneytrace.llm import generate_json
    items = []
    for i, s in enumerate(steps, 1):
        cited = [chunks[c] for c in s["citations"] if c in chunks]
        passages = "\n".join(f"  [{c['chunk_id']}] {c['text'][:1500]}" for c in cited) or "  (none)"
        items.append(f"STEP {i}: {s['text']}\nCITED PASSAGES:\n{passages}")
    verdicts: Dict[int, Dict] = {}
    try:
        res = generate_json(JUDGE_PROMPT.format(items="\n\n".join(items)), tier="judge", agent="grounding_checker",
                            max_tokens=12000)
        verdicts = {int(v.get("step")): v for v in res.get("verdicts", [])}
    except Exception as e:
        logger.warning(f"batched grounding judge failed ({type(e).__name__}: {str(e)[:120]}); judging steps one by one")
    for i, item in enumerate(items, 1):
        if i in verdicts:
            continue
        try:
            one = generate_json(JUDGE_PROMPT.format(items=item.replace(f"STEP {i}:", "STEP 1:", 1)), tier="judge",
                                agent="grounding_checker", max_tokens=6000)
            v = (one.get("verdicts") or [{}])[0]
            verdicts[i] = {"supported": bool(v.get("supported")), "reason": v.get("reason", "")}
        except Exception as e:
            logger.warning(f"grounding judge failed on step {i}: {type(e).__name__}")
    out = []
    for i, s in enumerate(steps, 1):
        v = verdicts.get(i) or {"supported": False, "reason": "judge unavailable"}
        has_valid_cite = any(c in chunks for c in s["citations"])
        out.append({"supported": bool(v.get("supported")) and has_valid_cite,
                    "reason": v.get("reason", "") if has_valid_cite else "no valid citation"})
    return out


def channels_step(language: str) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Find a retrieved passage that states the official channels; return (step, chunk) or (None, None)."""
    from rag.retriever import retrieve
    try:
        cites = retrieve(CHANNELS_QUERY, k=5)
    except Exception as e:
        logger.warning(f"channel retrieval failed: {e}")
        return None, None
    for c in cites:
        low = c.text.lower()
        facts = [f for f in ("1930", "cybercrime.gov.in", "bank") if f in low]
        if "1930" in facts or "cybercrime.gov.in" in facts:
            return {"text": channels_text(facts, language), "citations": [c.chunk_id], "kind": "official_channels"}, c.short()
    return None, None


_CHANNEL_PARTS = {
    "en": {"1930": "call the national cyber crime helpline 1930", "cybercrime.gov.in": "file a complaint at cybercrime.gov.in",
           "bank": "inform your bank", "lead": "Report the fraud immediately: ", "join": " / "},
    "hi": {"1930": "राष्ट्रीय साइबर क्राइम हेल्पलाइन 1930 पर कॉल करें", "cybercrime.gov.in": "cybercrime.gov.in पर शिकायत दर्ज करें",
           "bank": "अपने बैंक को सूचित करें", "lead": "धोखाधड़ी की तुरंत रिपोर्ट करें: ", "join": " / "},
    "ta": {"1930": "தேசிய சைபர் குற்ற உதவி எண் 1930-ஐ அழைக்கவும்", "cybercrime.gov.in": "cybercrime.gov.in-இல் புகார் செய்யவும்",
           "bank": "உங்கள் வங்கிக்குத் தெரிவிக்கவும்", "lead": "மோசடியை உடனே புகார் செய்யுங்கள்: ", "join": " / "},
    "kn": {"1930": "ರಾಷ್ಟ್ರೀಯ ಸೈಬರ್ ಅಪರಾಧ ಸಹಾಯವಾಣಿ 1930ಕ್ಕೆ ಕರೆ ಮಾಡಿ", "cybercrime.gov.in": "cybercrime.gov.in ನಲ್ಲಿ ದೂರು ನೀಡಿ",
           "bank": "ನಿಮ್ಮ ಬ್ಯಾಂಕಿಗೆ ತಿಳಿಸಿ", "lead": "ವಂಚನೆಯನ್ನು ತಕ್ಷಣ ವರದಿ ಮಾಡಿ: ", "join": " / "},
}


def channels_text(facts, language: str) -> str:
    """Official-channels step built only from the facts present in the supporting passage."""
    parts = _CHANNEL_PARTS.get(language, _CHANNEL_PARTS["en"])
    return parts["lead"] + parts["join"].join(parts[f] for f in facts) + "."


def finalize_guidance(draft_steps: List[Dict[str, Any]], language: str,
                      regenerate=None) -> Dict[str, Any]:
    """Grounding check + one regeneration + safe fallback. `regenerate(feedback)` returns new steps or None."""
    with agent_span("grounding_check", steps=len(draft_steps)):
        report = {"attempts": []}
        steps = draft_steps
        for attempt in (1, 2):
            chunks = load_chunks([c for s in steps for c in s["citations"]])
            verdicts = judge_steps(steps, chunks) if steps else []
            report["attempts"].append({"attempt": attempt, "steps": len(steps),
                                       "supported": sum(v["supported"] for v in verdicts),
                                       "verdicts": verdicts})
            unsupported = [(s, v) for s, v in zip(steps, verdicts) if not v["supported"]]
            if not unsupported or attempt == 2 or regenerate is None:
                break
            feedback = "\n".join(f"- \"{s['text']}\" was NOT supported by its citations ({v['reason']})."
                                 for s, v in unsupported)
            new_steps = regenerate(feedback)
            if not new_steps:
                break
            steps = new_steps
        kept = [dict(s, supported=True) for s, v in zip(steps, verdicts) if v["supported"]]
        all_chunks = load_chunks([c for s in kept for c in s["citations"]])

        has_channels = any(("1930" in s["text"]) or ("cybercrime.gov.in" in s["text"].lower()) for s in kept)
        if not has_channels:
            step, chunk = channels_step(language)
            if step:
                ch_chunks = {chunk["chunk_id"]: chunk}
                v = judge_steps([step], ch_chunks)[0]
                report["channels_step"] = v
                if v["supported"]:
                    kept.append(dict(step, supported=True))
                    all_chunks[chunk["chunk_id"]] = chunk

        has_channels = any(("1930" in s["text"]) or ("cybercrime.gov.in" in s["text"].lower()) for s in kept)
        if kept and not has_channels:
            # Official channels are mandatory; without a supporting passage they are added as an
            # uncited safety line, and the answer is honestly NOT counted as fully grounded.
            kept.append({"text": SAFE_FALLBACK.get(language, SAFE_FALLBACK["en"]), "citations": [],
                         "supported": False, "kind": "official_channels_uncited"})
        fallback_used = not kept
        if fallback_used:
            kept = [{"text": SAFE_FALLBACK.get(language, SAFE_FALLBACK["en"]), "citations": [], "supported": False,
                     "kind": "safe_fallback"}]
        drafted = len(draft_steps)
        grounded = (not fallback_used) and all(s.get("supported") for s in kept)
        sources = []
        for s in kept:
            for c in s["citations"]:
                ch = all_chunks.get(c)
                if ch and ch["chunk_id"] not in [x["chunk_id"] for x in sources]:
                    sources.append({"chunk_id": ch["chunk_id"], "doc_id": ch["doc_id"], "title": ch["title"],
                                    "issuer": ch["issuer"], "url": ch["url"]})
        report.update({"drafted_steps": drafted, "final_steps": len(kept), "fallback_used": fallback_used,
                       "fully_grounded": grounded})
        return {"steps": kept, "sources": sources, "grounding": report}


def render_guidance_text(result: Dict[str, Any]) -> str:
    """Plain text for notifications / voice: numbered steps with [n] source markers and a sources list."""
    src_index = {s["chunk_id"]: i for i, s in enumerate(result["sources"], 1)}
    lines = []
    for i, s in enumerate(result["steps"], 1):
        marks = "".join(f" [{src_index[c]}]" for c in s["citations"] if c in src_index)
        lines.append(f"{i}. {s['text']}{marks}")
    if result["sources"]:
        lines.append("")
        lines.append("Sources:")
        for i, s in enumerate(result["sources"], 1):
            lines.append(f"[{i}] {s['title']} — {s['issuer']} — {s['url']}")
    return "\n".join(lines)

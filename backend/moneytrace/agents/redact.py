"""
Deterministic PII redaction for text sent to an LLM.

Phone numbers, bank account / card numbers, Aadhaar-like 12-digit ids and email
addresses are replaced with stable placeholders ([PHONE_1], [ACCOUNT_1], ...).
Raw values stay only in the database; tools resolve placeholders server-side by
re-running the same deterministic redaction on the stored narrative.
UPI handles are kept: they identify the *recipient* and are needed for ledger and
mule-network lookups.
"""
import re
from typing import Dict, Tuple

_PATTERNS = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[a-z]{2,}(?:\.[a-z]{2,})?\b", re.I)),
    ("PHONE", re.compile(r"(?<![\w@])(?:\+?91[\s-]?)?[6-9]\d{2}[\s-]?\d{3}[\s-]?\d{4}(?!\d)|(?<![\w@])\+91-\d{5}-\d{5}(?!\d)")),
    ("CARD", re.compile(r"(?<!\d)(?:\d{4}[\s-]){3}\d{4}(?!\d)")),
    ("AADHAAR", re.compile(r"(?<!\d)\d{4}\s\d{4}\s\d{4}(?!\d)")),
    ("ACCOUNT", re.compile(r"(?<![\w@])(?:[A-Z]{2,6}-)?\d{9,18}(?![\w@])")),
]


def redact(text: str) -> Tuple[str, Dict[str, str]]:
    mapping: Dict[str, str] = {}
    counters: Dict[str, int] = {}
    reverse: Dict[str, str] = {}
    out = text or ""
    for label, pat in _PATTERNS:
        def _sub(m, label=label):
            raw = m.group(0)
            if raw in reverse:
                return reverse[raw]
            counters[label] = counters.get(label, 0) + 1
            ph = f"[{label}_{counters[label]}]"
            mapping[ph], reverse[raw] = raw, ph
            return ph
        out = pat.sub(_sub, out)
    return out, mapping


def resolve(value, original_text: str):
    """Map a placeholder (or a string containing placeholders) back to raw values."""
    if not value or not isinstance(value, str) or "[" not in value:
        return value
    _, mapping = redact(original_text)
    for ph, raw in mapping.items():
        value = value.replace(ph, raw)
    return value

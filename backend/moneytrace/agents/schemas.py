"""Structured records exchanged between agents (validated with Pydantic)."""
from typing import List, Optional
from pydantic import BaseModel, Field


class CaseRecord(BaseModel):
    """Structured case record produced by the intake agent from voice / screenshot / text."""
    amount: Optional[float] = Field(None, description="Amount lost in INR, if stated")
    transaction_id: Optional[str] = Field(None, description="UPI / bank transaction reference, if stated")
    counterparty_upi: Optional[str] = Field(None, description="UPI handle the money went to")
    phone: Optional[str] = Field(None, description="Scammer phone number (may be a redaction placeholder)")
    bank_account: Optional[str] = Field(None, description="Recipient bank account (may be a placeholder)")
    domain: Optional[str] = Field(None, description="Phishing link / domain mentioned")
    timestamps: List[str] = Field(default_factory=list, description="Dates / times mentioned")
    fraud_type: str = Field("Payment Fraud", description="Best guess of the scam type")
    language: str = Field("en", description="Language of the report: en, hi, ta, kn")
    channel: Optional[str] = Field(None, description="How the scammer reached the victim: call, SMS, WhatsApp, link, QR, app")
    summary: str = Field("", description="One-sentence neutral summary of what happened")
    source: str = Field("llm", description="llm | rules (deterministic fallback)")


class Assessment(BaseModel):
    severity: str = Field(description="CRITICAL, HIGH, MEDIUM or LOW")
    confidence: float = Field(ge=0.0, le=1.0)
    justification: str
    red_flags: List[str] = Field(default_factory=list)
    recommended_action: str = ""
    requires_human_review: bool = True
    source: str = "llm"


class GuidanceStep(BaseModel):
    text: str
    citations: List[str] = Field(default_factory=list, description="chunk_ids from search_advisories")


class GuidanceDraft(BaseModel):
    steps: List[GuidanceStep]

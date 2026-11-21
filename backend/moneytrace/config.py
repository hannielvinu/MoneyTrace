"""
Central configuration for MoneyTrace v2.

Every model name, price and feature flag is read from the environment here so
nothing is hard-coded in the agents. Prices are only used to *compute* cost from
measured token counts; the date they were checked is stored next to them and is
printed into RESULTS.md by the load test.
"""

import os
from dataclasses import dataclass, field
from typing import Dict


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _flag(name: str, default: bool = False) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class ModelPrice:
    """USD per 1M tokens."""
    input_per_m: float
    output_per_m: float


# Gemini API (AI Studio) paid-tier list prices, USD per 1M tokens.
# Source: https://ai.google.dev/gemini-api/docs/pricing
# NOTE: on the free tier the real charge is ₹0; cost/request is reported at
# paid-tier prices so the number is meaningful if the project upgrades.
# Override any of these with env vars PRICE_<MODEL>_IN / PRICE_<MODEL>_OUT.
DEFAULT_PRICES: Dict[str, ModelPrice] = {
    "gemini-2.5-flash": ModelPrice(0.30, 2.50),
    "gemini-2.5-flash-lite": ModelPrice(0.10, 0.40),
    "gemini-2.5-pro": ModelPrice(1.25, 10.00),
    "gemini-embedding-001": ModelPrice(0.15, 0.0),
}
PRICES_CHECKED_ON = _env("PRICES_CHECKED_ON", "2026-11-21 (verify on the pricing page before quoting)")


@dataclass(frozen=True)
class Settings:
    # --- storage ---
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL"))
    session_backend: str = field(default_factory=lambda: _env("SESSION_BACKEND", "auto"))  # auto|firestore|sqlite|memory
    firestore_project: str = field(default_factory=lambda: _env("GOOGLE_CLOUD_PROJECT"))
    firestore_database: str = field(default_factory=lambda: _env("FIRESTORE_DATABASE", "(default)"))
    firestore_collection: str = field(default_factory=lambda: _env("FIRESTORE_COLLECTION", "adk_sessions"))

    # --- models ---
    fast_model: str = field(default_factory=lambda: _env("GEMINI_FAST_MODEL", "gemini-2.5-flash"))
    strong_model: str = field(default_factory=lambda: _env("GEMINI_STRONG_MODEL", "gemini-2.5-flash"))
    judge_model: str = field(default_factory=lambda: _env("GEMINI_JUDGE_MODEL", "gemini-2.5-flash"))
    embedding_model: str = field(default_factory=lambda: _env("EMBEDDING_MODEL", "gemini-embedding-001"))
    embedding_dim: int = field(default_factory=lambda: int(_env("EMBEDDING_DIM", "768")))
    use_vertex: bool = field(default_factory=lambda: _flag("GOOGLE_GENAI_USE_VERTEXAI", False))

    # --- agents ---
    agent_engine: str = field(default_factory=lambda: _env("AGENT_ENGINE", "adk"))  # adk|legacy
    max_react_steps: int = field(default_factory=lambda: int(_env("MAX_REACT_STEPS", "8")))

    # --- RAG ---
    rag_top_k: int = field(default_factory=lambda: int(_env("RAG_TOP_K", "5")))
    rag_candidates: int = field(default_factory=lambda: int(_env("RAG_CANDIDATES", "20")))
    rag_rrf_k: int = field(default_factory=lambda: int(_env("RAG_RRF_K", "60")))
    rag_rerank: bool = field(default_factory=lambda: _flag("RAG_RERANK", False))

    # --- observability / cost ---
    otel_exporter: str = field(default_factory=lambda: _env("OTEL_EXPORTER", "console"))  # console|gcp|otlp|none
    usd_to_inr: float = field(default_factory=lambda: float(_env("USD_TO_INR", "84.0")))
    usd_to_inr_source: str = field(default_factory=lambda: _env(
        "USD_TO_INR_SOURCE", "config default; set USD_TO_INR to the RBI reference rate on the day you report"))

    # --- help desk ---
    helpdesk_mode: bool = field(default_factory=lambda: _flag("HELPDESK_MODE", True))
    retention_days: int = field(default_factory=lambda: int(_env("DATA_RETENTION_DAYS", "90")))

    def gemini_api_key(self) -> str:
        return _env("GEMINI_API_KEY") or _env("GOOGLE_API_KEY") or _env("LLM_API_KEY")

    def llm_configured(self) -> bool:
        return self.use_vertex or bool(self.gemini_api_key())

    def price_for(self, model: str) -> ModelPrice:
        key = model.upper().replace("-", "_").replace(".", "_")
        pin, pout = _env(f"PRICE_{key}_IN"), _env(f"PRICE_{key}_OUT")
        base = DEFAULT_PRICES.get(model)
        if base is None:
            # longest prefix match, e.g. "gemini-2.5-flash-001" -> "gemini-2.5-flash"
            for name in sorted(DEFAULT_PRICES, key=len, reverse=True):
                if model.startswith(name):
                    base = DEFAULT_PRICES[name]
                    break
        base = base or ModelPrice(0.0, 0.0)
        return ModelPrice(float(pin) if pin else base.input_per_m, float(pout) if pout else base.output_per_m)


def get_settings() -> Settings:
    # Re-read the environment each call (cheap) so tests can monkeypatch env vars.
    return Settings()

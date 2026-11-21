"""
Central configuration for MoneyTrace v2.

Every model name, price and feature flag is read from the environment here so
nothing is hard-coded in the agents. Prices are only used to *compute* cost from
measured token counts and must be configured explicitly (see below).
"""

import os
import re
from dataclasses import dataclass, field
from typing import Dict, Optional


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


# Model prices (USD per 1M tokens) are NOT hard-coded: they change often and must be copied from
# https://ai.google.dev/gemini-api/docs/pricing (or the Vertex AI pricing page) on the day you report.
# Set them as env vars, e.g.  PRICE_GEMINI_3_8_FLASH_IN=0.50  PRICE_GEMINI_3_8_FLASH_OUT=2.00
# and PRICES_CHECKED_ON=2026-11-25. Models without a configured price report cost as null ("not configured").
# Development providers on free endpoints can be set to 0 explicitly, e.g. PRICE_NVIDIA_NEMOTRON_..._IN=0.
DEFAULT_PRICES: Dict[str, ModelPrice] = {}
PRICES_CHECKED_ON = _env("PRICES_CHECKED_ON", "not set - prices not verified")


@dataclass(frozen=True)
class Settings:
    # --- storage ---
    database_url: str = field(default_factory=lambda: _env("DATABASE_URL"))
    session_backend: str = field(default_factory=lambda: _env("SESSION_BACKEND", "auto"))  # auto|firestore|sqlite|memory
    firestore_project: str = field(default_factory=lambda: _env("GOOGLE_CLOUD_PROJECT"))
    firestore_database: str = field(default_factory=lambda: _env("FIRESTORE_DATABASE", "(default)"))
    firestore_collection: str = field(default_factory=lambda: _env("FIRESTORE_COLLECTION", "adk_sessions"))

    # --- models ---
    # Defaults follow the model the v1 code already used (GEMINI_MODEL); override per tier.
    fast_model: str = field(default_factory=lambda: _env("GEMINI_FAST_MODEL", _env("GEMINI_MODEL", "gemini-3.8-flash")))
    strong_model: str = field(default_factory=lambda: _env("GEMINI_STRONG_MODEL", _env("GEMINI_MODEL", "gemini-3.8-flash")))
    judge_model: str = field(default_factory=lambda: _env("GEMINI_JUDGE_MODEL", _env("GEMINI_MODEL", "gemini-3.8-flash")))
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

    def price_for(self, model: str) -> Optional[ModelPrice]:
        """Configured price for a model, or None when no price has been set (cost is then reported as null)."""
        key = re.sub(r"[^A-Z0-9]+", "_", model.upper()).strip("_")
        pin, pout = _env(f"PRICE_{key}_IN"), _env(f"PRICE_{key}_OUT")
        if pin and pout:
            return ModelPrice(float(pin), float(pout))
        return DEFAULT_PRICES.get(model)


def get_settings() -> Settings:
    # Re-read the environment each call (cheap) so tests can monkeypatch env vars.
    return Settings()

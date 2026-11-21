"""
SQLAlchemy Core schema for MoneyTrace.

One schema, two engines:
- SQLite for local development and unit tests (DATABASE_URL=sqlite:///...)
- PostgreSQL (+pgvector) in production (DATABASE_URL=postgresql+psycopg://...)

Column names and types mirror the original SQLite schema so every caller keeps
working unchanged. `requires_human_review` / `read_status` stay INTEGER (0/1)
because existing code and the frontend compare them to 1.
"""

from sqlalchemy import (
    MetaData, Table, Column, Integer, BigInteger, String, Text, Float, DateTime, ForeignKey,
    Index, func,
)

metadata = MetaData()

users = Table(
    "users", metadata,
    Column("id", String(64), primary_key=True),
    Column("email", String(255), unique=True),
    Column("password_hash", String(255)),
    Column("name", String(255)),
    Column("role", String(32)),  # 'USER' or 'FRAUD_OPERATOR'
    Column("created_at", String(64)),
)

incidents = Table(
    "incidents", metadata,
    Column("id", String(32), primary_key=True),
    Column("user_id", String(64), ForeignKey("users.id")),
    Column("victim_name", Text),
    Column("victim_phone", Text),
    Column("language", String(8), server_default="en"),
    Column("amount", Float),
    Column("currency", String(8), server_default="INR"),
    Column("transaction_id", String(64)),
    Column("scam_type", String(128)),
    Column("severity", String(32)),
    Column("status", String(64)),
    Column("investigation_stage", String(64), server_default="REPORT_RECEIVED"),
    Column("confidence", Float),
    Column("narrative", Text),
    Column("victim_story_summary", Text),
    Column("recipient_upi", Text),
    Column("scammer_phone", Text),
    Column("bank_account", Text),
    Column("domain", Text),
    Column("qr_id", Text),
    Column("shared_cluster", Text),
    Column("victim_guidance", Text),
    Column("victim_guidance_audio_url", Text),
    Column("screenshot_url", Text),
    Column("ocr_extracted_data", Text),
    Column("requires_human_review", Integer, server_default="1"),
    Column("created_at", String(64)),
    Column("updated_at", String(64)),
    # Machine-readable timestamps (v2). Display strings above are kept for the UI.
    Column("created_ts", DateTime(timezone=True), server_default=func.now()),
    Column("guidance_ts", DateTime(timezone=True)),
)

transactions = Table(
    "transactions", metadata,
    Column("transaction_id", String(64), primary_key=True),
    Column("amount", Float),
    Column("currency", String(8), server_default="INR"),
    Column("sender", Text),
    Column("recipient", Text),
    Column("recipient_phone", Text),
    Column("recipient_bank", Text),
    Column("date", String(64)),
    Column("status", String(64)),
    Column("scam_category", String(128)),
    Column("note", Text),
)

entities = Table(
    "entities", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("incident_id", String(32), ForeignKey("incidents.id")),
    Column("entity_type", String(32)),
    Column("entity_value", Text),
    Index("ix_entities_value", "entity_type", "entity_value"),
)

audit_trail = Table(
    "audit_trail", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("incident_id", String(32), ForeignKey("incidents.id")),
    Column("timestamp", String(64)),
    Column("action", Text),
    Column("detail", Text),
    Index("ix_audit_incident", "incident_id"),
)

evidence_packages = Table(
    "evidence_packages", metadata,
    Column("incident_id", String(32), ForeignKey("incidents.id"), primary_key=True),
    Column("package_json", Text),
    Column("created_at", String(64)),
)

investigation_events = Table(
    "investigation_events", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("incident_id", String(32), ForeignKey("incidents.id")),
    Column("event_type", String(64)),
    Column("status", String(64)),
    Column("service", Text),
    Column("payload_json", Text),
    Column("timestamp", String(32)),
    Column("created_ts", DateTime(timezone=True), server_default=func.now()),
    Index("ix_events_incident", "incident_id"),
)

user_notifications = Table(
    "user_notifications", metadata,
    Column("id", String(64), primary_key=True),
    Column("user_id", String(64), ForeignKey("users.id")),
    Column("incident_id", String(32), ForeignKey("incidents.id")),
    Column("title", Text),
    Column("summary", Text),
    Column("guidance", Text),
    Column("read_status", Integer, server_default="0"),
    Column("created_at", String(64)),
)

# Atomic counters (incident id sequence) that behave the same on SQLite and Postgres.
counters = Table(
    "counters", metadata,
    Column("name", String(64), primary_key=True),
    Column("value", BigInteger, nullable=False),
)

# Per-request telemetry: latency, tokens and cost of every model call (Phase 5).
llm_calls = Table(
    "llm_calls", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("request_id", String(64), index=True),
    Column("incident_id", String(32)),
    Column("agent", String(64)),
    Column("model", String(128)),
    Column("input_tokens", Integer),
    Column("output_tokens", Integer),
    Column("latency_ms", Float),
    Column("cost_usd", Float),
    Column("created_ts", DateTime(timezone=True), server_default=func.now()),
)

# Help-desk usage log (Phase 8). No personal data: only event kind, category and timings.
usage_events = Table(
    "usage_events", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("kind", String(48), nullable=False),  # report_received | guidance_delivered | escalated | signoff
    Column("incident_id", String(32)),
    Column("scam_type", String(128)),
    Column("language", String(8)),
    Column("seconds_to_guidance", Float),
    Column("created_ts", DateTime(timezone=True), server_default=func.now(), index=True),
)

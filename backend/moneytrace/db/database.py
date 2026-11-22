"""
Database storage for MoneyTrace (SQLAlchemy Core).

DATABASE_URL selects the backend:
- unset / sqlite:///path  -> SQLite file (local development, unit tests)
- postgresql+psycopg://... -> PostgreSQL (Neon / Cloud SQL), pgvector enabled

The public functions keep the exact names and return shapes of the original
sqlite3 implementation, so callers did not need to change.
"""

import os
import json
import hashlib
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from sqlalchemy import create_engine, select, insert, update, delete, func, text, event
from sqlalchemy.engine import Engine

from moneytrace.db import models as m

logger = logging.getLogger("moneytrace.db")

_DEFAULT_DB_FILE = os.path.join(os.path.dirname(__file__), "moneytrace.db")
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# Neon CLI (`neon init` / `neon deploy` / `neon env pull`) writes DATABASE_URL (pooled) and DATABASE_URL_UNPOOLED
# (direct) into <repo>/.env.local. Load it as a fallback: explicit env vars and backend/.env take precedence.
try:
    from dotenv import load_dotenv as _load_dotenv
    _neon_env = os.path.join(_REPO_ROOT, ".env.local")
    if os.path.exists(_neon_env) and os.environ.get("MONEYTRACE_TESTING") != "1":
        _load_dotenv(_neon_env, override=False)
except Exception:  # pragma: no cover
    pass
INCIDENT_ID_BASE = 10482


def _normalise(url: str) -> str:
    # Accept plain postgres:// URLs from Neon / Heroku style providers; use the psycopg 3 driver.
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        return f"sqlite:///{_DEFAULT_DB_FILE}"
    return _normalise(url)


def migration_database_url() -> str:
    """Direct (unpooled) URL for Alembic / DDL. Neon's pooled endpoint runs PgBouncer in transaction mode, which
    breaks session-level operations, so migrations use DATABASE_URL_UNPOOLED, or the pooled URL with the
    `-pooler` host suffix removed (Neon's naming convention)."""
    from urllib.parse import urlparse
    url = _database_url()
    derived = url.replace("-pooler.", ".", 1) if "-pooler." in url else url
    direct = os.environ.get("DATABASE_URL_UNPOOLED", "").strip()
    if direct and not url.startswith("sqlite"):
        d, a = urlparse(_normalise(direct)), urlparse(derived)
        # only trust it when it is the direct endpoint of the SAME database the app uses
        if (d.hostname, d.path) == (a.hostname, a.path):
            return _normalise(direct)
    return derived


DATABASE_URL = _database_url()
DB_FILE = DATABASE_URL[len("sqlite:///"):] if DATABASE_URL.startswith("sqlite:///") else None

_engine: Optional[Engine] = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        if DATABASE_URL.startswith("sqlite"):
            _engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 30})

            @event.listens_for(_engine, "connect")
            def _sqlite_pragmas(dbapi_conn, _rec):
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.close()
        else:
            connect_args = {}
            if "-pooler." in DATABASE_URL:
                # PgBouncer (transaction mode): disable psycopg's automatic server-side prepared statements
                connect_args["prepare_threshold"] = None
            _engine = create_engine(
                DATABASE_URL,
                connect_args=connect_args,
                pool_pre_ping=True,
                pool_size=int(os.environ.get("DB_POOL_SIZE", "5")),
                max_overflow=int(os.environ.get("DB_MAX_OVERFLOW", "5")),
                pool_recycle=300,
            )
    return _engine


def is_postgres() -> bool:
    return get_engine().dialect.name == "postgresql"


def _now_display() -> str:
    return datetime.now().strftime("%d %b %Y, %H:%M IST")


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _rows(result) -> List[Dict[str, Any]]:
    return [dict(r) for r in result.mappings().all()]


def _row(result) -> Optional[Dict[str, Any]]:
    r = result.mappings().first()
    return dict(r) if r else None


# ---------------------------------------------------------------------------
# Schema management
# ---------------------------------------------------------------------------

def create_schema(drop_first: bool = False):
    """Create all core tables (idempotent). Used by init_db and the Alembic baseline."""
    eng = get_engine()
    if eng.dialect.name == "postgresql":
        with eng.begin() as conn:
            try:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            except Exception as e:  # pragma: no cover - depends on DB privileges
                logger.warning(f"Could not enable pgvector extension: {e}")
    if drop_first:
        m.metadata.drop_all(eng)
    if drop_first:
        with eng.begin() as conn:
            conn.execute(text("DROP TABLE IF EXISTS advisory_chunks"))
            conn.execute(text("DROP TABLE IF EXISTS advisory_documents"))
    m.metadata.create_all(eng, checkfirst=True)
    _add_missing_columns()
    from rag.store import ensure_rag_schema
    ensure_rag_schema(eng, dim=int(os.environ.get("EMBEDDING_DIM", "768")))


def _add_missing_columns():
    """Bring a pre-v2 SQLite file up to date (adds columns introduced in v2)."""
    eng = get_engine()
    from sqlalchemy import inspect
    insp = inspect(eng)
    for table in m.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name not in existing:
                coltype = col.type.compile(dialect=eng.dialect)
                with eng.begin() as conn:
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN {col.name} {coltype}'))
                logger.info(f"Added column {table.name}.{col.name}")


def init_db(force_reseed: bool = False):
    """Initializes the database schema and seeds synthetic data if empty."""
    create_schema(drop_first=force_reseed)
    eng = get_engine()
    with eng.begin() as conn:
        user_count = conn.execute(select(func.count()).select_from(m.users)).scalar()
        if user_count == 0 or force_reseed or os.environ.get("K_SERVICE"):
            seed_users(conn)  # on Cloud Run this re-applies (or skips) demo passwords from env on every start
    with eng.begin() as conn:
        incident_count = conn.execute(select(func.count()).select_from(m.incidents)).scalar()
        if incident_count == 0 or force_reseed:
            seed_data(conn)
    _ensure_incident_counter()


def _upsert(conn, table, values: Dict[str, Any], key: str):
    exists = conn.execute(select(table.c[key]).where(table.c[key] == values[key])).first()
    if exists:
        conn.execute(update(table).where(table.c[key] == values[key]).values(**values))
    else:
        conn.execute(insert(table).values(**values))


def seed_users(conn):
    """Demo accounts. On a deployed service (K_SERVICE set) they are created only with SEED_DEMO_USERS=1 and
    passwords taken from DEMO_VICTIM_PASSWORD / DEMO_OPERATOR_PASSWORD, so the public dev passwords never work live."""
    deployed = bool(os.environ.get("K_SERVICE"))
    if deployed and os.environ.get("SEED_DEMO_USERS", "0") != "1":
        return
    victim_pw = os.environ.get("DEMO_VICTIM_PASSWORD") or ("" if deployed else "victim123")
    operator_pw = os.environ.get("DEMO_OPERATOR_PASSWORD") or ("" if deployed else "operator123")
    users = []
    if victim_pw:
        users += [("usr_demo_victim_1", "victim@moneytrace.in", hash_password(victim_pw), "Ramesh Kumar (Victim)", "USER"),
                  ("usr_demo_victim_2", "victim2@moneytrace.in", hash_password(victim_pw), "Priya Sharma (Victim 2)", "USER")]
    if operator_pw:
        users += [("usr_demo_operator", "operator@moneytrace.in", hash_password(operator_pw), "Vikram Mehta (Fraud Ops)", "FRAUD_OPERATOR")]
    for uid, email, phash, name, role in users:
        _upsert(conn, m.users, {
            "id": uid, "email": email, "password_hash": phash, "name": name,
            "role": role, "created_at": _now_display(),
        }, "id")


def seed_data(conn):
    from moneytrace.data.synthetic_incidents import generate_synthetic_dataset
    dataset = generate_synthetic_dataset()

    for tx in dataset["transactions"]:
        _upsert(conn, m.transactions, {
            "transaction_id": tx["transaction_id"], "amount": tx["amount"],
            "currency": tx.get("currency", "INR"), "sender": tx.get("sender", "Anonymous"),
            "recipient": tx.get("recipient", ""), "recipient_phone": tx.get("recipient_phone", ""),
            "recipient_bank": tx.get("recipient_bank", ""), "date": tx.get("date", ""),
            "status": tx.get("status", "Completed"), "scam_category": tx.get("scam_category", ""),
            "note": tx.get("note", ""),
        }, "transaction_id")

    for inc in dataset["incidents"]:
        _upsert(conn, m.incidents, {
            "id": inc["id"], "user_id": "usr_demo_victim_1",
            "victim_name": inc.get("victim_name", "Anonymous"), "victim_phone": inc.get("victim_phone", ""),
            "language": "en", "amount": inc["amount"], "currency": inc.get("currency", "INR"),
            "transaction_id": inc["transaction_id"], "scam_type": inc.get("scam_type", "Unknown Scam"),
            "severity": inc.get("severity", "CRITICAL"), "status": inc.get("status", "ESCALATED"),
            "investigation_stage": "COMPLETE", "confidence": 0.92,
            "narrative": inc.get("narrative", ""), "victim_story_summary": inc.get("narrative", ""),
            "recipient_upi": inc.get("recipient_upi", ""), "scammer_phone": inc.get("scammer_phone", ""),
            "bank_account": inc.get("bank_account", ""), "domain": inc.get("domain", ""),
            "qr_id": inc.get("qr_id", ""), "shared_cluster": inc.get("shared_cluster", ""),
            "victim_guidance": "Do not send more money. Keep all transaction records and report to official cybercrime authority.",
            "requires_human_review": 1,
            "created_at": inc.get("created_at", ""), "updated_at": inc.get("created_at", ""),
        }, "id")

        for etype, evalue in [
            ("phone", inc.get("scammer_phone")),
            ("upi", inc.get("recipient_upi")),
            ("bank_account", inc.get("bank_account")),
            ("domain", inc.get("domain")),
            ("qr", inc.get("qr_id")),
        ]:
            if evalue:
                conn.execute(insert(m.entities).values(incident_id=inc["id"], entity_type=etype, entity_value=evalue))

        conn.execute(insert(m.audit_trail).values(
            incident_id=inc["id"], timestamp=inc.get("created_at"),
            action="Incident registered", detail="Incident recorded in MoneyTrace triage database.",
        ))


def _ensure_incident_counter():
    """Initialise the incident-id counter so new ids continue the MT-<n> series."""
    with get_engine().begin() as conn:
        row = conn.execute(select(m.counters.c.value).where(m.counters.c.name == "incident")).first()
        count = conn.execute(select(func.count()).select_from(m.incidents)).scalar() or 0
        floor = INCIDENT_ID_BASE + count
        if row is None:
            conn.execute(insert(m.counters).values(name="incident", value=floor))
        elif row[0] < floor:
            conn.execute(update(m.counters).where(m.counters.c.name == "incident").values(value=floor))


def next_incident_id() -> str:
    """Atomically allocate the next incident id (safe under concurrent requests)."""
    with get_engine().begin() as conn:
        res = conn.execute(
            update(m.counters).where(m.counters.c.name == "incident")
            .values(value=m.counters.c.value + 1).returning(m.counters.c.value)
        ).first()
        if res is None:
            conn.execute(insert(m.counters).values(name="incident", value=INCIDENT_ID_BASE + 1))
            value = INCIDENT_ID_BASE + 1
        else:
            value = res[0]
    return f"MT-{value}"


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    with get_engine().connect() as conn:
        return _row(conn.execute(select(m.users).where(m.users.c.email == email.strip().lower())))


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    with get_engine().connect() as conn:
        return _row(conn.execute(select(m.users).where(m.users.c.id == user_id)))


def create_user(user_id: str, email: str, password: str, name: str, role: str) -> Dict[str, Any]:
    with get_engine().begin() as conn:
        _upsert(conn, m.users, {
            "id": user_id, "email": email.strip().lower(), "password_hash": hash_password(password),
            "name": name, "role": role, "created_at": _now_display(),
        }, "id")
    return get_user_by_id(user_id)


# ---------------------------------------------------------------------------
# Incidents
# ---------------------------------------------------------------------------

def create_incident(values: Dict[str, Any]) -> str:
    values = dict(values)
    values.setdefault("id", next_incident_id())
    values.setdefault("created_ts", datetime.now(timezone.utc))
    with get_engine().begin() as conn:
        conn.execute(insert(m.incidents).values(**values))
    return values["id"]


def get_incident(incident_id: str) -> Optional[Dict[str, Any]]:
    with get_engine().connect() as conn:
        inc = _row(conn.execute(select(m.incidents).where(m.incidents.c.id == incident_id)))
        if not inc:
            return None
        inc.pop("created_ts", None)
        inc.pop("guidance_ts", None)

        inc["audit_trail"] = _rows(conn.execute(
            select(m.audit_trail.c.timestamp, m.audit_trail.c.action, m.audit_trail.c.detail)
            .where(m.audit_trail.c.incident_id == incident_id).order_by(m.audit_trail.c.id)
        ))
        inc["entities"] = _rows(conn.execute(
            select(m.entities.c.entity_type, m.entities.c.entity_value)
            .where(m.entities.c.incident_id == incident_id)
        ))
        pkg_row = conn.execute(
            select(m.evidence_packages.c.package_json).where(m.evidence_packages.c.incident_id == incident_id)
        ).first()
        if pkg_row and pkg_row[0]:
            try:
                inc["evidence_package"] = json.loads(pkg_row[0])
            except Exception:
                inc["evidence_package"] = None
        else:
            inc["evidence_package"] = None

        if inc.get("transaction_id"):
            inc["transaction"] = _row(conn.execute(
                select(m.transactions).where(m.transactions.c.transaction_id == inc["transaction_id"])
            ))
        else:
            inc["transaction"] = None
    return inc


_LIST_COLUMNS = ("id", "severity", "amount", "scam_type", "status", "investigation_stage",
                 "created_at", "victim_name", "recipient_upi", "scammer_phone")


def _incident_order():
    # Newest first by creation; ids are MT-<n> strings so fall back to id for seeded rows.
    return (m.incidents.c.created_ts.desc(), m.incidents.c.id.desc())


def list_incidents(limit: int = 100, include_review_flag: bool = False) -> List[Dict[str, Any]]:
    cols = [m.incidents.c[c] for c in _LIST_COLUMNS]
    if include_review_flag:
        cols.append(m.incidents.c.requires_human_review)
    with get_engine().connect() as conn:
        return _rows(conn.execute(select(*cols).order_by(m.incidents.c.id.desc()).limit(limit)))


def list_other_incidents(incident_id: str) -> List[Dict[str, Any]]:
    with get_engine().connect() as conn:
        rows = _rows(conn.execute(select(m.incidents).where(m.incidents.c.id != incident_id)))
    for r in rows:
        r.pop("created_ts", None)
        r.pop("guidance_ts", None)
    return rows


def get_dashboard_metrics() -> Dict[str, Any]:
    with get_engine().connect() as conn:
        total = conn.execute(select(func.count()).select_from(m.incidents)).scalar() or 0
        critical = conn.execute(
            select(func.count()).select_from(m.incidents).where(m.incidents.c.severity == "CRITICAL")
        ).scalar() or 0
        exposure = conn.execute(select(func.sum(m.incidents.c.amount))).scalar() or 0.0
        reviews = conn.execute(
            select(func.count()).select_from(m.incidents).where(m.incidents.c.requires_human_review == 1)
        ).scalar() or 0
    return {
        "active_incidents": total,
        "critical_incidents": critical,
        "reported_exposure": float(exposure),
        "human_reviews_required": reviews,
    }


def get_cluster_summary(limit: int = 6) -> List[Dict[str, Any]]:
    """Scam clusters computed from stored incidents (replaces the hard-coded demo list)."""
    i = m.incidents
    with get_engine().connect() as conn:
        groups = _rows(conn.execute(
            select(
                i.c.shared_cluster.label("name"),
                func.min(i.c.scam_type).label("category"),
                func.count().label("incident_count"),
                func.coalesce(func.sum(i.c.amount), 0).label("reported_exposure"),
                func.max(i.c.severity).label("max_severity"),
            )
            .where(i.c.shared_cluster.isnot(None), i.c.shared_cluster != "")
            .group_by(i.c.shared_cluster)
            .order_by(func.count().desc())
            .limit(limit)
        ))
        for g in groups:
            ids = [r[0] for r in conn.execute(select(i.c.id).where(i.c.shared_cluster == g["name"])).all()]
            ent_rows = conn.execute(
                select(m.entities.c.entity_value, func.count().label("n"))
                .where(m.entities.c.incident_id.in_(ids))
                .group_by(m.entities.c.entity_value)
                .order_by(func.count().desc())
            ).all()
            shared = [r for r in ent_rows if r[1] > 1]
            g["shared_entities_count"] = len(shared)
            g["lead_entity"] = (shared[0][0] if shared else (ent_rows[0][0] if ent_rows else ""))
            g["reported_exposure"] = float(g["reported_exposure"])
            g["status"] = "Active Threat" if g["incident_count"] >= 8 else "Monitoring"
            g.pop("max_severity", None)
    return groups


def get_user_incidents(user_id: str) -> List[Dict[str, Any]]:
    i = m.incidents
    with get_engine().connect() as conn:
        return _rows(conn.execute(
            select(i.c.id, i.c.amount, i.c.currency, i.c.transaction_id, i.c.scam_type, i.c.severity,
                   i.c.status, i.c.investigation_stage, i.c.created_at, i.c.narrative)
            .where(i.c.user_id == user_id)
            .order_by(i.c.created_ts.desc(), i.c.id.desc())
        ))


def update_incident_record(incident_id: str, updates: Dict[str, Any]):
    valid = {k: v for k, v in updates.items() if k in m.incidents.c}
    unknown = set(updates) - set(valid)
    if unknown:
        raise ValueError(f"Unknown incident columns: {sorted(unknown)}")
    with get_engine().begin() as conn:
        conn.execute(update(m.incidents).where(m.incidents.c.id == incident_id).values(**valid))


def mark_guidance_delivered(incident_id: str) -> Optional[float]:
    """Stamp the first time guidance reached the victim; returns seconds since the report."""
    now = datetime.now(timezone.utc)
    with get_engine().begin() as conn:
        row = conn.execute(select(m.incidents.c.created_ts, m.incidents.c.guidance_ts)
                           .where(m.incidents.c.id == incident_id)).first()
        if not row:
            return None
        created, already = row
        if already is None:
            conn.execute(update(m.incidents).where(m.incidents.c.id == incident_id).values(guidance_ts=now))
    if created is None:
        return None
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return (now - created).total_seconds()


# ---------------------------------------------------------------------------
# Notifications, events, ledger, audit, evidence
# ---------------------------------------------------------------------------

def get_user_notifications(user_id: str) -> List[Dict[str, Any]]:
    n = m.user_notifications
    with get_engine().connect() as conn:
        return _rows(conn.execute(select(n).where(n.c.user_id == user_id).order_by(n.c.id.desc())))


def create_user_notification(user_id: str, incident_id: str, title: str, summary: str, guidance: str):
    nid = f"NOTIF-{int(datetime.now().timestamp() * 1000000)}"
    with get_engine().begin() as conn:
        conn.execute(insert(m.user_notifications).values(
            id=nid, user_id=user_id, incident_id=incident_id, title=title, summary=summary,
            guidance=guidance, read_status=0, created_at=_now_display(),
        ))
    return nid


def save_investigation_event(incident_id: str, event_type: str, status: str, service: str, payload: Dict[str, Any]):
    with get_engine().begin() as conn:
        conn.execute(insert(m.investigation_events).values(
            incident_id=incident_id, event_type=event_type, status=status, service=service,
            payload_json=json.dumps(payload, ensure_ascii=False, default=str),
            timestamp=datetime.now().strftime("%H:%M:%S"),
            created_ts=datetime.now(timezone.utc),
        ))


def get_incident_events(incident_id: str) -> List[Dict[str, Any]]:
    e = m.investigation_events
    with get_engine().connect() as conn:
        rows = _rows(conn.execute(
            select(e.c.event_type, e.c.status, e.c.service, e.c.payload_json, e.c.timestamp)
            .where(e.c.incident_id == incident_id).order_by(e.c.id)
        ))
    for d in rows:
        try:
            d["payload"] = json.loads(d["payload_json"])
        except Exception:
            d["payload"] = {}
    return rows


def get_transaction(tx_id: str) -> Optional[Dict[str, Any]]:
    with get_engine().connect() as conn:
        return _row(conn.execute(select(m.transactions).where(m.transactions.c.transaction_id == tx_id)))


def find_transactions(recipient: Optional[str] = None, amount: Optional[float] = None,
                      limit: int = 5) -> List[Dict[str, Any]]:
    """Ledger search used by the investigation agent when no transaction id was given."""
    t = m.transactions
    q = select(t)
    if recipient:
        q = q.where(func.lower(t.c.recipient) == recipient.strip().lower())
    if amount:
        q = q.where(t.c.amount.between(amount - 0.5, amount + 0.5))
    if not recipient and not amount:
        return []
    with get_engine().connect() as conn:
        return _rows(conn.execute(q.limit(limit)))


def find_incidents_by_entity(entity_value: str, exclude_incident: Optional[str] = None) -> List[Dict[str, Any]]:
    e, i = m.entities, m.incidents
    q = (select(i.c.id, i.c.scam_type, i.c.amount, i.c.severity, i.c.shared_cluster, e.c.entity_type)
         .join(e, e.c.incident_id == i.c.id)
         .where(func.lower(e.c.entity_value) == entity_value.strip().lower()))
    if exclude_incident:
        q = q.where(i.c.id != exclude_incident)
    with get_engine().connect() as conn:
        return _rows(conn.execute(q))


def save_entities(incident_id: str, ents: Dict[str, Optional[str]]):
    with get_engine().begin() as conn:
        conn.execute(delete(m.entities).where(m.entities.c.incident_id == incident_id))
        for etype, value in ents.items():
            if value:
                conn.execute(insert(m.entities).values(incident_id=incident_id, entity_type=etype, entity_value=value))


def add_audit_log(incident_id: str, action: str, detail: str, timestamp: Optional[str] = None):
    with get_engine().begin() as conn:
        conn.execute(insert(m.audit_trail).values(
            incident_id=incident_id, timestamp=timestamp or datetime.now().strftime("%H:%M:%S"),
            action=action, detail=detail,
        ))


def save_evidence_package(incident_id: str, package: Dict[str, Any]):
    with get_engine().begin() as conn:
        _upsert(conn, m.evidence_packages, {
            "incident_id": incident_id,
            "package_json": json.dumps(package, ensure_ascii=False, default=str),
            "created_at": _now_display(),
        }, "incident_id")


# ---------------------------------------------------------------------------
# Telemetry + usage
# ---------------------------------------------------------------------------

def record_llm_call(**values):
    try:
        with get_engine().begin() as conn:
            conn.execute(insert(m.llm_calls).values(**values))
    except Exception as e:  # telemetry must never break a request
        logger.warning(f"record_llm_call failed: {e}")


def record_usage_event(kind: str, incident_id: Optional[str] = None, scam_type: Optional[str] = None,
                       language: Optional[str] = None, seconds_to_guidance: Optional[float] = None):
    try:
        with get_engine().begin() as conn:
            conn.execute(insert(m.usage_events).values(
                kind=kind, incident_id=incident_id, scam_type=scam_type, language=language,
                seconds_to_guidance=seconds_to_guidance, created_ts=datetime.now(timezone.utc),
            ))
    except Exception as e:
        logger.warning(f"record_usage_event failed: {e}")


def get_usage_summary(days: int = 30) -> Dict[str, Any]:
    """Daily help-desk usage from usage_events (contains no personal data)."""
    import statistics
    from datetime import timedelta
    since = datetime.now(timezone.utc) - timedelta(days=days)
    u = m.usage_events
    with get_engine().connect() as conn:
        rows = _rows(conn.execute(select(u.c.kind, u.c.scam_type, u.c.language, u.c.seconds_to_guidance, u.c.created_ts)
                                  .where(u.c.created_ts >= since).order_by(u.c.created_ts)))
    daily: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        ts = r["created_ts"]
        day = ts.strftime("%Y-%m-%d") if hasattr(ts, "strftime") else str(ts)[:10]
        d = daily.setdefault(day, {"date": day, "reports_received": 0, "guidance_delivered": 0, "escalations": 0,
                                   "operator_signoffs": 0, "by_scam_type": {}, "by_language": {}, "_secs": []})
        if r["kind"] == "report_received":
            d["reports_received"] += 1
            d["by_language"][r["language"] or "?"] = d["by_language"].get(r["language"] or "?", 0) + 1
        elif r["kind"] == "guidance_delivered":
            d["guidance_delivered"] += 1
            d["by_scam_type"][r["scam_type"] or "?"] = d["by_scam_type"].get(r["scam_type"] or "?", 0) + 1
            if r["seconds_to_guidance"] is not None:
                d["_secs"].append(r["seconds_to_guidance"])
        elif r["kind"] == "escalated":
            d["escalations"] += 1
        elif r["kind"] == "signoff":
            d["operator_signoffs"] += 1
    all_secs = []
    for d in daily.values():
        secs = d.pop("_secs")
        all_secs += secs
        d["median_seconds_to_first_guidance"] = round(statistics.median(secs), 1) if secs else None
    totals = {k: sum(d[k] for d in daily.values()) for k in ("reports_received", "guidance_delivered", "escalations",
                                                             "operator_signoffs")}
    totals["median_seconds_to_first_guidance"] = round(statistics.median(all_secs), 1) if all_secs else None
    return {"days": days, "daily": sorted(daily.values(), key=lambda d: d["date"]), "totals": totals}


def purge_reports_older_than(days: int, dry_run: bool = False) -> Dict[str, int]:
    """Delete victim reports (and everything derived from them) older than `days`. usage_events are kept: no PII."""
    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    i = m.incidents
    with get_engine().begin() as conn:
        ids = [r[0] for r in conn.execute(select(i.c.id).where(i.c.created_ts < cutoff)).all()]
        counts = {"incidents": len(ids)}
        if dry_run or not ids:
            return counts
        for tbl in (m.audit_trail, m.entities, m.evidence_packages, m.investigation_events, m.user_notifications):
            counts[tbl.name] = conn.execute(delete(tbl).where(tbl.c.incident_id.in_(ids))).rowcount
        counts["llm_calls"] = conn.execute(delete(m.llm_calls).where(m.llm_calls.c.incident_id.in_(ids))).rowcount
        conn.execute(update(m.usage_events).where(m.usage_events.c.incident_id.in_(ids)).values(incident_id=None))
        conn.execute(delete(i).where(i.c.id.in_(ids)))
    return counts

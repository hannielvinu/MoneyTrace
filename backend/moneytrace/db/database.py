"""
Database storage for MoneyTrace using SQLite.
Stores users, incidents, transactions, extracted entities, audit trail, evidence packages,
persistent investigation events, and user-safe notifications.
"""

import sqlite3
import json
import os
import hashlib
from typing import List, Dict, Any, Optional
from datetime import datetime

DB_FILE = os.path.join(os.path.dirname(__file__), "moneytrace.db")


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def get_db_connection():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(force_reseed: bool = False):
    """Initializes the database schema and seeds synthetic data if empty."""
    conn = get_db_connection()
    cur = conn.cursor()

    if force_reseed:
        cur.execute("DROP TABLE IF EXISTS incidents")
        cur.execute("DROP TABLE IF EXISTS users")
        cur.execute("DROP TABLE IF EXISTS transactions")
        cur.execute("DROP TABLE IF EXISTS entities")
        cur.execute("DROP TABLE IF EXISTS audit_trail")
        cur.execute("DROP TABLE IF EXISTS evidence_packages")
        cur.execute("DROP TABLE IF EXISTS investigation_events")
        cur.execute("DROP TABLE IF EXISTS user_notifications")
        conn.commit()

    # 1. Users table (Role: USER vs FRAUD_OPERATOR)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE,
        password_hash TEXT,
        name TEXT,
        role TEXT, -- 'USER' or 'FRAUD_OPERATOR'
        created_at TEXT
    );
    """)

    # 2. Incidents table with user_id, investigation_stage, screenshot_url, and ocr_data
    cur.execute("""
    CREATE TABLE IF NOT EXISTS incidents (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        victim_name TEXT,
        victim_phone TEXT,
        language TEXT DEFAULT 'en',
        amount REAL,
        currency TEXT DEFAULT 'INR',
        transaction_id TEXT,
        scam_type TEXT,
        severity TEXT,
        status TEXT,
        investigation_stage TEXT DEFAULT 'REPORT_RECEIVED',
        confidence REAL,
        narrative TEXT,
        victim_story_summary TEXT,
        recipient_upi TEXT,
        scammer_phone TEXT,
        bank_account TEXT,
        domain TEXT,
        qr_id TEXT,
        shared_cluster TEXT,
        victim_guidance TEXT,
        victim_guidance_audio_url TEXT,
        screenshot_url TEXT,
        ocr_extracted_data TEXT,
        requires_human_review BOOLEAN DEFAULT 1,
        created_at TEXT,
        updated_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    """)

    # 3. Transactions table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        transaction_id TEXT PRIMARY KEY,
        amount REAL,
        currency TEXT DEFAULT 'INR',
        sender TEXT,
        recipient TEXT,
        recipient_phone TEXT,
        recipient_bank TEXT,
        date TEXT,
        status TEXT,
        scam_category TEXT,
        note TEXT
    );
    """)

    # 4. Entities table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS entities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        incident_id TEXT,
        entity_type TEXT,
        entity_value TEXT,
        FOREIGN KEY(incident_id) REFERENCES incidents(id)
    );
    """)

    # 5. Audit Trail table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS audit_trail (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        incident_id TEXT,
        timestamp TEXT,
        action TEXT,
        detail TEXT,
        FOREIGN KEY(incident_id) REFERENCES incidents(id)
    );
    """)

    # 6. Evidence Packages table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS evidence_packages (
        incident_id TEXT PRIMARY KEY,
        package_json TEXT,
        created_at TEXT,
        FOREIGN KEY(incident_id) REFERENCES incidents(id)
    );
    """)

    # 7. Investigation Events table (Persistent SSE Event Log)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS investigation_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        incident_id TEXT,
        event_type TEXT,
        status TEXT,
        service TEXT,
        payload_json TEXT,
        timestamp TEXT,
        FOREIGN KEY(incident_id) REFERENCES incidents(id)
    );
    """)

    # 8. User Safe Notifications table
    cur.execute("""
    CREATE TABLE IF NOT EXISTS user_notifications (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        incident_id TEXT,
        title TEXT,
        summary TEXT,
        guidance TEXT,
        read_status BOOLEAN DEFAULT 0,
        created_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id),
        FOREIGN KEY(incident_id) REFERENCES incidents(id)
    );
    """)

    conn.commit()

    # Seed users and dataset if empty
    cur.execute("SELECT COUNT(*) FROM users")
    user_count = cur.fetchone()[0]

    if user_count == 0 or force_reseed:
        seed_users(cur)
        conn.commit()

    cur.execute("SELECT COUNT(*) FROM incidents")
    incident_count = cur.fetchone()[0]

    if incident_count == 0 or force_reseed:
        seed_data(conn)

    conn.close()


def seed_users(cur):
    users = [
        ("usr_demo_victim_1", "victim@moneytrace.in", hash_password("victim123"), "Ramesh Kumar (Victim)", "USER"),
        ("usr_demo_victim_2", "victim2@moneytrace.in", hash_password("victim123"), "Priya Sharma (Victim 2)", "USER"),
        ("usr_demo_operator", "operator@moneytrace.in", hash_password("operator123"), "Vikram Mehta (Fraud Ops)", "FRAUD_OPERATOR"),
    ]
    for uid, email, phash, name, role in users:
        cur.execute("""
        INSERT OR REPLACE INTO users (id, email, password_hash, name, role, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (uid, email, phash, name, role, datetime.now().strftime("%d %b %Y, %H:%M IST")))


def seed_data(conn):
    from moneytrace.data.synthetic_incidents import generate_synthetic_dataset
    dataset = generate_synthetic_dataset()
    cur = conn.cursor()

    for tx in dataset["transactions"]:
        cur.execute("""
        INSERT OR REPLACE INTO transactions (
            transaction_id, amount, currency, sender, recipient,
            recipient_phone, recipient_bank, date, status, scam_category, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            tx["transaction_id"], tx["amount"], tx.get("currency", "INR"),
            tx.get("sender", "Anonymous"), tx.get("recipient", ""),
            tx.get("recipient_phone", ""), tx.get("recipient_bank", ""),
            tx.get("date", ""), tx.get("status", "Completed"),
            tx.get("scam_category", ""), tx.get("note", "")
        ))

    for inc in dataset["incidents"]:
        cur.execute("""
        INSERT OR REPLACE INTO incidents (
            id, user_id, victim_name, victim_phone, language, amount, currency,
            transaction_id, scam_type, severity, status, investigation_stage, confidence,
            narrative, victim_story_summary, recipient_upi, scammer_phone,
            bank_account, domain, qr_id, shared_cluster, victim_guidance,
            requires_human_review, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            inc["id"], "usr_demo_victim_1", inc.get("victim_name", "Anonymous"), inc.get("victim_phone", ""),
            "en", inc["amount"], inc.get("currency", "INR"),
            inc["transaction_id"], inc.get("scam_type", "Unknown Scam"),
            inc.get("severity", "CRITICAL"), inc.get("status", "ESCALATED"),
            "COMPLETE",
            0.92, inc.get("narrative", ""), inc.get("narrative", ""),
            inc.get("recipient_upi", ""), inc.get("scammer_phone", ""),
            inc.get("bank_account", ""), inc.get("domain", ""),
            inc.get("qr_id", ""), inc.get("shared_cluster", ""),
            "Do not send more money. Keep all transaction records and report to official cybercrime authority.",
            1, inc.get("created_at", ""), inc.get("created_at", "")
        ))

        for etype, evalue in [
            ("phone", inc.get("scammer_phone")),
            ("upi", inc.get("recipient_upi")),
            ("bank_account", inc.get("bank_account")),
            ("domain", inc.get("domain")),
            ("qr", inc.get("qr_id")),
        ]:
            if evalue:
                cur.execute("""
                INSERT INTO entities (incident_id, entity_type, entity_value)
                VALUES (?, ?, ?)
                """, (inc["id"], etype, evalue))

        cur.execute("""
        INSERT INTO audit_trail (incident_id, timestamp, action, detail)
        VALUES (?, ?, ?, ?)
        """, (inc["id"], inc.get("created_at"), "Incident registered", "Incident recorded in MoneyTrace triage database."))

    conn.commit()


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def get_incident(incident_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return None

    inc = dict(row)

    cur.execute("SELECT timestamp, action, detail FROM audit_trail WHERE incident_id = ? ORDER BY id ASC", (incident_id,))
    inc["audit_trail"] = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT entity_type, entity_value FROM entities WHERE incident_id = ?", (incident_id,))
    inc["entities"] = [dict(r) for r in cur.fetchall()]

    cur.execute("SELECT package_json FROM evidence_packages WHERE incident_id = ?", (incident_id,))
    pkg_row = cur.fetchone()
    if pkg_row and pkg_row[0]:
        try:
            inc["evidence_package"] = json.loads(pkg_row[0])
        except Exception:
            inc["evidence_package"] = None
    else:
        inc["evidence_package"] = None

    if inc.get("transaction_id"):
        cur.execute("SELECT * FROM transactions WHERE transaction_id = ?", (inc["transaction_id"],))
        tx_row = cur.fetchone()
        inc["transaction"] = dict(tx_row) if tx_row else None
    else:
        inc["transaction"] = None

    conn.close()
    return inc


def get_user_incidents(user_id: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT id, amount, currency, transaction_id, scam_type, severity, status, investigation_stage, created_at, narrative
    FROM incidents
    WHERE user_id = ?
    ORDER BY created_at DESC
    """, (user_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def get_user_notifications(user_id: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT * FROM user_notifications
    WHERE user_id = ?
    ORDER BY created_at DESC
    """, (user_id,))
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def create_user_notification(user_id: str, incident_id: str, title: str, summary: str, guidance: str):
    conn = get_db_connection()
    cur = conn.cursor()
    nid = f"NOTIF-{int(datetime.now().timestamp()*1000)}"
    now_str = datetime.now().strftime("%d %b %Y, %H:%M IST")
    cur.execute("""
    INSERT INTO user_notifications (id, user_id, incident_id, title, summary, guidance, read_status, created_at)
    VALUES (?, ?, ?, ?, ?, ?, 0, ?)
    """, (nid, user_id, incident_id, title, summary, guidance, now_str))
    conn.commit()
    conn.close()
    return nid


def save_investigation_event(incident_id: str, event_type: str, status: str, service: str, payload: Dict[str, Any]):
    conn = get_db_connection()
    cur = conn.cursor()
    now_str = datetime.now().strftime("%H:%M:%S")
    cur.execute("""
    INSERT INTO investigation_events (incident_id, event_type, status, service, payload_json, timestamp)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (incident_id, event_type, status, service, json.dumps(payload, ensure_ascii=False), now_str))
    conn.commit()
    conn.close()


def get_incident_events(incident_id: str) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    SELECT event_type, status, service, payload_json, timestamp
    FROM investigation_events
    WHERE incident_id = ?
    ORDER BY id ASC
    """, (incident_id,))
    rows = []
    for r in cur.fetchall():
        d = dict(r)
        try:
            d["payload"] = json.loads(d["payload_json"])
        except Exception:
            d["payload"] = {}
        rows.append(d)
    conn.close()
    return rows


def get_transaction(tx_id: str) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM transactions WHERE transaction_id = ?", (tx_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def add_audit_log(incident_id: str, action: str, detail: str, timestamp: Optional[str] = None):
    if not timestamp:
        timestamp = datetime.now().strftime("%H:%M:%S")
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO audit_trail (incident_id, timestamp, action, detail)
    VALUES (?, ?, ?, ?)
    """, (incident_id, timestamp, action, detail))
    conn.commit()
    conn.close()


def save_evidence_package(incident_id: str, package: Dict[str, Any]):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
    INSERT OR REPLACE INTO evidence_packages (incident_id, package_json, created_at)
    VALUES (?, ?, ?)
    """, (incident_id, json.dumps(package, ensure_ascii=False), datetime.now().strftime("%d %b %Y, %H:%M IST")))
    conn.commit()
    conn.close()


def update_incident_record(incident_id: str, updates: Dict[str, Any]):
    conn = get_db_connection()
    cur = conn.cursor()
    
    fields = []
    values = []
    for k, v in updates.items():
        fields.append(f"{k} = ?")
        values.append(v)
    
    values.append(incident_id)
    cur.execute(f"UPDATE incidents SET {', '.join(fields)} WHERE id = ?", values)
    conn.commit()
    conn.close()

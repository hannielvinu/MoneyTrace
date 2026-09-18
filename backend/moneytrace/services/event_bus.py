"""
Real-time Event Bus for MoneyTrace.
Provides in-memory async SSE broadcasting for the 4 synchronized live views:
- Tab 1: User Portal (/portal)
- Tab 2: Live Investigation (/investigations)
- Tab 3: Case Workspace (/cases/:id)
- Tab 4: Fraud Operations Dashboard (/dashboard)

Also persists events into the database for auditability and history.
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional, Set
from datetime import datetime

from moneytrace.db.database import save_investigation_event

logger = logging.getLogger("moneytrace.events")

# Set of active async queues for connected SSE clients
_connected_subscribers: Set[asyncio.Queue] = set()


async def register_subscriber() -> asyncio.Queue:
    """Registers a new SSE client connection and returns an async queue."""
    q = asyncio.Queue()
    _connected_subscribers.add(q)
    return q


def unregister_subscriber(q: asyncio.Queue):
    """Removes a disconnected SSE client."""
    _connected_subscribers.discard(q)


async def emit_event(
    event_type: str,
    incident_id: str,
    status: str,
    service: str,
    payload: Optional[Dict[str, Any]] = None,
    user_id: Optional[str] = None
):
    """
    Publishes an event to all connected SSE clients and persists it in SQLite.
    
    Required event types:
    - INCIDENT_CREATED
    - INVESTIGATION_STARTED
    - TRANSACTION_FOUND
    - SIGNALS_ANALYZED
    - RELATED_INCIDENTS_FOUND
    - GRAPH_READY
    - EVIDENCE_PREPARED
    - N8N_WORKFLOW_STARTED
    - N8N_WORKFLOW_COMPLETED
    - HUMAN_REVIEW_REQUIRED
    - INCIDENT_COMPLETED
    - USER_NOTIFICATION_CREATED
    """
    now_str = datetime.now().strftime("%H:%M:%S")
    if payload is None:
        payload = {}

    event_data = {
        "event_type": event_type,
        "incident_id": incident_id,
        "status": status,
        "service": service,
        "payload": payload,
        "user_id": user_id,
        "timestamp": now_str
    }

    # 1. Persist to DB
    try:
        save_investigation_event(
            incident_id=incident_id,
            event_type=event_type,
            status=status,
            service=service,
            payload=payload
        )
    except Exception as e:
        logger.error(f"Failed to persist event {event_type}: {e}")

    # 2. Broadcast to all active SSE queues
    dead_queues = []
    for q in list(_connected_subscribers):
        try:
            q.put_nowait(event_data)
        except Exception:
            dead_queues.append(q)

    for dq in dead_queues:
        unregister_subscriber(dq)

    logger.info(f"[EVENT BUS] {event_type} (Incident: {incident_id}, Service: {service})")

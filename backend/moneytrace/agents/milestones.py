"""
Ordered emission of the 12 SSE milestones.

Agents call tools in whatever order their reasoning takes, but the UI and the
audit trail expect the canonical milestone order. A milestone is emitted only
once every earlier milestone has been emitted; otherwise it is buffered and
flushed as soon as the gap is filled. After the agent run, the coordinator's
guard fills any milestone the agents skipped (marked "via": "guard").
"""
import asyncio
from typing import Any, Dict, List, Optional

from moneytrace.services.event_bus import emit_event

ORDER = [
    "INCIDENT_CREATED", "INVESTIGATION_STARTED", "TRANSACTION_FOUND", "SIGNALS_ANALYZED",
    "RELATED_INCIDENTS_FOUND", "GRAPH_READY", "EVIDENCE_PREPARED", "N8N_WORKFLOW_STARTED",
    "N8N_WORKFLOW_COMPLETED", "HUMAN_REVIEW_REQUIRED", "INCIDENT_COMPLETED", "USER_NOTIFICATION_CREATED",
]


class MilestoneEmitter:
    def __init__(self, incident_id: str, user_id: Optional[str]):
        self.incident_id, self.user_id = incident_id, user_id
        self.emitted: List[str] = ["INCIDENT_CREATED"]  # emitted by the intake API before the pipeline starts
        self.pending: Dict[str, Dict[str, Any]] = {}
        self.lock = asyncio.Lock()

    def done(self, name: str) -> bool:
        return name in self.emitted

    def next_expected(self) -> Optional[str]:
        for m in ORDER:
            if m not in self.emitted:
                return m
        return None

    async def emit(self, name: str, status: str, service: str, payload: Dict[str, Any]):
        async with self.lock:
            if name in self.emitted or name in self.pending:
                return
            self.pending[name] = {"status": status, "service": service, "payload": payload}
            await self._flush()

    async def _flush(self):
        while True:
            nxt = self.next_expected()
            if nxt is None or nxt not in self.pending:
                return
            ev = self.pending.pop(nxt)
            await emit_event(event_type=nxt, incident_id=self.incident_id, status=ev["status"], service=ev["service"],
                             payload=ev["payload"], user_id=self.user_id)
            self.emitted.append(nxt)


_registry: Dict[str, MilestoneEmitter] = {}


def get_emitter(incident_id: str, user_id: Optional[str] = None) -> MilestoneEmitter:
    if incident_id not in _registry:
        _registry[incident_id] = MilestoneEmitter(incident_id, user_id)
    return _registry[incident_id]


def release(incident_id: str):
    _registry.pop(incident_id, None)

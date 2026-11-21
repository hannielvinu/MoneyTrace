"""
Firestore-backed ADK session service (agent state management).

Cloud Run instances are stateless; agent conversation state (turns, current
case, agent hand-offs) therefore lives in Firestore so it survives restarts and
scale-to-zero.

Document layout (all under one root collection, default `adk_sessions`):

    {root}/{app}                                   {"state": <app-scoped state>}
    {root}/{app}/users/{user}                      {"state": <user-scoped state>}
    {root}/{app}/users/{user}/sessions/{sid}       {"state", "last_update_time", ...}
    {root}/{app}/users/{user}/sessions/{sid}/events/{seq}_{event_id}
                                                   {"event": <Event JSON>, "timestamp", "seq"}

Events are stored as a JSON string because Firestore cannot hold nested arrays,
which ADK events (function-call parts) contain.

The client is injectable, so tests run against an in-process fake with the same
async API surface as `google.cloud.firestore.AsyncClient`.
"""

from __future__ import annotations

import time
import uuid
import logging
from typing import Any, Optional

from typing_extensions import override

from google.adk.events.event import Event
from google.adk.errors.already_exists_error import AlreadyExistsError
from google.adk.sessions.base_session_service import BaseSessionService, GetSessionConfig, ListSessionsResponse
from google.adk.sessions.session import Session
from google.adk.sessions.state import State
from google.adk.sessions import _session_util

logger = logging.getLogger("moneytrace.state.firestore")


def _key(s: str) -> str:
    """Firestore document ids may not contain '/' and may not be '.' or '..'."""
    s = (s or "_").replace("/", "%2F")
    return s if s not in (".", "..") else f"_{s}"


class FirestoreSessionService(BaseSessionService):

    def __init__(self, client: Any = None, *, project: Optional[str] = None,
                 database: str = "(default)", root_collection: str = "adk_sessions"):
        if client is None:
            from google.cloud import firestore  # imported lazily: optional dependency
            client = firestore.AsyncClient(project=project or None, database=database)
        self._db = client
        self._root = root_collection

    # ------------------------------------------------------------------ refs
    def _app_ref(self, app_name: str):
        return self._db.collection(self._root).document(_key(app_name))

    def _user_ref(self, app_name: str, user_id: str):
        return self._app_ref(app_name).collection("users").document(_key(user_id))

    def _session_ref(self, app_name: str, user_id: str, session_id: str):
        return self._user_ref(app_name, user_id).collection("sessions").document(_key(session_id))

    async def _read_state(self, ref) -> dict[str, Any]:
        snap = await ref.get()
        if not snap.exists:
            return {}
        return dict((snap.to_dict() or {}).get("state") or {})

    async def _merge_scoped_state(self, ref, delta: dict[str, Any]):
        if not delta:
            return
        current = await self._read_state(ref)
        current.update(delta)
        await ref.set({"state": current}, merge=True)

    async def _merged(self, session: Session) -> Session:
        app_state = await self._read_state(self._app_ref(session.app_name))
        user_state = await self._read_state(self._user_ref(session.app_name, session.user_id))
        for k, v in app_state.items():
            session.state[State.APP_PREFIX + k] = v
        for k, v in user_state.items():
            session.state[State.USER_PREFIX + k] = v
        return session

    # ------------------------------------------------------------------ API
    @override
    async def create_session(self, *, app_name: str, user_id: str,
                             state: dict[str, Any] | None = None,
                             session_id: str | None = None) -> Session:
        session_id = (session_id or "").strip() or uuid.uuid4().hex
        ref = self._session_ref(app_name, user_id, session_id)
        if (await ref.get()).exists:
            raise AlreadyExistsError(f"Session with id {session_id} already exists.")

        deltas = _session_util.extract_state_delta(state or {})
        await self._merge_scoped_state(self._app_ref(app_name), deltas["app"])
        await self._merge_scoped_state(self._user_ref(app_name, user_id), deltas["user"])

        now = time.time()
        session_state = _session_util.make_json_safe_state(deltas["session"]) if deltas["session"] else {}
        await ref.set({
            "app_name": app_name, "user_id": user_id, "session_id": session_id,
            "state": session_state, "last_update_time": now, "event_seq": 0,
        })
        session = Session(app_name=app_name, user_id=user_id, id=session_id,
                          state=dict(session_state), last_update_time=now)
        return await self._merged(session)

    @override
    async def get_session(self, *, app_name: str, user_id: str, session_id: str,
                          config: GetSessionConfig | None = None) -> Session | None:
        ref = self._session_ref(app_name, user_id, session_id)
        snap = await ref.get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}

        events: list[Event] = []
        async for ev_snap in ref.collection("events").order_by("seq").stream():
            ev = ev_snap.to_dict() or {}
            try:
                events.append(Event.model_validate_json(ev["event"]))
            except Exception as e:  # never fail a whole session on one bad record
                logger.warning(f"Skipping unreadable event {ev_snap.id}: {e}")

        if config:
            if config.after_timestamp is not None:
                events = [e for e in events if e.timestamp >= config.after_timestamp]
            if config.num_recent_events is not None:
                events = events[-config.num_recent_events:] if config.num_recent_events else []

        session = Session(app_name=app_name, user_id=user_id, id=session_id,
                          state=dict(data.get("state") or {}), events=events,
                          last_update_time=float(data.get("last_update_time") or 0.0))
        return await self._merged(session)

    async def _sessions_for_user(self, app_name: str, user_id: str) -> list[Session]:
        out = []
        async for s in self._user_ref(app_name, user_id).collection("sessions").stream():
            d = s.to_dict() or {}
            out.append(await self._merged(Session(
                app_name=app_name, user_id=d.get("user_id", user_id), id=d.get("session_id", s.id),
                state=dict(d.get("state") or {}), last_update_time=float(d.get("last_update_time") or 0.0))))
        return out

    @override
    async def list_sessions(self, *, app_name: str, user_id: str | None = None) -> ListSessionsResponse:
        sessions: list[Session] = []
        if user_id is not None:
            sessions = await self._sessions_for_user(app_name, user_id)
        else:
            async for u in self._app_ref(app_name).collection("users").stream():
                uid = u.id.replace("%2F", "/")
                sessions.extend(await self._sessions_for_user(app_name, uid))
        sessions.sort(key=lambda s: (s.last_update_time, s.user_id, s.id))
        return ListSessionsResponse(sessions=sessions)

    @override
    async def delete_session(self, *, app_name: str, user_id: str, session_id: str) -> None:
        ref = self._session_ref(app_name, user_id, session_id)
        async for ev in ref.collection("events").stream():
            await ev.reference.delete()
        await ref.delete()

    @override
    async def get_user_state(self, *, app_name: str, user_id: str) -> dict[str, Any]:
        return await self._read_state(self._user_ref(app_name, user_id))

    @override
    async def append_event(self, session: Session, event: Event) -> Event:
        if event.partial:
            return event
        event = await super().append_event(session, event)  # updates in-memory session, trims temp: keys
        session.last_update_time = event.timestamp

        ref = self._session_ref(session.app_name, session.user_id, session.id)
        snap = await ref.get()
        data = (snap.to_dict() or {}) if snap.exists else {}
        seq = int(data.get("event_seq") or 0) + 1

        stored_state = dict(data.get("state") or {})
        if event.actions and event.actions.state_delta:
            deltas = _session_util.extract_state_delta(event.actions.state_delta)
            await self._merge_scoped_state(self._app_ref(session.app_name), deltas["app"])
            await self._merge_scoped_state(self._user_ref(session.app_name, session.user_id), deltas["user"])
            stored_state.update(_session_util.make_json_safe_state(deltas["session"]))

        await ref.collection("events").document(f"{seq:08d}_{_key(event.id)}").set({
            "seq": seq, "timestamp": event.timestamp, "author": event.author,
            "event": event.model_dump_json(exclude_none=True, by_alias=True),
        })
        await ref.set({
            "app_name": session.app_name, "user_id": session.user_id, "session_id": session.id,
            "state": stored_state, "last_update_time": event.timestamp, "event_seq": seq,
        }, merge=True)
        return event

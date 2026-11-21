"""Agent session state must survive a process restart (Firestore in prod, SQLite locally)."""
import os
import tempfile

import pytest
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.genai import types

from moneytrace.state.firestore_session import FirestoreSessionService
from tests_v2.fake_firestore import FakeFirestore

APP, USER = "moneytrace", "usr_demo_victim_1"


def _event(author, text, delta=None):
    return Event(author=author, invocation_id="inv-1",
                 content=types.Content(role="model", parts=[types.Part(text=text)]),
                 actions=EventActions(state_delta=delta or {}))


async def _exercise(make_service):
    svc = make_service()
    s = await svc.create_session(app_name=APP, user_id=USER, state={"case_id": "MT-1", "user:lang": "ta"})
    await svc.append_event(s, _event("coordinator", "delegating to intake_agent",
                                     {"current_agent": "intake_agent", "temp:scratch": 1, "app:version": "v2"}))
    await svc.append_event(s, _event("intake_agent", "case structured", {"case": {"amount": 18500}}))

    restarted = make_service()  # new instance == new process; only the backing store is shared
    got = await restarted.get_session(app_name=APP, user_id=USER, session_id=s.id)
    assert got is not None
    assert [e.author for e in got.events] == ["coordinator", "intake_agent"]
    assert got.state["case_id"] == "MT-1"
    assert got.state["current_agent"] == "intake_agent"
    assert got.state["case"] == {"amount": 18500}
    assert got.state["user:lang"] == "ta"
    assert got.state["app:version"] == "v2"
    assert "temp:scratch" not in got.state

    listed = await restarted.list_sessions(app_name=APP, user_id=USER)
    assert [x.id for x in listed.sessions] == [s.id]
    await restarted.delete_session(app_name=APP, user_id=USER, session_id=s.id)
    assert await restarted.get_session(app_name=APP, user_id=USER, session_id=s.id) is None


async def test_firestore_session_survives_restart():
    store = FakeFirestore()
    await _exercise(lambda: FirestoreSessionService(client=store))


async def test_sqlite_session_survives_restart():
    from google.adk.sessions.sqlite_session_service import SqliteSessionService
    path = os.path.join(tempfile.mkdtemp(), "sessions.db")
    await _exercise(lambda: SqliteSessionService(path))


@pytest.mark.skipif(not os.environ.get("FIRESTORE_EMULATOR_HOST") and not os.environ.get("TEST_FIRESTORE_PROJECT"),
                    reason="needs the Firestore emulator or a real project")
async def test_real_firestore_survives_restart():
    project = os.environ.get("TEST_FIRESTORE_PROJECT", "demo-moneytrace")
    await _exercise(lambda: FirestoreSessionService(project=project, root_collection="adk_sessions_test"))

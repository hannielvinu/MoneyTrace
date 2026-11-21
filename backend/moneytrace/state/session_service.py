"""
Session-service factory for the ADK runner.

SESSION_BACKEND:
  firestore -> FirestoreSessionService (production, Cloud Run)
  sqlite    -> ADK SqliteSessionService on a local file (dev; survives restarts)
  memory    -> ADK InMemorySessionService (unit tests)
  auto      -> firestore when GOOGLE_CLOUD_PROJECT is set, otherwise sqlite
"""

import os
import logging
from functools import lru_cache

from google.adk.sessions.base_session_service import BaseSessionService

from moneytrace.config import get_settings

logger = logging.getLogger("moneytrace.state")

_DEFAULT_SQLITE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "db", "adk_sessions.db")


def resolve_backend() -> str:
    s = get_settings()
    backend = (s.session_backend or "auto").lower()
    if backend == "auto":
        backend = "firestore" if s.firestore_project else "sqlite"
    return backend


@lru_cache(maxsize=1)
def get_session_service() -> BaseSessionService:
    backend = resolve_backend()
    s = get_settings()
    if backend == "firestore":
        from moneytrace.state.firestore_session import FirestoreSessionService
        logger.info(f"ADK sessions: Firestore (project={s.firestore_project}, db={s.firestore_database})")
        return FirestoreSessionService(project=s.firestore_project, database=s.firestore_database,
                                       root_collection=s.firestore_collection)
    if backend == "sqlite":
        from google.adk.sessions.sqlite_session_service import SqliteSessionService
        path = os.environ.get("SESSION_SQLITE_PATH", _DEFAULT_SQLITE)
        logger.info(f"ADK sessions: SQLite file {path}")
        return SqliteSessionService(path)
    from google.adk.sessions.in_memory_session_service import InMemorySessionService
    logger.info("ADK sessions: in-memory")
    return InMemorySessionService()

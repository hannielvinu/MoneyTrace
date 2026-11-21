"""
Shared fixtures for the v2 test suite.

Every test runs against a throw-away database and with all external
integrations (Gemini, Sarvam, Cognee, n8n) unconfigured, so the suite is
deterministic and makes no network calls.
"""
import os
import sys
import tempfile

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

_TMP_DIR = tempfile.mkdtemp(prefix="moneytrace-test-")
_TEST_DB = os.path.join(_TMP_DIR, "test.db")

# Must be set before any moneytrace module is imported.
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_TEST_DB}")
os.environ["MONEYTRACE_TESTING"] = "1"
os.environ["SESSION_BACKEND"] = "memory"
os.environ["OTEL_EXPORTER"] = "none"
for _k in ("GEMINI_API_KEY", "LLM_API_KEY", "GOOGLE_API_KEY", "SARVAM_API_KEY",
           "COGNEE_API_KEY", "COGNEE_BASE_URL", "N8N_WEBHOOK_URL"):
    os.environ[_k] = ""

# Stop python-dotenv from re-populating keys from a developer's local .env
import dotenv  # noqa: E402
dotenv.load_dotenv = lambda *a, **k: False


@pytest.fixture(scope="session")
def app():
    from moneytrace.db import database
    database.init_db(force_reseed=True)
    from moneytrace.main import app as fastapi_app
    return fastapi_app


@pytest.fixture()
def no_sleep(monkeypatch):
    """Remove the cosmetic pacing delays in the pipeline."""
    import asyncio
    real_sleep = asyncio.sleep

    async def fast_sleep(_delay=0, *a, **k):
        await real_sleep(0)

    import moneytrace.services.investigation_agent as ia
    monkeypatch.setattr(ia.asyncio, "sleep", fast_sleep)
    yield


@pytest.fixture()
def client(app, no_sleep):
    from fastapi.testclient import TestClient
    with TestClient(app) as c:
        yield c


def _login(client, email, password):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def victim_headers(client):
    return _login(client, "victim@moneytrace.in", "victim123")


@pytest.fixture()
def victim2_headers(client):
    return _login(client, "victim2@moneytrace.in", "victim123")


@pytest.fixture()
def operator_headers(client):
    return _login(client, "operator@moneytrace.in", "operator123")

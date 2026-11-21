# MoneyTrace v2 — Implementation Plan

Status: **approved 2026-11-21; built phase by phase** (see "Decisions and deviations" at the end).
Companion to `docs/V2_SPEC.md`.

## 1. What exists today (from reading the repo)

| Area | Where | Notes |
|---|---|---|
| FastAPI app, JWT roles, SSE, SPA routes | `backend/moneytrace/main.py`, `auth.py`, `services/event_bus.py` | Raw `sqlite3` SQL is also written directly in `main.py` (incident insert, dashboard counts) |
| 12-milestone pipeline | `services/investigation_agent.py` → `run_investigation_pipeline()` | One linear async function that emits the 12 SSE events. Calls Cognee, Gemini, n8n and Sarvam TTS |
| Gemini | `services/gemini_service.py` | `google-genai` with an AI Studio API key (`GEMINI_API_KEY`/`LLM_API_KEY`), not Vertex AI |
| Storage | `db/database.py` | SQLite. 8 tables; `init_db(force_reseed)` seeds data from `data/synthetic_incidents.py` |
| Voice | `services/sarvam_service.py`, `services/voice_response.py` | Sarvam STT/TTS, en/hi/ta/kn, with labelled fallbacks |
| Classifier benchmark | `backend/evaluation/generate_dataset.py`, `evaluator.py`, `latest_run.json` | Rule-based classifier, 400-row test split. Saved run: accuracy 0.865, macro-F1 0.8737 |
| Acceptance test | `backend/test_acceptance.py` | Needs a live server on :8000, **asserts `GEMINI LIVE`** (needs a working Gemini key) |
| Legacy / unused | `backend/function_app.py`, `api/`, `agents/`, `bot/`, `pipeline/`, `tests/`, `evaluation/evaluate.py` | Old Azure "FraudShield" code. `tests/` imports `azure.functions`, and `evaluate.py` calls a dead Azure URL. |
| Deploy | `Dockerfile`, `render.yaml` | Render free plan, SQLite baked into the image |

## 2. Problems I found that touch the spec's "no invented numbers" rule

These are existing behaviours, not things I'll add. They matter because the resume claims sit on top of them:

1. **Screenshot parsing is a stub.** `/api/portal/upload-screenshot` always returns amount ₹18,500 and `kyc-update.pay@ybl`, with a fixed confidence of 0.88. The transaction ID is built from the digits in the filename. → Plan: real extraction with Gemini vision (structured output). The stub stays only as a fallback, labelled `"provider": "fallback"`.
2. **Hard-coded scores in the pipeline:** `risk_score: 0.94`, `confidence: 0.94`, and fixed red flags in `SIGNALS_ANALYZED`. The ledger match is also forced: any narrative containing "kyc" maps to `TXN784219`. → The ReAct investigation agent will compute these through tools. Where nothing is computed, the value becomes `null` instead of a made-up number.
3. **Dashboard clusters are hard-coded** in `main.py` (8/12/6/9 incidents, ₹384,000 and so on). → Compute them from the `incidents` table grouped by `shared_cluster`/`scam_type`.

I'll fix these as part of Phases 1 and 4 unless you say otherwise.

## 3. Layout of new code

All Python stays under `backend/` so the existing `moneytrace.*` imports keep working:

```
Makefile                         (repo root) dev / test / eval / ingest / load / deploy
RESULTS.md                       (repo root, final phase)
.github/workflows/ci.yml         Phase 6
backend/
  pytest.ini                     limits pytest to tests_v2/ (skips the legacy Azure tests)
  tests_v2/                      new unit tests
  moneytrace/config.py           one settings object (DATABASE_URL, model names, prices, flags)
  moneytrace/db/                 database.py rewritten on SQLAlchemy Core; same function names
  alembic/ + alembic.ini         migrations
  moneytrace/state/              Firestore + in-memory ADK session services
  moneytrace/agents/             ADK coordinator, intake, investigation, guidance, grounding
  moneytrace/telemetry.py        OpenTelemetry setup + token/cost accounting
  rag/                           sources.yaml, ingest.py, retriever.py, raw/ (gitignored), STATS.md
  evaluation/rag_golden.jsonl, rag_eval.py
  scripts/load_test.py, create_operator.py, usage_summary.py, deploy_cloudrun.sh
  results/                       baseline/, rag_eval/, load/  (raw output of every run)
```

## 4. Phase by phase

**Phase 0 — Baseline.**
- Add: `Makefile`, `backend/pytest.ini`, `tests_v2/` with tests for the auth guard, amount parser, entity extraction, the event order of `run_investigation_pipeline` (external calls mocked), and the DB helpers.
- Run: the classifier eval. Raw output goes to `results/baseline/`.
- Run: the acceptance test locally. I'll report exactly what passes. The `GEMINI LIVE` assertion fails without a key.
- No behaviour changes.

**Phase 1 — Storage.**
- Rewrite `db/database.py` on SQLAlchemy Core. Every public function keeps the same name and return shape, so callers don't change.
- Move the raw SQL in `main.py` and `investigation_agent.py` into DB helpers. That's needed because `?` placeholders break on Postgres.
- Add an Alembic baseline migration for all 8 tables, plus the `vector` extension when running on Postgres.
- Add `moneytrace/state/firestore_session.py`: a `BaseSessionService` subclass, with ADK's `InMemorySessionService` for tests.
- Local Postgres 16 is in this container. I'll build pgvector from source if I can. If I can't, the Postgres tests run in CI with the `pgvector/pgvector` Docker image.
- Untrack the committed `*.db` files and gitignore them.

**Phase 2 — Corpus.**
- Add `rag/sources.yaml` (**you review it before ingestion**), plus `rag/ingest.py` with robots.txt check, cache, pypdf/BeautifulSoup, about 600-token chunks with 100 overlap, a content hash, and an upsert.
- Embeddings: the model name comes from config. The default is `gemini-embedding-001` on Vertex AI, and I'll confirm its current dimension in the docs.
- Real counts go in `rag/STATS.md`.

**Phase 3 — Retrieval.**
- Add `rag/retriever.py`: pgvector cosine plus `ts_rank` full-text search, merged with RRF (k=60), returning the top 5.
- An optional reranker sits behind `RAG_RERANK=0/1`. I keep it only if recall@5 measurably improves.
- An ADK tool `search_advisories` returns `Citation(doc_id, title, issuer, url, section, text, score)`.

**Phase 4 — ADK agents.** Files in `moneytrace/agents/`: `coordinator.py`, `intake.py`, `investigation.py`, `guidance.py`, `grounding.py`, `redact.py`, `schemas.py`.
- The coordinator is an `LlmAgent` with `sub_agents=[intake, investigation, guidance]`.
- **Milestone safety:** each SSE milestone is emitted by the tool or callback that produces it, not by the LLM. After the ADK run, a guard emits any milestone that was skipped, in order, flagged `"via": "guard"`. The 12 events and their order therefore stay guaranteed.
- `AGENT_ENGINE=adk|legacy` (default `adk`). The legacy function stays available as a rollback.
- Grounding: an LLM checker judges each step against its cited chunk. If a step is unsupported it gets one regeneration; if it's still unsupported, the safe fallback text is used.
- PII redaction runs before every LLM call.

**Phase 5 — Observability.**
- `opentelemetry-instrumentation-fastapi` plus ADK's built-in spans.
- Locally the exporter is the console; in the cloud it's `opentelemetry-exporter-gcp-trace`.
- A per-request accounting object collects token usage from every model response. Prices and the INR rate live in `config.py`, with the date I checked them.
- Add `scripts/load_test.py`, with output to `results/load/`.

**Phase 6 — RAG eval.**
- I draft 100 golden questions in en/hi/ta. **You review the gold `doc_id`s.**
- `rag_eval.py` measures recall@5 and grounded % with an LLM judge, and builds the random 20 for your hand-check (agreement is computed from your labels).
- Add a RAG card on `/evaluation` and a `/api/evaluation/rag` endpoint.
- CI gate: unit tests plus a 20-question subset, compared against `results/rag_eval/baseline.json`.

**Phase 7 — Cloud Run.**
- Rework the `Dockerfile`: no SQLite baked in, migrations run on start.
- Add `scripts/deploy_cloudrun.sh`: service account plus IAM roles, Secret Manager, `--add-cloudsql-instances`, `asia-south1`, `--min-instances 0`, and a budget alert.
- **I give you the commands and only run them after you OK each one.** Render stays until Cloud Run is verified.

**Phase 8 — Help desk.**
- Add a disclaimer banner with 1930 and cybercrime.gov.in, a consent checkbox (the server rejects reports without it), and a privacy note.
- Add `scripts/create_operator.py` and a `usage_events` table with no PII.
- Add `scripts/usage_summary.py` (daily table) and `docs/OPERATOR_GUIDE.md`.
- Create `docs/discovery/` templates for you to fill in.

## 5. What stays as-is

Sarvam STT/TTS and voice responses, the Cognee service, the n8n service, JWT/auth logic, the SSE bus, and the frontend except the additions above. The classifier benchmark code and its numbers also stay unchanged. The legacy Azure code is left untouched; I'll only exclude it from pytest.

## 6. Risks

- **LLM non-determinism in the coordinator** can break the milestone order. Mitigation: the milestone guard plus the legacy flag described in Phase 4.
- **The acceptance test needs live keys.** It asserts `GEMINI LIVE`. I'll extend it to also accept a live Vertex status. With no keys it can't pass, and I'll say so rather than weaken it.
- **Corpus size.** From this container `rbi.org.in` is reachable. `npci.org.in` returns 403, and `cybercrime.gov.in`, `cert-in.org.in` and `rbikehtahai.rbi.org.in` don't respond. The real document count may come in well under 120. Options: (a) run `make ingest` on your laptop or from a Cloud Run job, (b) widen this environment's network. **The count will be whatever actually ingests.**
- **Cost.** Cloud SQL bills while the instance is running, even with no traffic, unlike Cloud Run at min-instances 0. I'll use the smallest shared-core tier and give you a stop/start command.
- **Postgres semantics.** `id` is built as `MT-{10482+COUNT+1}`, which can race under Postgres concurrency. I'll switch it to a sequence while keeping the same `MT-` format.

## 7. What I need from you

1. OK on this plan, including the three stub/hard-code fixes in section 2.
2. Your **GCP project ID**, and how I should authenticate. This container has no gcloud credentials. You can run the gcloud commands yourself, or grant a short-lived credential.
3. A Gemini/Vertex credential for local development. The acceptance test and the agents need live model calls. The proxy here lists `generativelanguage.googleapis.com`, but my test call came back 401.
4. Past commits are authored "agnes beulah". From now on every commit uses `Hanniel Vinu A <hannielvinu@gmail.com>` with no co-author lines. Rewriting the old commits as well would need a force-push of history. **Tell me if you want that.** Otherwise I leave them alone.

## 8. Decisions and deviations (recorded during the build)

| Topic | Spec | What was built | Why |
|---|---|---|---|
| Hosting | Cloud Run + Cloud SQL + Vertex AI | **Hybrid free**: Cloud Run, Firestore, Cloud Trace, Secret Manager on GCP free tier; **Neon** Postgres + pgvector; **Gemini API** (AI Studio key) for LLM + `gemini-embedding-001` | Hanniel chose a ₹0 setup; Cloud SQL / Vertex have no permanent free tier. Code still supports Cloud SQL (`DATABASE_URL`) and Vertex (`GOOGLE_GENAI_USE_VERTEXAI=true`). |
| Delegation | `LlmAgent(sub_agents=...)` | Coordinator `LlmAgent` delegates via `AgentTool` (agent-as-a-tool) | Deterministic hand-back after each specialist; LLM `transfer_to_agent` chains were unreliable. Still hierarchical delegation, visible in traces. |
| Milestones | same 12 SSE events | Ordered `MilestoneEmitter` + guard | Agents call tools in any order; UI needs canonical order. Guard completes skipped work and marks it `via: guard`. |
| Dev models | Gemini | NVIDIA-hosted `nemotron-3.5-lightning` / `minimax-m3.1-flash` and `nemotron-3-embed-1b` (2048-d, no HNSW → exact scan) via LiteLLM in the build sandbox | No working Gemini key in the sandbox. All dev-model numbers are labelled; re-run with Gemini. |
| Corpus size | ~120 docs | 49 docs ingested from the sandbox (131 candidates in `sources.yaml`) | PIB, NPCI, I4C, cybercrime.gov.in and the RBI PDF host refused the sandbox (robots 403 / bot challenge, never bypassed). `make ingest --refetch` from a laptop. |
| Human review gate | CRITICAL → sign-off | `HUMAN_REVIEW_REQUIRED` event always emitted (milestone count stays 12) with `required: true/false`; only CRITICAL sets `requires_human_review` | Keeps the 12-milestone contract while honouring the rule. |
| Cloud Run CPU | min instances 0 | `--no-cpu-throttling`, max 1 instance | Pipeline runs after the HTTP response; request-based billing would throttle it. |
| Grounded % | judge + human 20 | Strict judge; uncited mandatory channel line and safe fallback count as NOT grounded | Conservative definition so the metric cannot be inflated by the fallback. |

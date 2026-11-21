# MoneyTrace — Build Spec for Claude Code

## How to use this file

1. Save this file in the MoneyTrace repo as `docs/V2_SPEC.md`.
2. Open Claude Code in the repo root.
3. Paste the **Kickoff prompt** below.
4. Let it work one phase at a time. After each phase, check what it reports and say "continue to the next phase".
5. When everything is done, open `RESULTS.md` and copy the real measured numbers into your resume.

### Kickoff prompt (paste this into Claude Code)

```
Read docs/V2_SPEC.md completely, then read the whole repo (README, backend/moneytrace, evaluation/, test_acceptance.py, render.yaml, Dockerfile) so you understand the current system before changing anything.

Then write a short plan in docs/V2_PLAN.md: which files you will add or change in each phase, what stays as-is, and any risk to existing features. Show me the plan and wait for my OK.

After I approve, build the spec phase by phase (Phase 0 to Phase 8). After each phase:
- run the existing tests plus the new ones and fix failures,
- commit with a clear message,
- give me a 5-line summary: what changed, how to verify it, what's next.

Hard rules:
- Never invent, estimate or hard-code any metric. Every number in RESULTS.md must come from a script you actually ran, with the command and raw output saved.
- Keep every existing feature working: the 12-milestone pipeline, SSE updates, Sarvam voice, screenshot parsing, Cognee graph, n8n webhook, JWT roles, the /evaluation page.
- Ask me before anything that costs money or needs my Google Cloud account (creating instances, enabling APIs, deploying).
- No secrets in code or git. Use .env locally and Secret Manager in the cloud.
```

---

## Goal

Upgrade MoneyTrace from a hackathon demo into a production-grade, multi-agent fraud-response system on Google Cloud, and launch it as a UPI-scam help desk with VIT's WhiteHats cybersecurity club. When finished, every one of these must be true, with real measured numbers:

| Resume claim | What must exist |
|---|---|
| Agentic data pipeline: unstructured data (voice in 4 languages, screenshots, text) → structured case records | Existing intake, wrapped as an ADK agent, writing structured cases to Postgres |
| ADK coordinator delegating to intake, ReAct investigation and guidance agents | Google ADK multi-agent system with hierarchical delegation |
| RAG over ~120 RBI/NPCI fraud advisories, Vertex AI embeddings, pgvector vector database on Cloud SQL for PostgreSQL, with cited sources | Ingestion pipeline + retrieval + citations in every guidance answer |
| recall@5 and % of answers fully grounded on a 100-question eval set | Eval scripts + golden set + saved results |
| Deployed on Cloud Run behind JWT-secured REST APIs, Firestore for agent state management | Live Cloud Run URL; Firestore-backed session state |
| OpenTelemetry tracing on every request; p95 latency and cost per request (INR) | Traces visible in Cloud Trace; load-test script reporting p50/p95, tokens/sec, INR per request |
| 2 technical discovery sessions with WhiteHats; help desk launched with club members as operators | Help-desk mode, operator accounts, usage logging (done by Hanniel with the club) |

---

## Architecture (target)

```
Victim (web portal: voice / screenshot / text)
        │  JWT (USER)
        ▼
FastAPI on Cloud Run ──► OpenTelemetry ──► Cloud Trace
        │
        ▼
ADK Coordinator Agent  (hierarchical delegation)
   ├── Intake Agent        → transcribe (Sarvam), parse screenshot, extract structured case
   ├── Investigation Agent → ReAct tools: ledger lookup, signal scoring, Cognee graph search
   └── Guidance Agent      → RAG over RBI/NPCI advisories (pgvector), cited steps
        └── Grounding check: every step must cite a retrieved chunk, else safe fallback
        │
        ├── Cloud SQL for PostgreSQL + pgvector  (cases, audit, ledger, advisory chunks)
        ├── Firestore                            (agent session / conversation state)
        ├── Vertex AI                            (Gemini models + text embeddings)
        ├── Cognee Cloud                         (existing knowledge graph)
        └── n8n webhook                          (existing escalation)
        │
Fraud operator (WhiteHats member)  ── JWT (FRAUD_OPERATOR) ──► dashboard, sign-off on CRITICAL
```

---

## Phase 0 — Baseline and safety net

1. Run the app locally and `python -X utf8 test_acceptance.py`. Record what passes.
2. Run `evaluation/generate_dataset.py` then `evaluation/evaluator.py`. Confirm the existing classifier numbers reproduce (accuracy ~86.5%, macro-F1 ~87.4%). Save output to `results/baseline/`.
3. Add `pytest` unit tests around anything you will refactor (pipeline stages, auth guard, intake parsing).
4. Add a `Makefile` (or `scripts/`) with: `make dev`, `make test`, `make eval`, `make load`, `make deploy`.

**Done when:** baseline results saved, all existing tests pass.

---

## Phase 1 — Move storage to production-grade services

Cloud Run is stateless, so SQLite will lose data on restart.

1. Introduce SQLAlchemy (or keep the existing layer) with a `DATABASE_URL` setting. Support SQLite locally and **Cloud SQL for PostgreSQL** in the cloud.
2. Migrate tables: incidents, audit trail, ledger. Add Alembic migrations. Keep `init_db(force_reseed=True)` working.
3. Enable the `vector` extension in Postgres (`CREATE EXTENSION IF NOT EXISTS vector;`).
4. Add **Firestore** for agent session state (conversation turns, current case, agent hand-offs). Implement it as an ADK-compatible session service (a custom `BaseSessionService` backed by Firestore), with a local in-memory fallback for tests.

**Ask Hanniel before:** creating the Cloud SQL instance and Firestore database. Use the smallest Cloud SQL tier.

**Done when:** the full 12-milestone pipeline runs end to end on Postgres, and session state survives a server restart.

---

## Phase 2 — Advisory corpus and ingestion pipeline (RAG data)

1. Create `rag/sources.yaml` listing official fraud-response sources. Only use official, publicly available pages and PDFs, for example:
   - RBI circulars and master directions on digital payment fraud, customer liability for unauthorised electronic transactions, and fraud reporting
   - RBI public awareness material (e.g. "RBI Kehta Hai" / BE(A)WARE)
   - NPCI UPI safety guidance and dispute-resolution process
   - National Cyber Crime Reporting Portal (cybercrime.gov.in) guidance and the 1930 helpline process
   - CERT-In and I4C advisories on financial fraud
   Store for each: title, issuer, URL, date, language.
   Target about 120 documents, but **use the real count** of documents actually ingested.
   Tell Hanniel to review `sources.yaml` before ingestion.
2. `rag/ingest.py`:
   - download each source (respect robots.txt; cache raw files in `rag/raw/`),
   - extract text (use Document AI if enabled, otherwise `pypdf` / HTML parsing),
   - clean and chunk (~500–800 tokens, 100 overlap, keep headings),
   - embed with a **Vertex AI text embedding model** (read the model name from config, e.g. `text-embedding-005` or `gemini-embedding-001`; check current Vertex AI docs for the recommended model and its dimension),
   - upsert into a Postgres `advisory_chunks` table: `id, doc_id, title, issuer, url, published_date, section, text, embedding vector(N), tsv tsvector`.
   - create an HNSW (or IVFFlat) index on the embedding and a GIN index on `tsv`.
3. Make ingestion idempotent (hash of content) and log counts: documents, chunks, failures.

**Done when:** `make ingest` loads the corpus, and `rag/STATS.md` shows the real number of documents and chunks.

---

## Phase 3 — Retrieval with citations

1. `rag/retriever.py`: hybrid search = pgvector cosine top-k + Postgres full-text top-k, merged with reciprocal-rank fusion; return top 5 chunks with metadata.
2. Optional reranker (Vertex AI ranking API or a Gemini re-score) behind a config flag; measure whether it helps before keeping it.
3. Expose as an ADK tool: `search_advisories(query: str, k: int = 5) -> list[Citation]`.

**Done when:** unit tests show relevant chunks for sample questions, each with title + URL.

---

## Phase 4 — Rebuild the agents on Google ADK

Use the `google-adk` Python package. Check the current ADK docs for exact class names and APIs before writing code.

1. **Coordinator agent** (`LlmAgent` with `sub_agents`): reads the incoming report, decides which specialist to call, and keeps the case moving through the existing 12 milestones (emit the same SSE events).
2. **Intake agent:** wraps existing Sarvam transcription and screenshot parsing as tools; outputs a structured case record (Pydantic schema: amount, transaction ID, counterparty UPI, phone, timestamps, fraud type guess, language).
3. **Investigation agent (ReAct):** tools for ledger lookup, signal/severity scoring, Cognee graph search for related incidents and mule rings. It reasons, calls tools, observes, and repeats until it can justify a severity.
4. **Guidance agent:** builds step-by-step victim guidance **only from retrieved advisory chunks**, citing the source for each step (title + URL). Always includes the official reporting channels (1930 helpline, cybercrime.gov.in, the victim's bank).
5. **Grounding check (self-reflection):** after the guidance agent drafts an answer, a checker verifies every step is supported by a cited chunk. Unsupported steps are removed or regenerated once; if still unsupported, return a safe fallback ("Report immediately on 1930 / cybercrime.gov.in and contact your bank") rather than guessing.
6. Keep the human-in-the-loop rule: CRITICAL cases go to `HUMAN_REVIEW_REQUIRED` and need operator sign-off.
7. Use a fast model (Gemini Flash) for routine steps and a stronger model only where needed; make model names configurable.
8. Redact obvious personal data (phone numbers, account numbers) from text sent to the LLM where it is not needed, and keep the raw values only in the database.

**Done when:** the acceptance test passes using the ADK agents, and a demo case shows the coordinator's delegation in the logs/traces.

---

## Phase 5 — Observability: tracing, latency, tokens, cost

1. Add OpenTelemetry to FastAPI and to every agent and tool call (use ADK's built-in tracing where available). Export to **Cloud Trace** in the cloud and to the console locally.
2. Record per request: total latency, per-agent latency, input/output tokens per model call, tokens/sec, and cost.
3. Cost per request: tokens × current Vertex AI price per model (put prices in config, with the date you checked them) × an INR exchange rate from config. Save the config values used in `RESULTS.md`.
4. `scripts/load_test.py`: send 100 realistic requests (mixed languages and fraud types) to the deployed API and report p50, p95, mean latency, average tokens/sec, average INR per request. Save raw results to `results/load/`.

**Done when:** a trace for one request shows coordinator → sub-agents → tools in Cloud Trace, and the load test produces a results file.

---

## Phase 6 — RAG evaluation set and metrics

1. Build `evaluation/rag_golden.jsonl` with **100 questions** a scam victim would really ask (include Tamil, Hindi and English, and different fraud types: fake KYC, wrong UPI collect request, OTP/screen-share scams, fake customer care, investment/task scams).
   For each: the question, the gold advisory `doc_id`s that answer it, and a short reference answer.
   Draft them with the LLM from the corpus, then **show them to Hanniel for review**. He must check and fix at least the gold documents, because these labels decide the metric.
2. `evaluation/rag_eval.py`:
   - **recall@5**: share of questions where at least one gold document is in the top 5 retrieved.
   - **Fully grounded %**: share of answers where every guidance step is supported by a cited chunk, judged by an LLM judge with a strict rubric. Also have Hanniel hand-check a random 20 and report the agreement between judge and human.
   - Save per-question results and the summary to `results/rag_eval/`.
3. Add the RAG metrics to the existing `/evaluation` page, clearly labelled with the eval-set size and date.
4. Add a GitHub Actions workflow: run unit tests and a small RAG eval subset on every pull request; fail if recall or grounding drops below the last saved baseline.

**Done when:** `make eval` prints recall@5 and grounded % from real runs, saved in `results/`.

---

## Phase 7 — Deploy to Google Cloud Run

1. Dockerfile for Cloud Run (listens on `$PORT`).
2. Secrets in **Secret Manager**: LLM keys, Sarvam, Cognee, n8n webhook, JWT secret, DB password. Use a dedicated service account with only the IAM roles it needs (Cloud SQL Client, Vertex AI User, Firestore User, Secret Accessor, Cloud Trace Agent).
3. Connect Cloud Run to Cloud SQL (Cloud SQL connector or Unix socket).
4. Deploy with `gcloud run deploy` (give Hanniel the exact commands, and ask before running them). Region close to users (e.g. `asia-south1`).
5. Keep the Render deployment until Cloud Run is verified, then update the live URL in the README.
6. Set a **budget alert** on the Google Cloud project, and set min instances to 0 so it costs nothing when idle.

**Done when:** the live Cloud Run URL serves the portal, the acceptance test passes against it, and traces show up in Cloud Trace.

---

## Phase 8 — Help-desk launch with WhiteHats

Code part (Claude Code):
1. Help-desk mode on the portal: a clear banner stating it is an independent student project, not an official government or bank service, with the 1930 helpline and cybercrime.gov.in always visible.
2. A consent checkbox before a report is submitted; a short privacy note on what is stored and for how long.
3. A script to create `FRAUD_OPERATOR` accounts for club members.
4. Usage logging (no personal data): reports received, cases by type, escalations, operator sign-offs, median time to first guidance. Save a daily summary table so Hanniel can later report real usage numbers.
5. An operator quick-start guide in `docs/OPERATOR_GUIDE.md`.

Human part (Hanniel, not Claude Code):
- Run **2 technical discovery sessions** with WhiteHats before launch: what scams students actually face, what operators need on the dashboard, what language and channel victims prefer. Write short notes in `docs/discovery/session-1.md` and `session-2.md`, and turn the findings into issues.
- Launch the help desk with club members as operators.

---

## Final deliverable: RESULTS.md

Claude Code must produce `RESULTS.md` containing, each with the exact command, date and raw-output file:

- Number of advisory documents and chunks ingested
- recall@5 on the RAG eval set (and the set size)
- Fully grounded % (and judge-vs-human agreement on the 20 hand-checked answers)
- p50 and p95 latency from the load test against the live Cloud Run URL
- Average tokens/sec
- Average cost per request in INR (with the prices and exchange rate used)
- Existing classifier results (re-run, unchanged)
- Live URL, and links to a sample trace and the GitHub Actions run

Then Hanniel updates the resume with these real numbers. If a real number differs from the resume target (120 documents, recall@5 0.86, 88% grounded, p95 3.2 s, ₹0.30), **the resume changes, not the number.**

---

## Acceptance checklist

- [ ] All existing tests pass, plus new unit tests
- [ ] Pipeline runs on Cloud SQL Postgres; agent state in Firestore survives restarts
- [ ] Advisory corpus ingested; real document and chunk counts recorded
- [ ] ADK coordinator delegates to intake, ReAct investigation and guidance agents
- [ ] Every guidance step carries a citation; ungrounded answers fall back safely
- [ ] OpenTelemetry traces visible in Cloud Trace
- [ ] Load test run against the live URL; p50/p95, tokens/sec and INR per request saved
- [ ] 100-question RAG eval set reviewed by Hanniel; recall@5 and grounded % saved
- [ ] GitHub Actions runs tests and an eval gate on pull requests
- [ ] Live on Cloud Run with Secret Manager, least-privilege service account, budget alert
- [ ] Help-desk mode, consent, disclaimer, operator accounts, usage logging
- [ ] 2 discovery sessions documented; help desk launched with WhiteHats
- [ ] README updated with the live demo link at the top
- [ ] RESULTS.md complete with real, reproducible numbers

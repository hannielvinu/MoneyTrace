# MoneyTrace v2 — measured results

_Generated 2026-11-21 23:08 UTC by `python backend/scripts/make_results.py` from the raw result files listed in each section. Do not edit numbers by hand: re-run the command._

> **Read this first.** Every number below comes from a script that was actually run; the command, date and raw
> output file are given for each. Where a run used development substitutes (NVIDIA-hosted models instead of
> Gemini, a local server instead of Cloud Run, a draft eval set not yet reviewed by Hanniel) that is stated next
> to the number. Those numbers must be re-measured with the production setup before they go on a resume.

## 1. Advisory corpus

| Metric | Value |
|---|---|
| Documents ingested | **49** |
| Chunks ingested | **1106** |
| Embedding model | nvidia / `nvidia/nemotron-3-embed-1b` (2048-d) |
| Date | 2026-11-21T21:05:29.098870+00:00 |
| Command | `cd backend && python -m rag.ingest` |
| Raw output | `backend/results/ingest/ingest_20261121T210529Z.json`, `backend/rag/STATS.md` |

Sources: official RBI, NPCI, CERT-In, PIB, DoT (Sanchar Saathi), SEBI and Income Tax pages listed in `backend/rag/sources.yaml`. Sites that refused the cloud sandbox (PIB press releases, NPCI, I4C, cybercrime.gov.in, RBI PDF host) are listed as `unfetched` and can be ingested from a laptop (`python -m rag.ingest --refetch`).

## 2. RAG evaluation

| Metric | Value |
|---|---|
| Eval set | `evaluation/rag_golden.jsonl`, **100 questions**, status: draft |
| recall@5 | **0.72** (72/100) |
| recall@5 by language | en: 0.7, ta: 0.72, hi: 0.76 |
| recall@5 without query translation (ablation) | 0.69 |
| Fully grounded answers (independent auditor `minimaxai/minimax-m3.1-flash`, quote-verified) | **48.0 %** (48/100) |
| Pipeline self-check grounded (optimistic, for reference) | 100.0 % |
| First drafts fully grounded (before self-check) | 61.0 % |
| Safe-fallback answers | 0 |
| Answers with errors | 0 |
| Mean guidance latency | 16183.5 ms |
| Judge vs human agreement | pending: Hanniel fills `human_check.csv`, then `python -m evaluation.judge_agreement <run_dir>` |
| Embedding / guidance / judge models | `nvidia/nemotron-3-embed-1b` / `nvidia/nemotron-3.5-lightning-30b-a3b` / `nvidia/nemotron-3.5-lightning-30b-a3b` (nvidia) |
| Corpus at eval time | 49 documents, 1106 chunks |
| Date | 2026-11-21T22:07:58.501134+00:00 |
| Command | `cd backend && python -m evaluation.rag_eval --concurrency 5 --ablation` |
| Raw output | `backend/results/rag_eval/RAG_20261121T220703Z/per_question.jsonl`, `summary.json`, `human_check.csv` |

Caveat: the questions were drafted by an LLM from corpus passages (gold = the source passage's document) and are awaiting Hanniel's review of the gold labels; drafting from a passage makes retrieval easier than organic questions.

## 3. Latency, throughput and cost

| Metric | Value |
|---|---|
| Target | http://127.0.0.1:8000 |
| Requests | 24 (24 completed, 0 errors), concurrency 4 |
| Intake API latency p50 / p95 / mean | 13.1 / 684.2 / 100.8 ms |
| Time to guidance p50 / p95 / mean (full agent pipeline) | 47533.8 / 59991.0 / 47445.7 ms |
| Agent status per request | LLM LIVE (nvidia): 21, AGENTS FAILED (rules fallback): 3 |
| Avg output tokens/sec (model wall time) | 142.25 |
| Avg tokens per request (in / out) | 59247.2 / 5130.7 over 36.83 model calls |
| Avg cost per request | **not measured**: development models on a free endpoint, no price configured (re-run with Gemini and PRICE_* set) |
| Models | nvidia/nemotron-3.5-lightning-30b-a3b |
| Pricing used | prices {"nvidia/nemotron-3.5-lightning-30b-a3b": "not configured"} USD/1M tokens (checked not set - prices not verified); USD→INR 84.0 (config default; set USD_TO_INR to the RBI reference rate on the day you report) |
| Date | 2026-11-21T23:04:20.198239+00:00 |
| Command | `cd backend && python scripts/load_test.py --base-url http://127.0.0.1:8000 --n 24 --concurrency 4 --poll-timeout 500` |
| Raw output | `backend/results/load/LOAD_20261121T225909Z/requests.jsonl`, `summary.json`; all runs: `backend/results/load/README.md` |

Caveat: run against a local server (not Cloud Run) with NVIDIA-hosted development models, which have no price in the table (cost ₹0) and are far slower than Gemini Flash. Re-run against the live Cloud Run URL with Gemini.

## 4. Tracing

OpenTelemetry spans for FastAPI, the pipeline (`moneytrace.pipeline`, `coordinator`, `guard`, `grounding_check`) and ADK's own agent / LLM / tool spans. Exporter `OTEL_EXPORTER=gcp` sends them to Cloud Trace in production.
Sample trace from a local run: `backend/results/traces/sample_trace.md`.

## 5. Existing classifier benchmark (re-run, unchanged)

| Metric | Value |
|---|---|
| Test rows | 400 of 2000 (synthetic, seed 42) |
| Accuracy | 0.865 |
| Macro-F1 | 0.8737 |
| Binary fraud F1 | 0.9483 |
| Run | `RUN_20261121_184701_f1229c` at 2026-11-21T18:47:01.128698Z |
| Command | `cd backend && python evaluation/generate_dataset.py && python evaluation/evaluator.py` |
| Raw output | `backend/results/baseline/classifier_eval.log`, `backend/evaluation/runs/<run_id>/` |

## 6. Tests

- Unit tests: `cd backend && python -m pytest -q` (SQLite) and with `TEST_DATABASE_URL=postgresql+psycopg://...` (Postgres + pgvector).
- Acceptance test against the local v2 stack: `backend/results/acceptance_v2_local.log`.
- CI: `.github/workflows/ci.yml` (unit tests on SQLite + pgvector Postgres; RAG gate once the secrets are added).

## 7. Deployment

- Live URL: _not deployed yet_ (see `docs/HANNIEL_TODO.md` §C).
- Sample Cloud Trace link: _after deployment_.
- GitHub Actions run: _after the first pull request_.


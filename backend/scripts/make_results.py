"""
Render RESULTS.md from the raw result files (no number is typed by hand).

    python scripts/make_results.py

Sources:
  rag/STATS.md + results/ingest/*.json          corpus counts
  results/rag_eval/latest.json (+ run dir)      recall@5, fully grounded %, judge agreement
  results/load/latest.json (+ run dir)          p50 / p95 latency, tokens/sec, INR per request
  evaluation/latest_run.json                    classifier benchmark (unchanged)
  results/acceptance_v2_local.log               acceptance test output
"""
import glob
import json
import os
from datetime import datetime, timezone

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(BACKEND)


def _load(path):
    p = os.path.join(BACKEND, path)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def rel(p):
    return "backend/" + p if p and not p.startswith("backend/") else p


def main():
    ingest_logs = sorted(glob.glob(os.path.join(BACKEND, "results", "ingest", "ingest_*.json")))
    ingest = json.load(open(ingest_logs[-1], encoding="utf-8")) if ingest_logs else None
    rag = _load("results/rag_eval/latest.json")
    load = _load("results/load/latest.json")
    clf = _load("evaluation/latest_run.json")
    agree = None
    if rag and rag.get("run_dir"):
        agree = _load(os.path.join(rag["run_dir"], "judge_agreement.json"))

    L = ["# MoneyTrace v2 — measured results", "",
         f"_Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} by `python backend/scripts/make_results.py` "
         "from the raw result files listed in each section. Do not edit numbers by hand: re-run the command._", "",
         "> **Read this first.** Every number below comes from a script that was actually run; the command, date and raw",
         "> output file are given for each. Where a run used development substitutes (NVIDIA-hosted models instead of",
         "> Gemini, a local server instead of Cloud Run, a draft eval set not yet reviewed by Hanniel) that is stated next",
         "> to the number. Those numbers must be re-measured with the production setup before they go on a resume.", ""]

    L += ["## 1. Advisory corpus", ""]
    if ingest:
        c, e = ingest["corpus"], ingest["embedding"]
        L += ["| Metric | Value |", "|---|---|",
              f"| Documents ingested | **{c['documents']}** |", f"| Chunks ingested | **{c['chunks']}** |",
              f"| Embedding model | {e['provider']} / `{e['model']}` ({e['dim']}-d) |",
              f"| Date | {ingest['finished_at']} |", "| Command | `cd backend && python -m rag.ingest` |",
              f"| Raw output | `{rel(os.path.relpath(ingest_logs[-1], BACKEND))}`, `backend/rag/STATS.md` |", "",
              "Sources: official RBI, NPCI, CERT-In, PIB, DoT (Sanchar Saathi), SEBI and Income Tax pages listed in "
              "`backend/rag/sources.yaml`. Sites that refused the cloud sandbox (PIB press releases, NPCI, I4C, cybercrime.gov.in, "
              "RBI PDF host) are listed as `unfetched` and can be ingested from a laptop (`python -m rag.ingest --refetch`).", ""]
    else:
        L += ["Not run yet.", ""]

    L += ["## 2. RAG evaluation", ""]
    if rag:
        L += ["| Metric | Value |", "|---|---|",
              f"| Eval set | `{rag['eval_set']}`, **{rag['eval_set_size']} questions**, status: {', '.join(rag['review_status'])} |",
              f"| recall@5 | **{rag['recall_at_5']}** ({rag['recall_at_5_hits']}/{rag['eval_set_size']}) |",
              f"| recall@5 by language | {', '.join(f'{k}: {v}' for k, v in rag['recall_at_5_by_language'].items())} |"]
        if "recall_at_5_without_query_translation" in rag:
            L.append(f"| recall@5 without query translation (ablation) | {rag['recall_at_5_without_query_translation']} |")
        if "fully_grounded_pct" in rag:
            L += [f"| Fully grounded answers (independent auditor `{rag.get('eval_judge_model')}`, quote-verified) | **{rag['fully_grounded_pct']} %** ({rag['fully_grounded_count']}/{rag['eval_set_size']}) |",
                  f"| Pipeline self-check grounded (optimistic, for reference) | {rag.get('pipeline_self_check_grounded_pct')} % |",
                  f"| First drafts fully grounded (before self-check) | {rag.get('draft_fully_grounded_pct')} % |",
                  f"| Safe-fallback answers | {rag.get('safe_fallback_count')} |",
                  f"| Answers with errors | {rag.get('answers_with_errors')} |",
                  f"| Mean guidance latency | {rag.get('mean_guidance_latency_ms')} ms |"]
        if agree:
            L.append(f"| Judge vs human agreement ({agree['labelled']} hand-checked) | {agree['agreement']} (Cohen's κ {agree['cohens_kappa']}) |")
        else:
            L.append("| Judge vs human agreement | pending: Hanniel fills `human_check.csv`, then `python -m evaluation.judge_agreement <run_dir>` |")
        L += [f"| Embedding / guidance / judge models | `{rag['embedding_model']}` / `{rag['guidance_model']}` / `{rag['judge_model']}` ({rag['llm_provider']}) |",
              f"| Corpus at eval time | {rag['corpus']['documents']} documents, {rag['corpus']['chunks']} chunks |",
              f"| Date | {rag['date_utc']} |", f"| Command | `cd backend && {rag['command']}` |",
              f"| Raw output | `{rel(rag['run_dir'])}/per_question.jsonl`, `summary.json`, `human_check.csv` |", "",
              "Caveat: the questions were drafted by an LLM from corpus passages (gold = the source passage's document) and are "
              "awaiting Hanniel's review of the gold labels; drafting from a passage makes retrieval easier than organic questions.", ""]
    else:
        L += ["Not run yet.", ""]

    L += ["## 3. Latency, throughput and cost", ""]
    if load:
        L += ["| Metric | Value |", "|---|---|",
              f"| Target | {load['base_url']} |",
              f"| Requests | {load['requests']} ({load['completed']} completed, {load['errors']} errors), concurrency {load['concurrency']} |",
              f"| Intake API latency p50 / p95 / mean | {load['intake_latency_ms']['p50']} / {load['intake_latency_ms']['p95']} / {load['intake_latency_ms']['mean']} ms |",
              f"| Time to guidance p50 / p95 / mean (full agent pipeline) | {load['time_to_guidance_ms']['p50']} / {load['time_to_guidance_ms']['p95']} / {load['time_to_guidance_ms']['mean']} ms |",
              f"| Agent status per request | {', '.join(f'{k}: {v}' for k, v in load.get('ai_status_counts', {}).items())} |",
              f"| Avg output tokens/sec (model wall time) | {load['avg_output_tokens_per_sec']} |",
              f"| Avg tokens per request (in / out) | {load['avg_input_tokens']} / {load['avg_output_tokens']} over {load['avg_model_calls']} model calls |",
              (f"| Avg cost per request | ₹{load['avg_cost_inr_per_request']} |"
               if all(isinstance(v, dict) and (v.get('input_per_m') or v.get('output_per_m'))
                      for v in load['pricing']['prices_usd_per_1m'].values()) and load['pricing']['prices_usd_per_1m']
               else "| Avg cost per request | **not measured**: development models on a free endpoint, no price configured "
                    "(re-run with Gemini and PRICE_* set) |"),
              f"| Models | {', '.join(load['models'])} |",
              f"| Pricing used | prices {json.dumps(load['pricing']['prices_usd_per_1m'])} USD/1M tokens (checked {load['pricing']['checked_on']}); USD→INR {load['pricing']['usd_to_inr']} ({load['pricing']['usd_to_inr_source']}) |",
              f"| Date | {load['date_utc']} |", f"| Command | `cd backend && {load['command']}` |",
              f"| Raw output | `{rel(load['run_dir'])}/requests.jsonl`, `summary.json`; all runs: `backend/results/load/README.md` |", ""]
        if "127.0.0.1" in load["base_url"] or "localhost" in load["base_url"]:
            L += ["Caveat: run against a local server (not Cloud Run) with NVIDIA-hosted development models, which have no price "
                  "in the table (cost ₹0) and are far slower than Gemini Flash. Re-run against the live Cloud Run URL with Gemini.", ""]
    else:
        L += ["Not run yet.", ""]

    traces = os.path.join(BACKEND, "results", "traces", "sample_trace.md")
    L += ["## 4. Tracing", "",
          "OpenTelemetry spans for FastAPI, the pipeline (`moneytrace.pipeline`, `coordinator`, `guard`, `grounding_check`) and "
          "ADK's own agent / LLM / tool spans. Exporter `OTEL_EXPORTER=gcp` sends them to Cloud Trace in production."]
    L += [f"Sample trace from a local run: `backend/results/traces/sample_trace.md`." if os.path.exists(traces) else "No sample trace saved yet.", ""]

    L += ["## 5. Existing classifier benchmark (re-run, unchanged)", ""]
    if clf:
        mc = clf["metrics"]["multi_class"]
        bf = clf["metrics"]["binary_fraud"]
        L += ["| Metric | Value |", "|---|---|",
              f"| Test rows | {clf['test_sample_count']} of {clf['total_benchmark_records']} (synthetic, seed 42) |",
              f"| Accuracy | {mc['accuracy']} |", f"| Macro-F1 | {mc['macro_f1']} |", f"| Binary fraud F1 | {bf.get('f1')} |",
              f"| Run | `{clf['run_id']}` at {clf['timestamp']} |",
              "| Command | `cd backend && python evaluation/generate_dataset.py && python evaluation/evaluator.py` |",
              "| Raw output | `backend/results/baseline/classifier_eval.log`, `backend/evaluation/runs/<run_id>/` |", ""]

    L += ["## 6. Tests", "",
          "- Unit tests: `cd backend && python -m pytest -q` (SQLite) and with `TEST_DATABASE_URL=postgresql+psycopg://...` (Postgres + pgvector).",
          "- Acceptance test against the local v2 stack: `backend/results/acceptance_v2_local.log`.",
          "- CI: `.github/workflows/ci.yml` (unit tests on SQLite + pgvector Postgres; RAG gate once the secrets are added).", ""]
    L += ["## 7. Deployment", "", "- Live URL: _not deployed yet_ (see `docs/HANNIEL_TODO.md` §C).",
          "- Sample Cloud Trace link: _after deployment_.", "- GitHub Actions run: _after the first pull request_.", ""]

    open(os.path.join(ROOT, "RESULTS.md"), "w", encoding="utf-8").write("\n".join(L) + "\n")
    print("wrote RESULTS.md")


if __name__ == "__main__":
    main()

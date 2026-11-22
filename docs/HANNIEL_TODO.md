# What Hanniel needs to do (things Claude Code cannot do from its sandbox)

Status legend: ⬜ to do · ✅ done

## A. Accounts and keys (free)
1. ⬜ **Gemini API key** (free, no card): https://aistudio.google.com/apikey → put it in `backend/.env` as
   `GEMINI_API_KEY=...` and set `LLM_PROVIDER=gemini`, `EMBEDDING_PROVIDER=gemini`.
   For this cloud session, add it in the environment settings as a network secret for host
   `generativelanguage.googleapis.com` with header `x-goog-api-key` (the session's credential form cannot save that header).
2. ✅ **Neon Postgres** — project `holy-bar-58757480`, branch `production`, AWS ap-southeast-1 (Singapore),
   Postgres 18.7 + pgvector 0.8.7. Schema applied and verified (`backend/results/neon/neon_check.log`).
   On your laptop run `neon env pull` (or `neon init` with the same ids) to get `.env.local` with `DATABASE_URL`
   (pooled, for the app) and `DATABASE_URL_UNPOOLED` (direct, used automatically for Alembic migrations).
   Because the database is in Singapore, deploy Cloud Run with `REGION=asia-southeast1`.
3. ⬜ **Google Cloud project** with billing linked (needed even for the free tier). Note the `PROJECT_ID`.

## B. Build the real corpus and numbers (on your laptop)
4. ⬜ Review `backend/rag/sources.yaml` (set `include: false` on anything wrong; edit titles) and
   `backend/rag/source_overrides.yaml` (my exclusions, with reasons).
5. ⬜ Ingest from your laptop. Several sites (PIB, NPCI, I4C, cybercrime.gov.in, RBI PDFs) refused the cloud sandbox,
   so your laptop can fetch many more documents:
   ```bash
   cd backend && pip install -r requirements.txt
   python -m rag.ingest --refetch --reset
   ```
   `rag/STATS.md` then shows the real document / chunk counts.
6. ⬜ Review `backend/evaluation/rag_golden.jsonl` (100 drafted questions). For each row check `gold_doc_ids`
   (add other doc_ids that also answer it, remove wrong ones), fix unnatural questions, then set
   `"review_status": "reviewed"`.
7. ⬜ Run the evaluation and hand-check 20 answers:
   ```bash
   python -m evaluation.rag_eval
   # open results/rag_eval/<run>/human_check.csv, fill human_fully_grounded with 1/0
   python -m evaluation.judge_agreement results/rag_eval/<run>
   cp results/rag_eval/latest_subset.json results/rag_eval/baseline_subset.json   # after a --subset 20 run, for CI
   ```

## C. Deploy (Cloud Run free tier, ask yourself before each step)
8. ⬜ Create `backend/.env.cloud` (gitignored) with `DATABASE_URL` (Neon **pooled** string from `.env.local`), GEMINI_API_KEY, JWT_SECRET, SARVAM_API_KEY,
   COGNEE_API_KEY, N8N_WEBHOOK_URL` (generate JWT_SECRET with `python -c "import secrets;print(secrets.token_urlsafe(48))"`).
9. ⬜ Run, one at a time, reading each step first:
   ```bash
   export PROJECT_ID=<your-project> REGION=asia-southeast1
   bash backend/scripts/deploy_cloudrun.sh check
   bash backend/scripts/deploy_cloudrun.sh apis
   bash backend/scripts/deploy_cloudrun.sh sa
   bash backend/scripts/deploy_cloudrun.sh firestore
   bash backend/scripts/deploy_cloudrun.sh secrets
   bash backend/scripts/deploy_cloudrun.sh deploy
   BILLING_ACCOUNT=<id> BUDGET_INR=500 bash backend/scripts/deploy_cloudrun.sh budget
   bash backend/scripts/deploy_cloudrun.sh verify
   ```
   ⚠️ The deploy uses `--no-cpu-throttling` (instance-based billing, max 1 instance) because the agent pipeline
   runs after the HTTP response. Check the current free tier on https://cloud.google.com/run/pricing first.
10. ⬜ Before the load test, copy the current Gemini prices from https://ai.google.dev/gemini-api/docs/pricing into
    env vars on the Cloud Run service (not secrets), e.g. `PRICE_GEMINI_3_8_FLASH_IN=<usd per 1M input>`,
    `PRICE_GEMINI_3_8_FLASH_OUT=<usd per 1M output>`, `PRICES_CHECKED_ON=<date>`, and `USD_TO_INR=<RBI reference rate>`,
    `USD_TO_INR_SOURCE="RBI reference rate <date>"`. Without them cost is reported as "not configured".
    Note: the dev run averaged ~148k input tokens per case (passages repeated across agent calls) — cutting that is the
    main lever for the ₹/request number.
11. ⬜ Load test against the live URL and look at a trace in Cloud Trace (console → Trace explorer):
    ```bash
    cd backend && python scripts/load_test.py --base-url https://<service>.run.app --n 100 --concurrency 5
    ```
12. ⬜ Demo accounts on Cloud Run: by default they are **not** created (the public dev passwords never work live), and
    the service refuses to start without a real `JWT_SECRET`. For `verify` / the load test, either create real accounts
    (`create_operator.py`, and register a test victim) or deploy once with `SEED_DEMO_USERS=1` plus private
    `DEMO_VICTIM_PASSWORD` / `DEMO_OPERATOR_PASSWORD` env vars, run the tests with the same env vars, then redeploy without them.
13. ⬜ Add GitHub repo secrets `RAG_EVAL_DATABASE_URL` and `GEMINI_API_KEY` to enable the CI RAG gate.

## D. WhiteHats
14. ⬜ Run discovery session 1 and 2; fill in `docs/discovery/session-1.md` / `session-2.md`; open issues for findings.
15. ⬜ Create operator accounts: `python backend/scripts/create_operator.py --csv operators.csv` (columns `email,name`).
16. ⬜ Share `docs/OPERATOR_GUIDE.md` with operators; launch; run `python backend/scripts/usage_summary.py` weekly.

## E. Finally
17. ⬜ Re-run everything with Gemini and replace the dev-provider numbers in `RESULTS.md`; update the resume from
    RESULTS.md only (if a number differs from the target, the resume changes, not the number).

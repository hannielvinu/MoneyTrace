#!/usr/bin/env bash
# MoneyTrace -> Google Cloud Run (hybrid free setup). Run ONE step at a time and read what it does first.
#
#   bash backend/scripts/deploy_cloudrun.sh <step>
#
# Steps (in order):
#   check      show the gcloud account / project that will be used
#   apis       enable Cloud Run, Cloud Build, Artifact Registry, Secret Manager, Firestore, Cloud Trace
#   sa         create the runtime service account with least-privilege roles
#   firestore  create the (default) Firestore database in Native mode (free tier applies to (default) only)
#   secrets    create/update Secret Manager secrets from your local backend/.env.cloud (never committed)
#   deploy     build from source and deploy to Cloud Run (min-instances 0)
#   budget     create a budget alert on the billing account (needs BILLING_ACCOUNT)
#   verify     run the acceptance test against the deployed URL
#
# Required env: PROJECT_ID. Optional: REGION (asia-south1), SERVICE (moneytrace), BILLING_ACCOUNT, BUDGET_INR (500)
# --no-cpu-throttling: the agent pipeline runs as a background task after the intake response; with
# request-based billing Cloud Run would throttle CPU and stall it. Instance-based billing has its own free
# tier - check https://cloud.google.com/run/pricing before deploying; max-instances 1 caps the spend.
# Costs: Cloud Run / Firestore / Cloud Trace / Secret Manager (<= 6 secrets) stay inside Google's always-free
# quotas at this traffic level. Cloud Build has 120 free build-minutes/day. Artifact Registry gives 0.5 GB free
# storage; an image above that costs a few rupees a month - delete old images (step `cleanup`).
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-asia-south1}"
SERVICE="${SERVICE:-moneytrace}"
SA_NAME="${SA_NAME:-moneytrace-run}"
SA="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SECRETS=(DATABASE_URL GEMINI_API_KEY JWT_SECRET SARVAM_API_KEY COGNEE_API_KEY N8N_WEBHOOK_URL)

step="${1:-help}"
case "$step" in
  check)
    gcloud config list
    gcloud projects describe "$PROJECT_ID" --format='value(projectId,projectNumber)'
    ;;
  apis)
    gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
      secretmanager.googleapis.com firestore.googleapis.com cloudtrace.googleapis.com --project "$PROJECT_ID"
    ;;
  sa)
    gcloud iam service-accounts create "$SA_NAME" --display-name "MoneyTrace Cloud Run runtime" --project "$PROJECT_ID" || true
    # Least privilege: Firestore user, Secret accessor, Cloud Trace agent. (Add roles/aiplatform.user only if you
    # switch to Vertex AI, and roles/cloudsql.client only if you move from Neon to Cloud SQL.)
    for role in roles/datastore.user roles/secretmanager.secretAccessor roles/cloudtrace.agent roles/logging.logWriter; do
      gcloud projects add-iam-policy-binding "$PROJECT_ID" --member "serviceAccount:${SA}" --role "$role" --condition=None >/dev/null
      echo "granted $role"
    done
    ;;
  firestore)
    gcloud firestore databases create --database='(default)' --location="$REGION" --type=firestore-native --project "$PROJECT_ID"
    ;;
  secrets)
    ENV_FILE="${ENV_FILE:-$ROOT/backend/.env.cloud}"
    [ -f "$ENV_FILE" ] || { echo "Create $ENV_FILE with ${SECRETS[*]} (one KEY=value per line). It is gitignored."; exit 1; }
    for name in "${SECRETS[@]}"; do
      value="$(grep -E "^${name}=" "$ENV_FILE" | head -1 | cut -d= -f2-)"
      [ -n "$value" ] || { echo "skip $name (empty)"; continue; }
      gcloud secrets describe "$name" --project "$PROJECT_ID" >/dev/null 2>&1 || \
        gcloud secrets create "$name" --replication-policy=automatic --project "$PROJECT_ID"
      printf '%s' "$value" | gcloud secrets versions add "$name" --data-file=- --project "$PROJECT_ID" >/dev/null
      # keep only the newest version enabled (free tier: 6 active versions)
      for v in $(gcloud secrets versions list "$name" --filter='state=enabled' --format='value(name)' --sort-by=~createTime --project "$PROJECT_ID" | tail -n +2); do
        gcloud secrets versions disable "$v" --secret "$name" --project "$PROJECT_ID" >/dev/null
      done
      echo "secret $name updated"
    done
    ;;
  deploy)
    set_secrets=""
    for name in "${SECRETS[@]}"; do
      if gcloud secrets describe "$name" --project "$PROJECT_ID" >/dev/null 2>&1; then
        set_secrets="${set_secrets:+$set_secrets,}${name}=${name}:latest"
      fi
    done
    gcloud run deploy "$SERVICE" --source "$ROOT" --project "$PROJECT_ID" --region "$REGION" \
      --service-account "$SA" --allow-unauthenticated \
      --min-instances 0 --max-instances 1 --cpu 1 --memory 1Gi --concurrency 40 --timeout 300 \
      --no-cpu-throttling \
      --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT_ID},AGENT_ENGINE=adk,SESSION_BACKEND=firestore,OTEL_EXPORTER=gcp,LLM_PROVIDER=gemini,EMBEDDING_PROVIDER=gemini,EMBEDDING_MODEL=gemini-embedding-001,EMBEDDING_DIM=768,HELPDESK_MODE=1" \
      --set-secrets "$set_secrets"
    gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT_ID" --format='value(status.url)'
    ;;
  budget)
    BILLING_ACCOUNT="${BILLING_ACCOUNT:?set BILLING_ACCOUNT (gcloud billing accounts list)}"
    gcloud billing budgets create --billing-account "$BILLING_ACCOUNT" --display-name "MoneyTrace monthly" \
      --budget-amount "${BUDGET_INR:-500}INR" --threshold-rule=percent=0.5 --threshold-rule=percent=0.9 \
      --threshold-rule=percent=1.0 --filter-projects "projects/${PROJECT_ID}"
    ;;
  verify)
    URL="$(gcloud run services describe "$SERVICE" --region "$REGION" --project "$PROJECT_ID" --format='value(status.url)')"
    (cd "$ROOT/backend" && MONEYTRACE_BASE_URL="$URL" python -X utf8 test_acceptance.py)
    ;;
  cleanup)
    gcloud artifacts docker images list "${REGION}-docker.pkg.dev/${PROJECT_ID}/cloud-run-source-deploy" --include-tags --project "$PROJECT_ID"
    echo "Delete old digests with: gcloud artifacts docker images delete <IMAGE>@<DIGEST>"
    ;;
  *)
    sed -n '2,22p' "$0"
    ;;
esac

# MoneyTrace — Autonomous Financial Emergency Response

MoneyTrace turns a victim's first report into an autonomous financial emergency response for payment fraud and cyber financial crimes.

Built for the **Paytm Build for India AI Hackathon — Autonomous AI Teammates track**.

---

## The Problem

Financial fraud victims face immediate distress:
> *"My money is gone. What do I do now?"*

Traditional systems provide static forms, slow ticket resolution, or siloed dashboards. MoneyTrace delivers an autonomous financial emergency teammate that instantly ingests reports, matches transactions, discovers hidden fraud syndicates, seals forensic evidence packages, executes workflows via n8n, and provides victims with reassuring, user-safe guidance.

---

## Non-Negotiable Real Integrations & Architecture

MoneyTrace connects real sponsor services on its primary path:

1. **Sarvam AI (`SARVAM_API_KEY`)**:
   - Real browser microphone recording using `MediaRecorder`.
   - Audio file upload to `/api/voice/transcribe`.
   - Live Speech-to-Text supporting English, Hindi (हिन्दी), Tamil (தமிழ்), and Kannada (ಕನ್ನಡ).
   - If unconfigured or offline: transparently labelled as `"Sarvam Unconfigured — Local Resilience Mode"` (no deceptive mocks).

2. **n8n Pro (`N8N_WEBHOOK_URL`)**:
   - Real webhook integration receiving structured incident payloads.
   - Dispatches `N8N_WORKFLOW_STARTED`, validates incident, and registers `N8N_WORKFLOW_COMPLETED`.
   - Template workflow ready for import into your n8n workspace (`backend/n8n_moneytrace_workflow.json`).

3. **Cognee Cloud (`COGNEE_API_KEY`, `COGNEE_BASE_URL`)**:
   - Real knowledge graph integration: **ADD -> COGNIFY -> SEARCH**.
   - Emits `RELATED_INCIDENTS_FOUND` and `GRAPH_READY`.
   - Uncovers shared phone numbers, UPI VPAs, bank accounts, and fake KYC domains.
   - If unconfigured or offline: explicitly labelled as `"Cognee unavailable — local resilience mode"`.

4. **Single AI Investigation Agent**:
   - Combines victim story, synthetic financial ledger truth, risk signals, and relationship graphs.
   - Compiles downloadable cryptographic Evidence Packages (`EVD-<incident_id>`).
   - Generates tailored multilingual protective guidance and enforces human review on high-risk actions.

5. **Server-Side Authentication & Data Isolation**:
   - Role-based authorization (`USER` vs `FRAUD_OPERATOR`).
   - Users can **only** see their own incidents and safe protective notifications. Internal graphs, analyst notes, and other victims' personal information are strictly isolated.
   - Fraud operators have full access to the live pipeline, case workspace, and fraud console.

---

## Four Synchronized Live Views

Open four browser tabs simultaneously on `http://127.0.0.1:8000`:

| Tab | Route | Role | Purpose |
|---|---|---|---|
| **Tab 1** | `/portal` | `USER` | Victim emergency intake: live mic recording, text narrative, optional screenshot with OCR extraction, instant case reference, and safe protective guidance. |
| **Tab 2** | `/investigations` | `FRAUD_OPERATOR` | Live investigation pipeline with dotted progress advancing strictly on real SSE backend events (`INCIDENT_CREATED` → `N8N_WORKFLOW_COMPLETED` → `USER_NOTIFICATION_CREATED`). |
| **Tab 3** | `/cases/:incident_id` | `FRAUD_OPERATOR` | Interactive case workspace with dynamic canvas syndicate graph (click to inspect), red flags, JSON evidence package modal, and operator signoff. |
| **Tab 4** | `/dashboard` | `FRAUD_OPERATOR` | Fraud operations console with active incident metrics, syndicate cluster exposure, and live intake feed updating automatically via SSE. |

---

## Demo Credentials

Judges can switch demo accounts directly in the UI via the top-right role switcher:

| Role | Email | Password | Permissions |
|---|---|---|---|
| **USER (Victim 1)** | `victim@moneytrace.in` | `victim123` | Can access `/portal`. Isolated reports & notifications only. |
| **USER (Victim 2)** | `victim2@moneytrace.in` | `victim123` | Isolated secondary victim (validates data isolation). |
| **FRAUD_OPERATOR** | `operator@moneytrace.in` | `operator123` | Full access to `/investigations`, `/cases/:id`, and `/dashboard`. |

---

## Environment Setup

Create `.env` inside `backend/` (referenced in `.env.example`):

```bash
# LLM Engine
LLM_API_KEY=your_llm_api_key_here

# Sarvam AI (Speech-to-Text & Text-to-Speech)
SARVAM_API_KEY=your_sarvam_api_key_here

# Cognee Cloud
COGNEE_API_KEY=your_cognee_api_key_here
COGNEE_BASE_URL=https://api.cognee.ai

# n8n Pro Autonomous Response Webhook
N8N_WEBHOOK_URL=https://your-n8n-instance.com/webhook/moneytrace-incident

# JWT Authentication Secret
JWT_SECRET=moneytrace-super-secret-key-2026-secure

PORT=8000
```

> **Note on Fallbacks**: If API keys are not supplied, MoneyTrace runs in **Local Resilience Mode**. All fallbacks are explicitly labelled with their provider status so judges can verify execution transparency.

---

## Running the Application

### 1. Install Python Dependencies

```powershell
cd backend
pip install -r requirements.txt
```

### 2. Reset & Seed Database (Optional)

```powershell
python -c "from moneytrace.db.database import init_db; init_db(force_reseed=True)"
```

### 3. Start the Server

```powershell
python -m uvicorn moneytrace.main:app --host 127.0.0.1 --port 8000
```

Open: `http://127.0.0.1:8000`

---

## Running Automated Acceptance Tests

To verify authentication, data isolation, Sarvam STT, Cognee graph discovery, n8n webhook dispatch, and user notifications:

```powershell
$env:PYTHONIOENCODING="utf-8"
python test_acceptance.py
```

Expected output:
```text
✓ Health Check Passed
✓ Victim 1 logged in successfully
✓ Fraud Operator logged in successfully
✓ Data Isolation Confirmed: Victim blocked with HTTP 403 on operator endpoint
✓ Operator Dashboard Loaded: 122+ active incidents
✓ Sarvam STT Result: Provider='Sarvam Cloud AI' / 'Local Resilience Mode'
✓ Incident Registered: MT-10606, Message: 'Report submitted — investigation in progress.'
✓ Victim 1 isolated reports confirmed
✓ Victim 2 Isolation Verified: 0 leak of MT-10606
✓ User Notification Created: 'Investigation Complete: Protective Actions Required'
✓ Evidence Package: Severity=CRITICAL, Intel Layer='Cognee Cloud API'
✓ Persistent Event Bus recorded 12 milestones
✓ Operator Signoff Executed on MT-10606
🎉 ALL ACCEPTANCE CRITERIA TESTS PASSED SUCCESSFULLY! 🎉
```

---

## n8n Workflow Verification

1. Open your n8n workspace.
2. Click **Import from File** and select `backend/n8n_moneytrace_workflow.json`.
3. Set your production webhook URL to `N8N_WEBHOOK_URL` in `backend/.env`.
4. Submit any fraud report in Tab 1 (`/portal`).
5. Open n8n **Executions** tab to see the live execution trigger and structured incident payload.

---

## Verifying Sponsor Integrations

- **Sarvam AI**: Select Hindi (`hi`), Tamil (`ta`), or Kannada (`kn`) in Tab 1, press the microphone button, and narrate your report. The transcript box will update with the transcription and display `Sarvam Cloud AI (Live STT)`.
- **Cognee**: Look at Tab 3 (`/cases/:id`). The syndicate intelligence badge confirms `Cognee Cloud API` (or `Cognee unavailable — local resilience mode` if unconfigured) and renders the interactive canvas graph linking connected victim incidents.

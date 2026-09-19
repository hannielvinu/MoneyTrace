# MoneyTrace — Autonomous Financial Emergency Response

[![Live Demo](https://img.shields.io/badge/Live%20Demo-trycloudflare.com-00BAF2?style=for-the-badge&logo=cloudflare&logoColor=white)](https://use-pearl-hist-separately.trycloudflare.com)
[![Paytm Hackathon](https://img.shields.io/badge/Paytm%20Build%20for%20India-AI%20Hackathon%202026-002970?style=for-the-badge)](https://github.com/hannielvinu/MoneyTrace)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Gemini Cloud AI](https://img.shields.io/badge/Google%20Gemini-Cloud%20AI-8E75B2?style=for-the-badge&logo=google&logoColor=white)](https://deepmind.google/technologies/gemini/)

> **MoneyTrace turns a victim's first report into an autonomous financial emergency response for payment fraud and cyber financial crimes.**  
> Built for the **Paytm Build for India AI Hackathon — Autonomous AI Teammates track**.

---

## 🌐 Live Deployment

- **Live URL**: [https://use-pearl-hist-separately.trycloudflare.com](https://use-pearl-hist-separately.trycloudflare.com)
- **API Health Endpoint**: [https://use-pearl-hist-separately.trycloudflare.com/api/health](https://use-pearl-hist-separately.trycloudflare.com/api/health)
- **Evaluation Benchmark View**: [https://use-pearl-hist-separately.trycloudflare.com/evaluation](https://use-pearl-hist-separately.trycloudflare.com/evaluation)

---

## 💡 The Problem

When cyber financial fraud strikes, victims face critical distress:
> *"My money is gone. Who do I call? What do I do right now?"*

Traditional fraud handling offers static complaint forms, delayed human ticket queues, and fragmented banking databases. During the golden hour of financial crime, funds hop across synthetic UPI handles and mule accounts in seconds.

**MoneyTrace provides an autonomous financial emergency teammate** that:
1. Instantly ingests victim reports via multilingual speech, narrative text, or payment screenshots with OCR.
2. Cross-references internal financial ledgers to match transactions and extract counterparties.
3. Automatically uncovers hidden scam networks and syndicated mule clusters via Cognee Cloud.
4. Synthesizes an investigative forensic evidence package (`EVD-<id>`) with Gemini Cloud AI.
5. Dispatches automated protective mitigation workflows via n8n.
6. Delivers user-safe, reassuring guidance to victims while isolating confidential intelligence from non-operators.

---

## 🔬 Empirical Verification & Accuracy Benchmark

MoneyTrace includes a scientifically defensible, out-of-sample evaluation system (**Held-Out Blind Test Partition, Seed 42, 2,000 Records**) measuring structured fraud classification performance:

### 1. Multi-Class Classification (7 Classes)
| Metric | Benchmark Result |
|---|---|
| **Overall Accuracy** | **86.50%** |
| **Macro F1 (Unweighted)** | **87.37%** |
| **Weighted F1** | **86.57%** |
| **Macro Precision** | **88.88%** |
| **Macro Recall** | **86.58%** |

#### Per-Class Performance Breakdown (400 Held-Out Blind Test Cases)
| Fraud Category | Precision | Recall | F1-Score | Support |
|---|---|---|---|---|
| **LEGITIMATE** | 77.89% | 88.10% | 82.68% | 84 |
| **UPI_FRAUD** | 84.88% | 93.59% | 89.02% | 78 |
| **PHISHING** | 88.52% | 80.60% | 84.38% | 67 |
| **IMPERSONATION** | 91.30% | 79.25% | 84.85% | 53 |
| **INVESTMENT_FRAUD** | 100.00% | 81.25% | 89.66% | 48 |
| **ACCOUNT_TAKEOVER** | 79.55% | 89.74% | 84.34% | 39 |
| **WRONG_TRANSFER** | 100.00% | 93.55% | 96.67% | 31 |

### 2. Binary Fraud Detection (Malicious Fraud vs Legitimate/Wrong Transfer)
| Metric | Score | Notes |
|---|---|---|
| **Binary Fraud F1** | **94.83%** | Harmonic mean of precision and recall |
| **Binary Accuracy** | **92.75%** | Correct fraud vs non-fraud determinations |
| **Precision** | **96.38%** | Minimizes wrongful accusations of legitimate transactions |
| **Recall** | **93.33%** | Catches 266 out of 285 true fraud incidents |
| **False Positive Rate** | **8.70%** | Non-fraud flagged as fraud |
| **False Negative Rate** | **6.67%** | True fraud missed |

### 3. Rigorous Anti-Leakage & Provenance Controls
- **Zero Label Leakage**: Ground-truth labels (`fraud_class`, `is_fraud`) are strictly insulated from the inference pipeline.
- **Overlapping Features**: Legitimate transactions and fraud categories share overlapping amount distributions (₹150 to ₹45,000) and channels.
- **Cryptographic Provenance**: Canonical benchmark dataset SHA-256: `cdef60222fe47f2ff8569233ec8b02083d5844d5d42a4a1dfcc7de9f652cb6e9`.
- **Reproducibility**: Run `python evaluation/generate_dataset.py && python evaluation/evaluator.py`.

---

## ⚡ Architecture & Live Integrations

```
[Victim Browser / Portal]
      │ (Voice Audio / Text / Screenshot)
      ▼
[Sarvam AI Cloud STT] ──► [FastAPI Gateway] ──► [Persistent SQLite Store]
                                 │
                 ┌───────────────┴───────────────┐
                 ▼                               ▼
    [Gemini Cloud AI Investigator]    [Cognee Cloud Graph Engine]
      (Forensic Analysis & Story)      (Syndicate & Mule Network)
                 │                               │
                 └───────────────┬───────────────┘
                                 ▼
                     [n8n Autonomous Webhook]
                   (Triage & Response Orchestration)
                                 │
                                 ▼
                    [Real-Time SSE Event Bus]
             (Live Telemetry & Synchronized Dashboard)
```

1. **Sarvam AI Cloud STT (`SARVAM_API_KEY`)**:
   - Real in-browser microphone capture with `MediaRecorder`.
   - Real-time Speech-to-Text supporting English, Hindi (हिन्दी), Tamil (தமிழ்), and Kannada (ಕನ್ನಡ).
2. **Google Gemini Cloud AI (`LLM_API_KEY`)**:
   - Live multi-modal forensic narrative reasoning.
   - Extracts red flags, severity ratings, and compiles legal/banking evidence packages.
3. **Cognee Cloud (`COGNEE_API_KEY`, `COGNEE_BASE_URL`)**:
   - Real semantic graph pipeline: **ADD → COGNIFY → SEARCH**.
   - Identifies connected victims and discovers shared scammer infrastructure (phone, UPI VPAs, domains).
4. **n8n Workflow Automation (`N8N_WEBHOOK_URL`)**:
   - Webhook trigger on new incidents with structured validation.
   - Escalates high-risk cases and triggers notifications with execution tracking.
5. **Real-Time Server-Sent Events (SSE)**:
   - High-throughput event bus emitting 12 distinct milestone events across the lifecycle.
   - Live telemetry with real-time entrance highlights, dynamic progress bars, and syndicate similarity popups.

---

## 🖥️ Four Synchronized Role-Based Views

| View | Route | Role | Description |
|---|---|---|---|
| **Victim Emergency Intake** | `/portal` | `USER` | Live voice recording (Sarvam STT), OCR screenshot parsing, transaction matching, and user-safe protective guidance. |
| **Live Pipeline** | `/investigations` | `FRAUD_OPERATOR` | Real-time stage progress bars, active node pulsing, live telemetry feed with auto-dimming highlights, and syndicate alerts. |
| **Case Intelligence Workspace** | `/cases/:id` | `FRAUD_OPERATOR` | Interactive Canvas scam network graph, evidence JSON viewer, linked victims, and operator human-in-the-loop signoff. |
| **Command Console** | `/dashboard` | `FRAUD_OPERATOR` | Fleet-wide fraud analytics, cluster exposure tracking, and real-time incident queue. |
| **Accuracy Benchmark** | `/evaluation` | `FRAUD_OPERATOR` | Live evaluation dashboard showing multi-class matrices, binary accuracy, per-class F1, and methodology audit. |

---

## 🔑 Demo Access & Personas

Switch between personas directly inside the application interface:

| Persona | Email | Password | Role | Permissions |
|---|---|---|---|---|
| **Victim 1** | `victim@moneytrace.in` | `victim123` | `USER` | Emergency intake, personal incident status, safe advisories. |
| **Victim 2** | `victim2@moneytrace.in` | `victim123` | `USER` | Isolated tenant verifying cross-user data protection. |
| **Fraud Operator** | `operator@moneytrace.in` | `operator123` | `FRAUD_OPERATOR` | Full console, pipeline triage, intelligence graph, signoff. |

---

## 🚀 Local Development Setup

### 1. Clone the Repository
```bash
git clone https://github.com/hannielvinu/MoneyTrace.git
cd MoneyTrace/backend
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables
Create `.env` in `backend/` (refer to `.env.example`):
```env
LLM_API_KEY=your_gemini_api_key
SARVAM_API_KEY=your_sarvam_api_key
COGNEE_API_KEY=your_cognee_api_key
COGNEE_BASE_URL=https://api.cognee.ai
N8N_WEBHOOK_URL=https://your-n8n-instance.com/webhook/moneytrace-incident
JWT_SECRET=moneytrace-secure-jwt-secret-key-2026
PORT=8000
```

### 4. Initialize Database
```bash
python -c "from moneytrace.db.database import init_db; init_db(force_reseed=True)"
```

### 5. Launch the Server
```bash
python -m uvicorn moneytrace.main:app --host 127.0.0.1 --port 8000
```
Open: `http://127.0.0.1:8000`

---

## 🧪 Comprehensive Acceptance Tests

Run the full end-to-end verification suite:
```bash
python -X utf8 test_acceptance.py
```

Validates:
- Health check & API routes
- Tenant data isolation (USER vs FRAUD_OPERATOR HTTP 403 enforcement)
- Sarvam Cloud AI voice transcription
- Gemini Cloud AI investigation & structured story generation
- Cognee syndicate correlation & graph discovery
- n8n autonomous webhook dispatch & execution
- Complete 12-milestone persistent event bus lifecycle

---

## 👥 Team & Hackathon Submission

- **Repository**: [https://github.com/hannielvinu/MoneyTrace.git](https://github.com/hannielvinu/MoneyTrace.git)
- **Live Deployment**: [https://use-pearl-hist-separately.trycloudflare.com](https://use-pearl-hist-separately.trycloudflare.com)
- **Track**: Paytm Build for India AI Hackathon — Autonomous AI Teammates
- **Author**: [@hannielvinu](https://github.com/hannielvinu)

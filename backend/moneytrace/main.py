"""
MoneyTrace Unified FastAPI Server.
Provides:
- JWT Authentication endpoints (/api/auth/login, /api/auth/me)
- Server-Sent Events real-time event bus (/api/events)
- User Portal API (/api/portal/reports, /api/portal/my-reports, /api/portal/notifications)
- Voice STT & TTS with Sarvam AI (/api/voice/transcribe, /api/voice/synthesize)
- Screenshot upload & simulated/OCR metadata extraction (/api/portal/upload-screenshot)
- Fraud Operations Investigation endpoints (/api/incidents, /api/incidents/{id}, /api/incidents/{id}/investigate, /api/dashboard)
- Protected role-based access control (USER vs FRAUD_OPERATOR)
- Single-Page Application routes (/portal, /investigations, /cases/:id, /dashboard, /login)
"""

import os
import re
import json
import uuid
import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Form, BackgroundTasks, Depends
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from moneytrace.db.database import (
    init_db, get_incident, create_incident, list_incidents, get_dashboard_metrics,
    get_cluster_summary, record_usage_event, get_usage_summary,
    add_audit_log, get_transaction, get_user_by_email, get_user_by_id,
    hash_password, get_user_incidents, get_user_notifications,
    get_incident_events, update_incident_record
)
from moneytrace.auth import (
    create_access_token, get_current_user, require_operator, get_optional_user
)
from moneytrace.services.investigation_agent import run_investigation_pipeline
from moneytrace.services.sarvam_service import transcribe_audio, synthesize_guidance
from moneytrace.services.voice_response import generate_voice_response, resolve_amount_with_provenance
from moneytrace.services.cognee_service import build_compact_graph_nodes_and_edges
from moneytrace.services.event_bus import register_subscriber, unregister_subscriber, emit_event

# Initialize logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("moneytrace.server")

# Base directory paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_ROOT = os.path.dirname(os.path.dirname(BASE_DIR))
PUBLIC_DIR = os.path.join(WORKSPACE_ROOT, "public")
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOADS_DIR = os.path.join(STATIC_DIR, "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

# Ensure DB initialized
init_db(force_reseed=False)

app = FastAPI(
    title="MoneyTrace API",
    description="Autonomous financial emergency-response teammate for payment fraud victims",
    version="1.0.0"
)

from moneytrace.telemetry import setup_tracing
setup_tracing(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount public assets (contains moneytrace_logo.png)
if os.path.isdir(PUBLIC_DIR):
    app.mount("/public", StaticFiles(directory=PUBLIC_DIR), name="public")

# Mount frontend static directory
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# Pydantic Schemas
class LoginRequest(BaseModel):
    email: str
    password: str


class CreatePortalReportRequest(BaseModel):
    narrative: str
    language: Optional[str] = "en"
    transaction_id: Optional[str] = None
    amount: Optional[float] = None
    screenshot_url: Optional[str] = None
    ocr_data: Optional[Dict[str, Any]] = None
    consent: bool = False


class RespondRequest(BaseModel):
    action: Optional[str] = "escalate"


# ==========================================
# Health Check Endpoint
# ==========================================

@app.get("/api/health")
async def health():
    return {
        "status": "healthy",
        "service": "MoneyTrace Autonomous Response Teammate",
        "timestamp": datetime.now().isoformat()
    }


# ==========================================
# Authentication Endpoints
# ==========================================

@app.post("/api/auth/login")
async def api_login(req: LoginRequest):
    user = get_user_by_email(req.email)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    if user["password_hash"] != hash_password(req.password):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    token = create_access_token(user["id"], user["email"], user["role"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user["name"],
            "role": user["role"]
        }
    }


@app.get("/api/auth/me")
async def api_me(current_user: Dict[str, Any] = Depends(get_current_user)):
    return {
        "id": current_user["id"],
        "email": current_user["email"],
        "name": current_user["name"],
        "role": current_user["role"]
    }


# ==========================================
# Real-Time SSE Event Bus (/api/events)
# ==========================================

@app.get("/api/events")
async def sse_event_stream(request: Request):
    """
    Server-Sent Events endpoint powering real-time synchronization across:
    Tab 1: User Portal
    Tab 2: Live Investigation
    Tab 3: Case Workspace
    Tab 4: Fraud Operations Dashboard
    """
    queue = await register_subscriber()

    async def event_generator():
        try:
            # Send initial connection ping
            yield {
                "event": "CONNECTED",
                "data": json.dumps({
                    "status": "connected",
                    "time": datetime.now().strftime("%H:%M:%S")
                })
            }
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=20.0)
                    yield {
                        "event": event.get("event_type", "MESSAGE"),
                        "data": json.dumps(event)
                    }
                except asyncio.TimeoutError:
                    # Keepalive comment/ping
                    yield {
                        "event": "PING",
                        "data": json.dumps({"timestamp": datetime.now().strftime("%H:%M:%S")})
                    }
        finally:
            unregister_subscriber(queue)

    return EventSourceResponse(event_generator())


# ==========================================
# User Portal Endpoints (/portal)
# ==========================================

@app.post("/api/portal/upload-screenshot")
async def api_upload_screenshot(
    file: UploadFile = File(...),
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Uploads screenshot, saves to uploads directory, performs realistic extraction
    of transaction ID, amount, and recipient. Uncertain values are clearly marked.
    """
    filename = f"{uuid.uuid4().hex[:10]}_{file.filename}"
    filepath = os.path.join(UPLOADS_DIR, filename)
    
    contents = await file.read()
    with open(filepath, "wb") as f:
        f.write(contents)
    
    url = f"/static/uploads/{filename}"
    
    # Vision-model extraction; honest fallback (no invented values) when unavailable
    from moneytrace.services.screenshot_service import extract_payment_fields
    mime = file.content_type or "image/png"
    ocr_extracted = await asyncio.to_thread(extract_payment_fields, contents, mime)

    return {
        "screenshot_url": url,
        "filename": file.filename,
        "ocr_data": ocr_extracted
    }


@app.post("/api/portal/reports")
async def api_submit_portal_report(
    req: CreatePortalReportRequest,
    background_tasks: BackgroundTasks,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Authenticated victim report submission.
    Creates incident, links to authenticated user_id, emits INCIDENT_CREATED,
    and dispatches background investigation.
    """
    if os.environ.get("HELPDESK_MODE", "1").strip().lower() in ("1", "true", "yes") and not req.consent:
        raise HTTPException(status_code=400, detail="Consent is required before a report can be stored.")

    now_str = datetime.now().strftime("%d %b %Y, %H:%M IST")

    # Resolve amount lineage from spoken narrative vs manual request
    amt_info = resolve_amount_with_provenance(req.narrative, req.amount)
    canonical_amount = amt_info["amount"] or 0.0
    amount_source = amt_info["amount_source"]
    amount_source_text = amt_info["amount_source_text"]

    # Package OCR and amount lineage metadata
    ocr_meta = dict(req.ocr_data or {})
    ocr_meta["amount_provenance"] = {
        "transaction_amount": canonical_amount,
        "currency": "INR",
        "amount_source": amount_source,
        "amount_source_text": amount_source_text,
        "amount_conflict": amt_info.get("amount_conflict", False)
    }

    inc_id = create_incident({
        "user_id": current_user["id"],
        "victim_name": current_user.get("name") or "Authenticated Victim",
        "victim_phone": "",
        "language": req.language or "en",
        "amount": canonical_amount,
        "currency": "INR",
        "transaction_id": req.transaction_id or "",
        "scam_type": "Under Investigation",
        "severity": "PENDING",
        "status": "INVESTIGATING",
        "investigation_stage": "REPORT_RECEIVED",
        "confidence": 0.0,
        "narrative": req.narrative,
        "victim_story_summary": req.narrative[:150],
        "victim_guidance": "",
        "screenshot_url": req.screenshot_url or "",
        "ocr_extracted_data": json.dumps(ocr_meta),
        "requires_human_review": 1,
        "created_at": now_str,
        "updated_at": now_str,
    })

    # Detailed audit trail recording exact amount lineage
    amt_audit_detail = (
        f"Amount ₹{canonical_amount:,.2f} verified from {amount_source} ('{amount_source_text}')."
        if amount_source == "voice_transcript"
        else f"Amount recorded as {canonical_amount} (source: {amount_source})."
    )
    add_audit_log(inc_id, "Report received", f"Victim submitted report. {amt_audit_detail}", datetime.now().strftime("%H:%M:%S"))

    # Generate empathetic voice acknowledgement grounded in actual transcript amount
    voice_ack = await generate_voice_response(
        case_id=inc_id,
        event_type="complaint_received",
        language=req.language or "en",
        amount=canonical_amount if canonical_amount > 0 else None,
        amount_source=amount_source,
        complaint_narrative=req.narrative
    )

    # Emit real-time INCIDENT_CREATED with voice_response and amount lineage metadata attached
    await emit_event(
        event_type="INCIDENT_CREATED",
        incident_id=inc_id,
        status="RECEIVED",
        service="MoneyTrace Ingestion Gateway",
        payload={
            "incident_id": inc_id,
            "victim_name": current_user.get("name"),
            "amount": canonical_amount,
            "amount_provenance": ocr_meta["amount_provenance"],
            "transaction_id": req.transaction_id or "",
            "narrative_preview": req.narrative[:80],
            "language": req.language or "en",
            "voice_response": voice_ack
        },
        user_id=current_user["id"]
    )

    record_usage_event("report_received", inc_id, None, req.language or "en")

    # Launch autonomous investigation pipeline in background
    background_tasks.add_task(run_investigation_pipeline, inc_id)

    return {
        "incident_id": inc_id,
        "status": "INVESTIGATING",
        "investigation_stage": "REPORT_RECEIVED",
        "message": "Report submitted — investigation in progress.",
        "case_reference": inc_id,
        "amount": canonical_amount,
        "amount_provenance": ocr_meta["amount_provenance"],
        "voice_response": voice_ack
    }


@app.get("/api/portal/my-reports")
async def api_get_my_reports(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Returns ONLY the incidents submitted by the authenticated user (Data Isolation)."""
    reports = get_user_incidents(current_user["id"])
    return {"reports": reports}


@app.get("/api/portal/notifications")
async def api_get_my_notifications(current_user: Dict[str, Any] = Depends(get_current_user)):
    """Returns safe, user-facing notifications for the authenticated user without internal graph/analyst data."""
    notifs = get_user_notifications(current_user["id"])
    return {"notifications": notifs}


# ==========================================
# Sarvam AI Voice STT & TTS
# ==========================================

@app.post("/api/voice/transcribe")
async def api_voice_transcribe(
    audio: Optional[UploadFile] = File(None),
    language: str = Form("en")
):
    """
    Transcribes spoken victim report using Sarvam AI.
    Audio uploaded from browser microphone. Supports en, hi, ta, kn.
    """
    audio_bytes = b""
    if audio:
        audio_bytes = await audio.read()
    
    result = await transcribe_audio(audio_bytes, language=language)
    return result


@app.post("/api/voice/synthesize")
async def api_voice_synthesize(payload: Dict[str, str]):
    text = payload.get("text", "")
    language = payload.get("language", "en")
    audio_url = await synthesize_guidance(text, language)
    return {"audio_url": audio_url}


@app.get("/api/voice/response/{incident_id}/{event_type}")
async def api_get_voice_response(
    incident_id: str,
    event_type: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Returns the voice response audio URL and metadata for a given incident and event.
    Authorized: Incident owner or Fraud Operator.
    """
    inc = get_incident(incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    # Access control: user must own incident or be operator
    # Read amount source from ocr_extracted_data if available
    amt_source = "none"
    try:
        ocr_d = json.loads(inc.get("ocr_extracted_data") or "{}")
        amt_source = ocr_d.get("amount_provenance", {}).get("amount_source", "none")
    except Exception:
        pass

    voice_resp = await generate_voice_response(
        case_id=incident_id,
        event_type=event_type,
        language=inc.get("language", "en"),
        amount=inc.get("amount"),
        amount_source=amt_source,
        status=inc.get("status"),
        scam_type=inc.get("scam_type"),
        complaint_narrative=inc.get("narrative")
    )
    return voice_resp


# ==========================================
# Fraud Operator Endpoints (Protected by require_operator)
# ==========================================

@app.get("/api/incidents")
async def api_list_incidents(operator: Dict[str, Any] = Depends(require_operator)):
    """Lists all incidents for fraud operators."""
    rows = list_incidents(limit=100)
    return {"incidents": rows}


@app.get("/api/incidents/{incident_id}")
async def api_get_incident_detail(
    incident_id: str,
    operator: Dict[str, Any] = Depends(require_operator)
):
    """Full incident details including entities, audit trail, and evidence package."""
    inc = get_incident(incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")
    
    # Fetch events timeline
    events = get_incident_events(incident_id)
    inc["events"] = events
    return inc


@app.get("/api/incidents/{incident_id}/events")
async def api_get_incident_event_history(
    incident_id: str,
    operator: Dict[str, Any] = Depends(require_operator)
):
    """Returns full event timeline for live investigation visualization."""
    events = get_incident_events(incident_id)
    return {"incident_id": incident_id, "events": events}


@app.post("/api/incidents/{incident_id}/investigate")
async def api_investigate_incident(
    incident_id: str,
    operator: Dict[str, Any] = Depends(require_operator)
):
    """Manually trigger or rerun the AI Investigation Agent pipeline."""
    try:
        result = await run_investigation_pipeline(incident_id)
        return result
    except Exception as e:
        logger.exception(f"Investigation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/incidents/{incident_id}/related")
async def api_get_related_graph(
    incident_id: str,
    operator: Dict[str, Any] = Depends(require_operator)
):
    """Returns network graph nodes and edges for visual representation in Case Workspace."""
    inc = get_incident(incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")

    pkg = inc.get("evidence_package") or {}
    related_cases = pkg.get("related_incidents", [])
    shared_entities = pkg.get("shared_entities", [])

    graph = build_compact_graph_nodes_and_edges(
        current_incident=inc,
        related_incidents=related_cases,
        shared_entities=shared_entities
    )
    return graph


@app.post("/api/incidents/{incident_id}/review")
async def api_review_incident(
    incident_id: str,
    payload: Dict[str, Any],
    operator: Dict[str, Any] = Depends(require_operator)
):
    """Human Operator review decision (Approve escalation / Request Info)."""
    action = payload.get("action", "APPROVED")
    notes = payload.get("notes", "Reviewed by Fraud Operator.")

    update_incident_record(incident_id, {
        "requires_human_review": 0,
        "status": "OPERATOR_CONFIRMED" if action == "APPROVED" else "UNDER_REVIEW"
    })
    add_audit_log(incident_id, f"Human Review: {action}", f"{notes} (Operator: {operator['email']})")
    record_usage_event("signoff", incident_id, (get_incident(incident_id) or {}).get("scam_type"), None)

    await emit_event(
        event_type="INCIDENT_COMPLETED",
        incident_id=incident_id,
        status="OPERATOR_VERIFIED",
        service="Fraud Operations Team",
        payload={"action": action, "operator": operator["name"], "notes": notes}
    )

    return {"status": "SUCCESS", "action": action, "incident_id": incident_id}


@app.get("/api/incidents/{incident_id}/metrics")
async def api_incident_metrics(incident_id: str, operator: Dict[str, Any] = Depends(require_operator)):
    """Measured per-request telemetry for one investigation: latency, per-agent time, tokens, cost (INR)."""
    inc = get_incident(incident_id)
    if not inc:
        raise HTTPException(status_code=404, detail="Incident not found")
    pkg = inc.get("evidence_package") or {}
    return {"incident_id": incident_id, "investigation_stage": inc.get("investigation_stage"),
            "request_metrics": pkg.get("request_metrics"), "grounding": pkg.get("grounding"),
            "ai_investigator": pkg.get("ai_investigator")}


@app.get("/api/helpdesk/usage")
async def api_helpdesk_usage(days: int = 30, operator: Dict[str, Any] = Depends(require_operator)):
    """Help-desk usage (no personal data): reports, cases by type, escalations, sign-offs, median time to guidance."""
    return get_usage_summary(days)


@app.get("/api/helpdesk/info")
async def api_helpdesk_info():
    return {"helpdesk_mode": os.environ.get("HELPDESK_MODE", "1") in ("1", "true"),
            "disclaimer": "Independent student project - not an official government, police or bank service.",
            "official_channels": {"helpline": "1930", "portal": "https://cybercrime.gov.in"},
            "retention_days": int(os.environ.get("DATA_RETENTION_DAYS", "90"))}


@app.get("/api/dashboard")
async def api_get_dashboard(operator: Dict[str, Any] = Depends(require_operator)):
    """Fraud operations console metrics, syndicate clusters, and incident feed.
    All numbers are computed from the incidents table (no hard-coded demo values)."""
    metrics = get_dashboard_metrics()
    clusters = get_cluster_summary()
    rows = list_incidents(limit=60, include_review_flag=True)
    return {
        "metrics": {
            "active_incidents": metrics["active_incidents"],
            "critical_incidents": metrics["critical_incidents"],
            "potential_clusters": len(clusters),
            "reported_exposure": metrics["reported_exposure"],
            "human_reviews_required": metrics["human_reviews_required"]
        },
        "clusters": clusters,
        "incidents": rows
    }


# ==========================================
# Evaluation & Accuracy API Endpoints
# ==========================================

EVAL_DIR = os.path.join(WORKSPACE_ROOT, "backend", "evaluation")

def _load_latest_eval() -> Dict[str, Any]:
    latest_file = os.path.join(EVAL_DIR, "latest_run.json")
    if os.path.isfile(latest_file):
        with open(latest_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

@app.get("/api/evaluation/summary")
async def get_evaluation_summary():
    """Returns high-level evaluation metrics for multi-class and binary fraud detection."""
    data = _load_latest_eval()
    if not data:
        raise HTTPException(status_code=404, detail="Evaluation results not found. Run evaluator.py first.")
    return {
        "run_id": data.get("run_id"),
        "dataset_name": data.get("dataset_name"),
        "dataset_version": data.get("dataset_version"),
        "timestamp": data.get("timestamp"),
        "model_version": data.get("model_version"),
        "test_sample_count": data.get("test_sample_count"),
        "total_benchmark_records": data.get("total_benchmark_records"),
        "multi_class": {
            "accuracy": data["metrics"]["multi_class"]["accuracy"],
            "macro_f1": data["metrics"]["multi_class"]["macro_f1"],
            "macro_precision": data["metrics"]["multi_class"]["macro_precision"],
            "macro_recall": data["metrics"]["multi_class"]["macro_recall"],
            "weighted_f1": data["metrics"]["multi_class"]["weighted_f1"]
        },
        "binary_fraud": data["metrics"]["binary_fraud"],
        "component_evaluation": data.get("component_evaluation", {})
    }

@app.get("/api/evaluation/classification")
async def get_evaluation_classification():
    """Returns full multi-class classification metrics."""
    data = _load_latest_eval()
    if not data:
        raise HTTPException(status_code=404, detail="Evaluation results not found.")
    return data.get("metrics", {}).get("multi_class", {})

@app.get("/api/evaluation/confusion-matrix")
async def get_evaluation_confusion_matrix():
    """Returns the multi-class confusion matrix."""
    data = _load_latest_eval()
    if not data:
        raise HTTPException(status_code=404, detail="Evaluation results not found.")
    return {
        "classes": data.get("classes", []),
        "confusion_matrix": data.get("metrics", {}).get("multi_class", {}).get("confusion_matrix", {})
    }

@app.get("/api/evaluation/per-class")
async def get_evaluation_per_class():
    """Returns precision, recall, F1, and support for all 7 classes."""
    data = _load_latest_eval()
    if not data:
        raise HTTPException(status_code=404, detail="Evaluation results not found.")
    return {
        "classes": data.get("classes", []),
        "per_class": data.get("metrics", {}).get("multi_class", {}).get("per_class", {})
    }

@app.get("/api/evaluation/provenance")
async def get_evaluation_provenance():
    """Returns dataset manifest and provenance verification metadata."""
    manifest_file = os.path.join(EVAL_DIR, "dataset_manifest.json")
    if os.path.isfile(manifest_file):
        with open(manifest_file, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    else:
        manifest = {}
    return {
        "manifest": manifest,
        "methodology": {
            "target_insulation": "Ground truth (fraud_class, is_fraud) strictly withheld from inference pipeline.",
            "partition": "80% reference/dev set (1,600 records), 20% held-out blind test set (400 records).",
            "signals": "21 numerical features, 10 boolean flags, 7 categorical parameters, 1 natural language narrative.",
            "reproducibility": "Deterministic generation with fixed seed (42). Re-computable via evaluation/generate_dataset.py."
        }
    }

@app.get("/api/evaluation/rag")
async def get_evaluation_rag():
    """Latest full RAG evaluation (recall@5, fully grounded %), from results/rag_eval/latest.json."""
    path = os.path.join(WORKSPACE_ROOT, "backend", "results", "rag_eval", "latest.json")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="RAG evaluation not run yet: python -m evaluation.rag_eval")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/evaluation/runs")
async def get_evaluation_runs():
    """Lists available evaluation runs."""
    runs_dir = os.path.join(EVAL_DIR, "runs")
    runs = []
    if os.path.isdir(runs_dir):
        for d in sorted(os.listdir(runs_dir), reverse=True):
            r_path = os.path.join(runs_dir, d, "results.json")
            if os.path.isfile(r_path):
                try:
                    with open(r_path, "r", encoding="utf-8") as rf:
                        r_data = json.load(rf)
                        runs.append({
                            "run_id": r_data.get("run_id"),
                            "timestamp": r_data.get("timestamp"),
                            "test_sample_count": r_data.get("test_sample_count"),
                            "macro_f1": r_data.get("metrics", {}).get("multi_class", {}).get("macro_f1"),
                            "binary_f1": r_data.get("metrics", {}).get("binary_fraud", {}).get("f1"),
                            "accuracy": r_data.get("metrics", {}).get("multi_class", {}).get("accuracy")
                        })
                except Exception:
                    pass
    return {"runs": runs}


# ==========================================
# Frontend SPA Routes
# ==========================================

INDEX_HTML_PATH = os.path.join(STATIC_DIR, "index.html")

@app.get("/")
@app.get("/portal")
@app.get("/investigations")
@app.get("/cases/{incident_id}")
@app.get("/dashboard")
@app.get("/evaluation")
@app.get("/login")
async def serve_spa_routes(incident_id: Optional[str] = None):
    """Serves index.html for all valid SPA routes."""
    if os.path.isfile(INDEX_HTML_PATH):
        return FileResponse(INDEX_HTML_PATH)
    return HTMLResponse("<h1>MoneyTrace initializing...</h1>", status_code=200)

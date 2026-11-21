"""
MoneyTrace multi-agent pipeline on Google ADK.

    Coordinator (LlmAgent)
      ├── intake_agent        (AgentTool)  get_report -> save_case_record
      ├── investigation_agent (AgentTool)  ReAct: lookup_transaction / score_signals /
      │                                    search_related_incidents ... -> submit_assessment
      └── guidance_agent      (AgentTool)  search_advisories -> cited steps
    then deterministic post-processing:
      grounding check (self-reflection, one regeneration, safe fallback)
      -> evidence package -> n8n -> human-review gate -> voice -> victim notification

The coordinator delegates hierarchically by calling each specialist as an agent-tool
(ADK `AgentTool`); state written by a specialist flows back into the coordinator's
session. Agent session state is persisted by the configured session service
(Firestore in production) so it survives restarts.

Reliability: after the ADK run a guard checks the session state. Anything a
specialist failed to produce (no LLM configured, model error, skipped tool) is
completed deterministically and marked `source: rules` / `via: guard`, so all 12
milestones are always emitted in order.
"""

import asyncio
import json
import os
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

from moneytrace.agents import tools as T
from moneytrace.agents.guidance import GUIDANCE_INSTRUCTION, LANG_NAMES, finalize_guidance, parse_steps, render_guidance_text
from moneytrace.agents.milestones import get_emitter, release
from moneytrace.config import get_settings
from moneytrace.db.database import (
    get_incident, update_incident_record, add_audit_log, save_evidence_package, create_user_notification,
    mark_guidance_delivered, record_usage_event,
)
from moneytrace.llm import adk_model, llm_available, model_for, provider
from moneytrace.telemetry import agent_span, start_request, current_metrics, record_model_call

logger = logging.getLogger("moneytrace.agents.coordinator")

APP_NAME = "moneytrace"

INTAKE_INSTRUCTION = """You are the Intake agent. Turn the victim's unstructured report (typed text, voice transcript,
screenshot fields; any language) into a structured case record.
1. Call get_report.
2. Call save_case_record exactly once with the fields stated in the report. Never guess values that are not stated;
   keep placeholders like [PHONE_1] as they are. Pick the closest fraud_type.
3. Reply with one short sentence confirming what you saved."""

INVESTIGATION_INSTRUCTION = """You are the Investigation agent, working in a ReAct loop (Thought -> Action -> Observation).
Goal: a justified severity for the fraud case in state key `case_record`.
Available actions: lookup_transaction, score_signals, search_related_incidents, submit_assessment.
- Think about what evidence you still need, call ONE tool, read the observation, and repeat.
- Always look up the transaction, score the signals and search for related incidents before deciding
  (search_related_incidents before score_signals lets the score use network evidence).
- Severity guide: CRITICAL = large loss (>= ₹50,000), coercion such as 'digital arrest', or a mule network with
  several linked victims; HIGH = money lost to a confirmed scam pattern; MEDIUM = attempted fraud or small loss;
  LOW = no loss and weak signals.
- Finish by calling submit_assessment once, citing the observations in the justification. Then reply in one sentence."""

COORDINATOR_INSTRUCTION = """You are the MoneyTrace Coordinator for a payment-fraud help desk. A new victim report has
arrived. Delegate to your specialists in this order, one at a time, waiting for each result:
1. intake_agent - structure the report into a case record.
2. investigation_agent - investigate and assess severity.
3. guidance_agent - write cited, step-by-step victim guidance.
Do not write guidance yourself. After the three specialists have finished, reply with one line: DONE."""


def _build_agents():
    from google.adk.agents import LlmAgent
    from google.adk.tools.agent_tool import AgentTool
    from google.genai import types
    from rag.retriever import search_advisories

    gen = types.GenerateContentConfig(temperature=0.1)
    intake = LlmAgent(name="intake_agent", model=adk_model("fast"), instruction=INTAKE_INSTRUCTION,
                      description="Turns a victim's text/voice/screenshot report into a structured case record.",
                      tools=[T.get_report, T.save_case_record], generate_content_config=gen)
    investigation = LlmAgent(name="investigation_agent", model=adk_model("fast"), instruction=INVESTIGATION_INSTRUCTION,
                             description="ReAct investigator: ledger lookup, signal scoring, mule-network search, severity.",
                             tools=[T.lookup_transaction, T.score_signals, T.search_related_incidents, T.submit_assessment],
                             generate_content_config=gen)

    def _guidance_instruction(ctx) -> str:
        lang = (ctx.state.get("case_record") or {}).get("language") or ctx.state.get("language") or "en"
        return GUIDANCE_INSTRUCTION.format(language_name=LANG_NAMES.get(lang, "English"))

    guidance = LlmAgent(name="guidance_agent", model=adk_model("strong", thinking=False), instruction=_guidance_instruction,
                        description="Writes step-by-step victim guidance grounded only in retrieved official advisories.",
                        tools=[search_advisories], output_key="guidance_draft", generate_content_config=gen)
    coordinator = LlmAgent(name="coordinator", model=adk_model("fast"), instruction=COORDINATOR_INSTRUCTION,
                           description="Routes a fraud report through intake, investigation and guidance.",
                           tools=[AgentTool(agent=intake), AgentTool(agent=investigation), AgentTool(agent=guidance)],
                           generate_content_config=gen)
    return coordinator, guidance


def _usage_callback_plugin():
    """ADK plugin that records measured token usage of every model response."""
    from google.adk.plugins.base_plugin import BasePlugin

    class UsagePlugin(BasePlugin):
        def __init__(self):
            super().__init__(name="moneytrace_usage")
            self._t0: Dict[str, float] = {}

        async def before_model_callback(self, *, callback_context, llm_request):
            self._t0[callback_context.invocation_id + callback_context.agent_name] = time.perf_counter()
            return None

        async def after_model_callback(self, *, callback_context, llm_response):
            key = callback_context.invocation_id + callback_context.agent_name
            ms = (time.perf_counter() - self._t0.pop(key, time.perf_counter())) * 1000
            um = getattr(llm_response, "usage_metadata", None)
            if um is not None:
                out = int(getattr(um, "candidates_token_count", 0) or 0) + int(getattr(um, "thoughts_token_count", 0) or 0)
                record_model_call(callback_context.agent_name, model_for("strong" if callback_context.agent_name == "guidance_agent" else "fast"),
                                  int(getattr(um, "prompt_token_count", 0) or 0), out, ms)
            return None

    return UsagePlugin()


async def _run_adk(incident: Dict[str, Any], trace_log: list) -> Dict[str, Any]:
    """Run the coordinator; return the final session state."""
    from google.adk.runners import Runner
    from google.genai import types
    from moneytrace.state.session_service import get_session_service

    coordinator, _ = _build_agents()
    svc = get_session_service()
    session_id = f"{incident['id']}-{uuid.uuid4().hex[:6]}"
    state = {"incident_id": incident["id"], "user_id": incident.get("user_id"), "language": incident.get("language") or "en"}
    session = await svc.create_session(app_name=APP_NAME, user_id=incident.get("user_id") or "anonymous",
                                       session_id=session_id, state=state)
    runner = Runner(app_name=APP_NAME, agent=coordinator, session_service=svc, plugins=[_usage_callback_plugin()])
    msg = types.Content(role="user", parts=[types.Part(text=f"New fraud report {incident['id']} has arrived. Process it.")])
    max_steps = 60
    async for ev in runner.run_async(user_id=session.user_id, session_id=session.id, new_message=msg):
        calls = ev.get_function_calls() if hasattr(ev, "get_function_calls") else []
        for c in calls or []:
            trace_log.append({"t": round(time.time(), 3), "agent": ev.author, "action": "call", "tool": c.name})
        if ev.is_final_response() and ev.content and ev.content.parts:
            trace_log.append({"t": round(time.time(), 3), "agent": ev.author, "action": "final",
                              "text": (ev.content.parts[0].text or "")[:200]})
        max_steps -= 1
        if max_steps <= 0:
            trace_log.append({"agent": "coordinator", "action": "aborted", "reason": "step budget exhausted"})
            break
    final = await svc.get_session(app_name=APP_NAME, user_id=session.user_id, session_id=session.id)
    st = dict(final.state) if final else {}
    st["_adk_session_id"] = session.id
    return st


async def _regenerate_guidance(state: Dict[str, Any], feedback: str):
    """One regeneration of the guidance draft with grounding feedback (runs the guidance agent alone)."""
    from google.adk.runners import Runner
    from google.adk.sessions.in_memory_session_service import InMemorySessionService
    from google.genai import types
    _, guidance = _build_agents()
    svc = InMemorySessionService()
    s = await svc.create_session(app_name=APP_NAME, user_id="regen", state={k: v for k, v in state.items()
                                                                            if not k.startswith("_")})
    runner = Runner(app_name=APP_NAME, agent=guidance, session_service=svc, plugins=[_usage_callback_plugin()])
    msg = types.Content(role="user", parts=[types.Part(text=(
        "Your previous guidance had unsupported steps:\n" + feedback +
        "\nRewrite the guidance. Keep only claims stated in retrieved passages, and cite them."))])
    async for _ in runner.run_async(user_id="regen", session_id=s.id, new_message=msg):
        pass
    s2 = await svc.get_session(app_name=APP_NAME, user_id="regen", session_id=s.id)
    return parse_steps((s2.state if s2 else {}).get("guidance_draft"))


async def run_adk_pipeline(incident_id: str) -> Dict[str, Any]:
    incident = get_incident(incident_id)
    if not incident:
        raise ValueError(f"Incident {incident_id} not found")
    metrics = start_request(incident_id)
    user_id = incident.get("user_id")
    em = get_emitter(incident_id, user_id)
    trace_log: list = []
    language = incident.get("language") or "en"
    live = llm_available()

    with agent_span("moneytrace.pipeline", incident_id=incident_id, engine="adk", llm_provider=provider()):
        update_incident_record(incident_id, {"investigation_stage": "REPORT_UNDERSTOOD"})
        add_audit_log(incident_id, "Investigation started", f"ADK coordinator started (LLM live={live}, provider={provider()}).")
        await em.emit("INVESTIGATION_STARTED", "ACTIVE", "MoneyTrace ADK Coordinator",
                      {"message": "Coordinator delegating to intake, investigation and guidance agents.",
                       "engine": "google-adk", "llm_live": live})

        state: Dict[str, Any] = {}
        adk_error = None
        if live:
            try:
                with agent_span("coordinator", incident_id=incident_id):
                    state = await asyncio.wait_for(_run_adk(incident, trace_log), timeout=float(
                        os.environ.get("AGENT_TIMEOUT_S", "150")))
            except Exception as e:  # keep the case moving; the guard completes the rest
                adk_error = f"{type(e).__name__}: {str(e)[:300]}"
                logger.exception(f"ADK run failed for {incident_id}")
                trace_log.append({"agent": "coordinator", "action": "error", "error": adk_error})

        # ---------------- guard: complete anything the agents did not produce ----------------
        for k, v in T.RESULTS.pop(incident_id, {}).items():
            state.setdefault(k, v)
        with agent_span("guard", incident_id=incident_id):
            if not state.get("case_record"):
                rec = T.rule_based_case(get_incident(incident_id))
                T.persist_case_record(incident_id, rec)
                state["case_record"] = rec
                trace_log.append({"agent": "guard", "action": "intake_rules"})
            if not em.done("TRANSACTION_FOUND"):
                state["ledger"] = state.get("ledger") or T.ledger_lookup(incident_id)
                await T.emit_transaction_found(incident_id, user_id, state["ledger"], via="guard")
            if not em.done("RELATED_INCIDENTS_FOUND") or not em.done("GRAPH_READY"):
                rel = await T.related_search(incident_id)
                state["related"] = {k: v for k, v in rel.items() if k != "related_incidents"} | {
                    "related_incidents": rel["related_incidents"]}
                # signals may be buffered behind this milestone; scoring now can use network evidence
                if "SIGNALS_ANALYZED" not in em.pending and not em.done("SIGNALS_ANALYZED"):
                    state["signals"] = T.compute_signals(incident_id, state.get("ledger"), state["related"])
                    await T.emit_signals(incident_id, user_id, state["signals"], via="guard")
                await T.emit_related(incident_id, user_id, rel, via="guard")
            if not em.done("SIGNALS_ANALYZED"):
                state["signals"] = state.get("signals") or T.compute_signals(incident_id, state.get("ledger"), state.get("related"))
                await T.emit_signals(incident_id, user_id, state["signals"], via="guard")
            if not state.get("assessment"):
                state["assessment"] = T.heuristic_assessment(incident_id, state.get("signals") or {}, state.get("related") or {})
                trace_log.append({"agent": "guard", "action": "assessment_rules"})

        # ---------------- guidance: grounding check (self-reflection) ----------------
        draft = parse_steps(state.get("guidance_draft"))
        regen = None
        if live and draft:
            def regen(feedback, _state=state):
                try:
                    return asyncio.run_coroutine_threadsafe(_regenerate_guidance(_state, feedback), loop).result(timeout=90)
                except Exception as e:
                    logger.warning(f"regeneration failed: {e}")
                    return None
        loop = asyncio.get_running_loop()
        if not draft:
            trace_log.append({"agent": "guard", "action": "guidance_missing"})
        guidance = await asyncio.to_thread(finalize_guidance, draft, language, regen) if (draft or live) else \
            finalize_guidance([], language, None)
        guidance_text = render_guidance_text(guidance)

        result = await _finalize(incident_id, state, guidance, guidance_text, trace_log, adk_error, live)
    release(incident_id)
    return result


async def _finalize(incident_id: str, state: Dict[str, Any], guidance: Dict[str, Any], guidance_text: str,
                    trace_log: list, adk_error: Optional[str], live: bool) -> Dict[str, Any]:
    from moneytrace.services.n8n_service import trigger_n8n_response_workflow
    from moneytrace.services.voice_response import generate_voice_response, extract_amount_from_transcript

    inc = get_incident(incident_id)
    user_id = inc.get("user_id")
    em = get_emitter(incident_id, user_id)
    rec, a = state.get("case_record") or {}, state.get("assessment") or {}
    rel, sig, ledger = state.get("related") or {}, state.get("signals") or {}, state.get("ledger") or {}
    severity = a.get("severity", "HIGH")
    requires_review = bool(a.get("requires_human_review")) or severity == "CRITICAL"
    p = provider()
    agents_live = live and not adk_error and a.get("source") == "llm"
    status = ("GEMINI LIVE" if p == "gemini" else f"LLM LIVE ({p})") if agents_live else (
        "GEMINI NOT CONFIGURED" if not live else "AGENTS FAILED (rules fallback)")

    evidence = {
        "incident_id": incident_id, "transaction_id": inc.get("transaction_id"), "amount": inc.get("amount"),
        "currency": "INR", "incident_type": inc.get("scam_type"), "severity": severity,
        "confidence": a.get("confidence"), "victim_story_summary": rec.get("summary") or (inc.get("narrative") or "")[:200],
        "entities": {"upi": inc.get("recipient_upi"), "phone": inc.get("scammer_phone"),
                     "bank_account": inc.get("bank_account"), "domain": inc.get("domain")},
        "red_flags": a.get("red_flags") or [s["signal"] for s in sig.get("signals", [])],
        "risk_score": sig.get("risk_score"), "signals": sig.get("signals", []),
        "severity_justification": a.get("justification"),
        "intelligence_layer": rel.get("provider"),
        "ai_investigator": {"provider": f"Google ADK multi-agent ({p})", "status": status,
                            "model": model_for("fast"), "engine": "google-adk",
                            "timestamp": datetime.now().strftime("%d %b %Y, %H:%M IST"), "error": adk_error},
        "case_record": rec, "ledger_match": ledger,
        "potential_scam_network": rel.get("network_detected"), "related_incidents_count": rel.get("related_count", 0),
        "shared_entities_count": len(rel.get("shared_entities", [])), "shared_entities": rel.get("shared_entities", []),
        "related_incidents": rel.get("related_incidents", []), "recommended_action": a.get("recommended_action"),
        "victim_guidance": guidance_text, "guidance_steps": guidance["steps"], "guidance_sources": guidance["sources"],
        "grounding": guidance["grounding"], "evidence_required": [
            "Transaction SMS / bank statement entry", "Screenshots of the chat, call log or link", "Recipient UPI ID / account"],
        "requires_human_review": requires_review, "agent_trace": trace_log,
        "adk_session_id": state.get("_adk_session_id"),
        "evidence_timestamp": datetime.now().strftime("%d %b %Y, %H:%M:%S IST"),
    }
    save_evidence_package(incident_id, evidence)
    add_audit_log(incident_id, "Evidence package ready", f"Severity {severity} ({a.get('source')}); guidance grounded="
                  f"{guidance['grounding'].get('fully_grounded')}")
    await em.emit("EVIDENCE_PREPARED", "COMPILED", f"Evidence Compiler ({status})", {
        "evidence_package_id": f"EVD-{incident_id}", "severity": severity, "red_flags_count": len(evidence["red_flags"]),
        "ai_status": status, "model": model_for("fast"), "guidance_steps": len(guidance["steps"]),
        "fully_grounded": guidance["grounding"].get("fully_grounded")})

    await em.emit("N8N_WORKFLOW_STARTED", "RUNNING", "n8n Response Orchestrator",
                  {"message": "Dispatching incident payload to n8n webhook workflow."})
    wf = await trigger_n8n_response_workflow(
        incident_data={"id": incident_id, "severity": severity, "amount": inc.get("amount"), "scam_type": inc.get("scam_type"),
                       "recipient_upi": inc.get("recipient_upi"), "scammer_phone": inc.get("scammer_phone")},
        evidence_package=evidence)
    ok = wf.get("status", "COMPLETED") == "COMPLETED"
    await em.emit("N8N_WORKFLOW_COMPLETED", "SUCCESS" if ok else "FAILED", f"n8n ({wf.get('execution_type', 'webhook')})", {
        "workflow_status": wf.get("status"), "execution_type": wf.get("execution_type"),
        "stages_completed": len(wf.get("stages", [])) if ok else 0, "error": wf.get("error")})

    await em.emit("HUMAN_REVIEW_REQUIRED", "FLAGGED" if requires_review else "NOT_REQUIRED", "Fraud Operations Policy Engine", {
        "required": requires_review, "severity": severity,
        "reason": "CRITICAL case: operator sign-off required before any recovery action." if requires_review
        else "Not CRITICAL: guidance delivered without mandatory sign-off."})
    if requires_review:
        record_usage_event("escalated", incident_id, inc.get("scam_type"), inc.get("language"))

    amt_src = extract_amount_from_transcript(inc.get("narrative") or "")["amount_source"]
    voice = await generate_voice_response(case_id=incident_id, event_type="investigation_completed",
                                          language=inc.get("language") or "en", amount=inc.get("amount"),
                                          amount_source=amt_src, status="ESCALATED" if requires_review else "GUIDANCE_SENT",
                                          scam_type=inc.get("scam_type"), complaint_narrative=inc.get("narrative"),
                                          investigation_result=evidence)
    final_status = "ESCALATED" if requires_review else "GUIDANCE_SENT"
    update_incident_record(incident_id, {
        "severity": severity, "status": final_status, "investigation_stage": "COMPLETE",
        "confidence": a.get("confidence"), "victim_story_summary": evidence["victim_story_summary"],
        "victim_guidance": guidance_text, "victim_guidance_audio_url": voice.get("audio_url") or "",
        "requires_human_review": 1 if requires_review else 0,
        "updated_at": datetime.now().strftime("%d %b %Y, %H:%M IST")})
    await em.emit("INCIDENT_COMPLETED", "COMPLETED", "MoneyTrace ADK Pipeline", {
        "final_status": final_status, "scam_type": inc.get("scam_type"), "severity": severity, "voice_response": voice})

    amount = inc.get("amount") or 0
    summary = (f"Your report about the ₹{amount:,.2f} transfer has been reviewed ({inc.get('scam_type')})." if amount
               else f"Your report has been reviewed ({inc.get('scam_type')}).")
    title = "Investigation Complete: Protective Actions Required"
    notif_id = create_user_notification(user_id, incident_id, title, summary, guidance_text) if user_id else ""
    secs = mark_guidance_delivered(incident_id)
    m = current_metrics()
    if m is not None and m.first_guidance_ms is None:
        m.first_guidance_ms = (time.perf_counter() - m.started) * 1000
    record_usage_event("guidance_delivered", incident_id, inc.get("scam_type"), inc.get("language"), secs)
    await em.emit("USER_NOTIFICATION_CREATED", "DELIVERED", "Victim Communications Service", {
        "notification_id": notif_id, "title": title, "summary": summary, "guidance": guidance_text,
        "guidance_steps": guidance["steps"], "sources": guidance["sources"],
        "language": inc.get("language"), "voice_response": voice})

    metrics_summary = m.summary() if m else {}
    if m is not None:
        evidence["request_metrics"] = metrics_summary
        save_evidence_package(incident_id, evidence)
    return {"incident": get_incident(incident_id), "evidence_package": evidence, "workflow": wf,
            "metrics": metrics_summary}


async def run_guidance_only(question: str, language: str = "en", fraud_type: str = "") -> Dict[str, Any]:
    """Run the production guidance agent + grounding check for one free-text question (used by the RAG eval)."""
    from google.adk.runners import Runner
    from google.adk.sessions.in_memory_session_service import InMemorySessionService
    from google.genai import types

    _, guidance_agent = _build_agents()
    svc = InMemorySessionService()
    state = {"language": language, "case_record": {"summary": question, "fraud_type": fraud_type or "unknown",
                                                    "language": language}}
    s = await svc.create_session(app_name=APP_NAME, user_id="eval", state=state)
    runner = Runner(app_name=APP_NAME, agent=guidance_agent, session_service=svc, plugins=[_usage_callback_plugin()])
    msg = types.Content(role="user", parts=[types.Part(text=f"Victim's question: {question}")])
    async for _ in runner.run_async(user_id="eval", session_id=s.id, new_message=msg):
        pass
    s2 = await svc.get_session(app_name=APP_NAME, user_id="eval", session_id=s.id)
    st = dict(s2.state) if s2 else {}
    draft = parse_steps(st.get("guidance_draft"))
    loop = asyncio.get_running_loop()

    def regen(feedback):
        async def _r():
            return await _regenerate_guidance(st, feedback)
        try:
            return asyncio.run_coroutine_threadsafe(_r(), loop).result(timeout=120)
        except Exception:
            return None
    result = await asyncio.to_thread(finalize_guidance, draft, language, regen if draft else None)
    result["draft"] = draft
    return result

"""
Observability for MoneyTrace: OpenTelemetry tracing + per-request token/cost accounting.

- setup_tracing(app): FastAPI auto-instrumentation; exporter chosen by OTEL_EXPORTER
  (gcp -> Cloud Trace, otlp -> any OTLP collector, console -> stdout, none).
  ADK emits its own spans (agent runs, LLM calls, tool calls) through the same
  global tracer provider, so one trace shows request -> coordinator -> sub-agents -> tools.
- RequestMetrics: a contextvar-scoped accumulator. Every model call records
  input/output tokens, latency and model; cost is computed from the measured
  tokens and the configured price table (moneytrace.config).
"""

import contextvars
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from moneytrace.config import get_settings

logger = logging.getLogger("moneytrace.telemetry")

_tracer = None
_initialised = False


def get_tracer():
    global _tracer
    if _tracer is None:
        from opentelemetry import trace
        _tracer = trace.get_tracer("moneytrace")
    return _tracer


def setup_tracing(app=None, service_name: str = "moneytrace-api"):
    """Configure the global tracer provider once; instrument the FastAPI app if given."""
    global _initialised
    exporter_kind = get_settings().otel_exporter.lower()
    if exporter_kind == "none" or os.environ.get("MONEYTRACE_TESTING") == "1" and exporter_kind != "memory":
        return None
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor

    if not _initialised:
        provider = TracerProvider(resource=Resource.create({
            "service.name": service_name,
            "service.version": os.environ.get("K_REVISION", "local"),
        }))
        if exporter_kind == "gcp":
            from opentelemetry.exporter.cloud_trace import CloudTraceSpanExporter
            provider.add_span_processor(BatchSpanProcessor(CloudTraceSpanExporter(
                project_id=os.environ.get("GOOGLE_CLOUD_PROJECT") or None)))
        elif exporter_kind == "otlp":
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        elif exporter_kind == "jsonl":
            provider.add_span_processor(SimpleSpanProcessor(JsonlSpanExporter(
                os.environ.get("OTEL_JSONL_PATH", os.path.join("results", "traces", "spans.jsonl")))))
        else:
            from opentelemetry.sdk.trace.export import ConsoleSpanExporter
            provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
        try:
            trace.set_tracer_provider(provider)
        except Exception as e:  # already set by another library
            logger.warning(f"tracer provider already set: {e}")
        _initialised = True
        logger.info(f"OpenTelemetry tracing enabled (exporter={exporter_kind})")

    if app is not None:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
            FastAPIInstrumentor.instrument_app(app, excluded_urls="api/health,api/events,static/.*,public/.*")
        except Exception as e:
            logger.warning(f"FastAPI instrumentation failed: {e}")
    return trace.get_tracer_provider()


class JsonlSpanExporter:
    """Writes finished spans as JSON lines (used to keep a raw trace file next to load-test results)."""

    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    def export(self, spans):
        import json
        from opentelemetry.sdk.trace.export import SpanExportResult
        with open(self.path, "a", encoding="utf-8") as f:
            for s in spans:
                f.write(json.dumps({
                    "trace_id": format(s.context.trace_id, "032x"), "span_id": format(s.context.span_id, "016x"),
                    "parent_id": format(s.parent.span_id, "016x") if s.parent else None, "name": s.name,
                    "start": s.start_time, "end": s.end_time, "duration_ms": (s.end_time - s.start_time) / 1e6,
                    "attributes": {k: (v if isinstance(v, (str, int, float, bool)) else str(v))
                                   for k, v in (s.attributes or {}).items()},
                }) + "\n")
        return SpanExportResult.SUCCESS

    def shutdown(self):
        pass

    def force_flush(self, timeout_millis: int = 30000):
        return True


# ---------------------------------------------------------------------------
# Per-request token / cost accounting
# ---------------------------------------------------------------------------

@dataclass
class ModelCall:
    agent: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cost_usd: float


@dataclass
class RequestMetrics:
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    incident_id: Optional[str] = None
    started: float = field(default_factory=time.perf_counter)
    calls: List[ModelCall] = field(default_factory=list)
    agent_latency_ms: Dict[str, float] = field(default_factory=dict)
    first_guidance_ms: Optional[float] = None

    def add_call(self, agent: str, model: str, input_tokens: int, output_tokens: int, latency_ms: float):
        price = get_settings().price_for(model)
        cost = (input_tokens * price.input_per_m + output_tokens * price.output_per_m) / 1e6
        self.calls.append(ModelCall(agent, model, int(input_tokens or 0), int(output_tokens or 0), latency_ms, cost))
        try:
            from moneytrace.db.database import record_llm_call
            record_llm_call(request_id=self.request_id, incident_id=self.incident_id, agent=agent, model=model,
                            input_tokens=int(input_tokens or 0), output_tokens=int(output_tokens or 0),
                            latency_ms=latency_ms, cost_usd=cost)
        except Exception:
            pass

    def add_agent_time(self, agent: str, ms: float):
        self.agent_latency_ms[agent] = self.agent_latency_ms.get(agent, 0.0) + ms

    def summary(self) -> Dict:
        s = get_settings()
        inp = sum(c.input_tokens for c in self.calls)
        out = sum(c.output_tokens for c in self.calls)
        gen_ms = sum(c.latency_ms for c in self.calls)
        usd = sum(c.cost_usd for c in self.calls)
        return {
            "request_id": self.request_id,
            "incident_id": self.incident_id,
            "total_latency_ms": round((time.perf_counter() - self.started) * 1000, 1),
            "agent_latency_ms": {k: round(v, 1) for k, v in self.agent_latency_ms.items()},
            "model_calls": len(self.calls),
            "input_tokens": inp,
            "output_tokens": out,
            # output tokens per second of model wall-time (generation throughput)
            "output_tokens_per_sec": round(out / (gen_ms / 1000), 2) if gen_ms > 0 else None,
            "cost_usd": round(usd, 8),
            "cost_inr": round(usd * s.usd_to_inr, 6),
            "models": sorted({c.model for c in self.calls}),
        }


_current: contextvars.ContextVar[Optional[RequestMetrics]] = contextvars.ContextVar("moneytrace_request_metrics",
                                                                                     default=None)


def start_request(incident_id: Optional[str] = None) -> RequestMetrics:
    m = RequestMetrics(incident_id=incident_id)
    _current.set(m)
    return m


def current_metrics() -> Optional[RequestMetrics]:
    return _current.get()


def record_model_call(agent: str, model: str, input_tokens: int, output_tokens: int, latency_ms: float):
    m = _current.get()
    if m is not None:
        m.add_call(agent, model, input_tokens, output_tokens, latency_ms)
    try:
        from opentelemetry import trace
        span = trace.get_current_span()
        if span and span.is_recording():
            span.add_event("model_call", {"agent": agent, "model": model, "gen_ai.usage.input_tokens": int(input_tokens or 0),
                                          "gen_ai.usage.output_tokens": int(output_tokens or 0), "latency_ms": latency_ms})
    except Exception:
        pass


class agent_span:
    """Context manager: OTel span + per-agent latency accounting."""

    def __init__(self, name: str, **attrs):
        self.name, self.attrs = name, attrs

    def __enter__(self):
        self.t0 = time.perf_counter()
        self._cm = get_tracer().start_as_current_span(self.name, attributes={k: str(v) for k, v in self.attrs.items()})
        self.span = self._cm.__enter__()
        return self.span

    def __exit__(self, *exc):
        ms = (time.perf_counter() - self.t0) * 1000
        m = _current.get()
        if m is not None:
            m.add_agent_time(self.name, ms)
        return self._cm.__exit__(*exc)

"""
Thin LLM client used outside the ADK runner (grounding checker, reranker, LLM judge,
screenshot extraction) plus the model factory for ADK agents.

LLM_PROVIDER:
  gemini  (default)  google-genai: Gemini API key, or Vertex AI when GOOGLE_GENAI_USE_VERTEXAI=true
  groq / nvidia      OpenAI-compatible endpoints, for development where no Gemini key exists.
                     ADK agents use them through LiteLlm.

Every call records measured token usage and latency through moneytrace.telemetry.
"""

import json
import os
import time
import logging
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from moneytrace.config import get_settings
from moneytrace.telemetry import record_model_call

logger = logging.getLogger("moneytrace.llm")

OPENAI_COMPAT = {
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "openai/gpt-oss-120b", "openai/gpt-oss-20b"),
    "nvidia": ("https://integrate.api.nvidia.com/v1", "NVIDIA_API_KEY", "minimaxai/minimax-m3.1-flash",
               "nvidia/nemotron-3.5-lightning-30b-a3b"),
}


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float


def provider() -> str:
    return os.environ.get("LLM_PROVIDER", "gemini").strip().lower()


def model_for(tier: str = "fast") -> str:
    """Model id for a tier: fast (routine steps), strong (guidance drafting), judge (evaluation)."""
    s = get_settings()
    p = provider()
    if p in OPENAI_COMPAT:
        _, _, strong, fast = OPENAI_COMPAT[p]
        if tier == "vision":
            return os.environ.get("DEV_VISION_MODEL") or "nvidia/nemotron-3.5-super-vl-120b-a12b"
        env = {"fast": "DEV_FAST_MODEL", "strong": "DEV_STRONG_MODEL", "judge": "DEV_JUDGE_MODEL"}[tier]
        return os.environ.get(env) or (fast if tier == "fast" else strong)
    return {"fast": s.fast_model, "strong": s.strong_model, "judge": s.judge_model, "vision": s.fast_model}[tier]


def llm_available() -> bool:
    p = provider()
    if p in OPENAI_COMPAT:
        return True  # key injected by env or by the outbound proxy
    return get_settings().llm_configured()


def adk_model(tier: str = "fast", thinking: bool = True) -> Any:
    """Model argument for google.adk LlmAgent: a Gemini model id, or a LiteLlm wrapper."""
    p = provider()
    name = model_for(tier)
    if p in OPENAI_COMPAT:
        import litellm
        from google.adk.models.lite_llm import LiteLlm
        litellm.num_retries = int(os.environ.get("LLM_NUM_RETRIES", "4"))
        litellm.request_timeout = 120
        base, key_env, _, _ = OPENAI_COMPAT[p]
        os.environ.setdefault(key_env, "proxy-injected")
        if p == "groq":
            return LiteLlm(model=f"groq/{name}")
        extra = {}
        if p == "nvidia" and "nemotron" in name and not thinking:
            extra["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
        return LiteLlm(model=f"openai/{name}", api_base=base, api_key=os.environ[key_env], **extra)
    return name


_genai_client = None


def _gemini_client():
    global _genai_client
    if _genai_client is None:
        from google import genai
        s = get_settings()
        if s.use_vertex:
            _genai_client = genai.Client(vertexai=True, project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
                                         location=os.environ.get("GOOGLE_CLOUD_LOCATION", "asia-south1"))
        else:
            _genai_client = genai.Client(api_key=s.gemini_api_key())
    return _genai_client


def generate_text(prompt: str, *, tier: str = "fast", agent: str = "llm", json_mode: bool = False,
                  system: Optional[str] = None, temperature: float = 0.0, max_tokens: int = 2048,
                  image_bytes: Optional[bytes] = None, image_mime: str = "image/png",
                  model: Optional[str] = None, provider_override: Optional[str] = None) -> LLMResult:
    p = (provider_override or provider()).strip().lower()
    model = model or model_for(tier)
    t0 = time.perf_counter()
    if p in OPENAI_COMPAT:
        base, key_env, _, _ = OPENAI_COMPAT[p]
        msgs = []
        if system:
            msgs.append({"role": "system", "content": system})
        if image_bytes:
            import base64
            uri = f"data:{image_mime};base64,{base64.b64encode(image_bytes).decode()}"
            msgs.append({"role": "user", "content": [{"type": "text", "text": prompt},
                                                     {"type": "image_url", "image_url": {"url": uri}}]})
        else:
            msgs.append({"role": "user", "content": prompt})
        body = {"model": model, "messages": msgs, "temperature": temperature, "max_tokens": max_tokens}
        if p == "nvidia" and "nemotron" in model and os.environ.get("DEV_THINKING", "0") != "1":
            body["chat_template_kwargs"] = {"enable_thinking": False}  # judge / translator: no hidden reasoning tokens
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        delay = 2.0
        for attempt in range(5):
            r = httpx.post(f"{base}/chat/completions", json=body, timeout=120,
                           headers={"Authorization": f"Bearer {os.environ.get(key_env, 'proxy-injected')}"})
            if r.status_code in (429, 500, 502, 503) and attempt < 4:
                time.sleep(delay)
                delay *= 2
                continue
            break
        if r.status_code != 200:
            raise RuntimeError(f"{p} HTTP {r.status_code}: {r.text[:300]}")
        d = r.json()
        text = d["choices"][0]["message"].get("content") or ""
        usage = d.get("usage") or {}
        inp, out = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
    else:
        from google.genai import types
        cfg = types.GenerateContentConfig(temperature=temperature, max_output_tokens=max_tokens,
                                          system_instruction=system,
                                          response_mime_type="application/json" if json_mode else None)
        contents: Any = prompt
        if image_bytes:
            contents = [types.Part.from_bytes(data=image_bytes, mime_type=image_mime), prompt]
        resp = _gemini_client().models.generate_content(model=model, contents=contents, config=cfg)
        text = resp.text or ""
        um = resp.usage_metadata
        inp = int(getattr(um, "prompt_token_count", 0) or 0)
        out = int(getattr(um, "candidates_token_count", 0) or 0) + int(getattr(um, "thoughts_token_count", 0) or 0)
    ms = (time.perf_counter() - t0) * 1000
    record_model_call(agent, model, inp, out, ms)
    return LLMResult(text=text, model=model, input_tokens=inp, output_tokens=out, latency_ms=ms)


def generate_json(prompt: str, **kw) -> Any:
    res = generate_text(prompt, json_mode=True, **kw)
    txt = res.text.strip()
    if txt.startswith("```"):
        txt = txt.strip("`")
        txt = txt[txt.find("{"):] if "{" in txt else txt
    start = min([i for i in (txt.find("{"), txt.find("[")) if i >= 0], default=0)
    return json.loads(txt[start:])

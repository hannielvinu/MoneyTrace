"""
Embedding providers for the advisory corpus.

EMBEDDING_PROVIDER:
  gemini  (default) Gemini API / Vertex AI `gemini-embedding-001` via google-genai,
          task types RETRIEVAL_DOCUMENT / RETRIEVAL_QUERY, output_dimensionality=EMBEDDING_DIM (768).
  nvidia  NVIDIA API catalog (OpenAI-compatible), e.g. nvidia/nemotron-3-embed-1b (2048-d).
          Used for development where no Gemini key is available.
  hash    Deterministic bag-of-words hashing. Unit tests ONLY - never used for reported metrics.

Every returned vector is L2-normalised. The provider/model/dimension used at
ingest time is stored in the `rag_meta` table, and retrieval refuses to run with
a different model (mixing embedding spaces silently ruins recall).
"""

import hashlib
import math
import os
import re
import time
import logging
from dataclasses import dataclass
from typing import List, Sequence

import httpx

logger = logging.getLogger("moneytrace.rag.embeddings")


def _norm(v: Sequence[float]) -> List[float]:
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


@dataclass
class EmbeddingUsage:
    calls: int = 0
    texts: int = 0
    input_tokens: int = 0


class BaseEmbedder:
    provider = "base"
    model = ""
    dim = 0
    batch_size = 32

    def __init__(self):
        self.usage = EmbeddingUsage()

    def _embed(self, texts: List[str], kind: str) -> List[List[float]]:
        raise NotImplementedError

    def _with_retry(self, texts: List[str], kind: str) -> List[List[float]]:
        delay = 2.0
        for attempt in range(8):
            try:
                return self._embed(texts, kind)
            except Exception as e:
                msg = str(e)
                transient = any(s in msg for s in ("429", "overloaded", "503", "500", "RESOURCE_EXHAUSTED",
                                                    "timed out", "Timeout", "502", "504"))
                if not transient or attempt == 7:
                    raise
                logger.warning(f"embedding retry {attempt + 1}: {msg[:120]}")
                time.sleep(delay)
                delay = min(delay * 2, 65)
        raise RuntimeError("unreachable")

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        # EMBED_BATCH_SIZE / EMBED_PAUSE_S pace large documents under free-tier per-minute quotas
        size = int(os.environ.get("EMBED_BATCH_SIZE", self.batch_size))
        pause = float(os.environ.get("EMBED_PAUSE_S", "0"))
        out: List[List[float]] = []
        for i in range(0, len(texts), size):
            if i and pause:
                time.sleep(pause)
            batch = texts[i:i + size]
            out.extend(_norm(v) for v in self._with_retry(batch, "document"))
        return out

    def embed_query(self, text: str) -> List[float]:
        return _norm(self._with_retry([text], "query")[0])

    def describe(self) -> dict:
        return {"provider": self.provider, "model": self.model, "dim": self.dim}


class GeminiEmbedder(BaseEmbedder):
    provider = "gemini"
    batch_size = 50

    def __init__(self, model: str, dim: int):
        super().__init__()
        from google import genai
        self.model, self.dim = model, dim
        use_vertex = os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in ("1", "true")
        if use_vertex:
            self.client = genai.Client(vertexai=True, project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
                                       location=os.environ.get("GOOGLE_CLOUD_LOCATION", "asia-south1"))
            self.provider = "vertex"
        else:
            key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY") or os.environ.get("LLM_API_KEY")
            self.client = genai.Client(api_key=key)

    def _embed(self, texts, kind):
        from google.genai import types
        res = self.client.models.embed_content(
            model=self.model, contents=texts,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT" if kind == "document" else "RETRIEVAL_QUERY",
                output_dimensionality=self.dim),
        )
        self.usage.calls += 1
        self.usage.texts += len(texts)
        self.usage.input_tokens += sum(len(t) // 4 for t in texts)  # API does not return token counts
        return [e.values for e in res.embeddings]


class NvidiaEmbedder(BaseEmbedder):
    provider = "nvidia"
    batch_size = 16

    def __init__(self, model: str, dim: int):
        super().__init__()
        self.model, self.dim = model, dim
        self.url = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1") + "/embeddings"
        self.key = os.environ.get("NVIDIA_API_KEY", "proxy-injected")
        self.client = httpx.Client(timeout=120)

    def _embed(self, texts, kind):
        body = {"model": self.model, "input": texts, "input_type": "passage" if kind == "document" else "query",
                "encoding_format": "float", "truncate": "END"}
        r = self.client.post(self.url, json=body, headers={"Authorization": f"Bearer {self.key}"})
        if r.status_code != 200:
            raise RuntimeError(f"NVIDIA embeddings HTTP {r.status_code}: {r.text[:200]}")
        d = r.json()
        self.usage.calls += 1
        self.usage.texts += len(texts)
        self.usage.input_tokens += int((d.get("usage") or {}).get("prompt_tokens") or 0)
        vecs = [x["embedding"] for x in sorted(d["data"], key=lambda x: x["index"])]
        if vecs and len(vecs[0]) != self.dim:
            raise RuntimeError(f"model returned {len(vecs[0])}-d vectors, EMBEDDING_DIM={self.dim}")
        return vecs


class HashEmbedder(BaseEmbedder):
    """Deterministic hashed bag of words (+ bigrams). Tests only."""
    provider = "hash"
    batch_size = 1000

    def __init__(self, dim: int = 256):
        super().__init__()
        self.model, self.dim = "hash-bow", dim

    def _embed(self, texts, kind):
        out = []
        for t in texts:
            v = [0.0] * self.dim
            toks = re.findall(r"\w+", t.lower())
            for tok in toks + [a + "_" + b for a, b in zip(toks, toks[1:])]:
                h = int(hashlib.md5(tok.encode()).hexdigest(), 16)
                v[h % self.dim] += 1.0 if (h >> 8) % 2 else -1.0
            out.append(v)
        return out


_DEFAULTS = {
    "gemini": ("gemini-embedding-001", 768),
    "vertex": ("gemini-embedding-001", 768),
    "nvidia": ("nvidia/nemotron-3-embed-1b", 2048),
    "hash": ("hash-bow", 256),
}


def get_embedder(provider: str = None) -> BaseEmbedder:
    provider = (provider or os.environ.get("EMBEDDING_PROVIDER", "gemini")).lower()
    model_default, dim_default = _DEFAULTS.get(provider, _DEFAULTS["gemini"])
    model = os.environ.get("EMBEDDING_MODEL") or model_default
    dim = int(os.environ.get("EMBEDDING_DIM") or dim_default)
    if provider in ("gemini", "vertex"):
        return GeminiEmbedder(model, dim)
    if provider == "nvidia":
        return NvidiaEmbedder(model, dim)
    if provider == "hash":
        return HashEmbedder(dim)
    raise ValueError(f"unknown EMBEDDING_PROVIDER {provider}")

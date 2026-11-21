"""
Hybrid retrieval over the advisory corpus.

score = reciprocal-rank fusion (RRF, k=60) of
  - pgvector cosine top-N   (semantic; works across English / Hindi / Tamil queries)
  - Postgres full-text top-N (exact terms: "1930", "UPI PIN", "KYC", circular numbers)
then de-duplicated so one document cannot fill all k slots, and optionally
re-scored by an LLM reranker (RAG_RERANK=1; kept only if it improves recall@5).

Public API:
    retrieve(query, k=5) -> list[Citation]
    search_advisories(query, k=5) -> list[dict]      # ADK tool
"""

import os
import time
import logging
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional

from moneytrace.config import get_settings

logger = logging.getLogger("moneytrace.rag.retriever")


@dataclass
class Citation:
    chunk_id: str
    doc_id: str
    title: str
    issuer: str
    url: str
    section: str
    published_date: Optional[str]
    text: str
    score: float
    vector_rank: Optional[int] = None
    keyword_rank: Optional[int] = None

    def short(self, max_chars: int = 900) -> Dict:
        d = asdict(self)
        d["text"] = self.text[:max_chars]
        return d


@dataclass
class RetrievalTrace:
    query: str
    latency_ms: float = 0.0
    vector_hits: int = 0
    keyword_hits: int = 0
    reranked: bool = False
    embedding_model: str = ""
    extra: Dict = field(default_factory=dict)


_embedder = None
_embedder_key = None


def _get_embedder():
    global _embedder, _embedder_key
    from rag.embeddings import get_embedder
    key = (os.environ.get("EMBEDDING_PROVIDER"), os.environ.get("EMBEDDING_MODEL"), os.environ.get("EMBEDDING_DIM"))
    if _embedder is None or key != _embedder_key:
        _embedder, _embedder_key = get_embedder(), key
    return _embedder


def rrf_merge(lists: List[List[Dict]], k: int = 60) -> List[Dict]:
    """Reciprocal-rank fusion. Each input list is ordered best-first and items carry an 'id'."""
    scores: Dict[str, float] = {}
    items: Dict[str, Dict] = {}
    ranks: Dict[str, Dict[int, int]] = {}
    for li, lst in enumerate(lists):
        for rank, item in enumerate(lst, 1):
            cid = item["id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
            items.setdefault(cid, item)
            ranks.setdefault(cid, {})[li] = rank
    merged = sorted(items.values(), key=lambda it: scores[it["id"]], reverse=True)
    for it in merged:
        it["rrf_score"] = scores[it["id"]]
        it["_ranks"] = ranks[it["id"]]
    return merged


def _diversify(items: List[Dict], k: int, max_per_doc: int = 2) -> List[Dict]:
    out, per_doc = [], {}
    for it in items:
        if per_doc.get(it["doc_id"], 0) >= max_per_doc:
            continue
        out.append(it)
        per_doc[it["doc_id"]] = per_doc.get(it["doc_id"], 0) + 1
        if len(out) == k:
            break
    if len(out) < k:  # corpus too small for diversity: fill with the remaining best
        seen = {o["id"] for o in out}
        out += [it for it in items if it["id"] not in seen][: k - len(out)]
    return out


def _translate_enabled() -> bool:
    return os.environ.get("RAG_QUERY_TRANSLATE", "1").strip().lower() in ("1", "true", "yes")


def is_non_english(text: str) -> bool:
    non_ascii_letters = sum(1 for ch in text if ord(ch) > 0x900)
    return non_ascii_letters > max(3, len(text) * 0.2)


def translate_query(query: str) -> Optional[str]:
    """English rendering of a Hindi / Tamil / Kannada query (adds English vector + full-text lists to the fusion)."""
    if not is_non_english(query):
        return None
    try:
        from moneytrace.llm import generate_text, llm_available
        if not llm_available():
            return None
        res = generate_text("Translate this message from a scam victim into plain English. Output only the translation.\n\n"
                            + query, tier="fast", agent="query_translator", max_tokens=1500)
        out = (res.text or "").strip().strip('"')
        return out or None
    except Exception as e:
        logger.warning(f"query translation failed: {type(e).__name__}")
        return None


def retrieve(query: str, k: Optional[int] = None, engine=None, trace: Optional[RetrievalTrace] = None,
             rerank: Optional[bool] = None, translate: Optional[bool] = None) -> List[Citation]:
    from rag import store
    s = get_settings()
    k = k or s.rag_top_k
    n = max(s.rag_candidates, k)
    rerank = s.rag_rerank if rerank is None else rerank
    if engine is None:
        from moneytrace.db.database import get_engine
        engine = get_engine()
    t0 = time.perf_counter()
    emb = _get_embedder()
    english = translate_query(query) if (translate if translate is not None else _translate_enabled()) else None
    with engine.connect() as conn:
        meta = store.get_meta(conn)
        if meta.get("embedding_model") and meta["embedding_model"] != emb.model:
            raise RuntimeError(f"corpus was embedded with {meta['embedding_model']} but the retriever is configured "
                               f"for {emb.model}; set EMBEDDING_PROVIDER/EMBEDDING_MODEL to match or re-ingest")
        qvec = emb.embed_query(query)
        vec_hits = store.vector_search(conn, qvec, n)
        kw_hits = store.keyword_search(conn, query, n)
        lists = [vec_hits, kw_hits]
        if english:
            lists.append(store.vector_search(conn, emb.embed_query(english), n))
            lists.append(store.keyword_search(conn, english, n))
    merged = rrf_merge(lists, k=s.rag_rrf_k)
    if rerank and merged:
        from rag.rerank import llm_rerank
        merged = llm_rerank(query, merged[: max(10, k * 2)])
    top = _diversify(merged, k)
    if trace is not None:
        trace.latency_ms = (time.perf_counter() - t0) * 1000
        trace.vector_hits, trace.keyword_hits = len(vec_hits), len(kw_hits)
        trace.reranked, trace.embedding_model = bool(rerank), emb.model
        trace.extra["translated_query"] = english
    return [Citation(chunk_id=it["id"], doc_id=it["doc_id"], title=it["title"] or "", issuer=it["issuer"] or "",
                     url=it["url"] or "", section=it.get("section") or "", published_date=it.get("published_date"),
                     text=it["text"], score=round(float(it.get("rerank_score", it["rrf_score"])), 5),
                     vector_rank=it["_ranks"].get(0), keyword_rank=it["_ranks"].get(1)) for it in top]


def search_advisories(query: str, k: int = 5) -> List[Dict]:
    """Search official RBI / NPCI / CERT-In / I4C / SEBI fraud advisories.

    Use this before giving a scam victim any step. Each result has a chunk_id,
    title, issuer, url and the advisory text; cite the chunk_id of every
    result you rely on.

    Args:
        query: what the victim needs to know, e.g. "UPI money sent to fraudster how to report".
        k: number of passages to return (default 5).
    """
    try:
        return [c.short() for c in retrieve(query, k=k)]
    except Exception as e:  # a tool must return data, not raise, so the agent can fall back safely
        logger.error(f"search_advisories failed: {e}")
        return [{"error": f"advisory search unavailable: {type(e).__name__}"}]

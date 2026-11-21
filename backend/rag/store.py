"""
Storage for the advisory corpus.

PostgreSQL (production): pgvector `vector(N)` column + HNSW cosine index, and a
generated `tsvector` column + GIN index for full-text search.

SQLite (unit tests / offline dev only): the embedding is stored as JSON and both
searches run in Python. This keeps the retrieval code path testable without a
Postgres server; real metrics are only ever measured on Postgres.
"""

import json
import math
import re
import logging
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.engine import Connection

logger = logging.getLogger("moneytrace.rag.store")


def _is_pg(conn: Connection) -> bool:
    return conn.dialect.name == "postgresql"


def create_rag_schema(conn: Connection, dim: int = 768):
    if _is_pg(conn):
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS advisory_documents (
            doc_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            issuer TEXT,
            url TEXT,
            published_date TEXT,
            language TEXT,
            content_hash TEXT,
            n_chunks INTEGER,
            fetched_at TIMESTAMPTZ DEFAULT now()
        )"""))
        conn.execute(text(f"""
        CREATE TABLE IF NOT EXISTS advisory_chunks (
            id TEXT PRIMARY KEY,
            doc_id TEXT NOT NULL REFERENCES advisory_documents(doc_id) ON DELETE CASCADE,
            title TEXT,
            issuer TEXT,
            url TEXT,
            published_date TEXT,
            section TEXT,
            chunk_index INTEGER,
            text TEXT NOT NULL,
            content_hash TEXT,
            embedding vector({dim}),
            tsv tsvector GENERATED ALWAYS AS (
                setweight(to_tsvector('english', coalesce(title, '') || ' ' || coalesce(section, '')), 'A') ||
                setweight(to_tsvector('english', text), 'B')
            ) STORED
        )"""))
        if dim <= 2000:  # pgvector HNSW limit for the `vector` type
            conn.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw ON advisory_chunks "
                "USING hnsw (embedding vector_cosine_ops)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_chunks_tsv ON advisory_chunks USING gin (tsv)"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS ix_chunks_doc ON advisory_chunks (doc_id)"))
    else:
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS advisory_documents (
            doc_id TEXT PRIMARY KEY, title TEXT NOT NULL, issuer TEXT, url TEXT,
            published_date TEXT, language TEXT, content_hash TEXT, n_chunks INTEGER,
            fetched_at TEXT DEFAULT CURRENT_TIMESTAMP
        )"""))
        conn.execute(text("""
        CREATE TABLE IF NOT EXISTS advisory_chunks (
            id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, title TEXT, issuer TEXT, url TEXT,
            published_date TEXT, section TEXT, chunk_index INTEGER, text TEXT NOT NULL,
            content_hash TEXT, embedding TEXT
        )"""))


def _create_meta(conn: Connection):
    conn.execute(text("CREATE TABLE IF NOT EXISTS rag_meta (key TEXT PRIMARY KEY, value TEXT)"))


def get_meta(conn: Connection) -> Dict[str, str]:
    _create_meta(conn)
    return {r[0]: r[1] for r in conn.execute(text("SELECT key, value FROM rag_meta")).all()}


def set_meta(conn: Connection, values: Dict[str, Any]):
    _create_meta(conn)
    for k, v in values.items():
        conn.execute(text("DELETE FROM rag_meta WHERE key = :k"), {"k": k})
        conn.execute(text("INSERT INTO rag_meta (key, value) VALUES (:k, :v)"), {"k": k, "v": str(v)})


def ensure_rag_schema(engine, dim: int = 768):
    with engine.begin() as conn:
        _create_meta(conn)
        create_rag_schema(conn, dim)


def reset_rag_schema(engine, dim: int, embedder_desc: Dict[str, Any]):
    """Drop and recreate the corpus tables for a new embedding model / dimension."""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS advisory_chunks"))
        conn.execute(text("DROP TABLE IF EXISTS advisory_documents"))
        _create_meta(conn)
        conn.execute(text("DELETE FROM rag_meta"))
        create_rag_schema(conn, dim)
        set_meta(conn, {"embedding_provider": embedder_desc["provider"], "embedding_model": embedder_desc["model"],
                        "embedding_dim": dim})


def _vec_literal(vec: Sequence[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in vec) + "]"


def get_document_hash(conn: Connection, doc_id: str) -> Optional[str]:
    row = conn.execute(text("SELECT content_hash FROM advisory_documents WHERE doc_id = :d"), {"d": doc_id}).first()
    return row[0] if row else None


def upsert_document(conn: Connection, doc: Dict[str, Any], chunks: List[Dict[str, Any]]):
    """Replace a document and all its chunks atomically (caller owns the transaction)."""
    conn.execute(text("DELETE FROM advisory_chunks WHERE doc_id = :d"), {"d": doc["doc_id"]})
    conn.execute(text("DELETE FROM advisory_documents WHERE doc_id = :d"), {"d": doc["doc_id"]})
    conn.execute(text("""
        INSERT INTO advisory_documents (doc_id, title, issuer, url, published_date, language, content_hash, n_chunks)
        VALUES (:doc_id, :title, :issuer, :url, :published_date, :language, :content_hash, :n_chunks)
    """), {**{k: doc.get(k) for k in ("doc_id", "title", "issuer", "url", "published_date", "language", "content_hash")},
           "n_chunks": len(chunks)})
    pg = _is_pg(conn)
    for c in chunks:
        params = {k: c.get(k) for k in ("id", "doc_id", "title", "issuer", "url", "published_date",
                                         "section", "chunk_index", "text", "content_hash")}
        params["embedding"] = _vec_literal(c["embedding"]) if pg else json.dumps(c["embedding"])
        cast = "CAST(:embedding AS vector)" if pg else ":embedding"
        conn.execute(text(f"""
            INSERT INTO advisory_chunks (id, doc_id, title, issuer, url, published_date, section, chunk_index,
                                         text, content_hash, embedding)
            VALUES (:id, :doc_id, :title, :issuer, :url, :published_date, :section, :chunk_index,
                    :text, :content_hash, {cast})
        """), params)


def delete_documents_not_in(conn: Connection, keep_ids: List[str]) -> int:
    rows = conn.execute(text("SELECT doc_id FROM advisory_documents")).all()
    stale = [r[0] for r in rows if r[0] not in set(keep_ids)]
    for d in stale:
        conn.execute(text("DELETE FROM advisory_chunks WHERE doc_id = :d"), {"d": d})
        conn.execute(text("DELETE FROM advisory_documents WHERE doc_id = :d"), {"d": d})
    return len(stale)


def corpus_stats(conn: Connection) -> Dict[str, Any]:
    docs = conn.execute(text("SELECT COUNT(*) FROM advisory_documents")).scalar() or 0
    chunks = conn.execute(text("SELECT COUNT(*) FROM advisory_chunks")).scalar() or 0
    by_issuer = conn.execute(text(
        "SELECT issuer, COUNT(*) FROM advisory_documents GROUP BY issuer ORDER BY COUNT(*) DESC")).all()
    return {"documents": docs, "chunks": chunks, "by_issuer": {r[0]: r[1] for r in by_issuer}}


_COLS = "id, doc_id, title, issuer, url, published_date, section, chunk_index, text"


def _row_to_dict(r) -> Dict[str, Any]:
    keys = ["id", "doc_id", "title", "issuer", "url", "published_date", "section", "chunk_index", "text"]
    return {k: r[i] for i, k in enumerate(keys)}


def vector_search(conn: Connection, query_vec: Sequence[float], k: int) -> List[Dict[str, Any]]:
    if _is_pg(conn):
        rows = conn.execute(text(f"""
            SELECT {_COLS}, 1 - (embedding <=> CAST(:q AS vector)) AS score
            FROM advisory_chunks
            ORDER BY embedding <=> CAST(:q AS vector)
            LIMIT :k
        """), {"q": _vec_literal(query_vec), "k": k}).all()
        return [{**_row_to_dict(r), "score": float(r[9])} for r in rows]

    rows = conn.execute(text(f"SELECT {_COLS}, embedding FROM advisory_chunks")).all()
    qn = math.sqrt(sum(x * x for x in query_vec)) or 1.0
    scored = []
    for r in rows:
        v = json.loads(r[9])
        vn = math.sqrt(sum(x * x for x in v)) or 1.0
        scored.append((sum(a * b for a, b in zip(query_vec, v)) / (qn * vn), r))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [{**_row_to_dict(r), "score": float(s)} for s, r in scored[:k]]


_TOKEN = re.compile(r"[\w']+", re.UNICODE)
_STOP = {"the", "a", "an", "of", "to", "and", "or", "in", "on", "for", "is", "my", "i", "me", "what",
         "how", "do", "should", "it", "be", "if", "with", "can", "was", "are", "this", "that", "by"}


def keyword_search(conn: Connection, query: str, k: int) -> List[Dict[str, Any]]:
    try:
        return _keyword_search(conn, query, k)
    except Exception as e:  # full-text is a booster; never fail retrieval because of it
        logger.warning(f"keyword search failed, using vector results only: {type(e).__name__}")
        try:
            conn.rollback()
        except Exception:
            pass
        return []


def _keyword_search(conn: Connection, query: str, k: int) -> List[Dict[str, Any]]:
    if _is_pg(conn):
        rows = conn.execute(text(f"""
            SELECT {_COLS}, ts_rank_cd(tsv, q) AS score
            FROM advisory_chunks, websearch_to_tsquery('english', :q) q
            WHERE tsv @@ q
            ORDER BY score DESC
            LIMIT :k
        """), {"q": query, "k": k}).all()
        if not rows:
            # websearch_to_tsquery ANDs terms; fall back to OR semantics for long natural questions.
            # English stemming config: only ASCII alphanumeric terms are meaningful (and safe) here.
            terms = [t for t in _TOKEN.findall(query.lower())
                     if t not in _STOP and len(t) > 2 and re.fullmatch(r"[a-z0-9]+", t)]
            if terms:
                rows = conn.execute(text(f"""
                    SELECT {_COLS}, ts_rank_cd(tsv, q) AS score
                    FROM advisory_chunks, to_tsquery('english', :q) q
                    WHERE tsv @@ q
                    ORDER BY score DESC
                    LIMIT :k
                """), {"q": " | ".join(terms), "k": k}).all()
        return [{**_row_to_dict(r), "score": float(r[9])} for r in rows]

    terms = {t for t in _TOKEN.findall(query.lower()) if t not in _STOP}
    rows = conn.execute(text(f"SELECT {_COLS} FROM advisory_chunks")).all()
    scored = []
    for r in rows:
        body = _TOKEN.findall(f"{r[2]} {r[6] or ''} {r[8]}".lower())
        if not body:
            continue
        hits = sum(1 for t in body if t in terms)
        if hits:
            scored.append((hits / math.sqrt(len(body)), r))
    scored.sort(key=lambda t: t[0], reverse=True)
    return [{**_row_to_dict(r), "score": float(s)} for s, r in scored[:k]]

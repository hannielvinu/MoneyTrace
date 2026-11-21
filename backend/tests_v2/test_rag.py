"""Chunking, idempotent upsert and hybrid retrieval (SQLite + deterministic hash embedder; no network)."""
import os
import tempfile

import pytest
from sqlalchemy import create_engine

from rag import store
from rag.ingest import chunk_document, approx_tokens, content_hash
from rag.retriever import retrieve, rrf_merge, search_advisories
from rag.embeddings import HashEmbedder

DOCS = [
    ("rbi-liability", "Customer Protection – Limiting Liability of Customers in Unauthorised Electronic Banking Transactions",
     "Reserve Bank of India", "https://www.rbi.org.in/x1",
     "# Zero liability\nA customer has zero liability when the unauthorised transaction is reported to the bank "
     "within three working days of receiving the communication from the bank.\n# Limited liability\n"
     "If the delay in reporting is four to seven working days, the customer liability is limited."),
    ("npci-pin", "UPI safety: never enter your UPI PIN to receive money", "NPCI", "https://www.npci.org.in/x2",
     "You never need to enter your UPI PIN to receive money. A collect request asking for your PIN is a fraud. "
     "Decline unknown collect requests."),
    ("i4c-1930", "Report financial cyber fraud on 1930", "I4C, Ministry of Home Affairs", "https://cybercrime.gov.in/x3",
     "Call the national cyber crime helpline 1930 immediately or file a complaint on cybercrime.gov.in "
     "so that the money can be frozen in the fraudster's account."),
]


@pytest.fixture()
def corpus(monkeypatch):
    path = os.path.join(tempfile.mkdtemp(), "rag.db")
    eng = create_engine(f"sqlite:///{path}")
    monkeypatch.setenv("EMBEDDING_PROVIDER", "hash")
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    monkeypatch.setenv("EMBEDDING_DIM", "256")
    emb = HashEmbedder(256)
    store.reset_rag_schema(eng, 256, emb.describe())
    with eng.begin() as conn:
        for doc_id, title, issuer, url, text in DOCS:
            chunks = chunk_document(text, chunk_tokens=40, overlap_tokens=5) or [{"section": "", "text": text}]
            vecs = emb.embed_documents([f"{title}\n{c['text']}" for c in chunks])
            store.upsert_document(conn, {"doc_id": doc_id, "title": title, "issuer": issuer, "url": url,
                                         "published_date": None, "language": "en", "content_hash": "h"},
                                  [{"id": f"{doc_id}#{i}", "doc_id": doc_id, "title": title, "issuer": issuer, "url": url,
                                    "published_date": None, "section": c["section"], "chunk_index": i, "text": c["text"],
                                    "content_hash": "c", "embedding": v} for i, (c, v) in enumerate(zip(chunks, vecs))])
    return eng


def test_chunker_respects_size_and_keeps_sections():
    text = "# Section A\n" + " ".join(["word"] * 900) + "\n# Section B\n" + "short tail paragraph " * 20
    chunks = chunk_document(text, chunk_tokens=200, overlap_tokens=20)
    assert len(chunks) >= 4
    assert all(approx_tokens(c["text"]) <= 230 for c in chunks)
    assert {c["section"] for c in chunks} == {"Section A", "Section B"}


def test_content_hash_changes_with_model():
    a = content_hash("x", {"provider": "gemini", "model": "m1", "dim": 768})
    b = content_hash("x", {"provider": "gemini", "model": "m2", "dim": 768})
    assert a != b


def test_rrf_prefers_items_ranked_by_both():
    v = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    k = [{"id": "b"}, {"id": "x"}, {"id": "y"}]
    merged = [m["id"] for m in rrf_merge([v, k])]
    assert merged[0] == "b"


def test_upsert_is_idempotent(corpus):
    with corpus.begin() as conn:
        before = store.corpus_stats(conn)
        rows = [{"id": "npci-pin#0", "doc_id": "npci-pin", "title": "t", "issuer": "NPCI", "url": "u",
                 "published_date": None, "section": "", "chunk_index": 0, "text": "again", "content_hash": "c",
                 "embedding": [0.0] * 256}]
        store.upsert_document(conn, {"doc_id": "npci-pin", "title": "t", "issuer": "NPCI", "url": "u",
                                     "published_date": None, "language": "en", "content_hash": "h2"}, rows)
        after = store.corpus_stats(conn)
    assert after["documents"] == before["documents"]


@pytest.mark.parametrize("query,expected_doc", [
    ("how many days to report unauthorised transaction for zero liability", "rbi-liability"),
    ("caller asked me to enter my UPI PIN to receive money", "npci-pin"),
    ("which helpline number do I call for cyber fraud 1930", "i4c-1930"),
])
def test_hybrid_retrieval_returns_relevant_citation(corpus, query, expected_doc):
    res = retrieve(query, k=3, engine=corpus)
    assert res[0].doc_id == expected_doc
    assert res[0].title and res[0].url.startswith("https://")


def test_retriever_refuses_mismatched_embedding_model(corpus, monkeypatch):
    with corpus.begin() as conn:
        store.set_meta(conn, {"embedding_model": "some-other-model"})
    with pytest.raises(RuntimeError):
        retrieve("1930", k=3, engine=corpus)


def test_search_tool_never_raises(monkeypatch):
    monkeypatch.setattr("rag.retriever.retrieve", lambda *a, **k: (_ for _ in ()).throw(ValueError("db down")))
    import asyncio
    out = asyncio.run(search_advisories("anything"))
    assert out and "error" in out[0]

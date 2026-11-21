"""
Ingest the reviewed advisory corpus into Postgres + pgvector.

    python -m rag.ingest                 # uses rag/sources.yaml, EMBEDDING_PROVIDER, DATABASE_URL
    python -m rag.ingest --refetch       # also retry entries marked `unfetched` (run on a laptop)

Pipeline per source (include: true):
  fetch (cache in rag/raw/, robots.txt respected) -> extract text (HTML / PDF)
  -> clean -> chunk (~600 tokens, 100-token overlap, headings kept as section labels)
  -> embed (Gemini / Vertex / NVIDIA) -> upsert into advisory_documents / advisory_chunks.

Idempotent: a document whose content hash (text + chunking parameters + embedding
model) is unchanged is skipped. Counts are written to rag/STATS.md and
results/ingest/<timestamp>.json.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from typing import Dict, List, Tuple

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from dotenv import load_dotenv  # noqa: E402
load_dotenv(os.path.join(BACKEND, ".env"))

from rag.fetch import PoliteFetcher, extract  # noqa: E402
from rag.embeddings import get_embedder  # noqa: E402
from rag import store  # noqa: E402

CHUNK_TOKENS = int(os.environ.get("RAG_CHUNK_TOKENS", "600"))
OVERLAP_TOKENS = int(os.environ.get("RAG_OVERLAP_TOKENS", "100"))
CHARS_PER_TOKEN = 4  # documented approximation for English text; used only for chunk sizing
MAX_DOC_CHUNKS = int(os.environ.get("RAG_MAX_DOC_CHUNKS", "400"))


def approx_tokens(s: str) -> int:
    return max(1, len(s) // CHARS_PER_TOKEN)


def split_sections(text: str) -> List[Tuple[str, str]]:
    """Split on '# heading' lines produced by the extractor -> [(section, body)]."""
    sections, current, buf = [], "", []
    for line in text.splitlines():
        if line.startswith("# "):
            if buf:
                sections.append((current, "\n".join(buf)))
                buf = []
            current = line[2:].strip()[:200]
        else:
            buf.append(line)
    if buf:
        sections.append((current, "\n".join(buf)))
    return sections


def _split_long(paragraph: str, max_chars: int) -> List[str]:
    if len(paragraph) <= max_chars:
        return [paragraph]
    sentences = re.split(r"(?<=[.!?।])\s+", paragraph)
    out, cur = [], ""
    for s in sentences:
        while len(s) > max_chars:  # pathological sentence (tables, lists without punctuation)
            out.append(s[:max_chars])
            s = s[max_chars:]
        if len(cur) + len(s) + 1 > max_chars and cur:
            out.append(cur)
            cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        out.append(cur)
    return out


def chunk_document(text: str, chunk_tokens: int = CHUNK_TOKENS, overlap_tokens: int = OVERLAP_TOKENS) -> List[Dict]:
    """Greedy paragraph packing within sections; overlap carries the tail of the previous chunk."""
    max_chars = chunk_tokens * CHARS_PER_TOKEN
    overlap_chars = overlap_tokens * CHARS_PER_TOKEN
    chunks: List[Dict] = []
    tail = ""
    for section, body in split_sections(text):
        paras = [p.strip() for p in body.split("\n") if p.strip()]
        pieces: List[str] = []
        for p in paras:
            pieces.extend(_split_long(p, max_chars))
        cur = tail
        for p in pieces:
            if len(cur) + len(p) + 1 > max_chars and cur.strip() and cur != tail:
                chunks.append({"section": section, "text": cur.strip()})
                tail = cur[-overlap_chars:]
                cut = tail.find(" ")
                tail = tail[cut + 1:] if 0 <= cut < 80 else tail
                cur = tail + " " + p
            else:
                cur = (cur + "\n" + p) if cur else p
        if cur.strip() and cur != tail:
            chunks.append({"section": section, "text": cur.strip()})
            tail = cur[-overlap_chars:]
    # drop chunks that are pure overlap / boilerplate
    return [c for c in chunks if approx_tokens(c["text"]) >= 25]


def content_hash(text: str, embed_desc: Dict) -> str:
    key = f"{CHUNK_TOKENS}:{OVERLAP_TOKENS}:{embed_desc['provider']}:{embed_desc['model']}:{embed_desc['dim']}\n{text}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def embedding_input(title: str, section: str, text: str) -> str:
    """Contextualise each chunk with its document title and section for better retrieval."""
    head = title if not section or section == title else f"{title} — {section}"
    return f"{head}\n{text}"


def load_sources(path: str) -> List[Dict]:
    data = yaml.safe_load(open(path, encoding="utf-8")) or {}
    return [s for s in data.get("sources", []) if s.get("include", True)]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default=os.path.join(HERE, "sources.yaml"))
    ap.add_argument("--refetch", action="store_true", help="also try entries with status: unfetched")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--reset", action="store_true", help="drop and rebuild the corpus tables")
    args = ap.parse_args(argv)

    from moneytrace.db.database import get_engine, create_schema
    create_schema()
    engine = get_engine()
    embedder = get_embedder()
    desc = embedder.describe()

    with engine.begin() as conn:
        meta = store.get_meta(conn)
    if args.reset or meta.get("embedding_model") not in (None, desc["model"]) or \
            (meta.get("embedding_dim") and int(meta["embedding_dim"]) != desc["dim"]) or not meta:
        print(f"(re)creating corpus tables for {desc}")
        store.reset_rag_schema(engine, desc["dim"], desc)

    sources = load_sources(args.sources)
    if not args.refetch:
        sources = [s for s in sources if s.get("status") == "fetched"]
    if args.limit:
        sources = sources[: args.limit]

    started = time.time()
    log = {"started_at": datetime.now(timezone.utc).isoformat(), "embedding": desc, "chunk_tokens": CHUNK_TOKENS,
           "overlap_tokens": OVERLAP_TOKENS, "documents": [], "failures": [], "skipped_unchanged": 0}
    fetcher = PoliteFetcher()
    try:
        for i, src in enumerate(sources, 1):
            url = src["url"]
            res = fetcher.fetch(url)
            if not res.ok:
                log["failures"].append({"doc_id": src["doc_id"], "url": url, "stage": "fetch", "error": res.error})
                print(f"[{i}/{len(sources)}] FETCH FAIL {res.error[:70]} {url}")
                continue
            try:
                doc = extract(res)
            except Exception as e:
                log["failures"].append({"doc_id": src["doc_id"], "url": url, "stage": "extract", "error": repr(e)[:200]})
                continue
            title = src.get("title") or doc.title or url
            h = content_hash(doc.text, desc)
            with engine.begin() as conn:
                if store.get_document_hash(conn, src["doc_id"]) == h:
                    log["skipped_unchanged"] += 1
                    continue
            chunks = chunk_document(doc.text)[:MAX_DOC_CHUNKS]
            if not chunks:
                log["failures"].append({"doc_id": src["doc_id"], "url": url, "stage": "chunk", "error": "no text"})
                continue
            try:
                vecs = embedder.embed_documents([embedding_input(title, c["section"], c["text"]) for c in chunks])
            except Exception as e:
                log["failures"].append({"doc_id": src["doc_id"], "url": url, "stage": "embed", "error": repr(e)[:300]})
                print(f"[{i}/{len(sources)}] EMBED FAIL {repr(e)[:100]}")
                continue
            rows = []
            for j, (c, v) in enumerate(zip(chunks, vecs)):
                rows.append({"id": f"{src['doc_id']}#{j:04d}", "doc_id": src["doc_id"], "title": title,
                             "issuer": src.get("issuer"), "url": url, "published_date": src.get("published_date") or doc.published_date,
                             "section": c["section"], "chunk_index": j, "text": c["text"],
                             "content_hash": hashlib.sha1(c["text"].encode()).hexdigest(), "embedding": v})
            try:
                with engine.begin() as conn:
                    store.upsert_document(conn, {"doc_id": src["doc_id"], "title": title, "issuer": src.get("issuer"), "url": url,
                                                 "published_date": src.get("published_date") or doc.published_date,
                                                 "language": src.get("language") or doc.language, "content_hash": h}, rows)
            except Exception as e:
                log["failures"].append({"doc_id": src["doc_id"], "url": url, "stage": "store", "error": repr(e)[:200]})
                print(f"[{i}/{len(sources)}] STORE FAIL {repr(e)[:100]}")
                continue
            log["documents"].append({"doc_id": src["doc_id"], "title": title, "chunks": len(rows), "chars": len(doc.text)})
            print(f"[{i}/{len(sources)}] {len(rows):4d} chunks  {title[:70]}")
    finally:
        fetcher.close()

    with engine.begin() as conn:
        stats = store.corpus_stats(conn)
        store.set_meta(conn, {"last_ingest_at": datetime.now(timezone.utc).isoformat()})
    log["finished_at"] = datetime.now(timezone.utc).isoformat()
    log["duration_s"] = round(time.time() - started, 1)
    log["embedding_usage"] = embedder.usage.__dict__
    log["corpus"] = stats
    out_dir = os.path.join(BACKEND, "results", "ingest")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"ingest_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)
    write_stats_md(stats, log, out, args.sources)
    print(json.dumps({"documents": stats["documents"], "chunks": stats["chunks"], "failures": len(log["failures"]),
                      "skipped_unchanged": log["skipped_unchanged"], "log": out}))


def write_stats_md(stats: Dict, log: Dict, log_path: str, sources_path: str):
    data = yaml.safe_load(open(sources_path, encoding="utf-8")) or {}
    allsrc = data.get("sources", [])
    lines = [
        "# Advisory corpus statistics",
        "",
        f"Generated by `python -m rag.ingest` at {log['finished_at']} (raw log: `{os.path.relpath(log_path, BACKEND)}`).",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Documents ingested | **{stats['documents']}** |",
        f"| Chunks ingested | **{stats['chunks']}** |",
        f"| Embedding | {log['embedding']['provider']} / `{log['embedding']['model']}` ({log['embedding']['dim']}-d) |",
        f"| Chunking | ~{log['chunk_tokens']} tokens, {log['overlap_tokens']}-token overlap (4 chars/token approximation) |",
        f"| Failures this run | {len(log['failures'])} |",
        f"| Entries in sources.yaml | {len(allsrc)} ({sum(1 for s in allsrc if s.get('include', True))} included, "
        f"{sum(1 for s in allsrc if s.get('status') == 'unfetched')} not fetchable from the ingesting machine) |",
        "",
        "## Documents by issuer",
        "",
        "| Issuer | Documents |",
        "|---|---|",
    ]
    lines += [f"| {k} | {v} |" for k, v in stats["by_issuer"].items()]
    if log["failures"]:
        lines += ["", "## Failures", "", "| doc_id | stage | error |", "|---|---|---|"]
        lines += [f"| {f['doc_id']} | {f['stage']} | {f['error'][:90].replace('|', '/')} |" for f in log["failures"]]
    with open(os.path.join(HERE, "STATS.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()

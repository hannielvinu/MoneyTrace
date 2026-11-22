"""
Apply the MoneyTrace schema to Neon and verify it over Neon's HTTPS SQL endpoint.

    python scripts/neon_http_check.py [--apply] [--dim 768]

Why HTTPS: some sandboxes (e.g. the Claude Code cloud sandbox) only allow outbound HTTPS, so the normal psycopg
TCP connection to Neon cannot be opened there. Neon's `/sql` endpoint (the transport behind
@neondatabase/serverless) runs the same SQL over HTTPS. The app itself still uses psycopg over TCP (pooled
DATABASE_URL) on Cloud Run and laptops; this script only provisions and checks the database.

--apply : create the extension, all tables and indexes (same DDL as the Alembic migrations, IF NOT EXISTS) and stamp
          alembic_version, so a later `alembic upgrade head` is a no-op.
Then it runs the retriever's vector + full-text queries against a temporary row and deletes it.
Reads DATABASE_URL_UNPOOLED (direct endpoint) from the environment or <repo>/.env.local.
"""
import argparse
import json
import os
import sys
import time
import urllib.parse

import httpx

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(BACKEND)
sys.path.insert(0, BACKEND)


def _url():
    from dotenv import dotenv_values
    env = {**dotenv_values(os.path.join(ROOT, ".env.local")), **os.environ}
    url = env.get("DATABASE_URL_UNPOOLED") or env.get("DATABASE_URL", "").replace("-pooler.", ".", 1)
    if "neon.tech" not in url:
        sys.exit("DATABASE_URL_UNPOOLED / DATABASE_URL for Neon not found (run `neon env pull`)")
    return url


class NeonHTTP:
    def __init__(self, url):
        self.url, self.host = url, urllib.parse.urlparse(url).hostname
        self.client = httpx.Client(timeout=60)

    def sql(self, query, params=None):
        r = self.client.post(f"https://{self.host}/sql", json={"query": query, "params": params or []},
                             headers={"Neon-Connection-String": self.url})
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
        return r.json().get("rows", [])


def ddl_statements(dim):
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateTable, CreateIndex
    from moneytrace.db.models import metadata
    from rag.store import create_rag_schema

    d = postgresql.dialect()
    out = ["CREATE EXTENSION IF NOT EXISTS vector"]
    for t in metadata.sorted_tables:
        out.append(str(CreateTable(t, if_not_exists=True).compile(dialect=d)).strip())
        for ix in t.indexes:
            out.append(str(CreateIndex(ix, if_not_exists=True).compile(dialect=d)).strip())

    class Recorder:  # captures the RAG DDL that create_rag_schema() issues on Postgres
        dialect = d
        stmts = []

        def execute(self, stmt, *a, **k):
            self.stmts.append(str(stmt).strip())

    rec = Recorder()
    create_rag_schema(rec, dim=dim)
    out += [s for s in rec.stmts if s != "CREATE EXTENSION IF NOT EXISTS vector"]
    out.append("CREATE TABLE IF NOT EXISTS rag_meta (key TEXT PRIMARY KEY, value TEXT)")
    out.append("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--dim", type=int, default=int(os.environ.get("EMBEDDING_DIM", "768")))
    a = ap.parse_args()
    db = NeonHTTP(_url())
    report = {"endpoint": db.host}
    t0 = time.time()
    report["server"] = db.sql("select version() as v, current_database() as db")[0]
    if a.apply:
        stmts = ddl_statements(a.dim)
        for s in stmts:
            db.sql(s)
        if not db.sql("select version_num from alembic_version"):
            db.sql("insert into alembic_version (version_num) values ($1)", ["0002_advisory_chunks"])
        report["ddl_statements_applied"] = len(stmts)
    report["pgvector"] = db.sql("select extversion from pg_extension where extname = 'vector'")
    report["tables"] = [r["tablename"] for r in db.sql(
        "select tablename from pg_tables where schemaname = 'public' order by tablename")]
    report["indexes_on_advisory_chunks"] = [r["indexname"] for r in db.sql(
        "select indexname from pg_indexes where tablename = 'advisory_chunks' order by indexname")]
    report["alembic_version"] = db.sql("select version_num from alembic_version")

    # Retrieval smoke test with a temporary document (deleted afterwards)
    dim = int(db.sql("select atttypmod as d from pg_attribute where attrelid = 'advisory_chunks'::regclass "
                     "and attname = 'embedding'")[0]["d"])
    vec = "[" + ",".join("1" if i == 0 else "0" for i in range(dim)) + "]"
    db.sql("insert into advisory_documents (doc_id, title, issuer, url, content_hash, n_chunks) "
           "values ('neon-check', 'Neon check', 'test', 'https://example.invalid', 'x', 1) on conflict do nothing")
    db.sql("insert into advisory_chunks (id, doc_id, title, issuer, url, section, chunk_index, text, content_hash, embedding) "
           "values ('neon-check#0', 'neon-check', 'Neon check', 'test', 'https://example.invalid', '', 0, "
           "'Call the cyber crime helpline 1930 to report UPI fraud', 'x', $1::vector) on conflict do nothing", [vec])
    report["vector_search"] = db.sql(
        "select id, 1 - (embedding <=> $1::vector) as score from advisory_chunks order by embedding <=> $1::vector limit 1", [vec])
    report["fulltext_search"] = db.sql(
        "select id, ts_rank_cd(tsv, q) as score from advisory_chunks, websearch_to_tsquery('english', $1) q "
        "where tsv @@ q order by score desc limit 1", ["helpline 1930 UPI fraud"])
    db.sql("delete from advisory_documents where doc_id = 'neon-check'")
    report["cleanup_rows_left"] = db.sql("select count(*) as n from advisory_chunks where doc_id = 'neon-check'")[0]["n"]
    report["seconds"] = round(time.time() - t0, 2)
    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()

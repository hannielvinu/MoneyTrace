"""RAG corpus tables: advisory_documents + advisory_chunks.

Postgres: embedding vector(N) with an HNSW cosine index and a GIN index on a
generated tsvector. SQLite (tests only): embedding stored as JSON text.

Revision ID: 0002_advisory_chunks
"""
import os
from alembic import op

revision = "0002_advisory_chunks"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade():
    from rag.store import create_rag_schema
    create_rag_schema(op.get_bind(), dim=int(os.environ.get("EMBEDDING_DIM", "768")))


def downgrade():
    op.execute("DROP TABLE IF EXISTS advisory_chunks")
    op.execute("DROP TABLE IF EXISTS advisory_documents")

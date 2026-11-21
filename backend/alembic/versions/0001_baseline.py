"""Baseline: core MoneyTrace tables (users, incidents, ledger, audit, events, notifications,
counters, llm_calls, usage_events) and the pgvector extension on Postgres.

Uses checkfirst so it can be applied on top of a database created by the pre-v2 app.

Revision ID: 0001_baseline
"""
from alembic import op
import sqlalchemy as sa

from moneytrace.db.models import metadata

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    metadata.create_all(bind, checkfirst=True)


def downgrade():
    metadata.drop_all(op.get_bind())

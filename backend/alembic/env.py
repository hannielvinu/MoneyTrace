"""Alembic environment: uses the same DATABASE_URL resolution as the app."""
import os
import sys

from alembic import context

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv  # noqa: E402
load_dotenv()

from sqlalchemy import create_engine  # noqa: E402

from moneytrace.db.database import get_engine, migration_database_url  # noqa: E402
from moneytrace.db.models import metadata  # noqa: E402


def migration_engine():
    """Migrations run over the direct (unpooled) connection; see migration_database_url()."""
    url = migration_database_url()
    return get_engine() if url.startswith("sqlite") else create_engine(url, pool_pre_ping=True)

target_metadata = metadata


def run_migrations_offline():
    context.configure(url=migration_database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    with migration_engine().connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

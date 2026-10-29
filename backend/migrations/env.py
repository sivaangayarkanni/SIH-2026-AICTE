"""Alembic env: URL comes from DATABASE_URL (same resolution as the app)."""
from alembic import context
from app.config import DB_URL
from app.db import Base, engine

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to):
    # raw-DDL objects (pgvector HNSW indexes) are managed in app.db.PG_DDL, not by autogenerate
    return not (type_ == "index" and name and "hnsw" in name)


def run_migrations_offline():
    context.configure(url=DB_URL, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True, include_object=include_object)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

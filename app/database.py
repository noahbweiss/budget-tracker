"""SQLAlchemy engine/session setup.

TODO: add Alembic migrations once the schema stabilizes. For the skeleton
stage, tables are created directly from models at startup (see main.py).
"""
from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import settings

# check_same_thread=False is needed for SQLite + FastAPI's threaded requests.
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if "sqlite" in settings.database_url else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency that yields a DB session per-request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# Columns added to models after this app already had real user data in the
# wild — Base.metadata.create_all() only creates *missing* tables, it never
# alters existing ones, so a fresh install gets these for free (create_all
# makes the table with the column already there) but an existing
# data/finance.db needs an explicit ALTER TABLE. This is a stopgap until
# Alembic is set up (see the module docstring's TODO); it's deliberately
# tiny — just "does this column exist, add it if not" — not a general
# migration system.
_ADDED_COLUMNS = [
    ("accounts", "starting_balance", "NUMERIC(12, 2)"),
    ("transactions", "balance", "NUMERIC(12, 2)"),
    ("accounts", "simplefin_account_id", "VARCHAR(255)"),
    ("accounts", "simplefin_connection_id", "INTEGER"),
    ("accounts", "reported_balance", "NUMERIC(12, 2)"),
    ("accounts", "reported_balance_as_of", "DATE"),
]


def ensure_schema_migrations(engine: Engine) -> None:
    """Idempotent: add any column in _ADDED_COLUMNS that's missing from an
    existing table. Call after Base.metadata.create_all(), which must run
    first so a brand-new database has the tables to inspect at all.
    """
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, column, column_type in _ADDED_COLUMNS:
            if table not in table_names:
                continue  # a fresh table from create_all() already has every current column
            existing = {c["name"] for c in inspector.get_columns(table)}
            if column not in existing:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}"))

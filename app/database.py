"""SQLAlchemy engine/session setup.

Schema changes go through Alembic (migrations/ at the repo root) — see
run_migrations() below. This replaced an earlier stopgap
(create_all() + a hand-maintained _ADDED_COLUMNS list of raw ALTER TABLEs)
that worked but was never a real migration system; it's gone now, not kept
alongside the new one.
"""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
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


# Repo root — app/database.py -> app/ -> repo root — same anchoring pattern
# main.py uses for APP_DIR, so this doesn't depend on the process's cwd.
_REPO_ROOT = Path(__file__).resolve().parent.parent
_ALEMBIC_INI = _REPO_ROOT / "alembic.ini"

# The very first Alembic revision (migrations/versions/0001_baseline_schema.py)
# captures the exact schema this app already had before Alembic existed —
# see that file's own docstring. This constant, not the string "head", is
# what a pre-Alembic existing database gets stamped at (see run_migrations
# below): stamping at "head" would be wrong the moment a second revision
# ships, since it would skip that revision entirely on an existing database
# that never actually had it applied.
_BASELINE_REVISION = "0001"


def run_migrations(database_url: str | None = None) -> None:
    """Bring the database schema up to date via Alembic.

    `database_url` defaults to settings.database_url (the app's real
    database) — overriding it is for tests, so this function can be
    exercised against a throwaway SQLite file instead of the real one.

    Two cases, distinguished by what's already in the database:

    - Genuinely empty database (no tables at all — a fresh clone or a
      test's throwaway file): run every migration from the start,
      `alembic upgrade head`. This creates the schema from scratch, same
      end result Base.metadata.create_all() used to produce.
    - Existing pre-Alembic database (this app's tables already exist, but
      there's no alembic_version table yet — i.e. every real installation
      that existed before this function did): the schema is already at
      exactly the baseline revision, from create_all() + the old
      _ADDED_COLUMNS stopgap having already run historically. Replaying
      the baseline's CREATE TABLEs would fail (the tables are already
      there), so this stamps the database at _BASELINE_REVISION — marks it
      as "already at this revision" with no DDL executed — and then runs
      `upgrade head` normally, which applies anything added after the
      baseline.

    A database already managed by Alembic (has an alembic_version table)
    just gets a normal `upgrade head` either way.
    """
    url = database_url or settings.database_url
    bind_engine = engine if database_url is None else create_engine(url)

    cfg = Config(str(_ALEMBIC_INI))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", url)

    try:
        inspector = inspect(bind_engine)
        table_names = set(inspector.get_table_names())
        has_alembic_version = "alembic_version" in table_names
        has_app_tables = "accounts" in table_names  # any real app table = pre-Alembic existing DB

        if not has_alembic_version and has_app_tables:
            command.stamp(cfg, _BASELINE_REVISION)

        command.upgrade(cfg, "head")
    finally:
        if database_url is not None:
            bind_engine.dispose()

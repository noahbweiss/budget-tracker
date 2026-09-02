"""Tests for app.database.run_migrations(), the Alembic-backed replacement
for the old create_all() + _ADDED_COLUMNS stopgap.

Uses real on-disk SQLite files (via pytest's tmp_path) rather than
`:memory:` — Alembic opens its own connection to the given URL, and an
in-memory SQLite database is scoped to a single connection, so a second
connection would just see an empty database regardless of what the first
one did. That mismatch is exactly the class of bug this suite needs to be
able to catch, so it needs a database multiple connections can actually
share.

Asserts against the *current* Alembic head, computed from migrations/
itself (see _head_revision()) rather than a hardcoded revision string —
the specific head keeps moving as new migrations land (it was "0001"
when this suite was first written; Phase A already moved it), so pinning
a literal string here would make this suite something every future phase
has to remember to edit.
"""
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from app.database import run_migrations

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _url(tmp_path, name="test.db"):
    return f"sqlite:///{tmp_path / name}"


def _head_revision() -> str:
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_REPO_ROOT / "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head()


def _build_legacy_pre_alembic_database(url: str) -> None:
    """Hand-builds the exact schema a real installation had the moment
    before Alembic was introduced — i.e. what the old create_all() +
    _ADDED_COLUMNS stopgap actually produced: the 4 tables with every
    column that existed by then, but notably *without* the foreign key
    on accounts.simplefin_connection_id (a plain ALTER TABLE ADD COLUMN
    can't add a constraint — see migrations/versions/fk_fix_accounts_
    simplefin.py) and *without* any column a later Alembic migration
    introduced (e.g. Transaction.is_transfer/transfer_pair_id).

    Deliberately hand-written DDL, not Base.metadata.create_all() — the
    live ORM models describe *today's* full schema, which only matched
    "the legacy pre-Alembic shape" back when Phase 0 shipped. Using it
    here would silently drift out of sync with what a real legacy
    database looks like every time a later phase adds a column, the same
    way tests/test_database.py's old _pre_migration_engine() hand-built
    DDL rather than trusting the live models for the same reason.
    """
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "CREATE TABLE categories (id INTEGER PRIMARY KEY, name VARCHAR(80) NOT NULL UNIQUE, "
                    "kind VARCHAR(10) NOT NULL)"
                )
            )
            conn.execute(
                text(
                    "CREATE TABLE simplefin_connections (id INTEGER PRIMARY KEY, "
                    "access_url VARCHAR(500) NOT NULL, created_at DATETIME NOT NULL, last_synced_at DATETIME)"
                )
            )
            conn.execute(
                text(
                    "CREATE TABLE accounts (id INTEGER PRIMARY KEY, name VARCHAR(120) NOT NULL, "
                    "institution VARCHAR(120), account_type VARCHAR(50) NOT NULL, source VARCHAR(20) NOT NULL, "
                    "created_at DATETIME NOT NULL, starting_balance NUMERIC(12, 2), "
                    "simplefin_account_id VARCHAR(255), simplefin_connection_id INTEGER, "
                    "reported_balance NUMERIC(12, 2), reported_balance_as_of DATE)"
                )
            )
            conn.execute(
                text(
                    "CREATE TABLE transactions (id INTEGER PRIMARY KEY, account_id INTEGER NOT NULL, "
                    "category_id INTEGER, date DATE NOT NULL, amount NUMERIC(12, 2) NOT NULL, "
                    "description VARCHAR(255) NOT NULL, external_id VARCHAR(255), balance NUMERIC(12, 2), "
                    "FOREIGN KEY(account_id) REFERENCES accounts (id), "
                    "FOREIGN KEY(category_id) REFERENCES categories (id))"
                )
            )
            conn.execute(
                text(
                    "INSERT INTO accounts (id, name, account_type, source, created_at) "
                    "VALUES (1, 'Checking', 'checking', 'manual', '2026-01-01 00:00:00')"
                )
            )
    finally:
        engine.dispose()


def test_upgrade_from_empty_creates_full_schema(tmp_path):
    """A brand-new database (a fresh clone, or a test's throwaway file) has
    no tables at all — run_migrations() should run every migration from
    the start and end up with the full current schema, the same result
    Base.metadata.create_all() used to produce.
    """
    url = _url(tmp_path)

    run_migrations(database_url=url)

    engine = create_engine(url)
    try:
        table_names = set(inspect(engine).get_table_names())
        assert {"accounts", "categories", "transactions", "simplefin_connections"} <= table_names
        assert "alembic_version" in table_names
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert version == _head_revision()
    finally:
        engine.dispose()


def test_stamps_and_preserves_data_on_a_pre_alembic_database(tmp_path):
    """Simulates the real scenario this exists for: an existing
    data/finance.db from before Alembic was introduced — the app's tables
    already exist, but there's no alembic_version table yet.
    run_migrations() must recognize this, stamp it at the baseline
    revision instead of trying to replay the baseline's CREATE TABLEs
    (which would fail — the tables are already there), and then apply
    every migration since — all without touching existing data.
    """
    url = _url(tmp_path, "legacy.db")
    _build_legacy_pre_alembic_database(url)

    run_migrations(database_url=url)

    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            assert version == _head_revision()
            row = conn.execute(text("SELECT name, account_type FROM accounts WHERE id = 1")).fetchone()
            assert row.name == "Checking"
            assert row.account_type == "checking"
            # Migrations since the baseline actually applied, not just stamped past:
            fk_names = {fk["name"] for fk in inspect(engine).get_foreign_keys("accounts")}
            assert "fk_accounts_simplefin_connection_id_simplefin_connections" in fk_names
            txn_columns = {c["name"] for c in inspect(engine).get_columns("transactions")}
            assert {"is_transfer", "transfer_pair_id"} <= txn_columns
    finally:
        engine.dispose()


def test_run_migrations_is_idempotent(tmp_path):
    """Startup calls this on every launch — a second run against an
    already-migrated database must be a no-op, not an error.
    """
    url = _url(tmp_path)

    run_migrations(database_url=url)
    run_migrations(database_url=url)  # must not raise

    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert version == _head_revision()
    finally:
        engine.dispose()

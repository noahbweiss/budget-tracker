"""Tests for app.database's schema-migration stopgap.

Simulates the real scenario this exists for: someone already has a
populated data/finance.db from before `starting_balance`/`balance` were
added to the models. Base.metadata.create_all() would silently do
nothing for their existing tables (it only creates missing ones), so
ensure_schema_migrations() has to actually ALTER TABLE.
"""
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import StaticPool

from app.database import ensure_schema_migrations


def _pre_migration_engine():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT, institution TEXT, "
                "account_type TEXT, source TEXT, created_at TEXT)"
            )
        )
        conn.execute(
            text(
                "CREATE TABLE transactions (id INTEGER PRIMARY KEY, account_id INTEGER, category_id INTEGER, "
                "date TEXT, amount NUMERIC, description TEXT, external_id TEXT)"
            )
        )
    return engine


def test_adds_missing_columns_to_existing_tables():
    engine = _pre_migration_engine()

    ensure_schema_migrations(engine)

    inspector = inspect(engine)
    assert "starting_balance" in {c["name"] for c in inspector.get_columns("accounts")}
    assert "balance" in {c["name"] for c in inspector.get_columns("transactions")}


def test_is_idempotent_and_does_not_clobber_existing_data():
    engine = _pre_migration_engine()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO accounts (id, name, account_type, source) VALUES (1, 'Checking', 'checking', 'manual')")
        )

    ensure_schema_migrations(engine)
    ensure_schema_migrations(engine)  # must not error or duplicate the column on a second run

    with engine.begin() as conn:
        row = conn.execute(text("SELECT name, starting_balance FROM accounts WHERE id = 1")).fetchone()
    assert row.name == "Checking"
    assert row.starting_balance is None


def test_noop_on_a_table_that_does_not_exist_yet():
    # A brand-new database has no tables at all before create_all() runs —
    # ensure_schema_migrations() must not error in that case either.
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    ensure_schema_migrations(engine)  # should simply do nothing

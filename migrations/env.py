"""Alembic environment configuration.

Wires Alembic to this app's own SQLAlchemy setup rather than a separate,
hardcoded database URL in alembic.ini: the URL always comes from
app.config.settings.database_url (which reads .env / the DATABASE_URL env
var, same as app/database.py's own engine), so `alembic` CLI commands and
the running app never disagree about which database file they mean.

target_metadata is app.database.Base.metadata. Importing app.models isn't
optional here even though nothing in this file references it directly —
that import is what registers every model class on Base, which is what
`alembic revision --autogenerate` diffs against; without it, Base.metadata
would be empty and autogenerate would try to drop every table.

The URL fallback below only fires when nothing has already set
sqlalchemy.url on the Config object — app.database.run_migrations() sets
it explicitly before invoking Alembic (so it can point at a throwaway
database in tests without touching the real one); a bare `alembic ...`
run from the CLI has nothing set yet, so it falls back to the app's real
configured database here.
"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

import app.models  # noqa: F401 — import side effect: registers models on Base
from app.config import settings
from app.database import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# alembic.ini deliberately leaves sqlalchemy.url unset (see its comment).
# Only fall back to the app's configured database URL if nothing set one
# already — see the module docstring for why this must not be unconditional.
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # render_as_batch=True: SQLite's ALTER TABLE can't add a constraint
        # (e.g. Transaction.transfer_pair_id's foreign key) or drop a
        # column at all — Alembic's "batch mode" works around this by
        # recreating the table under the hood (copy data, drop, rename)
        # instead of emitting DDL SQLite doesn't support. Harmless no-op
        # for other databases, so this stays on unconditionally rather
        # than branching on dialect.
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

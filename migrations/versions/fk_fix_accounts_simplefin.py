"""fix missing fk on accounts.simplefin_connection_id

Every *pre-Alembic* installation's database is missing this foreign key
at the SQLite level, even though app/models.py has always declared it:
the old `_ADDED_COLUMNS` stopgap (app/database.py's old
ensure_schema_migrations()) added this column via a plain
`ALTER TABLE ... ADD COLUMN` — SQLite's ALTER TABLE can never add a
foreign key constraint, only a column, so the constraint was silently
never applied. Found by running `alembic check` against a copy of the
real data/finance.db during Phase A verification, not by inspecting
models.py alone.

`migrations/versions/0001_baseline_schema.py` already gets this right
for anything Alembic creates fresh — a real `CREATE TABLE` includes the
constraint from the start — so this migration checks first and is a
no-op on any database that already has it (every fresh install; skipping
this check produced a harmless-but-sloppy duplicate FK constraint when
first written, caught by inspecting a fresh test database's resulting
schema before this landed).

No data changes: SQLite doesn't enforce foreign keys unless
`PRAGMA foreign_keys = ON` is set (this app doesn't set it), so any
existing simplefin_connection_id values are already valid — this just
makes the schema match what app/models.py has always said.

Revision ID: fk_fix_accounts_simplefin
Revises: 0001
Create Date: 2026-08-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fk_fix_accounts_simplefin"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONSTRAINT_NAME = "fk_accounts_simplefin_connection_id_simplefin_connections"


def _already_has_fk(bind) -> bool:
    inspector = sa.inspect(bind)
    return any(
        fk["constrained_columns"] == ["simplefin_connection_id"] and fk["referred_table"] == "simplefin_connections"
        for fk in inspector.get_foreign_keys("accounts")
    )


def upgrade() -> None:
    bind = op.get_bind()
    if _already_has_fk(bind):
        return
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.create_foreign_key(
            _CONSTRAINT_NAME, "simplefin_connections", ["simplefin_connection_id"], ["id"]
        )


def downgrade() -> None:
    bind = op.get_bind()
    if not _already_has_fk(bind):
        return
    with op.batch_alter_table("accounts", schema=None) as batch_op:
        batch_op.drop_constraint(_CONSTRAINT_NAME, type_="foreignkey")

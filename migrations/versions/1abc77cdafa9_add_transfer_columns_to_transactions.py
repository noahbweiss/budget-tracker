"""add transfer columns to transactions

Adds Transaction.is_transfer / transfer_pair_id — see app/models.py and
app/services/transfers.py. is_transfer gets a server_default so this
migration doesn't fail against a real, populated transactions table (the
common case — this is the first schema change since the Alembic baseline,
so every existing installation's database has real rows here); the
server_default is then dropped once the backfill is done, since
app/models.py's own default=False only needs to apply at the Python/ORM
level for new rows going forward, not as a permanent DB-level default.

Uses batch mode throughout: SQLite's ALTER TABLE can't add a foreign key
constraint (or drop a column, on the way back down) directly — Alembic's
batch mode works around this by recreating the table under the hood.

Revision ID: 1abc77cdafa9
Revises: fk_fix_accounts_simplefin
Create Date: 2026-08-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1abc77cdafa9"
down_revision: Union[str, Sequence[str], None] = "fk_fix_accounts_simplefin"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("is_transfer", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch_op.add_column(sa.Column("transfer_pair_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_transactions_transfer_pair_id_transactions", "transactions", ["transfer_pair_id"], ["id"]
        )

    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.alter_column("is_transfer", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.drop_constraint("fk_transactions_transfer_pair_id_transactions", type_="foreignkey")
        batch_op.drop_column("transfer_pair_id")
        batch_op.drop_column("is_transfer")

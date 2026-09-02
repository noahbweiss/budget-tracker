"""add tags and reimbursed column

New Tag/TransactionTag tables (see app/models.py and app/services/tags.py
— a small, fixed, code-owned set of transaction labels, not a
user-creatable one) and Transaction.reimbursed. reimbursed gets a
server_default for the same reason is_transfer did in the previous
migration — this app already has real populated databases, so a NOT
NULL column needs something to fill existing rows with — then the
server_default is dropped once the backfill is done, leaving only
app/models.py's own default=False at the Python/ORM level.

Revision ID: cc8c5168154e
Revises: 1abc77cdafa9
Create Date: 2026-08-29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "cc8c5168154e"
down_revision: Union[str, Sequence[str], None] = "1abc77cdafa9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_table(
        "transaction_tags",
        sa.Column("transaction_id", sa.Integer(), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"]),
        sa.ForeignKeyConstraint(["transaction_id"], ["transactions.id"]),
        sa.PrimaryKeyConstraint("transaction_id", "tag_id"),
    )
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("reimbursed", sa.Boolean(), nullable=False, server_default=sa.false()))

    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.alter_column("reimbursed", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("transactions", schema=None) as batch_op:
        batch_op.drop_column("reimbursed")

    op.drop_table("transaction_tags")
    op.drop_table("tags")

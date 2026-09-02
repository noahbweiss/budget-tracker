"""Core data models.

TODO: revisit fields once import/sync flows are implemented (e.g. dedup
keys for transactions coming from SimpleFin vs CSV import).
"""
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    institution: Mapped[str | None] = mapped_column(String(120), nullable=True)
    account_type: Mapped[str] = mapped_column(String(50))  # checking, savings, credit, etc.
    # "manual" (CSV import) or "simplefin"
    source: Mapped[str] = mapped_column(String(20), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Optional user-entered baseline, used as a fallback when no imported
    # transaction carries its own bank-reported `balance` — see
    # app/services/balances.py for how these combine.
    starting_balance: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    # Populated only for source == "simplefin" accounts. SimpleFin reports
    # one current balance per account on every sync (not a per-transaction
    # running balance like some CSV exports) — see
    # app/services/simplefin_sync.py. simplefin_account_id is the id
    # SimpleFin uses for this account within its bridge connection, used to
    # match an existing local Account on resync instead of recreating it.
    simplefin_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    simplefin_connection_id: Mapped[int | None] = mapped_column(
        ForeignKey("simplefin_connections.id"), nullable=True
    )
    reported_balance: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    reported_balance_as_of: Mapped[date | None] = mapped_column(Date, nullable=True)

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account")
    simplefin_connection: Mapped["SimplefinConnection | None"] = relationship(back_populates="accounts")


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    # "income" or "expense" — helps aggregation logic separate the two.
    kind: Mapped[str] = mapped_column(String(10), default="expense")

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="category")


class Tag(Base):
    """A small, fixed, code-owned set of labels a transaction can carry —
    unlike Category, the user can't create new ones. See
    app/services/tags.py's SYSTEM_TAGS for the current slug list and
    docs/2026-08-29-feature-plan.md's Phase B notes for why this is a
    many-to-many table rather than a couple of booleans on Transaction:
    a deliberate choice (asked of, and made by, the user directly), not
    an oversight.
    """

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(50), unique=True)
    name: Mapped[str] = mapped_column(String(50))

    transactions: Mapped[list["Transaction"]] = relationship(secondary="transaction_tags", back_populates="tags")


class TransactionTag(Base):
    """Join table for Transaction<->Tag. No extra columns of its own —
    per-tag state that only makes sense for one specific tag (e.g.
    "reimbursed," which only means anything for the "reimbursable" tag)
    lives on Transaction directly instead, so it doesn't need to be
    bolted onto this generic row.
    """

    __tablename__ = "transaction_tags"

    transaction_id: Mapped[int] = mapped_column(ForeignKey("transactions.id"), primary_key=True)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id"), primary_key=True)


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    category_id: Mapped[int | None] = mapped_column(ForeignKey("categories.id"), nullable=True)

    date: Mapped[date] = mapped_column(Date)
    # Positive = income, negative = spending. Keeping one signed field
    # instead of separate amount/type columns simplifies aggregation math.
    amount: Mapped[float] = mapped_column(Numeric(12, 2))
    description: Mapped[str] = mapped_column(String(255))

    # Helps avoid duplicate imports across CSV re-imports / SimpleFin syncs.
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # The account's running balance as of this transaction, when the
    # source (a bank's CSV export, sometimes OFX/SimpleFin) actually
    # reports one. Nullable — most imports won't have this. When present,
    # it's authoritative for "what's my balance" (see
    # app/services/balances.py) since it's the bank's own number, not a
    # sum we computed that has no idea what existed before tracking began.
    balance: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)

    # A transfer between the user's own accounts (e.g. paying off a
    # credit card from checking) is never real income or spending — see
    # app/services/transfers.py and aggregation.get_period_dashboard()'s
    # exclusion filter. transfer_pair_id optionally links this row to the
    # transaction on the other side (opposite sign, the other account);
    # linking is never required — a transaction can be marked as a
    # transfer on its own with no pair at all (e.g. the other account
    # isn't tracked in this app), and that's a fully valid end state.
    is_transfer: Mapped[bool] = mapped_column(default=False)
    transfer_pair_id: Mapped[int | None] = mapped_column(ForeignKey("transactions.id"), nullable=True)

    # Whether an "owed to me" transaction has been paid back. Only
    # meaningful alongside the "reimbursable" tag (see app/services/
    # tags.py) but kept as its own column rather than folded into
    # TransactionTag, since it's a status specific to one tag, not a
    # generic property every tag needs. Simple manual toggle for now —
    # no link to the actual incoming payment, no partial amounts (see
    # CLAUDE.md's reimbursement convention for what's deferred).
    reimbursed: Mapped[bool] = mapped_column(default=False)

    account: Mapped["Account"] = relationship(back_populates="transactions")
    category: Mapped["Category | None"] = relationship(back_populates="transactions")
    transfer_pair: Mapped["Transaction | None"] = relationship(
        "Transaction", remote_side="Transaction.id", foreign_keys=[transfer_pair_id]
    )
    tags: Mapped[list["Tag"]] = relationship(secondary="transaction_tags", back_populates="transactions")


class SimplefinConnection(Base):
    """One SimpleFin Bridge connection — in practice almost always just one
    row, but modeled as a table (not a single Settings value) since one
    access_url can cover multiple bank accounts and a user could in theory
    connect more than one bridge. See app/services/simplefin_client.py for
    the protocol this stores credentials for.
    """

    __tablename__ = "simplefin_connections"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Embeds HTTP Basic Auth credentials (https://user:pass@bridge/...) —
    # this is the actual bearer credential for pulling bank data, treat it
    # like a secret: never rendered back into any template.
    access_url: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    accounts: Mapped[list["Account"]] = relationship(back_populates="simplefin_connection")

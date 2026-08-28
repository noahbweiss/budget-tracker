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

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account")


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True)
    # "income" or "expense" — helps aggregation logic separate the two.
    kind: Mapped[str] = mapped_column(String(10), default="expense")

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="category")


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

    account: Mapped["Account"] = relationship(back_populates="transactions")
    category: Mapped["Category | None"] = relationship(back_populates="transactions")

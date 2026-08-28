"""Account balance resolution.

There's no reliable way to know an account's *real* balance from tracked
transactions alone unless something actually tells us — the model has no
"opening balance" baked in, and a plain sum of tracked transactions will
never match a real bank balance if any activity happened before the
first imported transaction, which is the common case (nobody imports an
account's entire lifetime on day one). Three-tier fallback, most
trustworthy first:

1. The most recent transaction that carries its own `balance` (from a
   CSV column the bank actually reports — see csv_importer.py's
   ColumnMapping.balance — or, eventually, SimpleFin) — this is the
   bank's own number, not something we computed, so it's exact.
2. Account.starting_balance (a one-time user-entered baseline, set on
   the account edit form) plus the sum of every tracked transaction —
   an estimate, but usually close.
3. Just the sum of tracked transactions, honestly labeled as *not* a
   real balance — it has no idea what existed before tracking started.
"""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Account, Transaction


@dataclass(frozen=True)
class AccountBalance:
    amount: Decimal
    source: str  # "reported" | "estimated" | "net_only"
    as_of: date | None = None  # only set when source == "reported"


def resolve_balance(db: Session, account: Account) -> AccountBalance:
    latest_reported = (
        db.query(Transaction)
        .filter(Transaction.account_id == account.id, Transaction.balance.isnot(None))
        .order_by(Transaction.date.desc(), Transaction.id.desc())
        .first()
    )
    if latest_reported is not None:
        return AccountBalance(amount=Decimal(latest_reported.balance), source="reported", as_of=latest_reported.date)

    net = _sum_transactions(db, account.id)
    if account.starting_balance is not None:
        return AccountBalance(amount=Decimal(account.starting_balance) + net, source="estimated")

    return AccountBalance(amount=net, source="net_only")


def _sum_transactions(db: Session, account_id: int) -> Decimal:
    total = Decimal("0")
    for (amount,) in db.query(Transaction.amount).filter(Transaction.account_id == account_id).all():
        total += Decimal(amount)
    return total

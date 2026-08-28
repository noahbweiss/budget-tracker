"""Turns a raw SimpleFin /accounts response into local Account/Transaction
rows. Kept separate from simplefin_client.py (the network layer) and
routers/simplefin.py (the HTTP layer) so this — the actual "what do we do
with the data" logic — is testable without mocking HTTP at all: tests
just hand it a response dict shaped like the real API's.

Accounts are matched across syncs by (simplefin_connection_id,
simplefin_account_id) — SimpleFin's own account id — so re-syncing
updates the same local Account instead of creating a new one every time.
Once created, a resync never overwrites name/institution/account_type:
those are left alone in case the user edited them locally. Balance is
always refreshed, since SimpleFin's balance is meant to reflect "right
now" on every sync.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Account, SimplefinConnection, Transaction

# Well under SimpleFin's ~45-day recommended window (see
# simplefin_client.py's docstring) — this is for keeping an
# already-imported account current, not historical backfill; CSV/OFX
# import (no such window) is the tool for a first-time full history.
DEFAULT_SYNC_LOOKBACK_DAYS = 30

# Heuristic only — SimpleFin doesn't report an account type, unlike this
# app's own account_type field. Checked in order; first match wins.
_TYPE_HINTS = [
    ("saving", "savings"),
    ("credit", "credit"),
    ("invest", "investment"),
    ("loan", "loan"),
]


@dataclass
class SyncResult:
    accounts_created: int = 0
    accounts_updated: int = 0
    transactions_imported: int = 0
    transactions_skipped: int = 0
    errors: list[str] = field(default_factory=list)


def apply_sync_response(db: Session, connection: SimplefinConnection, response: dict) -> SyncResult:
    result = SyncResult(errors=list(response.get("errors") or []))

    for remote_account in response.get("accounts", []):
        account, created = _upsert_account(db, connection, remote_account)
        if created:
            result.accounts_created += 1
        else:
            result.accounts_updated += 1

        imported, skipped = _sync_transactions(db, account, remote_account.get("transactions") or [])
        result.transactions_imported += imported
        result.transactions_skipped += skipped

    connection.last_synced_at = datetime.utcnow()
    db.commit()
    return result


def _upsert_account(db: Session, connection: SimplefinConnection, remote_account: dict) -> tuple[Account, bool]:
    remote_id = remote_account["id"]
    account = (
        db.query(Account)
        .filter(Account.simplefin_connection_id == connection.id, Account.simplefin_account_id == remote_id)
        .first()
    )
    created = account is None
    if account is None:
        org = remote_account.get("org") or {}
        name = remote_account.get("name") or remote_id
        account = Account(
            name=name,
            institution=org.get("name"),
            account_type=_guess_account_type(name),
            source="simplefin",
            simplefin_connection_id=connection.id,
            simplefin_account_id=remote_id,
        )
        db.add(account)
        db.flush()  # so account.id exists for the transactions below

    if remote_account.get("balance") is not None:
        account.reported_balance = Decimal(remote_account["balance"])
        balance_date = remote_account.get("balance-date")
        if balance_date is not None:
            account.reported_balance_as_of = datetime.fromtimestamp(balance_date, tz=timezone.utc).date()

    return account, created


def _guess_account_type(name: str) -> str:
    lowered = name.lower()
    for hint, account_type in _TYPE_HINTS:
        if hint in lowered:
            return account_type
    return "checking"


def _sync_transactions(db: Session, account: Account, remote_transactions: list[dict]) -> tuple[int, int]:
    existing_ids = {
        t.external_id
        for t in db.query(Transaction.external_id)
        .filter(Transaction.account_id == account.id, Transaction.external_id.isnot(None))
        .all()
    }

    imported = 0
    skipped = 0
    for remote_txn in remote_transactions:
        external_id = str(remote_txn["id"])
        if external_id in existing_ids:
            skipped += 1
            continue

        db.add(
            Transaction(
                account_id=account.id,
                date=datetime.fromtimestamp(remote_txn["posted"], tz=timezone.utc).date(),
                amount=Decimal(remote_txn["amount"]),
                description=_transaction_description(remote_txn),
                external_id=external_id,
            )
        )
        existing_ids.add(external_id)
        imported += 1

    return imported, skipped


def _transaction_description(remote_txn: dict) -> str:
    # payee (merchant name) is more recognizable to a human than
    # description in practice, when both are present.
    payee = (remote_txn.get("payee") or "").strip()
    description = (remote_txn.get("description") or "").strip()
    return payee or description or "(no description)"

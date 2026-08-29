"""Turns a raw SimpleFin /accounts response into local Account/Transaction
rows. Kept separate from simplefin_client.py (the network layer) and
routers/simplefin.py (the HTTP layer) so this — the actual "what do we do
with the data" logic — is testable without mocking HTTP at all: tests
just hand it a response dict shaped like the real API's.

Accounts are matched across syncs by (simplefin_connection_id,
simplefin_account_id) — SimpleFin's own account id — so re-syncing
updates the same local Account instead of creating a new one every time.
Once created/linked, a resync never overwrites name/institution/
account_type: those are left alone in case the user edited them locally.
Balance is always refreshed, since SimpleFin's balance is meant to
reflect "right now" on every sync.

**A remote account with no local match is never auto-created.** Real
usage surfaced why: connecting SimpleFin for an account you'd already
CSV-imported silently created a second, separate local Account for the
same real-world card — the two then showed different partial data and
different balances, with no link between them (see app/services/
account_merge.py, built to clean up exactly that after the fact). The
fix here is upstream of that: `partition_response()` splits a sync into
accounts that already match something locally (synced immediately, no
interruption — see `sync_matched_accounts()`) and accounts with no match
yet, which the router routes to a review step instead
(`create_new_account()` or `link_to_existing_account()`, depending on
what the user picks there).
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
    accounts_updated: int = 0
    transactions_imported: int = 0
    transactions_skipped: int = 0
    errors: list[str] = field(default_factory=list)


def partition_response(
    db: Session, connection: SimplefinConnection, response: dict
) -> tuple[list[dict], list[dict]]:
    """Splits response["accounts"] into (matched, new): `matched` entries
    already correspond to a local Account (by simplefin_account_id under
    this connection); `new` entries don't yet and need a human decision
    (routers/simplefin.py's "new accounts found" review step) before
    anything is created.
    """
    matched = []
    new = []
    for remote_account in response.get("accounts", []):
        exists = (
            db.query(Account.id)
            .filter(
                Account.simplefin_connection_id == connection.id,
                Account.simplefin_account_id == remote_account["id"],
            )
            .first()
            is not None
        )
        (matched if exists else new).append(remote_account)
    return matched, new


def sync_matched_accounts(
    db: Session, connection: SimplefinConnection, matched_remote_accounts: list[dict]
) -> SyncResult:
    """Refreshes balance + pulls new transactions for remote accounts that
    already have a local match. Never creates an Account — see this
    module's docstring for why that's routed through a review step
    instead.
    """
    result = SyncResult(errors=[])
    for remote_account in matched_remote_accounts:
        account = (
            db.query(Account)
            .filter(
                Account.simplefin_connection_id == connection.id,
                Account.simplefin_account_id == remote_account["id"],
            )
            .one()
        )
        _update_reported_balance(account, remote_account)
        imported, skipped = _sync_transactions(db, account, remote_account.get("transactions") or [])
        result.accounts_updated += 1
        result.transactions_imported += imported
        result.transactions_skipped += skipped

    connection.last_synced_at = datetime.utcnow()
    db.commit()
    return result


def create_new_account(db: Session, connection: SimplefinConnection, remote_account: dict) -> Account:
    """Creates a fresh local Account for a remote account the user chose
    "create new" for during the "new accounts found" review step, and
    syncs its balance + transactions into it.
    """
    org = remote_account.get("org") or {}
    name = remote_account.get("name") or remote_account["id"]
    account = Account(
        name=name,
        institution=org.get("name"),
        account_type=_guess_account_type(name),
        source="simplefin",
        simplefin_connection_id=connection.id,
        simplefin_account_id=remote_account["id"],
    )
    db.add(account)
    db.flush()

    _update_reported_balance(account, remote_account)
    _sync_transactions(db, account, remote_account.get("transactions") or [])
    db.commit()
    return account


def link_to_existing_account(
    db: Session, connection: SimplefinConnection, remote_account: dict, account_id: int
) -> Account:
    """Attaches a remote SimpleFin account to an EXISTING local Account —
    the user chose "link to existing" during the review step, presumably
    because they'd already CSV-imported this same real-world account —
    instead of creating a new one, then syncs into it.
    """
    account = db.get(Account, account_id)
    account.simplefin_connection_id = connection.id
    account.simplefin_account_id = remote_account["id"]

    _update_reported_balance(account, remote_account)
    _sync_transactions(db, account, remote_account.get("transactions") or [])
    db.commit()
    return account


def _update_reported_balance(account: Account, remote_account: dict) -> None:
    if remote_account.get("balance") is None:
        return
    account.reported_balance = Decimal(remote_account["balance"])
    balance_date = remote_account.get("balance-date")
    if balance_date is not None:
        account.reported_balance_as_of = datetime.fromtimestamp(balance_date, tz=timezone.utc).date()


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

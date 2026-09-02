"""Marking transactions as transfers between the user's own accounts —
most commonly, paying off a credit card from checking. A transfer is
never real income or spending (it's the user's own money moving between
their own accounts), so aggregation.get_period_dashboard() excludes
is_transfer transactions from the totals/chart/category breakdown
everyone sees by default. It still counts in balances.py's
"starting_balance + net" tier, since it genuinely changes each
individual account's balance — only aggregation.py's income/spending
math treats it specially.

Pairing is optional, not required (established by explicit user
decision, not an oversight): marking one side of a transfer is a fully
valid end state on its own — e.g. the other account isn't tracked in
this app at all, so there's nothing to link to. link_transfer_pair
confirms a specific match; the Transactions page (redesigned 2026-08-30)
gets there by having the user select both sides themselves and mark them
as a transfer together — see docs/2026-08-30-transactions-page-
redesign.md. (An earlier version of this module had a
find_transfer_candidates() heuristic that suggested a match for a human
to confirm; retired once selecting both sides directly replaced it —
nothing in the app called it anymore.)
"""
from sqlalchemy.orm import Session

from app.models import Transaction


def mark_as_transfer(db: Session, transaction: Transaction) -> None:
    """Marks a single transaction as a transfer, unpaired. Caller commits."""
    transaction.is_transfer = True


def unmark_transfer(db: Session, transaction: Transaction) -> None:
    """Clears is_transfer, and if the transaction was paired, unlinks
    *both* sides — not just the one being unmarked, since leaving the
    partner's is_transfer=True with a transfer_pair_id pointing at a
    transaction that no longer considers itself a transfer would be a
    dangling half-pair. Caller commits.
    """
    pair = db.get(Transaction, transaction.transfer_pair_id) if transaction.transfer_pair_id else None
    transaction.is_transfer = False
    transaction.transfer_pair_id = None
    if pair is not None:
        pair.is_transfer = False
        pair.transfer_pair_id = None


def link_transfer_pair(db: Session, transaction: Transaction, pair: Transaction) -> None:
    """Confirms a specific match: sets is_transfer + transfer_pair_id on
    both sides symmetrically. Caller commits.
    """
    transaction.is_transfer = True
    transaction.transfer_pair_id = pair.id
    pair.is_transfer = True
    pair.transfer_pair_id = transaction.id


def clear_pair_on_delete(db: Session, transaction: Transaction) -> None:
    """Call before deleting a transaction that might be one side of a
    transfer pair (e.g. account_merge discarding a confirmed-duplicate
    transaction) — nulls out its partner's transfer_pair_id and clears
    the partner's is_transfer, so deleting one side never leaves the
    other pointing at a row that no longer exists. No-op if the
    transaction being deleted isn't paired. Caller commits/deletes.
    """
    if transaction.transfer_pair_id is None:
        return
    pair = db.get(Transaction, transaction.transfer_pair_id)
    if pair is not None:
        pair.is_transfer = False
        pair.transfer_pair_id = None

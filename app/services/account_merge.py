"""Merging two Accounts that turned out to represent the same real-world
account — e.g. a CSV-imported history and a SimpleFin connection that
auto-created its own separate Account for the same card before the two
were ever linked.

`find_duplicate_candidates()` matches transactions across the two
accounts by (date, amount) — CSV's external_id (a hash of date+amount+
description) and SimpleFin's own transaction id never coincide even for
the identical real transaction, so ordinary external_id dedup can't
catch this overlap. Matching by (date, amount) alone casts a wide net on
purpose: the caller (routers/accounts.py) shows each candidate pair to
the user for confirmation rather than silently discarding anything — a
coincidental same-day-same-amount pair that isn't really the same
transaction should stay as two rows, and only a human comparing both
descriptions can tell the difference.

`execute_merge()` acts on whatever the human confirmed: pairs in
`discard_source_transaction_ids` are dropped (the target's copy of that
pair survives); everything else — unmatched transactions, and any
candidate pair the human rejected — is simply moved onto the target
account.

Transfer-pair integrity (added alongside app/services/transfers.py):
a merge can affect a transaction's transfer_pair_id two ways — a
discarded transaction might be one side of a transfer pair (its partner
would otherwise dangle, pointing at a deleted row), and a transaction
moved onto the target account might turn out to now share an account
with its transfer partner (the two accounts that had the transfer
between them are being merged into one, so it isn't a transfer to
anywhere anymore). Both are handled below rather than left to the
transfers module, since only execute_merge() knows which transactions
are being deleted vs. moved onto which account.
"""
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import Account, Transaction
from app.services import transfers


def find_duplicate_candidates(
    db: Session, source_account_id: int, target_account_id: int
) -> tuple[list[tuple[Transaction, Transaction]], list[Transaction]]:
    """Returns (pairs, unmatched_source_transactions).

    Each pair is (source transaction, target transaction) sharing the
    same date and amount — a candidate duplicate. When more than one
    transaction on a side shares the same (date, amount) key (e.g. two
    separate same-day charges), pairs are formed 1:1 in id order rather
    than matching every source transaction against a single target
    transaction repeatedly.
    """
    source_txns = (
        db.query(Transaction).filter(Transaction.account_id == source_account_id).order_by(Transaction.id).all()
    )
    target_txns = (
        db.query(Transaction).filter(Transaction.account_id == target_account_id).order_by(Transaction.id).all()
    )

    target_by_key: dict[tuple, list[Transaction]] = defaultdict(list)
    for t in target_txns:
        target_by_key[(t.date, t.amount)].append(t)

    pairs: list[tuple[Transaction, Transaction]] = []
    unmatched: list[Transaction] = []
    for s in source_txns:
        candidates = target_by_key.get((s.date, s.amount))
        if candidates:
            pairs.append((s, candidates.pop(0)))
        else:
            unmatched.append(s)

    return pairs, unmatched


@dataclass
class MergeResult:
    moved: int
    discarded: int


def execute_merge(
    db: Session,
    source_account_id: int,
    target_account_id: int,
    discard_source_transaction_ids: set[int],
) -> MergeResult:
    """Reassigns every source-account transaction onto the target account,
    except the ones in `discard_source_transaction_ids` (deleted instead
    — the target already holds an equivalent transaction for those).
    Transfers SimpleFin linkage/reported balance from source to target
    only if the target doesn't already have its own, then deletes the
    (now-empty) source account.
    """
    source = db.get(Account, source_account_id)
    target = db.get(Account, target_account_id)

    moved = 0
    discarded = 0
    moved_transactions: list[Transaction] = []
    for txn in db.query(Transaction).filter(Transaction.account_id == source_account_id).all():
        if txn.id in discard_source_transaction_ids:
            # A discarded transaction might be one side of a transfer pair
            # — clear its partner's fields before the row disappears, or
            # the partner would be left pointing at a deleted transaction.
            transfers.clear_pair_on_delete(db, txn)
            db.delete(txn)
            discarded += 1
        else:
            txn.account_id = target_account_id
            moved += 1
            moved_transactions.append(txn)

    # Flush the reassignments before deleting source: otherwise SQLAlchemy's
    # unit-of-work can still treat these transactions as source's children
    # (they were only reassigned via the raw FK column, not the ORM
    # relationship) and null out their account_id as part of "de-parenting"
    # them from the deleted account — which fails, since account_id is
    # NOT NULL. Flushing first means the delete's cascade check sees them
    # already moved.
    db.flush()

    # A transfer pair that now has both sides on the same account (the
    # two accounts that had the transfer between them are being merged
    # into one) is no longer a transfer at all — clear both sides. Only
    # moved transactions can trigger this: an unmoved (discarded) side
    # was already handled above, and a transaction that was already on
    # the target account before the merge can't newly collide with
    # anything by this merge alone.
    for txn in moved_transactions:
        if txn.is_transfer and txn.transfer_pair_id is not None:
            pair = db.get(Transaction, txn.transfer_pair_id)
            if pair is not None and pair.account_id == target_account_id:
                txn.is_transfer = False
                txn.transfer_pair_id = None
                pair.is_transfer = False
                pair.transfer_pair_id = None

    if target.simplefin_account_id is None and source.simplefin_account_id is not None:
        target.simplefin_account_id = source.simplefin_account_id
        target.simplefin_connection_id = source.simplefin_connection_id
        target.reported_balance = source.reported_balance
        target.reported_balance_as_of = source.reported_balance_as_of

    db.delete(source)
    db.commit()

    return MergeResult(moved=moved, discarded=discarded)

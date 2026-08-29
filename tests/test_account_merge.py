"""Tests for app.services.account_merge.

The core problem this solves: two local Accounts end up representing the
same real-world account (e.g. a CSV-imported history plus a SimpleFin
connection that auto-created its own Account for the same card). CSV
transactions and SimpleFin transactions never share an external_id even
when they're the same real transaction — CSV's is a hash of
(date, amount, description), SimpleFin's is its own transaction id — so
ordinary external_id dedup can't catch the overlap. find_duplicate_candidates
matches by (date, amount) instead and leaves the judgment call to a human
review step; execute_merge acts on whatever the human confirmed.
"""
from datetime import date
from decimal import Decimal

from app.models import Account, Transaction
from app.services.account_merge import execute_merge, find_duplicate_candidates


def _account(db_session, **kwargs):
    account = Account(name=kwargs.pop("name", "Account"), account_type=kwargs.pop("account_type", "checking"), **kwargs)
    db_session.add(account)
    db_session.flush()
    return account


def _txn(db_session, account_id, d, amount, description="x", **kwargs):
    t = Transaction(account_id=account_id, date=d, amount=amount, description=description, **kwargs)
    db_session.add(t)
    db_session.flush()
    return t


# ---- find_duplicate_candidates ----


def test_matches_transactions_by_date_and_amount(db_session):
    source = _account(db_session, name="CSV Card")
    target = _account(db_session, name="Synced Card")
    s1 = _txn(db_session, source.id, date(2026, 7, 1), -42.50, description="JOHNS FISHIN SHACK")
    t1 = _txn(db_session, target.id, date(2026, 7, 1), -42.50, description="John's Fishin Shack")
    db_session.commit()

    pairs, unmatched = find_duplicate_candidates(db_session, source.id, target.id)

    assert len(pairs) == 1
    assert pairs[0][0].id == s1.id
    assert pairs[0][1].id == t1.id
    assert unmatched == []


def test_no_match_when_date_or_amount_differ(db_session):
    source = _account(db_session, name="CSV Card")
    target = _account(db_session, name="Synced Card")
    s1 = _txn(db_session, source.id, date(2026, 7, 1), -42.50)
    _txn(db_session, target.id, date(2026, 7, 2), -42.50)  # different date
    _txn(db_session, target.id, date(2026, 7, 1), -10.00)  # different amount
    db_session.commit()

    pairs, unmatched = find_duplicate_candidates(db_session, source.id, target.id)

    assert pairs == []
    assert [t.id for t in unmatched] == [s1.id]


def test_pairs_same_day_same_amount_transactions_one_to_one(db_session):
    # Two genuinely separate $20 charges on the same day on each side —
    # should pair up 1:1, not have one target transaction matched twice.
    source = _account(db_session, name="CSV Card")
    target = _account(db_session, name="Synced Card")
    s1 = _txn(db_session, source.id, date(2026, 7, 1), -20.00, description="Gas A")
    s2 = _txn(db_session, source.id, date(2026, 7, 1), -20.00, description="Gas B")
    t1 = _txn(db_session, target.id, date(2026, 7, 1), -20.00, description="Gas A")
    t2 = _txn(db_session, target.id, date(2026, 7, 1), -20.00, description="Gas B")
    db_session.commit()

    pairs, unmatched = find_duplicate_candidates(db_session, source.id, target.id)

    assert len(pairs) == 2
    assert unmatched == []
    matched_target_ids = {p[1].id for p in pairs}
    assert matched_target_ids == {t1.id, t2.id}
    matched_source_ids = {p[0].id for p in pairs}
    assert matched_source_ids == {s1.id, s2.id}


def test_extra_unmatched_transaction_when_counts_differ(db_session):
    source = _account(db_session, name="CSV Card")
    target = _account(db_session, name="Synced Card")
    s1 = _txn(db_session, source.id, date(2026, 7, 1), -20.00)
    s2 = _txn(db_session, source.id, date(2026, 7, 1), -20.00)  # a second $20 charge that day
    _txn(db_session, target.id, date(2026, 7, 1), -20.00)  # only one on target's side
    db_session.commit()

    pairs, unmatched = find_duplicate_candidates(db_session, source.id, target.id)

    assert len(pairs) == 1
    assert len(unmatched) == 1
    assert unmatched[0].id in {s1.id, s2.id}


# ---- execute_merge ----


def test_execute_merge_moves_unmatched_transactions(db_session):
    source = _account(db_session, name="CSV Card")
    target = _account(db_session, name="Synced Card")
    s1 = _txn(db_session, source.id, date(2026, 7, 1), -20.00)
    db_session.commit()

    execute_merge(db_session, source_account_id=source.id, target_account_id=target.id, discard_source_transaction_ids=set())

    db_session.refresh(s1)
    assert s1.account_id == target.id


def test_execute_merge_discards_confirmed_duplicates(db_session):
    source = _account(db_session, name="CSV Card")
    target = _account(db_session, name="Synced Card")
    s1 = _txn(db_session, source.id, date(2026, 7, 1), -20.00, description="dup")
    t1 = _txn(db_session, target.id, date(2026, 7, 1), -20.00, description="dup")
    db_session.commit()

    result = execute_merge(
        db_session, source_account_id=source.id, target_account_id=target.id, discard_source_transaction_ids={s1.id}
    )

    remaining = db_session.query(Transaction).filter(Transaction.account_id == target.id).all()
    assert [t.id for t in remaining] == [t1.id]  # s1 discarded, t1 kept
    assert result.moved == 0
    assert result.discarded == 1


def test_execute_merge_keeps_unconfirmed_pair_as_two_separate_transactions(db_session):
    # If the human unchecks a candidate pair (says "these are actually
    # different"), both must survive under the target account.
    source = _account(db_session, name="CSV Card")
    target = _account(db_session, name="Synced Card")
    s1 = _txn(db_session, source.id, date(2026, 7, 1), -20.00, description="Gas A")
    t1 = _txn(db_session, target.id, date(2026, 7, 1), -20.00, description="Gas B")
    db_session.commit()

    execute_merge(db_session, source_account_id=source.id, target_account_id=target.id, discard_source_transaction_ids=set())

    remaining_ids = {t.id for t in db_session.query(Transaction).filter(Transaction.account_id == target.id).all()}
    assert remaining_ids == {s1.id, t1.id}


def test_execute_merge_deletes_source_account(db_session):
    source = _account(db_session, name="CSV Card")
    target = _account(db_session, name="Synced Card")
    db_session.commit()

    execute_merge(db_session, source_account_id=source.id, target_account_id=target.id, discard_source_transaction_ids=set())

    assert db_session.get(Account, source.id) is None
    assert db_session.get(Account, target.id) is not None


def test_execute_merge_transfers_simplefin_linkage_from_source(db_session):
    source = _account(
        db_session,
        name="Synced Card",
        source="simplefin",
        simplefin_account_id="remote-123",
        reported_balance=Decimal("500.00"),
        reported_balance_as_of=date(2026, 7, 1),
    )
    target = _account(db_session, name="CSV Card")  # the manual one survives
    db_session.commit()

    execute_merge(db_session, source_account_id=source.id, target_account_id=target.id, discard_source_transaction_ids=set())

    db_session.refresh(target)
    assert target.simplefin_account_id == "remote-123"
    assert target.reported_balance == Decimal("500.00")
    assert target.reported_balance_as_of == date(2026, 7, 1)


def test_execute_merge_does_not_overwrite_targets_existing_simplefin_linkage(db_session):
    source = _account(db_session, name="A", simplefin_account_id="remote-A")
    target = _account(db_session, name="B", simplefin_account_id="remote-B", reported_balance=Decimal("10.00"))
    db_session.commit()

    execute_merge(db_session, source_account_id=source.id, target_account_id=target.id, discard_source_transaction_ids=set())

    db_session.refresh(target)
    assert target.simplefin_account_id == "remote-B"
    assert target.reported_balance == Decimal("10.00")

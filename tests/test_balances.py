"""Tests for app.services.balances.resolve_balance's four-tier fallback:
account-level reported balance (SimpleFin) > transaction-level reported
balance (CSV/OFX) > starting_balance + net > net alone (honestly labeled
as not a real balance).
"""
from datetime import date
from decimal import Decimal

from app.models import Account, Transaction
from app.services.balances import resolve_balance


def _txn(account_id, d, amount, balance=None):
    return Transaction(account_id=account_id, date=d, amount=amount, description="x", balance=balance)


def test_account_level_reported_balance_outranks_everything(db_session):
    account = Account(
        name="Checking",
        account_type="checking",
        starting_balance=Decimal("999.00"),
        reported_balance=Decimal("2050.00"),
        reported_balance_as_of=date(2026, 6, 2),
    )
    db_session.add(account)
    db_session.flush()
    db_session.add(_txn(account.id, date(2026, 6, 1), 100, balance=Decimal("1.00")))  # would win tier 2
    db_session.commit()

    result = resolve_balance(db_session, account)
    assert result.source == "reported"
    assert result.amount == Decimal("2050.00")
    assert result.as_of == date(2026, 6, 2)


def test_uses_latest_reported_balance_when_present(db_session):
    account = Account(name="Checking", account_type="checking")
    db_session.add(account)
    db_session.flush()
    db_session.add_all(
        [
            _txn(account.id, date(2026, 7, 1), 100, balance=Decimal("600.00")),
            _txn(account.id, date(2026, 7, 5), -50, balance=Decimal("550.00")),
        ]
    )
    db_session.commit()

    result = resolve_balance(db_session, account)
    assert result.source == "reported"
    assert result.amount == Decimal("550.00")
    assert result.as_of == date(2026, 7, 5)


def test_reported_balance_wins_even_if_a_later_transaction_lacks_one(db_session):
    account = Account(name="Checking", account_type="checking")
    db_session.add(account)
    db_session.flush()
    db_session.add_all(
        [
            _txn(account.id, date(2026, 7, 1), 100, balance=Decimal("600.00")),
            _txn(account.id, date(2026, 7, 10), -20, balance=None),  # no reported balance
        ]
    )
    db_session.commit()

    result = resolve_balance(db_session, account)
    assert result.source == "reported"
    assert result.amount == Decimal("600.00")
    assert result.as_of == date(2026, 7, 1)


def test_falls_back_to_starting_balance_plus_net_when_no_reported_balance(db_session):
    account = Account(name="Checking", account_type="checking", starting_balance=Decimal("100.00"))
    db_session.add(account)
    db_session.flush()
    db_session.add_all(
        [
            _txn(account.id, date(2026, 7, 1), 500),
            _txn(account.id, date(2026, 7, 5), -50),
        ]
    )
    db_session.commit()

    result = resolve_balance(db_session, account)
    assert result.source == "estimated"
    assert result.amount == Decimal("550.00")  # 100 starting + 500 - 50


def test_falls_back_to_net_only_with_no_starting_balance_or_reported(db_session):
    account = Account(name="Checking", account_type="checking")
    db_session.add(account)
    db_session.flush()
    db_session.add_all([_txn(account.id, date(2026, 7, 1), 500), _txn(account.id, date(2026, 7, 5), -50)])
    db_session.commit()

    result = resolve_balance(db_session, account)
    assert result.source == "net_only"
    assert result.amount == Decimal("450.00")


def test_net_only_with_no_transactions_at_all(db_session):
    account = Account(name="Checking", account_type="checking")
    db_session.add(account)
    db_session.commit()

    result = resolve_balance(db_session, account)
    assert result.source == "net_only"
    assert result.amount == Decimal("0")


def test_ties_on_date_broken_by_most_recently_inserted(db_session):
    account = Account(name="Checking", account_type="checking")
    db_session.add(account)
    db_session.flush()
    same_day = date(2026, 7, 1)
    db_session.add_all(
        [
            _txn(account.id, same_day, 10, balance=Decimal("110.00")),
            _txn(account.id, same_day, 20, balance=Decimal("130.00")),
        ]
    )
    db_session.commit()

    result = resolve_balance(db_session, account)
    assert result.amount == Decimal("130.00")

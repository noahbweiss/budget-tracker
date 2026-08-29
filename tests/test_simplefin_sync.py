"""Tests for app.services.simplefin_sync.

FAKE_RESPONSE below is modeled directly on a real response captured from
SimpleFin's own demo bridge (beta-bridge.simplefin.org) during
development — same field names/shapes, trimmed down.
"""
from datetime import date
from decimal import Decimal

from app.models import Account, SimplefinConnection, Transaction
from app.services.simplefin_sync import (
    create_new_account,
    link_to_existing_account,
    partition_response,
    sync_matched_accounts,
)

FAKE_RESPONSE = {
    "errors": [],
    "accounts": [
        {
            "id": "demo-savings",
            "name": "SimpleFIN Savings",
            "currency": "USD",
            "balance": "113705.51",
            "available-balance": "113705.51",
            "balance-date": 1787961600,  # 2026-08-29 (a UTC midnight timestamp)
            "transactions": [
                {
                    "id": "txn-1",
                    "posted": 1787904000,
                    "amount": "-140.00",
                    "description": "Fishing bait",
                    "payee": "John's Fishin Shack",
                    "memo": "JOHNS FISHIN SHACK BAIT",
                },
                {
                    "id": "txn-2",
                    "posted": 1787932800,
                    "amount": "2500.00",
                    "description": "Paycheck",
                },
            ],
            "holdings": [{"id": "h1", "symbol": "AAPL", "shares": "10", "market_value": "1900.00"}],
            "org": {"domain": "beta-bridge.simplefin.org", "name": "SimpleFIN Demo", "id": "simplefin.demoorg"},
        }
    ],
}


def _connection(db_session):
    connection = SimplefinConnection(access_url="https://demo:demo@bridge.example.com/simplefin")
    db_session.add(connection)
    db_session.flush()
    return connection


# ---- partition_response ----


def test_partition_puts_unmatched_accounts_in_new(db_session):
    connection = _connection(db_session)
    db_session.commit()

    matched, new = partition_response(db_session, connection, FAKE_RESPONSE)

    assert matched == []
    assert len(new) == 1
    assert new[0]["id"] == "demo-savings"


def test_partition_puts_already_linked_accounts_in_matched(db_session):
    connection = _connection(db_session)
    account = Account(
        name="Existing", account_type="savings", simplefin_connection_id=connection.id, simplefin_account_id="demo-savings"
    )
    db_session.add(account)
    db_session.commit()

    matched, new = partition_response(db_session, connection, FAKE_RESPONSE)

    assert new == []
    assert len(matched) == 1


def test_partition_does_not_match_across_different_connections(db_session):
    connection = _connection(db_session)
    other_connection = SimplefinConnection(access_url="https://other:other@bridge.example.com/simplefin")
    db_session.add(other_connection)
    db_session.flush()
    # Same remote account id, but linked to a *different* connection —
    # should not count as a match for `connection`.
    account = Account(
        name="Existing",
        account_type="savings",
        simplefin_connection_id=other_connection.id,
        simplefin_account_id="demo-savings",
    )
    db_session.add(account)
    db_session.commit()

    matched, new = partition_response(db_session, connection, FAKE_RESPONSE)

    assert matched == []
    assert len(new) == 1


# ---- create_new_account ----


def test_create_new_account_creates_and_syncs(db_session):
    connection = _connection(db_session)
    db_session.commit()

    account = create_new_account(db_session, connection, FAKE_RESPONSE["accounts"][0])

    assert account.name == "SimpleFIN Savings"
    assert account.institution == "SimpleFIN Demo"
    assert account.source == "simplefin"
    assert account.account_type == "savings"
    assert account.simplefin_account_id == "demo-savings"
    assert account.reported_balance == Decimal("113705.51")
    assert db_session.query(Transaction).filter(Transaction.account_id == account.id).count() == 2


def test_create_new_account_transaction_description_prefers_payee(db_session):
    connection = _connection(db_session)
    db_session.commit()
    account = create_new_account(db_session, connection, FAKE_RESPONSE["accounts"][0])

    txn1 = db_session.query(Transaction).filter(Transaction.external_id == "txn-1").one()
    assert txn1.description == "John's Fishin Shack"
    txn2 = db_session.query(Transaction).filter(Transaction.external_id == "txn-2").one()
    assert txn2.description == "Paycheck"


# ---- link_to_existing_account ----


def test_link_to_existing_account_attaches_and_syncs_without_creating_new(db_session):
    connection = _connection(db_session)
    existing = Account(name="My CSV-Imported Savings", account_type="savings")
    db_session.add(existing)
    db_session.commit()

    result = link_to_existing_account(db_session, connection, FAKE_RESPONSE["accounts"][0], existing.id)

    assert result.id == existing.id
    assert result.name == "My CSV-Imported Savings"  # not overwritten
    assert result.simplefin_account_id == "demo-savings"
    assert result.simplefin_connection_id == connection.id
    assert result.reported_balance == Decimal("113705.51")
    assert db_session.query(Account).count() == 1  # no second account created
    assert db_session.query(Transaction).filter(Transaction.account_id == existing.id).count() == 2


def test_link_to_existing_account_dedupes_transactions_already_there(db_session):
    connection = _connection(db_session)
    existing = Account(name="My Savings", account_type="savings")
    db_session.add(existing)
    db_session.flush()
    db_session.add(Transaction(account_id=existing.id, date=date(2026, 8, 28), amount=-140, description="x", external_id="txn-1"))
    db_session.commit()

    link_to_existing_account(db_session, connection, FAKE_RESPONSE["accounts"][0], existing.id)

    # txn-1 already existed (by external_id) — only txn-2 should be newly added.
    assert db_session.query(Transaction).filter(Transaction.account_id == existing.id).count() == 2


# ---- sync_matched_accounts ----


def test_sync_matched_accounts_never_creates_a_new_account(db_session):
    connection = _connection(db_session)
    existing = Account(
        name="Existing",
        account_type="savings",
        simplefin_connection_id=connection.id,
        simplefin_account_id="demo-savings",
    )
    db_session.add(existing)
    db_session.commit()

    result = sync_matched_accounts(db_session, connection, FAKE_RESPONSE["accounts"])

    assert db_session.query(Account).count() == 1
    assert result.accounts_updated == 1
    assert result.transactions_imported == 2


def test_sync_matched_accounts_does_not_reduplicate_on_resync(db_session):
    connection = _connection(db_session)
    existing = Account(
        name="Existing",
        account_type="savings",
        simplefin_connection_id=connection.id,
        simplefin_account_id="demo-savings",
    )
    db_session.add(existing)
    db_session.commit()

    sync_matched_accounts(db_session, connection, FAKE_RESPONSE["accounts"])
    result = sync_matched_accounts(db_session, connection, FAKE_RESPONSE["accounts"])

    assert result.transactions_imported == 0
    assert result.transactions_skipped == 2
    assert db_session.query(Transaction).count() == 2


def test_sync_matched_accounts_sets_last_synced_at(db_session):
    connection = _connection(db_session)
    existing = Account(
        name="Existing",
        account_type="savings",
        simplefin_connection_id=connection.id,
        simplefin_account_id="demo-savings",
    )
    db_session.add(existing)
    db_session.commit()

    assert connection.last_synced_at is None
    sync_matched_accounts(db_session, connection, FAKE_RESPONSE["accounts"])
    assert connection.last_synced_at is not None

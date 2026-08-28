"""Tests for app.services.simplefin_sync.

FAKE_RESPONSE below is modeled directly on a real response captured from
SimpleFin's own demo bridge (beta-bridge.simplefin.org) during
development — same field names/shapes, trimmed down.
"""
from datetime import date
from decimal import Decimal

from app.models import Account, SimplefinConnection, Transaction
from app.services.simplefin_sync import apply_sync_response

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


def test_creates_new_account_and_transactions(db_session):
    connection = _connection(db_session)

    result = apply_sync_response(db_session, connection, FAKE_RESPONSE)

    assert result.accounts_created == 1
    assert result.accounts_updated == 0
    assert result.transactions_imported == 2
    assert result.transactions_skipped == 0
    assert result.errors == []

    account = db_session.query(Account).one()
    assert account.name == "SimpleFIN Savings"
    assert account.institution == "SimpleFIN Demo"
    assert account.source == "simplefin"
    assert account.account_type == "savings"  # guessed from "Savings" in the name
    assert account.simplefin_account_id == "demo-savings"
    assert account.simplefin_connection_id == connection.id
    assert account.reported_balance == Decimal("113705.51")
    assert account.reported_balance_as_of == date(2026, 8, 29)


def test_transaction_fields_mapped_correctly(db_session):
    connection = _connection(db_session)
    apply_sync_response(db_session, connection, FAKE_RESPONSE)

    txns = {t.external_id: t for t in db_session.query(Transaction).all()}
    assert txns["txn-1"].amount == -140
    assert txns["txn-1"].description == "John's Fishin Shack"  # payee preferred over description
    assert txns["txn-1"].date == date(2026, 8, 28)

    assert txns["txn-2"].amount == 2500
    assert txns["txn-2"].description == "Paycheck"  # no payee — falls back to description


def test_holdings_are_ignored(db_session):
    connection = _connection(db_session)
    apply_sync_response(db_session, connection, FAKE_RESPONSE)
    # No error, and nothing resembling a holding got created anywhere —
    # the account and its 2 real transactions are all that exist.
    assert db_session.query(Transaction).count() == 2


def test_resync_updates_existing_account_without_creating_duplicate(db_session):
    connection = _connection(db_session)
    apply_sync_response(db_session, connection, FAKE_RESPONSE)

    updated_response = {
        "errors": [],
        "accounts": [
            {
                **FAKE_RESPONSE["accounts"][0],
                "balance": "120000.00",
                "balance-date": 1788048000,  # a day later
                "transactions": FAKE_RESPONSE["accounts"][0]["transactions"],  # same 2 txns again
            }
        ],
    }
    result = apply_sync_response(db_session, connection, updated_response)

    assert result.accounts_created == 0
    assert result.accounts_updated == 1
    assert result.transactions_imported == 0
    assert result.transactions_skipped == 2  # both already existed — not duplicated

    assert db_session.query(Account).count() == 1
    account = db_session.query(Account).one()
    assert account.reported_balance == Decimal("120000.00")


def test_resync_does_not_clobber_user_edited_name_or_type(db_session):
    connection = _connection(db_session)
    apply_sync_response(db_session, connection, FAKE_RESPONSE)

    account = db_session.query(Account).one()
    account.name = "My Renamed Savings"
    account.account_type = "other"
    db_session.commit()

    apply_sync_response(db_session, connection, FAKE_RESPONSE)

    db_session.refresh(account)
    assert account.name == "My Renamed Savings"
    assert account.account_type == "other"


def test_resync_picks_up_new_transactions_only(db_session):
    connection = _connection(db_session)
    apply_sync_response(db_session, connection, FAKE_RESPONSE)

    response_with_new_txn = {
        "errors": [],
        "accounts": [
            {
                **FAKE_RESPONSE["accounts"][0],
                "transactions": [
                    *FAKE_RESPONSE["accounts"][0]["transactions"],
                    {"id": "txn-3", "posted": 1788019200, "amount": "-25.00", "description": "Coffee"},
                ],
            }
        ],
    }
    result = apply_sync_response(db_session, connection, response_with_new_txn)

    assert result.transactions_imported == 1
    assert result.transactions_skipped == 2
    assert db_session.query(Transaction).count() == 3


def test_surfaces_api_errors_without_failing(db_session):
    connection = _connection(db_session)
    response = {**FAKE_RESPONSE, "errors": ["Requested date range exceeds recommended range of 45 days."]}

    result = apply_sync_response(db_session, connection, response)

    assert result.errors == ["Requested date range exceeds recommended range of 45 days."]
    assert result.accounts_created == 1  # still processed normally


def test_guesses_checking_when_no_type_hint_in_name(db_session):
    connection = _connection(db_session)
    response = {
        "errors": [],
        "accounts": [
            {
                "id": "demo-checking",
                "name": "Everyday Account",
                "balance": "500.00",
                "balance-date": 1787961600,
                "transactions": [],
                "org": {"name": "Some Bank"},
            }
        ],
    }
    apply_sync_response(db_session, connection, response)
    account = db_session.query(Account).one()
    assert account.account_type == "checking"


def test_sets_last_synced_at(db_session):
    connection = _connection(db_session)
    assert connection.last_synced_at is None
    apply_sync_response(db_session, connection, FAKE_RESPONSE)
    assert connection.last_synced_at is not None

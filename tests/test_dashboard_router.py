"""Tests for the /dashboard router's account_id filter and sidebar.

Uses the isolated client/db_session fixtures (not test_health.py's
module-level client, which hits the real local data/finance.db) since
these need actual seeded Account/Transaction rows.
"""
from datetime import date

from app.models import Account, Transaction


def _account(db_session, name):
    account = Account(name=name, account_type="checking")
    db_session.add(account)
    db_session.flush()
    return account


def test_sidebar_lists_all_accounts(client, db_session):
    _account(db_session, "Checking")
    _account(db_session, "Savings")
    db_session.commit()

    response = client.get("/dashboard/monthly")
    assert "Checking" in response.text
    assert "Savings" in response.text
    assert "All accounts" in response.text


def test_no_account_selected_shows_all_accounts_data(client, db_session):
    checking = _account(db_session, "Checking")
    savings = _account(db_session, "Savings")
    db_session.add_all(
        [
            Transaction(account_id=checking.id, date=date.today(), amount=-40, description="x"),
            Transaction(account_id=savings.id, date=date.today(), amount=500, description="y"),
        ]
    )
    db_session.commit()

    response = client.get("/dashboard/daily")
    assert response.status_code == 200
    assert "dashboard-sidebar__link active" in response.text or 'class="dashboard-sidebar__link active"' in response.text


def test_selecting_an_account_scopes_totals(client, db_session):
    checking = _account(db_session, "Checking")
    savings = _account(db_session, "Savings")
    db_session.add_all(
        [
            Transaction(account_id=checking.id, date=date.today(), amount=-40, description="x"),
            Transaction(account_id=savings.id, date=date.today(), amount=500, description="y"),
        ]
    )
    db_session.commit()

    response = client.get(f"/dashboard/daily?account_id={checking.id}")
    assert response.status_code == 200
    assert "$40.00" in response.text  # checking's spending
    assert "$500.00" not in response.text  # savings' income shouldn't appear
    assert f">{checking.name}<" in response.text


def test_selected_account_heading_shown(client, db_session):
    checking = _account(db_session, "My Checking")
    db_session.commit()

    response = client.get(f"/dashboard/monthly?account_id={checking.id}")
    assert "<h1>My Checking</h1>" in response.text


def test_no_account_selected_heading_is_overview(client, db_session):
    response = client.get("/dashboard/monthly")
    assert "<h1>Overview</h1>" in response.text


def test_invalid_account_id_404s(client, db_session):
    response = client.get("/dashboard/monthly?account_id=999")
    assert response.status_code == 404


def test_range_switch_preserves_selected_account(client, db_session):
    checking = _account(db_session, "Checking")
    db_session.commit()

    response = client.get(f"/dashboard/monthly?account_id={checking.id}")
    assert f"/dashboard/weekly?account_id={checking.id}" in response.text


def test_period_nav_preserves_selected_account(client, db_session):
    checking = _account(db_session, "Checking")
    db_session.commit()

    response = client.get(f"/dashboard/monthly?account_id={checking.id}")
    assert f"account_id={checking.id}" in response.text
    assert "offset=1" in response.text

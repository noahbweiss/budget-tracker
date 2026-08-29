"""Tests for the /simplefin router. Mocks SimpleFinClient's two network
methods (exchange_setup_token, get_accounts_and_transactions) — the
protocol assumptions they encode were verified manually against the real
demo bridge; see simplefin_client.py's docstring and
test_simplefin_client.py.
"""
import re

import httpx
import pytest

from app.models import Account, SimplefinConnection
from app.services.simplefin_client import SimpleFinClient

FAKE_RESPONSE = {
    "errors": [],
    "accounts": [
        {
            "id": "demo-checking",
            "name": "Demo Checking",
            "balance": "1000.00",
            "balance-date": 1787961600,
            "transactions": [{"id": "t1", "posted": 1787904000, "amount": "-50.00", "description": "Coffee"}],
            "org": {"name": "Demo Bank"},
        }
    ],
}


@pytest.fixture()
def mock_exchange(monkeypatch):
    monkeypatch.setattr(
        SimpleFinClient, "exchange_setup_token", lambda self, token: "https://demo:demo@bridge.example.com/simplefin"
    )


@pytest.fixture()
def mock_sync(monkeypatch):
    monkeypatch.setattr(SimpleFinClient, "get_accounts_and_transactions", lambda self, start_date=None: FAKE_RESPONSE)


def _extract_hidden_json(html: str) -> str:
    match = re.search(r"name=\"remote_account_json\" value='([^']*)'", html)
    assert match, "no remote_account_json hidden field found"
    return match.group(1)


def test_index_shows_connect_form_when_no_connection(client):
    response = client.get("/simplefin/")
    assert response.status_code == 200
    assert "setup_token" in response.text
    assert "Connected" not in response.text


def test_connect_with_bad_token_returns_400(client, db_session, monkeypatch):
    def fail(self, token):
        raise ValueError("setup token isn't valid base64")

    monkeypatch.setattr(SimpleFinClient, "exchange_setup_token", fail)

    response = client.post("/simplefin/connect", data={"setup_token": "not-valid"})
    assert response.status_code == 400
    assert db_session.query(SimplefinConnection).count() == 0


def test_connect_with_unmatched_remote_account_shows_review_step(client, db_session, mock_exchange, mock_sync):
    response = client.post("/simplefin/connect", data={"setup_token": "Zm9v"})

    assert response.status_code == 200
    assert "New accounts found" in response.text
    assert "Demo Checking" in response.text
    # Nothing created yet — still pending a choice.
    assert db_session.query(Account).count() == 0
    assert db_session.query(SimplefinConnection).count() == 1  # connection itself is saved


def test_resolve_new_accounts_create_new(client, db_session, mock_exchange, mock_sync):
    connect_response = client.post("/simplefin/connect", data={"setup_token": "Zm9v"})
    remote_json = _extract_hidden_json(connect_response.text)

    response = client.post(
        "/simplefin/resolve-new-accounts",
        data={"remote_account_json": remote_json, "choice": "new"},
    )
    assert response.status_code == 200
    assert "Connected" in response.text

    account = db_session.query(Account).one()
    assert account.name == "Demo Checking"
    assert account.source == "simplefin"


def test_resolve_new_accounts_link_to_existing(client, db_session, mock_exchange, mock_sync):
    existing = Account(name="My CSV Checking", account_type="checking")
    db_session.add(existing)
    db_session.commit()

    connect_response = client.post("/simplefin/connect", data={"setup_token": "Zm9v"})
    remote_json = _extract_hidden_json(connect_response.text)
    assert "My CSV Checking" in connect_response.text  # offered as a link target

    response = client.post(
        "/simplefin/resolve-new-accounts",
        data={"remote_account_json": remote_json, "choice": str(existing.id)},
    )
    assert response.status_code == 200

    assert db_session.query(Account).count() == 1  # no second account created
    db_session.refresh(existing)
    assert existing.simplefin_account_id == "demo-checking"
    assert existing.name == "My CSV Checking"  # not overwritten


def test_already_linked_account_syncs_without_a_review_step(client, db_session, mock_exchange, mock_sync):
    # First connect creates the link (via "new"); a second sync of the
    # same remote account should go straight through, no review step.
    connect_response = client.post("/simplefin/connect", data={"setup_token": "Zm9v"})
    remote_json = _extract_hidden_json(connect_response.text)
    client.post("/simplefin/resolve-new-accounts", data={"remote_account_json": remote_json, "choice": "new"})

    response = client.post("/simplefin/sync")
    assert response.status_code == 200
    assert "New accounts found" not in response.text
    assert "Connected" in response.text

    assert db_session.query(Account).count() == 1  # still just one


def test_sync_without_a_connection_404s(client):
    response = client.post("/simplefin/sync")
    assert response.status_code == 404


def test_connect_sync_failure_still_saves_connection(client, db_session, mock_exchange, monkeypatch):
    def fail_sync(self, start_date=None):
        raise httpx.HTTPError("network down")

    monkeypatch.setattr(SimpleFinClient, "get_accounts_and_transactions", fail_sync)

    response = client.post("/simplefin/connect", data={"setup_token": "Zm9v"})
    assert response.status_code == 200
    assert "Sync failed" in response.text
    assert db_session.query(SimplefinConnection).count() == 1


def test_access_url_never_rendered(client, db_session, mock_exchange, mock_sync):
    connect_response = client.post("/simplefin/connect", data={"setup_token": "Zm9v"})
    remote_json = _extract_hidden_json(connect_response.text)
    resolve_response = client.post(
        "/simplefin/resolve-new-accounts", data={"remote_account_json": remote_json, "choice": "new"}
    )
    for response in (connect_response, resolve_response):
        assert "demo:demo" not in response.text
        assert "bridge.example.com" not in response.text

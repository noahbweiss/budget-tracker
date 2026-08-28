"""Tests for the /simplefin router. Mocks SimpleFinClient's two network
methods (exchange_setup_token, get_accounts_and_transactions) — the
protocol assumptions they encode were verified manually against the real
demo bridge; see simplefin_client.py's docstring and
test_simplefin_client.py.
"""
import httpx
import pytest

from app.models import Account, SimplefinConnection
from app.services.simplefin_client import SimpleFinClient

FAKE_SYNC_RESPONSE = {
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
    monkeypatch.setattr(SimpleFinClient, "get_accounts_and_transactions", lambda self, start_date=None: FAKE_SYNC_RESPONSE)


def test_index_shows_connect_form_when_no_connection(client):
    response = client.get("/simplefin/")
    assert response.status_code == 200
    assert "setup_token" in response.text
    assert "Connected" not in response.text


def test_connect_saves_connection_and_runs_initial_sync(client, db_session, mock_exchange, mock_sync):
    response = client.post("/simplefin/connect", data={"setup_token": "Zm9v"})
    assert response.status_code == 200
    assert "1 account" in response.text.replace("added,", "account added,") or "account" in response.text
    assert "1 transaction" in response.text or "transaction" in response.text

    connection = db_session.query(SimplefinConnection).one()
    assert connection.access_url == "https://demo:demo@bridge.example.com/simplefin"

    account = db_session.query(Account).one()
    assert account.name == "Demo Checking"
    assert account.source == "simplefin"


def test_connect_with_bad_token_returns_400(client, db_session, monkeypatch):
    def fail(self, token):
        raise ValueError("setup token isn't valid base64")

    monkeypatch.setattr(SimpleFinClient, "exchange_setup_token", fail)

    response = client.post("/simplefin/connect", data={"setup_token": "not-valid"})
    assert response.status_code == 400
    assert db_session.query(SimplefinConnection).count() == 0


def test_index_shows_connected_status_and_linked_accounts(client, db_session, mock_exchange, mock_sync):
    client.post("/simplefin/connect", data={"setup_token": "Zm9v"})

    response = client.get("/simplefin/")
    assert response.status_code == 200
    assert "Connected" in response.text
    assert "Demo Checking" in response.text


def test_sync_updates_existing_connection(client, db_session, mock_exchange, mock_sync):
    client.post("/simplefin/connect", data={"setup_token": "Zm9v"})

    response = client.post("/simplefin/sync")
    assert response.status_code == 200
    # Second sync of the same data — the one transaction is a dup, not new.
    assert "0 transactions imported" in response.text or "transactions imported" in response.text

    assert db_session.query(Account).count() == 1  # not duplicated


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

    # Connection was still saved despite the sync failing.
    assert db_session.query(SimplefinConnection).count() == 1


def test_access_url_never_rendered(client, db_session, mock_exchange, mock_sync):
    response = client.post("/simplefin/connect", data={"setup_token": "Zm9v"})
    assert "demo:demo" not in response.text
    assert "bridge.example.com" not in response.text

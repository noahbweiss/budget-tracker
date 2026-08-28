"""Tests for app.services.simplefin_client.

Mocks httpx rather than hitting the real network — the protocol
assumptions here (plain-text claim response, embedded Basic Auth,
start-date as a unix timestamp) were verified manually against the real
SimpleFin demo bridge (beta-bridge.simplefin.org) during development;
see simplefin_client.py's module docstring. Keeping that out of the
automated suite avoids tests that are flaky/slow/dependent on an
external service staying up.
"""
import base64
from datetime import date

import httpx
import pytest

from app.services.simplefin_client import SimpleFinClient


class _FakeResponse:
    def __init__(self, text="", json_data=None, status_code=200):
        self.text = text
        self._json = json_data
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=httpx.Response(self.status_code))

    def json(self):
        return self._json


def test_exchange_setup_token_decodes_and_posts_to_claim_url(monkeypatch):
    claim_url = "https://bridge.example.com/simplefin/claim/DEMO-abc123"
    setup_token = base64.b64encode(claim_url.encode()).decode()

    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        return _FakeResponse(text="https://demo:demo@bridge.example.com/simplefin")

    monkeypatch.setattr(httpx, "post", fake_post)

    client = SimpleFinClient()
    access_url = client.exchange_setup_token(setup_token)

    assert captured["url"] == claim_url
    assert access_url == "https://demo:demo@bridge.example.com/simplefin"


def test_exchange_setup_token_rejects_invalid_base64():
    client = SimpleFinClient()
    with pytest.raises(ValueError):
        client.exchange_setup_token("not valid base64!!!")


def test_exchange_setup_token_rejects_non_url_response(monkeypatch):
    # Matches the real API's behavior for an already-claimed token: a
    # plain-text "Forbidden" body, not a URL.
    monkeypatch.setattr(httpx, "post", lambda url, **kwargs: _FakeResponse(text="Forbidden (was it already claimed?)"))

    client = SimpleFinClient()
    setup_token = base64.b64encode(b"https://bridge.example.com/claim/x").decode()
    with pytest.raises(ValueError):
        client.exchange_setup_token(setup_token)


def test_get_accounts_and_transactions_requires_access_url():
    client = SimpleFinClient(access_url=None)
    with pytest.raises(ValueError):
        client.get_accounts_and_transactions()


def test_get_accounts_and_transactions_hits_accounts_endpoint(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["params"] = kwargs.get("params")
        return _FakeResponse(json_data={"errors": [], "accounts": []})

    monkeypatch.setattr(httpx, "get", fake_get)

    client = SimpleFinClient(access_url="https://demo:demo@bridge.example.com/simplefin")
    result = client.get_accounts_and_transactions()

    assert captured["url"] == "https://demo:demo@bridge.example.com/simplefin/accounts"
    assert result == {"errors": [], "accounts": []}


def test_get_accounts_and_transactions_passes_start_date_as_unix_timestamp(monkeypatch):
    captured = {}
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: captured.update(kwargs) or _FakeResponse(json_data={}))

    client = SimpleFinClient(access_url="https://demo:demo@bridge.example.com/simplefin")
    client.get_accounts_and_transactions(start_date=date(2026, 6, 1))

    assert "start-date" in captured["params"]
    assert isinstance(captured["params"]["start-date"], int)

"""Thin client around the SimpleFin Bridge API.

Reference: https://www.simplefin.org/protocol.html — verified live
against the real demo bridge (beta-bridge.simplefin.org) rather than
implemented from memory alone. Confirmed directly:

- A "setup token" is base64 of a one-time-use claim URL. POSTing an empty
  body to that claim URL returns the permanent access URL as plain text
  (not JSON) — e.g. `https://demo:demo@bridge/simplefin`. Claiming twice
  404/403s ("was it already claimed?") — a setup token is single-use, the
  access URL is what gets stored and reused for every future sync.
- The access URL embeds HTTP Basic Auth credentials; httpx resolves
  those from the URL automatically, no extra auth wiring needed.
- GET {access_url}/accounts returns
  {"errors": [...], "accounts": [...]}. Each account has "balance"
  (string decimal, current balance as of "balance-date", a unix
  timestamp) and "transactions" (each with "id" — a real stable id, used
  directly as external_id — "posted" (unix timestamp), "amount" (string
  decimal, already signed the same way this app's Transaction.amount
  is: negative = money out), "description", and optionally "payee"/
  "memo"). Accounts can also carry "holdings" (investment positions) —
  not imported; this app tracks cash-flow transactions, a brokerage
  portfolio is a different feature not attempted here.
- Without a start-date query param, the API only returns the last day or
  so of transactions. It also caps how far back start-date can reach and
  returns a message in "errors" (not a hard failure) if you ask for more
  than it wants to give — 90 days is a hard cap, and it recommends
  staying within 45. See DEFAULT_SYNC_LOOKBACK_DAYS in simplefin_sync.py
  for why this app defaults to well under that: SimpleFin sync is for
  keeping already-imported accounts current, not for full historical
  backfill — CSV/OFX import (which has no such window) is the tool for
  that.
"""
import base64
from datetime import date, datetime, time, timezone

import httpx

_TIMEOUT = 30


class SimpleFinClient:
    def __init__(self, access_url: str | None = None):
        self.access_url = access_url

    def exchange_setup_token(self, setup_token: str) -> str:
        """Decode the base64 setup token to a claim URL, POST to it once,
        and return the permanent access URL from the plain-text response
        body.

        Raises:
            ValueError: the token isn't valid base64, or the claim
                response didn't look like a URL (e.g. an already-claimed
                token's "Forbidden" text body).
            httpx.HTTPStatusError: a non-2xx response.
        """
        try:
            claim_url = base64.b64decode(setup_token.strip(), validate=True).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("setup token isn't valid base64") from exc

        response = httpx.post(claim_url, timeout=_TIMEOUT)
        response.raise_for_status()
        access_url = response.text.strip()
        if not access_url.startswith("http"):
            raise ValueError(f"unexpected claim response (already claimed?): {access_url!r}")
        return access_url

    def get_accounts_and_transactions(self, start_date: date | None = None) -> dict:
        """GET {access_url}/accounts. Returns the parsed JSON as-is —
        app.services.simplefin_sync turns it into local Account/
        Transaction rows; this client stays a dumb transport layer.
        """
        if not self.access_url:
            raise ValueError("no access_url configured — connect a bank first")

        params = {}
        if start_date is not None:
            start_dt = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
            params["start-date"] = int(start_dt.timestamp())

        response = httpx.get(f"{self.access_url}/accounts", params=params, timeout=_TIMEOUT)
        response.raise_for_status()
        return response.json()

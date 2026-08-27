"""Thin client around the SimpleFin Bridge API.

Reference: https://www.simplefin.org/protocol.html

TODO:
  - exchange_setup_token(): POST the base64-decoded setup token URL to
    get a permanent access URL (this is the one-time exchange step).
  - get_accounts_and_transactions(): GET the access URL's /accounts
    endpoint to pull current balances + transactions.
"""
import httpx


class SimpleFinClient:
    def __init__(self, access_url: str | None = None):
        self.access_url = access_url

    def exchange_setup_token(self, setup_token: str) -> str:
        """TODO: decode the base64 setup token to get a claim URL, POST to
        it, and return the permanent access URL from the response body.
        """
        raise NotImplementedError("SimpleFin token exchange not yet implemented")

    def get_accounts_and_transactions(self) -> dict:
        """TODO: GET {access_url}/accounts and return parsed JSON."""
        if not self.access_url:
            raise ValueError("no access_url configured — connect a bank first")
        raise NotImplementedError("SimpleFin sync not yet implemented")

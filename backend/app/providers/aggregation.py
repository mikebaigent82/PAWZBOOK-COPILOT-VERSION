"""Account-aggregation provider abstraction.

The planner works fully with manual entry and CSV import. Linking accounts is
optional and goes through this interface so providers can be swapped. Bank
credentials are never seen or stored by this application: a provider's own
hosted widget collects them and hands back a revocable access token.

No provider ever returns invented balances. Without credentials the status is
simply "not connected".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import httpx

from ..config import Settings


@dataclass
class ProviderStatus:
    provider: str
    available: bool
    message: str


class AggregationProvider(Protocol):
    name: str

    def status(self) -> ProviderStatus: ...

    def create_link_token(self, user_ref: str) -> dict: ...


class NotConfigured:
    name = "none"

    def status(self) -> ProviderStatus:
        return ProviderStatus(
            "none", False,
            "Account linking is not set up. You can enter balances by hand or import a CSV file - "
            "everything in the planner works that way.")

    def create_link_token(self, user_ref: str) -> dict:
        raise RuntimeError("Account linking is not configured")


class PlaidProvider:
    """Minimal Plaid client: creates a Link token for Plaid's hosted widget.
    Token exchange and balance sync are the next step (see docs/ARCHITECTURE.md)."""

    name = "plaid"
    HOSTS = {"sandbox": "https://sandbox.plaid.com", "production": "https://production.plaid.com"}

    def __init__(self, client_id: str, secret: str, env: str):
        self.client_id, self.secret, self.env = client_id, secret, env

    def status(self) -> ProviderStatus:
        return ProviderStatus("plaid", True, f"Plaid is configured ({self.env}).")

    def create_link_token(self, user_ref: str) -> dict:
        resp = httpx.post(f"{self.HOSTS.get(self.env, self.HOSTS['sandbox'])}/link/token/create", timeout=20, json={
            "client_id": self.client_id, "secret": self.secret, "client_name": "Retirement planner",
            "user": {"client_user_id": user_ref}, "products": ["investments"], "country_codes": ["US"],
            "language": "en",
        })
        resp.raise_for_status()
        data = resp.json()
        return {"link_token": data["link_token"], "expiration": data.get("expiration")}


class StubProvider(NotConfigured):
    """Placeholder for other aggregators (for example Yodlee or MX)."""

    def __init__(self, name: str):
        self.name = name

    def status(self) -> ProviderStatus:
        return ProviderStatus(self.name, False, f"The '{self.name}' connector is not implemented yet.")


def get_provider(settings: Settings) -> AggregationProvider:
    if settings.aggregation_provider == "plaid":
        if settings.plaid_client_id and settings.plaid_secret:
            return PlaidProvider(settings.plaid_client_id, settings.plaid_secret, settings.plaid_env)
        return NotConfigured()
    if settings.aggregation_provider not in ("none", ""):
        return StubProvider(settings.aggregation_provider)
    return NotConfigured()

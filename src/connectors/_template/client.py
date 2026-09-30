"""HTTP client for this source.

A real connector builds a ``SourceClient`` with the source's documented rate
limit and reads its API key from an environment variable (never a literal). The
template has no live source, so it only offers the recorded-fixture client.
"""

from __future__ import annotations

from pathlib import Path

from src.connectors.env import ConfigurationError
from src.connectors.http import SourceClient, build_user_agent, fixture_transport

SOURCE = "template_demo"
FIXTURES = Path(__file__).parent / "fixtures"


def build_client(*, fixture_mode: bool) -> SourceClient:
    if not fixture_mode:
        raise ConfigurationError("the template connector has no live source; use fixture mode")
    routes = {"tract_values.csv": (FIXTURES / "tract_values.csv").read_bytes()}
    return SourceClient(
        SOURCE,
        user_agent=build_user_agent(contact="fixture-mode"),
        transport=fixture_transport(routes),
        min_interval_s=0,
        sleep=lambda _seconds: None,
    )

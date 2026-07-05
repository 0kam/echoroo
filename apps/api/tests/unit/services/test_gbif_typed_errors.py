"""Unit tests for typed GBIF upstream-failure errors (SFR-3).

The batch/resolution paths (``resolve_taxon`` / ``get_vernacular_names``) must
distinguish a genuine "no match" (successful GBIF response with zero results)
from an upstream outage (transport error / timeout / HTTP 5xx). The former
returns ``None`` / ``[]``; the latter raises :class:`GBIFUnavailableError` so a
GBIF outage can no longer masquerade as a legitimate empty result.

All external HTTP is faked; no live network is used and the rate limiter is a
no-op so tests stay fast.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from echoroo.core.exceptions import ExternalServiceError, GBIFUnavailableError
from echoroo.services import gbif as gbif_module
from echoroo.services.gbif import GBIFService


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _acquire(self: Any) -> None:
        return None

    monkeypatch.setattr(gbif_module.RateLimiter, "acquire", _acquire)


class _OkResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _EmptyClient:
    """Returns a successful response carrying an explicit empty match."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def __call__(self, *args: Any, **kwargs: Any) -> _EmptyClient:
        return self

    async def __aenter__(self) -> _EmptyClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def get(self, url: str, params: dict[str, Any] | None = None) -> _OkResponse:
        return _OkResponse(self._payload)


class _FailingClient:
    """Simulates an upstream failure on every GET.

    ``mode="status"`` raises :class:`httpx.HTTPStatusError` (a 5xx);
    ``mode="request"`` raises :class:`httpx.RequestError` (transport/timeout).
    """

    def __init__(self, mode: str) -> None:
        self._mode = mode

    def __call__(self, *args: Any, **kwargs: Any) -> _FailingClient:
        return self

    async def __aenter__(self) -> _FailingClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        request = httpx.Request("GET", url)
        if self._mode == "status":
            response = httpx.Response(503, request=request)
            raise httpx.HTTPStatusError(
                "Service Unavailable", request=request, response=response
            )
        raise httpx.ConnectTimeout("upstream timed out", request=request)


def _install(monkeypatch: pytest.MonkeyPatch, client: Any) -> None:
    monkeypatch.setattr(gbif_module.httpx, "AsyncClient", client)


# ---------------------------------------------------------------------------
# resolve_taxon
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_taxon_returns_none_on_legit_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, _EmptyClient({"matchType": "NONE"}))
    svc = GBIFService()
    assert await svc.resolve_taxon("Nonexistent species") is None


@pytest.mark.asyncio
async def test_resolve_taxon_raises_on_http_5xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, _FailingClient("status"))
    svc = GBIFService()
    with pytest.raises(GBIFUnavailableError):
        await svc.resolve_taxon("Parus major")


@pytest.mark.asyncio
async def test_resolve_taxon_raises_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, _FailingClient("request"))
    svc = GBIFService()
    with pytest.raises(GBIFUnavailableError) as exc_info:
        await svc.resolve_taxon("Parus major")
    # GBIFUnavailableError is a subtype of the generic ExternalServiceError and
    # surfaces as 502 at the API boundary.
    assert isinstance(exc_info.value, ExternalServiceError)
    assert exc_info.value.status_code == 502


# ---------------------------------------------------------------------------
# get_vernacular_names
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_vernacular_names_returns_empty_on_legit_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, _EmptyClient({"results": []}))
    svc = GBIFService()
    assert await svc.get_vernacular_names(12345) == []


@pytest.mark.asyncio
async def test_get_vernacular_names_raises_on_http_5xx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, _FailingClient("status"))
    svc = GBIFService()
    with pytest.raises(GBIFUnavailableError):
        await svc.get_vernacular_names(12345)


@pytest.mark.asyncio
async def test_get_vernacular_names_raises_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, _FailingClient("request"))
    svc = GBIFService()
    with pytest.raises(GBIFUnavailableError):
        await svc.get_vernacular_names(12345)

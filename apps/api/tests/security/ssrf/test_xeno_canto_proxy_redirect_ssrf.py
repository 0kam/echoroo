"""Phase 17 A-10 (Codex Major 3): redirect SSRF on the Xeno-canto sonogram proxy.

The sonogram proxy validates the user-supplied URL against an allowlist, but
prior to this fix it called ``httpx.AsyncClient(follow_redirects=True)``, so
an open redirect on the allowed host (``xeno-canto.org``) could ship the
backend a ``Location`` header pointing at an internal address (e.g.
``http://169.254.169.254/`` AWS metadata or RFC-1918 ranges).  The
``Location`` was never re-validated.

This module verifies the post-fix behaviour:

  1. Initial allowlist + DNS guard rejects literal-IP / private-host URLs.
  2. ``follow_redirects=False`` is in force — redirects are handled manually.
  3. Each ``Location`` is ``urljoin``-ed and re-validated; private-IP targets
     are refused with HTTP 502.
  4. Open redirect from ``xeno-canto.org`` to AWS metadata / RFC-1918 / link-
     local hosts is rejected.
  5. Legitimate intra-host redirect (xeno-canto.org/foo -> /bar) is followed.
  6. A redirect chain longer than ``_SONOGRAM_MAX_REDIRECTS`` is refused.

The tests drive the route handler coroutine directly, monkeypatching
``socket.getaddrinfo`` (so DNS does not leak into CI) and stubbing
``httpx.AsyncClient`` to return scripted responses without opening a socket.

Shim: OFF — coroutine-level unit tests, no HTTP transport.
"""

from __future__ import annotations

import socket
from collections.abc import Iterable
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from echoroo.api.v1 import xeno_canto as xc_module


# ---------------------------------------------------------------------------
# DNS + httpx stubs
# ---------------------------------------------------------------------------


def _public_addr_info(host: str, _port: int | None = None) -> list[tuple[Any, ...]]:
    """Return a fake getaddrinfo result with a single public IPv4 address.

    8.8.8.8 (Google Public DNS) is a real-world public IP whose
    ``ipaddress`` membership predicates (``is_private`` / ``is_reserved``
    / ``is_loopback`` / ``is_link_local`` / ``is_multicast``) all return
    False, so the validator's post-resolve guard treats it as routable.
    TEST-NET ranges (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24) are
    flagged ``is_reserved=True`` by Python and would be rejected.
    """
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 0))]


def _private_addr_info(host: str, _port: int | None = None) -> list[tuple[Any, ...]]:
    """Return a fake getaddrinfo result resolving to a loopback address."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0))]


class _StubResponse:
    """Minimal stand-in for ``httpx.Response`` used by the redirect loop."""

    def __init__(
        self,
        status_code: int,
        *,
        content: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}


class _ScriptedClient:
    """Async-context-manager stub returning queued responses in order."""

    def __init__(self, script: list[_StubResponse]) -> None:
        self._script = list(script)
        self.calls: list[str] = []

    async def __aenter__(self) -> "_ScriptedClient":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        return None

    async def get(self, url: str, headers: dict[str, str] | None = None) -> _StubResponse:
        self.calls.append(url)
        if not self._script:
            raise AssertionError(f"Unexpected GET to {url!r} — script exhausted")
        return self._script.pop(0)


def _patch_httpx(
    monkeypatch: pytest.MonkeyPatch, script: Iterable[_StubResponse]
) -> _ScriptedClient:
    client = _ScriptedClient(list(script))

    def _factory(*_args: object, **_kwargs: object) -> _ScriptedClient:
        # Capture follow_redirects to ensure the production code is requesting
        # manual redirect handling.
        assert _kwargs.get("follow_redirects") is False, (
            "sonogram proxy must use follow_redirects=False"
        )
        return client

    monkeypatch.setattr(xc_module.httpx, "AsyncClient", _factory)
    return client


# ---------------------------------------------------------------------------
# Section 1: initial-URL guard (sanity coverage for the new helper)
# ---------------------------------------------------------------------------


def test_validate_sonogram_url_rejects_non_https() -> None:
    with pytest.raises(HTTPException) as excinfo:
        xc_module._validate_sonogram_url("http://xeno-canto.org/foo.png")
    assert excinfo.value.status_code == 400


def test_validate_sonogram_url_rejects_off_allowlist_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _public_addr_info)
    with pytest.raises(HTTPException) as excinfo:
        xc_module._validate_sonogram_url("https://evil.example.com/foo.png")
    assert excinfo.value.status_code == 400


def test_validate_sonogram_url_rejects_literal_loopback_ip() -> None:
    # Literal IP host is rejected before DNS even runs.
    with pytest.raises(HTTPException):
        xc_module._validate_sonogram_url("https://127.0.0.1/foo.png")


def test_validate_sonogram_url_rejects_dns_pointing_at_private_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _private_addr_info)
    with pytest.raises(HTTPException) as excinfo:
        xc_module._validate_sonogram_url("https://xeno-canto.org/foo.png")
    assert excinfo.value.status_code == 400


def test_validate_sonogram_url_accepts_public_xc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(socket, "getaddrinfo", _public_addr_info)
    # Should not raise.
    xc_module._validate_sonogram_url("https://xeno-canto.org/some/sonogram.png")


# ---------------------------------------------------------------------------
# Section 2: redirect SSRF behaviour (Codex Major 3 fix)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_proxy_sonogram_uses_follow_redirects_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A direct 200 response must be served without httpx-side redirect chasing."""
    monkeypatch.setattr(socket, "getaddrinfo", _public_addr_info)
    client = _patch_httpx(
        monkeypatch,
        [
            _StubResponse(
                200,
                content=b"\x89PNG\r\n",
                headers={"content-type": "image/png"},
            )
        ],
    )
    resp = await xc_module.proxy_sonogram(
        project_id=uuid4(),
        url="https://xeno-canto.org/foo.png",
    )
    # FastAPI Response object — verify body and content type were forwarded.
    assert resp.body == b"\x89PNG\r\n"
    assert resp.media_type == "image/png"
    assert client.calls == ["https://xeno-canto.org/foo.png"]


@pytest.mark.asyncio
async def test_proxy_sonogram_rejects_redirect_to_aws_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Open redirect from xeno-canto.org -> 169.254.169.254 must 502."""
    monkeypatch.setattr(socket, "getaddrinfo", _public_addr_info)
    _patch_httpx(
        monkeypatch,
        [
            _StubResponse(
                302,
                headers={"location": "http://169.254.169.254/latest/meta-data/"},
            ),
        ],
    )
    with pytest.raises(HTTPException) as excinfo:
        await xc_module.proxy_sonogram(
            project_id=uuid4(),
            url="https://xeno-canto.org/foo.png",
        )
    assert excinfo.value.status_code == 502


@pytest.mark.asyncio
async def test_proxy_sonogram_rejects_redirect_to_private_ip_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Open redirect from xeno-canto.org -> RFC-1918 IP literal must 502."""
    monkeypatch.setattr(socket, "getaddrinfo", _public_addr_info)
    _patch_httpx(
        monkeypatch,
        [
            _StubResponse(
                301,
                headers={"location": "https://10.0.0.5/internal"},
            ),
        ],
    )
    with pytest.raises(HTTPException) as excinfo:
        await xc_module.proxy_sonogram(
            project_id=uuid4(),
            url="https://xeno-canto.org/foo.png",
        )
    assert excinfo.value.status_code == 502


@pytest.mark.asyncio
async def test_proxy_sonogram_rejects_redirect_when_dns_resolves_to_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A redirect to an allowed host whose DNS now points at a loopback IP must 502."""
    # Initial validation: getaddrinfo returns public.
    # Second validation (after redirect): getaddrinfo returns loopback.
    call_state: dict[str, int] = {"n": 0}

    def _alternating_addr_info(
        host: str, port: int | None = None
    ) -> list[tuple[Any, ...]]:
        call_state["n"] += 1
        if call_state["n"] == 1:
            return _public_addr_info(host, port)
        return _private_addr_info(host, port)

    monkeypatch.setattr(socket, "getaddrinfo", _alternating_addr_info)
    _patch_httpx(
        monkeypatch,
        [
            _StubResponse(
                302,
                headers={"location": "https://xeno-canto.org/redir-target.png"},
            ),
        ],
    )
    with pytest.raises(HTTPException) as excinfo:
        await xc_module.proxy_sonogram(
            project_id=uuid4(),
            url="https://xeno-canto.org/foo.png",
        )
    assert excinfo.value.status_code == 502


@pytest.mark.asyncio
async def test_proxy_sonogram_follows_legitimate_intrahost_redirect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """xeno-canto.org/foo -> xeno-canto.org/bar must be followed and served."""
    monkeypatch.setattr(socket, "getaddrinfo", _public_addr_info)
    client = _patch_httpx(
        monkeypatch,
        [
            _StubResponse(302, headers={"location": "/bar.png"}),
            _StubResponse(
                200,
                content=b"PNGDATA",
                headers={"content-type": "image/png"},
            ),
        ],
    )
    resp = await xc_module.proxy_sonogram(
        project_id=uuid4(),
        url="https://xeno-canto.org/foo.png",
    )
    assert resp.body == b"PNGDATA"
    # urljoin('https://xeno-canto.org/foo.png', '/bar.png')
    assert client.calls == [
        "https://xeno-canto.org/foo.png",
        "https://xeno-canto.org/bar.png",
    ]


@pytest.mark.asyncio
async def test_proxy_sonogram_rejects_excessive_redirect_depth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A redirect chain longer than ``_SONOGRAM_MAX_REDIRECTS`` must 502."""
    monkeypatch.setattr(socket, "getaddrinfo", _public_addr_info)
    # Build _SONOGRAM_MAX_REDIRECTS + 1 redirects, all to legitimate hosts.
    chain_depth = xc_module._SONOGRAM_MAX_REDIRECTS + 1
    script = [
        _StubResponse(302, headers={"location": f"/hop-{i}.png"})
        for i in range(chain_depth)
    ]
    _patch_httpx(monkeypatch, script)

    with pytest.raises(HTTPException) as excinfo:
        await xc_module.proxy_sonogram(
            project_id=uuid4(),
            url="https://xeno-canto.org/foo.png",
        )
    assert excinfo.value.status_code == 502


@pytest.mark.asyncio
async def test_proxy_sonogram_rejects_redirect_without_location_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 3xx response missing a Location header must 502."""
    monkeypatch.setattr(socket, "getaddrinfo", _public_addr_info)
    _patch_httpx(monkeypatch, [_StubResponse(301, headers={})])

    with pytest.raises(HTTPException) as excinfo:
        await xc_module.proxy_sonogram(
            project_id=uuid4(),
            url="https://xeno-canto.org/foo.png",
        )
    assert excinfo.value.status_code == 502


# ---------------------------------------------------------------------------
# Section 3: source-level invariant — follow_redirects=False string present
# ---------------------------------------------------------------------------


def test_sonogram_proxy_source_disables_httpx_redirects() -> None:
    """Static guard: production code must opt out of httpx auto-follow."""
    import inspect

    src = inspect.getsource(xc_module.proxy_sonogram)
    assert "follow_redirects=False" in src, (
        "proxy_sonogram must call httpx.AsyncClient(follow_redirects=False) so "
        "redirects are validated through _validate_sonogram_url instead of "
        "being silently chased."
    )


__all__ = [
    "test_proxy_sonogram_follows_legitimate_intrahost_redirect",
    "test_proxy_sonogram_rejects_excessive_redirect_depth",
    "test_proxy_sonogram_rejects_redirect_to_aws_metadata",
    "test_proxy_sonogram_rejects_redirect_to_private_ip_host",
    "test_proxy_sonogram_rejects_redirect_when_dns_resolves_to_private",
    "test_proxy_sonogram_rejects_redirect_without_location_header",
    "test_proxy_sonogram_uses_follow_redirects_false",
    "test_sonogram_proxy_source_disables_httpx_redirects",
    "test_validate_sonogram_url_accepts_public_xc",
    "test_validate_sonogram_url_rejects_dns_pointing_at_private_ip",
    "test_validate_sonogram_url_rejects_literal_loopback_ip",
    "test_validate_sonogram_url_rejects_non_https",
    "test_validate_sonogram_url_rejects_off_allowlist_host",
]

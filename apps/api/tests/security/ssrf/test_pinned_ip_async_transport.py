"""Unit tests for PinnedIPAsyncTransport.handle_async_request().

Verifies that:
  - The connect URL is rewritten to the pinned IP literal.
  - The ``Host`` header is preserved as the original hostname.
  - ``request.extensions["sni_hostname"]`` is set to the original hostname.
  - Cross-host redirects are rejected with SSRFGuardError.
  - Requests to non-allowlisted hosts are rejected.
  - Construction with a private IP is rejected immediately.

No real network I/O — the inner transport is replaced with a fake
synchronous-response stub so these tests run without internet access.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from echoroo.core.url_allowlist import PinnedIPAsyncTransport, SSRFGuardError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(
    url: str,
    *,
    method: str = "GET",
    extensions: dict[str, Any] | None = None,
) -> httpx.Request:
    """Build an httpx.Request suitable for passing to handle_async_request."""
    req = httpx.Request(method, url, extensions=extensions or {})
    # httpx lazily creates the stream; attach a no-op one so the transport
    # can copy it without error.
    req.stream = MagicMock()  # type: ignore[assignment]
    return req


def _fake_inner_transport() -> tuple[httpx.AsyncBaseTransport, list[httpx.Request]]:
    """Return a fake inner transport and a list that collects rewritten requests."""
    captured: list[httpx.Request] = []

    async def _handle(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(200)

    transport = AsyncMock(spec=httpx.AsyncBaseTransport)
    transport.handle_async_request.side_effect = _handle
    return transport, captured


# ---------------------------------------------------------------------------
# Construction-time validation
# ---------------------------------------------------------------------------


def test_pinned_transport_rejects_private_ip_at_construction() -> None:
    """Building a PinnedIPAsyncTransport with a private/loopback IP must raise."""
    for private_ip in ("127.0.0.1", "10.0.0.1", "192.168.1.1", "169.254.169.254"):
        with pytest.raises(SSRFGuardError, match="non-routable"):
            PinnedIPAsyncTransport(
                pinned_host="xeno-canto.org",
                pinned_ip=private_ip,
            )


# ---------------------------------------------------------------------------
# URL rewrite
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_async_request_rewrites_url_to_pinned_ip() -> None:
    """handle_async_request must replace the URL host with the pinned IP."""
    public_ip = "8.8.8.42"  # TEST-NET-3 (documentation range — publicly routable)
    inner, captured = _fake_inner_transport()

    transport = PinnedIPAsyncTransport(
        pinned_host="xeno-canto.org",
        pinned_ip=public_ip,
        allowed_hosts=frozenset({"xeno-canto.org"}),
    )
    transport._inner = inner  # type: ignore[assignment]

    req = _make_request("https://xeno-canto.org/api/3/recordings?query=owl")
    await transport.handle_async_request(req)

    assert len(captured) == 1
    rewritten = captured[0]
    assert rewritten.url.host == public_ip, (
        f"URL host should be the pinned IP {public_ip!r}, got {rewritten.url.host!r}"
    )


@pytest.mark.asyncio
async def test_handle_async_request_rewrites_ipv6_url() -> None:
    """IPv6 pinned IPs are wrapped in square brackets in the rewritten URL host."""
    public_ipv6 = "2606:4700::1111"  # Cloudflare public DNS (routable IPv6)
    inner, captured = _fake_inner_transport()

    transport = PinnedIPAsyncTransport(
        pinned_host="xeno-canto.org",
        pinned_ip=public_ipv6,
        allowed_hosts=frozenset({"xeno-canto.org"}),
    )
    transport._inner = inner  # type: ignore[assignment]

    req = _make_request("https://xeno-canto.org/sounds/spectrogram/1234.png")
    await transport.handle_async_request(req)

    assert len(captured) == 1
    # httpx normalises the host; verify it contains the IPv6 literal
    rewritten_host = captured[0].url.host
    assert "2606:4700::1111" in rewritten_host, (
        f"IPv6 host should appear in the rewritten URL, got {rewritten_host!r}"
    )


# ---------------------------------------------------------------------------
# Host header preservation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_async_request_preserves_host_header() -> None:
    """The ``Host`` header must equal the *original* hostname, not the IP."""
    public_ip = "8.8.8.7"
    inner, captured = _fake_inner_transport()

    transport = PinnedIPAsyncTransport(
        pinned_host="xeno-canto.org",
        pinned_ip=public_ip,
        allowed_hosts=frozenset({"xeno-canto.org"}),
    )
    transport._inner = inner  # type: ignore[assignment]

    req = _make_request("https://xeno-canto.org/sounds/spectrogram/42.png")
    await transport.handle_async_request(req)

    rewritten = captured[0]
    host_header = rewritten.headers.get("host", "")
    assert host_header == "xeno-canto.org", (
        f"Host header should be 'xeno-canto.org', got {host_header!r}"
    )


@pytest.mark.asyncio
async def test_handle_async_request_preserves_host_header_with_port() -> None:
    """Port is appended to the Host header only when present in the original URL."""
    public_ip = "8.8.8.7"
    inner, captured = _fake_inner_transport()

    transport = PinnedIPAsyncTransport(
        pinned_host="xeno-canto.org",
        pinned_ip=public_ip,
        allowed_hosts=frozenset({"xeno-canto.org"}),
    )
    transport._inner = inner  # type: ignore[assignment]

    req = _make_request("https://xeno-canto.org:8443/sounds/spectrogram/99.png")
    await transport.handle_async_request(req)

    rewritten = captured[0]
    host_header = rewritten.headers.get("host", "")
    assert "xeno-canto.org" in host_header, (
        f"Host header should contain 'xeno-canto.org', got {host_header!r}"
    )
    assert "8443" in host_header, (
        f"Host header should include port 8443, got {host_header!r}"
    )


# ---------------------------------------------------------------------------
# SNI hostname
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_async_request_sets_sni_hostname() -> None:
    """extensions['sni_hostname'] must be the original hostname for TLS cert validation."""
    public_ip = "8.8.8.5"
    inner, captured = _fake_inner_transport()

    transport = PinnedIPAsyncTransport(
        pinned_host="xeno-canto.org",
        pinned_ip=public_ip,
        allowed_hosts=frozenset({"xeno-canto.org"}),
    )
    transport._inner = inner  # type: ignore[assignment]

    req = _make_request("https://xeno-canto.org/sounds/spectrogram/7.png")
    await transport.handle_async_request(req)

    rewritten = captured[0]
    sni = rewritten.extensions.get("sni_hostname")
    assert sni == "xeno-canto.org", (
        f"sni_hostname extension should be 'xeno-canto.org', got {sni!r}"
    )


# ---------------------------------------------------------------------------
# Cross-host redirect rejection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_async_request_rejects_cross_host_redirect() -> None:
    """A request whose host differs from the pinned host must raise SSRFGuardError."""
    public_ip = "8.8.8.5"
    inner, _ = _fake_inner_transport()

    transport = PinnedIPAsyncTransport(
        pinned_host="xeno-canto.org",
        pinned_ip=public_ip,
        allowed_hosts=frozenset({"xeno-canto.org", "evil.example.com"}),
    )
    transport._inner = inner  # type: ignore[assignment]

    # Simulate a redirect that landed on a different host (even if it's
    # in the general allowlist).
    req = _make_request("https://evil.example.com/steal?q=data")
    with pytest.raises(SSRFGuardError, match="pinned hostname"):
        await transport.handle_async_request(req)


# ---------------------------------------------------------------------------
# Non-allowlisted host rejection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_async_request_rejects_non_allowlisted_host() -> None:
    """Requests to hosts not in allowed_hosts must raise SSRFGuardError."""
    public_ip = "8.8.8.99"
    inner, _ = _fake_inner_transport()

    transport = PinnedIPAsyncTransport(
        pinned_host="xeno-canto.org",
        pinned_ip=public_ip,
        allowed_hosts=frozenset({"xeno-canto.org"}),
    )
    transport._inner = inner  # type: ignore[assignment]

    req = _make_request("https://attacker.example.com/payload")
    with pytest.raises(SSRFGuardError, match="allowlist"):
        await transport.handle_async_request(req)


# ---------------------------------------------------------------------------
# Scheme rejection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_async_request_rejects_non_https_scheme() -> None:
    """Non http/https schemes must be rejected by handle_async_request."""
    public_ip = "8.8.8.1"
    inner, _ = _fake_inner_transport()

    transport = PinnedIPAsyncTransport(
        pinned_host="xeno-canto.org",
        pinned_ip=public_ip,
        allowed_hosts=frozenset({"xeno-canto.org"}),
    )
    transport._inner = inner  # type: ignore[assignment]

    # ftp:// scheme — not in ALLOWED_SCHEMES
    req = _make_request("ftp://xeno-canto.org/sounds/spectrogram/1.png")
    with pytest.raises(SSRFGuardError, match="scheme"):
        await transport.handle_async_request(req)

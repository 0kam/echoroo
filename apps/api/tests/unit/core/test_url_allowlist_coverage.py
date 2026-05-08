"""Unit tests targeting specific coverage gaps in echoroo.core.url_allowlist.

Targets uncovered lines reported at 83% coverage:
  - Lines 133-134: socket.gaierror in _resolve_host
  - Lines 140-142: IPv6 AF_INET6 branch in the address loop
  - Line 144: no addresses returned after resolution
  - Lines 204-205: scheme_not_allowed in validate_audio_url
  - Lines 209-210: missing_host in validate_audio_url
  - Lines 219-220: host_is_ip_literal reject
  - Lines 231-233: dns_resolution_failed audit + re-raise
  - Lines 257-261: is_allowed_audio_url returns False (exception path)
  - Line 352: PinnedIPAsyncTransport.aclose()

These are pure unit tests — no DB, no network.
"""

from __future__ import annotations

import ipaddress
import socket
from unittest.mock import AsyncMock, patch

import pytest

from echoroo.core.url_allowlist import (
    PinnedIPAsyncTransport,
    SSRFGuardError,
    _is_blocked_ip,
    _resolve_host,
    is_allowed_audio_url,
    validate_audio_url,
)

# ---------------------------------------------------------------------------
# _is_blocked_ip — IPv6 reserved ranges (branch coverage)
# ---------------------------------------------------------------------------


def test_is_blocked_ip_ipv6_loopback() -> None:
    """::1 (IPv6 loopback) must be blocked."""
    assert _is_blocked_ip(ipaddress.IPv6Address("::1")) is True


def test_is_blocked_ip_ipv6_link_local() -> None:
    """fe80:: (IPv6 link-local) must be blocked."""
    assert _is_blocked_ip(ipaddress.IPv6Address("fe80::1")) is True


def test_is_blocked_ip_ipv6_ula() -> None:
    """fd00:: (IPv6 ULA / private) must be blocked."""
    assert _is_blocked_ip(ipaddress.IPv6Address("fd00::1")) is True


def test_is_blocked_ip_ipv6_multicast() -> None:
    """ff02:: (IPv6 multicast) must be blocked."""
    assert _is_blocked_ip(ipaddress.IPv6Address("ff02::1")) is True


def test_is_blocked_ip_ipv6_unspecified() -> None:
    """:: (IPv6 unspecified) must be blocked."""
    assert _is_blocked_ip(ipaddress.IPv6Address("::")) is True


def test_is_blocked_ip_ipv6_public_returns_false() -> None:
    """2606:4700::1111 (Cloudflare public) must NOT be blocked."""
    assert _is_blocked_ip(ipaddress.IPv6Address("2606:4700::1111")) is False


# ---------------------------------------------------------------------------
# _resolve_host — error paths
# ---------------------------------------------------------------------------


def test_resolve_host_gaierror_raises_ssrf_guard_error() -> None:
    """socket.gaierror must be converted to SSRFGuardError (lines 133-134)."""
    with patch(
        "echoroo.core.url_allowlist.socket.getaddrinfo",
        side_effect=socket.gaierror("Name or service not known"),
    ), pytest.raises(SSRFGuardError, match="could not be resolved"):
        _resolve_host("nonexistent.example.invalid")


def test_resolve_host_ipv6_af_inet6_branch() -> None:
    """AF_INET6 entries must be parsed to IPv6Address (lines 140-142)."""
    # Inject a fake AF_INET6 response (4-tuple: host, port, flowinfo, scopeid)
    public_ipv6 = "2606:4700::1111"
    fake_results = [
        (
            socket.AF_INET6,
            socket.SOCK_STREAM,
            0,
            "",
            (public_ipv6, 0, 0, 0),  # (host, port, flowinfo, scopeid)
        )
    ]
    with patch(
        "echoroo.core.url_allowlist.socket.getaddrinfo",
        return_value=fake_results,
    ):
        addrs = _resolve_host("some-host.example.com")
    assert len(addrs) == 1
    assert isinstance(addrs[0], ipaddress.IPv6Address)
    assert str(addrs[0]) == public_ipv6


def test_resolve_host_empty_results_raises_ssrf_guard_error() -> None:
    """DNS returning no AF_INET/AF_INET6 entries must raise SSRFGuardError (line 144)."""
    # Return a result with an unknown family so no addresses are collected
    fake_results = [
        (socket.AF_UNSPEC, socket.SOCK_STREAM, 0, "", ("", 0))
    ]
    with patch(
        "echoroo.core.url_allowlist.socket.getaddrinfo",
        return_value=fake_results,
    ), pytest.raises(SSRFGuardError, match="produced no addresses"):
        _resolve_host("weird-host.example.com")


# ---------------------------------------------------------------------------
# validate_audio_url — scheme checks (lines 204-205)
# ---------------------------------------------------------------------------


def test_validate_audio_url_rejects_ftp_scheme() -> None:
    """ftp:// scheme must be rejected with scheme_not_allowed (lines 204-205)."""
    with pytest.raises(SSRFGuardError, match="scheme not allowed"):
        validate_audio_url(
            "ftp://xeno-canto.org/file.mp3",
            allowed_hosts=frozenset({"xeno-canto.org"}),
        )


def test_validate_audio_url_rejects_javascript_scheme() -> None:
    """javascript: scheme must be rejected (lines 204-205)."""
    with pytest.raises(SSRFGuardError, match="scheme not allowed"):
        validate_audio_url(
            "javascript:alert(1)",
            allowed_hosts=frozenset({"xeno-canto.org"}),
        )


def test_validate_audio_url_rejects_empty_scheme() -> None:
    """No scheme (bare hostname) must be rejected (lines 204-205)."""
    with pytest.raises(SSRFGuardError, match="scheme not allowed"):
        validate_audio_url(
            "xeno-canto.org/sounds/foo.mp3",
            allowed_hosts=frozenset({"xeno-canto.org"}),
        )


# ---------------------------------------------------------------------------
# validate_audio_url — missing host (lines 209-210)
# ---------------------------------------------------------------------------


def test_validate_audio_url_rejects_url_with_no_host() -> None:
    """URL with http scheme but no host component must be rejected (lines 209-210)."""
    # urlparse("http:///path") → scheme="http", hostname=None
    with pytest.raises(SSRFGuardError, match="no host component"):
        validate_audio_url(
            "http:///some/path",
            allowed_hosts=frozenset({"xeno-canto.org"}),
        )


# ---------------------------------------------------------------------------
# validate_audio_url — IP literal as host (lines 219-220)
# ---------------------------------------------------------------------------


def test_validate_audio_url_rejects_ipv4_literal_as_host() -> None:
    """IPv4 literal in URL host must be rejected (lines 219-220)."""
    with pytest.raises(SSRFGuardError, match="named host"):
        validate_audio_url(
            "https://8.8.8.8/some/file.mp3",
            allowed_hosts=frozenset({"xeno-canto.org"}),
        )


def test_validate_audio_url_rejects_ipv6_literal_as_host() -> None:
    """IPv6 literal in URL host must be rejected (lines 219-220)."""
    with pytest.raises(SSRFGuardError, match="named host"):
        validate_audio_url(
            "https://[2606:4700::1111]/some/file.mp3",
            allowed_hosts=frozenset({"xeno-canto.org"}),
        )


def test_validate_audio_url_rejects_private_ipv4_literal() -> None:
    """Private IPv4 literal in URL host must be rejected (lines 219-220)."""
    with pytest.raises(SSRFGuardError, match="named host"):
        validate_audio_url(
            "https://192.168.1.1/admin",
            allowed_hosts=frozenset({"xeno-canto.org"}),
        )


# ---------------------------------------------------------------------------
# validate_audio_url — DNS resolution failure → audit + re-raise (lines 231-233)
# ---------------------------------------------------------------------------


def test_validate_audio_url_dns_failure_raises_ssrf_guard_error() -> None:
    """DNS failure during validate_audio_url must be audited and re-raised (lines 231-233)."""
    with patch(
        "echoroo.core.url_allowlist.socket.getaddrinfo",
        side_effect=socket.gaierror("NXDOMAIN"),
    ), pytest.raises(SSRFGuardError, match="could not be resolved"):
        validate_audio_url(
            "https://xeno-canto.org/file.mp3",
            allowed_hosts=frozenset({"xeno-canto.org"}),
        )


# ---------------------------------------------------------------------------
# is_allowed_audio_url — boolean wrapper returning False (lines 257-261)
# ---------------------------------------------------------------------------


def test_is_allowed_audio_url_returns_false_for_invalid_scheme() -> None:
    """is_allowed_audio_url returns False when validate_audio_url raises (lines 257-261)."""
    result = is_allowed_audio_url(
        "ftp://xeno-canto.org/file.mp3",
        allowed_hosts=frozenset({"xeno-canto.org"}),
    )
    assert result is False


def test_is_allowed_audio_url_returns_false_for_disallowed_host() -> None:
    """is_allowed_audio_url returns False for disallowed host (lines 257-261)."""
    result = is_allowed_audio_url(
        "https://evil.example.com/file.mp3",
        allowed_hosts=frozenset({"xeno-canto.org"}),
    )
    assert result is False


def test_is_allowed_audio_url_returns_false_for_ip_literal() -> None:
    """is_allowed_audio_url returns False for IP literal as host (lines 257-261)."""
    result = is_allowed_audio_url(
        "https://8.8.8.8/file.mp3",
        allowed_hosts=frozenset({"xeno-canto.org"}),
    )
    assert result is False


def test_is_allowed_audio_url_returns_true_for_valid_url() -> None:
    """is_allowed_audio_url returns True when validation passes."""
    public_ip = "8.8.8.8"
    with patch(
        "echoroo.core.url_allowlist.socket.getaddrinfo",
        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 0, "", (public_ip, 0))],
    ):
        result = is_allowed_audio_url(
            "https://xeno-canto.org/file.mp3",
            allowed_hosts=frozenset({"xeno-canto.org"}),
        )
    assert result is True


# ---------------------------------------------------------------------------
# PinnedIPAsyncTransport.aclose() — line 352
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pinned_transport_aclose_delegates_to_inner() -> None:
    """aclose() must call the inner transport's aclose() (line 352)."""
    transport = PinnedIPAsyncTransport(
        pinned_host="xeno-canto.org",
        pinned_ip="8.8.8.8",
        allowed_hosts=frozenset({"xeno-canto.org"}),
    )
    mock_inner = AsyncMock()
    transport._inner = mock_inner  # type: ignore[assignment]

    await transport.aclose()

    mock_inner.aclose.assert_called_once()


@pytest.mark.asyncio
async def test_pinned_transport_context_manager_aenter_aexit() -> None:
    """__aenter__/__aexit__ must delegate to inner transport."""
    transport = PinnedIPAsyncTransport(
        pinned_host="xeno-canto.org",
        pinned_ip="8.8.8.8",
        allowed_hosts=frozenset({"xeno-canto.org"}),
    )
    mock_inner = AsyncMock()
    transport._inner = mock_inner  # type: ignore[assignment]

    async with transport:
        pass

    mock_inner.__aenter__.assert_called_once()
    mock_inner.__aexit__.assert_called_once()


# ---------------------------------------------------------------------------
# validate_audio_url — IPv6 pinned fallback (no IPv4 in results)
# ---------------------------------------------------------------------------


def test_validate_audio_url_pins_ipv6_when_no_ipv4() -> None:
    """When DNS only returns IPv6 addresses, pin to the first IPv6 address."""
    public_ipv6 = "2606:4700::1111"
    with patch(
        "echoroo.core.url_allowlist.socket.getaddrinfo",
        return_value=[
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", (public_ipv6, 0, 0, 0))
        ],
    ):
        _url, pinned = validate_audio_url(
            "https://xeno-canto.org/file.mp3",
            allowed_hosts=frozenset({"xeno-canto.org"}),
        )
    assert pinned == public_ipv6


# ---------------------------------------------------------------------------
# PinnedIPAsyncTransport.handle_async_request — DNS rebinding / cross-host
# defences. These exercise the request-time guards that protect against a
# rebinding attack flipping the resolved IP between validation and connect:
# the transport refuses to issue any request whose host does not match the
# pinned hostname, refuses non-allowed schemes, and refuses non-allowlisted
# hosts. The caller is responsible for re-validating redirect Location URLs
# (``follow_redirects=False`` is the build_pinned_async_client default), and
# this transport ensures any such re-validated request that targets a
# different host is rejected before TCP connect.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pinned_transport_rejects_cross_host_redirect() -> None:
    """A request whose URL host differs from the pinned host must be rejected.

    This is the runtime arm of the SSRF rebinding defence: even if a
    caller (or buggy redirect-following code) hands the transport a URL
    that resolved to a different name, the request must error out before
    TCP connect. The error is a SSRFGuardError, not a network error, so
    the audit trail records it as a deliberate refusal.
    """
    import httpx

    transport = PinnedIPAsyncTransport(
        pinned_host="xeno-canto.org",
        pinned_ip="8.8.8.8",
        allowed_hosts=frozenset({"xeno-canto.org", "api.gbif.org"}),
    )
    # api.gbif.org is allowlisted but not the pinned host, so the
    # cross-host arm fires (not the not-in-allowlist arm).
    request = httpx.Request("GET", "https://api.gbif.org/v1/species")
    with pytest.raises(SSRFGuardError, match="cross-host redirect"):
        await transport.handle_async_request(request)


@pytest.mark.asyncio
async def test_pinned_transport_rejects_disallowed_host() -> None:
    """A URL host that is not on the allowlist must be rejected before connect."""
    import httpx

    transport = PinnedIPAsyncTransport(
        pinned_host="xeno-canto.org",
        pinned_ip="8.8.8.8",
        allowed_hosts=frozenset({"xeno-canto.org"}),
    )
    request = httpx.Request("GET", "https://evil.example.com/redirect-target")
    with pytest.raises(SSRFGuardError, match="not in SSRF allowlist"):
        await transport.handle_async_request(request)


@pytest.mark.asyncio
async def test_pinned_transport_rejects_non_http_scheme() -> None:
    """A non-http(s) scheme reaching handle_async_request must be rejected."""
    import httpx

    transport = PinnedIPAsyncTransport(
        pinned_host="xeno-canto.org",
        pinned_ip="8.8.8.8",
        allowed_hosts=frozenset({"xeno-canto.org"}),
    )
    # httpx will reject ftp:// at construct, so build a request that
    # passes httpx's own scheme check (http) but then mutate the URL to
    # carry a forbidden scheme. We do this by constructing the URL via
    # httpx.URL and then patching the scheme via the request copy_with.
    request = httpx.Request("GET", "http://xeno-canto.org/file.mp3")
    request.url = request.url.copy_with(scheme="ftp")
    with pytest.raises(SSRFGuardError, match="scheme not allowed"):
        await transport.handle_async_request(request)


@pytest.mark.asyncio
async def test_pinned_transport_rewrites_url_to_pinned_ip_and_preserves_host() -> None:
    """Request to the pinned host is forwarded with the URL host rewritten.

    The inner transport receives a URL whose host is the pinned IP
    literal (so anyio.connect_tcp skips DNS), but the ``Host`` header
    and ``sni_hostname`` extension preserve the user-facing hostname so
    TLS cert validation still pins to the original name. This is the
    core mechanism that defeats DNS rebinding: even if an attacker
    flipped DNS between validation and now, the connect target was
    fixed at validation time.
    """
    import httpx

    transport = PinnedIPAsyncTransport(
        pinned_host="xeno-canto.org",
        pinned_ip="8.8.8.8",
        allowed_hosts=frozenset({"xeno-canto.org"}),
    )

    captured: dict[str, httpx.Request] = {}

    async def _capture(req: httpx.Request) -> httpx.Response:
        captured["req"] = req
        return httpx.Response(200, content=b"ok")

    mock_inner = AsyncMock()
    mock_inner.handle_async_request = _capture
    transport._inner = mock_inner  # type: ignore[assignment]

    request = httpx.Request("GET", "https://xeno-canto.org/file.mp3")
    response = await transport.handle_async_request(request)

    assert response.status_code == 200
    forwarded = captured["req"]
    # URL host MUST have been rewritten to the pinned IP literal
    assert forwarded.url.host == "8.8.8.8"
    # ``Host`` header preserves the user-facing hostname for upstream routing
    assert forwarded.headers["host"] == "xeno-canto.org"
    # SNI extension preserves the user-facing hostname for TLS cert validation
    assert forwarded.extensions.get("sni_hostname") == "xeno-canto.org"


def test_pinned_transport_refuses_private_pinned_ip() -> None:
    """Constructing a transport with a private pinned IP must raise.

    Defence in depth: even if a caller bypasses validate_audio_url and
    hands us a private/loopback IP directly, the transport refuses to
    build. This protects against bugs in the caller from turning into
    SSRF on the inner transport.
    """
    with pytest.raises(SSRFGuardError, match="non-routable"):
        PinnedIPAsyncTransport(
            pinned_host="xeno-canto.org",
            pinned_ip="127.0.0.1",
            allowed_hosts=frozenset({"xeno-canto.org"}),
        )


def test_pinned_transport_refuses_link_local_imds_pinned_ip() -> None:
    """The classic AWS IMDS address must be refused as a pinned IP."""
    with pytest.raises(SSRFGuardError, match="non-routable"):
        PinnedIPAsyncTransport(
            pinned_host="xeno-canto.org",
            pinned_ip="169.254.169.254",
            allowed_hosts=frozenset({"xeno-canto.org"}),
        )


# ---------------------------------------------------------------------------
# validate_audio_url — DNS-resolved private IP rejection (lines 237-238)
# ---------------------------------------------------------------------------


def test_validate_audio_url_rejects_dns_resolved_private_ipv4() -> None:
    """When DNS for an allowlisted host returns a private IP, reject (lines 237-238).

    This is the rebinding *first-resolution* defence: an attacker who
    controls authoritative DNS for an allowlisted hostname must not be
    able to point it at 127.0.0.1 / RFC1918 / IMDS.
    """
    with patch(
        "echoroo.core.url_allowlist.socket.getaddrinfo",
        return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("127.0.0.1", 0)),
        ],
    ), pytest.raises(SSRFGuardError, match="non-routable"):
        validate_audio_url(
            "https://xeno-canto.org/file.mp3",
            allowed_hosts=frozenset({"xeno-canto.org"}),
        )


def test_validate_audio_url_rejects_dns_resolved_imds_address() -> None:
    """DNS resolving to AWS IMDS link-local must be rejected (lines 237-238)."""
    with patch(
        "echoroo.core.url_allowlist.socket.getaddrinfo",
        return_value=[
            (socket.AF_INET, socket.SOCK_STREAM, 0, "", ("169.254.169.254", 0)),
        ],
    ), pytest.raises(SSRFGuardError, match="non-routable"):
        validate_audio_url(
            "https://xeno-canto.org/file.mp3",
            allowed_hosts=frozenset({"xeno-canto.org"}),
        )


def test_validate_audio_url_rejects_dns_resolved_private_ipv6() -> None:
    """DNS resolving to IPv6 ULA must be rejected (lines 237-238, IPv6 arm)."""
    with patch(
        "echoroo.core.url_allowlist.socket.getaddrinfo",
        return_value=[
            (socket.AF_INET6, socket.SOCK_STREAM, 0, "", ("fd00::1", 0, 0, 0)),
        ],
    ), pytest.raises(SSRFGuardError, match="non-routable"):
        validate_audio_url(
            "https://xeno-canto.org/file.mp3",
            allowed_hosts=frozenset({"xeno-canto.org"}),
        )


# ---------------------------------------------------------------------------
# _format_ip_for_url — IPv6 bracketing (line 283)
# ---------------------------------------------------------------------------


def test_format_ip_for_url_brackets_ipv6() -> None:
    """IPv6 pinned IPs are bracketed in URL form so URL parsers split host/port.

    Without brackets ``2606:4700::1111:443`` is ambiguous — port could be
    ``1111:443`` or ``443``. This is exercised indirectly by
    ``PinnedIPAsyncTransport`` constructed with an IPv6 pin.
    """
    transport = PinnedIPAsyncTransport(
        pinned_host="xeno-canto.org",
        pinned_ip="2606:4700::1111",
        allowed_hosts=frozenset({"xeno-canto.org"}),
    )
    # Internal helper exposed via the formatted URL host
    assert transport._pinned_ip_url_host == "[2606:4700::1111]"


# ---------------------------------------------------------------------------
# build_pinned_async_client — wires validate + transport (lines 441-455)
# ---------------------------------------------------------------------------


def test_build_pinned_async_client_returns_client_and_pin() -> None:
    """build_pinned_async_client must validate, build a client, and return the pin.

    DNS is mocked to a deterministic public IP so this stays a pure
    unit test.
    """
    import httpx

    from echoroo.core.url_allowlist import build_pinned_async_client

    with patch(
        "echoroo.core.url_allowlist.socket.getaddrinfo",
        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 0))],
    ):
        client, pinned_ip = build_pinned_async_client(
            "https://xeno-canto.org/file.mp3",
            allowed_hosts=frozenset({"xeno-canto.org"}),
        )

    try:
        assert pinned_ip == "8.8.8.8"
        assert isinstance(client, httpx.AsyncClient)
        # follow_redirects defaults to False so callers must explicitly
        # re-validate each Location URL — that is the contract.
        assert client.follow_redirects is False
    finally:
        # Avoid leaking httpx connection pool warnings
        import asyncio
        asyncio.get_event_loop().run_until_complete(client.aclose())


def test_build_pinned_async_client_rejects_invalid_url() -> None:
    """build_pinned_async_client propagates SSRFGuardError from validate."""
    from echoroo.core.url_allowlist import build_pinned_async_client

    with pytest.raises(SSRFGuardError):
        build_pinned_async_client(
            "ftp://xeno-canto.org/file.mp3",
            allowed_hosts=frozenset({"xeno-canto.org"}),
        )

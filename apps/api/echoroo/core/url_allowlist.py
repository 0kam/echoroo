"""SSRF guard for outbound HTTP requests originating from user-controlled URLs.

This helper enforces an OWASP A10 mitigation around any backend code that
fetches a URL whose host is influenced by user input (e.g. ``SourceConfig
.source_url`` flows feeding ``services/search.py::_download_audio_url``,
or audio-fetch flows targeting xeno-canto / GBIF media).

The guard rejects URLs that:

  * use a scheme other than ``http`` / ``https``
  * resolve (post-DNS) to a loopback / link-local / RFC1918 / multicast /
    unspecified / reserved IP — the post-resolve check defeats the
    *naive* TOCTOU shape (the IP returned at validation time is private)
  * have a hostname that is not on the static service allowlist

DNS rebinding TOCTOU defence
----------------------------

A pre-flight ``socket.getaddrinfo`` check alone is **not** sufficient:
``httpx`` re-resolves the hostname when it opens the TCP connection, and
an attacker who controls the authoritative DNS server for an allowed
hostname can flip the answer between validation and connect (DNS
rebinding). To eliminate this race, callers must use
:class:`PinnedIPAsyncTransport` (or :func:`build_pinned_async_client`)
which:

  1. Calls :func:`validate_audio_url` to resolve and pick a *single*
     public IP address (the *pin*).
  2. Rewrites every outbound request URL so the connect target is that
     pinned IP, while preserving the original ``Host`` header and TLS
     ``server_hostname`` (SNI) so certificate validation still binds to
     the user-facing hostname.
  3. Re-validates redirect ``Location`` URLs against the same allowlist
     and pins a fresh IP for each hop.

Because the connection target is an IP literal, ``httpcore`` /
``anyio.connect_tcp`` skips DNS entirely on the actual connect, so a
post-validation rebinding cannot be exploited.

Hostname allowlist
------------------

Only the hostnames hard-coded in :data:`ALLOWED_AUDIO_HOSTS` are
accepted. New external destinations must be added here alongside a
security review entry in
``apps/api/tests/security/ssrf/test_external_url_rejection.py``.

The helper is deliberately narrow: it is the SSRF guard for *user-
supplied* URL inputs only. Server-initiated calls to first-party
services (e.g. internal Redis, S3) do not pass through this module.
"""

from __future__ import annotations

import ipaddress
import logging
import socket
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlparse

import httpx

if TYPE_CHECKING:
    from httpx._transports.base import AsyncBaseTransport
else:
    AsyncBaseTransport = httpx.AsyncBaseTransport

logger = logging.getLogger(__name__)


class SSRFGuardError(ValueError):
    """Raised when a URL fails SSRF allowlist validation.

    The attached message is safe to surface as an HTTP 400 detail; it
    contains only the rejection category, never the resolved private
    IP or other internal infrastructure details.
    """


# ---------------------------------------------------------------------------
# Allowed hostnames for user-controlled audio fetches.
#
# These are the only external services the backend will dereference on
# behalf of an authenticated user.  Sub-domains are matched exactly
# (``api.gbif.org`` does NOT permit ``evil.api.gbif.org`` unless added
# explicitly) to keep the surface tight.
# ---------------------------------------------------------------------------

ALLOWED_AUDIO_HOSTS: Final[frozenset[str]] = frozenset(
    {
        "xeno-canto.org",
        "www.xeno-canto.org",
        "api.gbif.org",
        "api.inaturalist.org",
    }
)

ALLOWED_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})


def _is_blocked_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True for IPs that must never be reached from a server-side fetch.

    Covers loopback, link-local, multicast, unspecified, reserved, and
    private (RFC1918 / IPv6 ULA) ranges. The combination defeats both
    naive 127.0.0.1 SSRF and AWS IMDS-style 169.254.169.254 attacks.
    """
    return (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
        or ip.is_private
    )


def _resolve_host(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve hostname via DNS and return all addresses.

    If ``host`` is already an IP literal we still pass it through the
    ipaddress parser so the caller gets a uniform return type.
    """
    # Direct IP literal — skip DNS round-trip
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass

    try:
        results = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise SSRFGuardError(f"hostname could not be resolved: {host}") from exc

    addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for family, _socktype, _proto, _canon, sockaddr in results:
        if family == socket.AF_INET:
            addresses.append(ipaddress.IPv4Address(sockaddr[0]))
        elif family == socket.AF_INET6:
            # sockaddr for AF_INET6 is (host, port, flowinfo, scopeid)
            addresses.append(ipaddress.IPv6Address(sockaddr[0]))
    if not addresses:
        raise SSRFGuardError(f"hostname produced no addresses: {host}")
    return addresses


def _audit_reject(url: str, reason: str) -> None:
    """Emit a structured warning so audit handlers can persist the event."""
    logger.warning(
        "ssrf_guard.reject",
        extra={
            "event": "ssrf_guard.reject",
            "url": url,
            "reason": reason,
        },
    )


def validate_audio_url(
    url: str,
    *,
    allowed_hosts: Iterable[str] | None = None,
) -> tuple[str, str]:
    """Validate that ``url`` is safe to fetch as a user-controlled audio source.

    Performs four checks, in order:

      1. URL parses with an http/https scheme and a non-empty hostname.
      2. Hostname is on the static allowlist.
      3. DNS resolves to at least one IP address.
      4. None of the resolved IPs are loopback / link-local / RFC1918 /
         multicast / reserved.

    The single resolved IP that the caller should pin to (the *first*
    public IPv4, or the first public IPv6 if no IPv4 is available) is
    returned alongside the URL. Use this IP with
    :class:`PinnedIPAsyncTransport` to defeat DNS rebinding TOCTOU
    attacks.

    Args:
        url: The user-supplied URL to validate.
        allowed_hosts: Optional override for the static allowlist
            (test seam — production callers should rely on the default).

    Returns:
        A ``(url, pinned_ip)`` tuple. ``pinned_ip`` is a string IP literal
        (e.g. ``"203.0.113.7"`` or ``"2001:db8::1"``) that the caller
        must use as the actual TCP connect target.

    Raises:
        SSRFGuardError: If any check fails. The message is safe to log /
            return as an HTTP 400 detail.
    """
    hosts = (
        frozenset(h.lower() for h in allowed_hosts)
        if allowed_hosts is not None
        else ALLOWED_AUDIO_HOSTS
    )

    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ALLOWED_SCHEMES:
        _audit_reject(url, f"scheme_not_allowed:{scheme!r}")
        raise SSRFGuardError(f"URL scheme not allowed: {scheme!r}")

    host = (parsed.hostname or "").lower()
    if not host:
        _audit_reject(url, "missing_host")
        raise SSRFGuardError("URL has no host component")

    # IP literals as the *URL host* are always rejected for user-controlled
    # URLs. The hostname must be on the named-host allowlist.
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        _audit_reject(url, "host_is_ip_literal")
        raise SSRFGuardError("URL host must be a named host, not an IP literal")

    if host not in hosts:
        _audit_reject(url, f"host_not_in_allowlist:{host}")
        raise SSRFGuardError(f"host not in SSRF allowlist: {host}")

    # Post-resolve check (DNS rebinding *first-resolution* defence).
    # The pin returned here is what the actual TCP connect must target —
    # see :class:`PinnedIPAsyncTransport` for the TOCTOU guard.
    try:
        addresses = _resolve_host(host)
    except SSRFGuardError:
        _audit_reject(url, "dns_resolution_failed")
        raise

    for addr in addresses:
        if _is_blocked_ip(addr):
            _audit_reject(url, f"private_ip_resolved:{addr}")
            raise SSRFGuardError(
                f"host resolved to a non-routable address: {addr}"
            )

    # Prefer IPv4 for the pin (more universally reachable, simpler URL
    # rewriting); fall back to IPv6 only if no IPv4 was returned.
    ipv4 = next(
        (a for a in addresses if isinstance(a, ipaddress.IPv4Address)), None
    )
    pinned = ipv4 if ipv4 is not None else addresses[0]
    return url, str(pinned)


def is_allowed_audio_url(url: str, *, allowed_hosts: Iterable[str] | None = None) -> bool:
    """Boolean wrapper around :func:`validate_audio_url`.

    Useful for guard-clause sites that prefer ``if not is_allowed...``
    over try/except. The same audit-log warning is emitted on rejection.
    """
    try:
        validate_audio_url(url, allowed_hosts=allowed_hosts)
    except SSRFGuardError:
        return False
    return True


# ---------------------------------------------------------------------------
# IP-pinning httpx transport
#
# Defeats DNS rebinding TOCTOU: ``validate_audio_url`` resolves the
# hostname once and returns the chosen public IP; the transport rewrites
# the connect target on every request to that IP literal, so the actual
# TCP connect skips DNS entirely. The original hostname is preserved in
# the ``Host:`` header and the TLS ``server_hostname`` (SNI) so cert
# validation still binds to the user-facing name.
# ---------------------------------------------------------------------------


def _format_ip_for_url(ip: str) -> str:
    """Return the host fragment to embed in a URL.

    IPv6 literals must be wrapped in square brackets.
    """
    addr = ipaddress.ip_address(ip)
    if isinstance(addr, ipaddress.IPv6Address):
        return f"[{addr}]"
    return str(addr)


class PinnedIPAsyncTransport(httpx.AsyncBaseTransport):
    """An ``httpx`` async transport that pins all connects to a fixed IP.

    Wraps an inner :class:`httpx.AsyncHTTPTransport` and, on every
    outbound request:

      1. Validates the request URL against :data:`ALLOWED_AUDIO_HOSTS`
         (defence in depth — catches a redirect that escaped the
         caller's pre-flight check).
      2. Verifies that the URL host matches the *expected* hostname for
         which this transport was pinned. Cross-host redirects are
         rejected; the caller must build a fresh pinned transport.
      3. Rewrites the URL host to the pinned IP literal.
      4. Adds an explicit ``Host:`` header with the original hostname.
      5. Sets ``request.extensions["sni_hostname"]`` so TLS cert
         validation still uses the user-facing hostname.

    Because the rewritten URL host is an IP literal,
    ``httpcore`` / ``anyio.connect_tcp`` performs no DNS lookup at
    connect time, so a rebinding attack on the original hostname has no
    effect on which IP we actually reach.

    Note: this transport is intentionally bound to a *single* hostname
    and IP. Callers who must follow cross-host redirects should disable
    auto-redirect on the client and re-validate / rebuild the transport
    per hop using :func:`validate_audio_url`.
    """

    def __init__(
        self,
        *,
        pinned_host: str,
        pinned_ip: str,
        verify: bool = True,
        http1: bool = True,
        http2: bool = False,
        allowed_hosts: Iterable[str] | None = None,
    ) -> None:
        self._pinned_host = pinned_host.lower()
        self._pinned_ip = pinned_ip
        self._pinned_ip_url_host = _format_ip_for_url(pinned_ip)
        # Validate IP belongs to the allowlist of public ranges right now —
        # if a caller hands us a private IP we refuse to even build the
        # transport.
        if _is_blocked_ip(ipaddress.ip_address(pinned_ip)):
            raise SSRFGuardError(
                f"pinned IP is non-routable: {pinned_ip}"
            )
        self._allowed_hosts = (
            frozenset(h.lower() for h in allowed_hosts)
            if allowed_hosts is not None
            else ALLOWED_AUDIO_HOSTS
        )
        self._inner: httpx.AsyncBaseTransport = httpx.AsyncHTTPTransport(
            verify=verify, http1=http1, http2=http2
        )

    async def __aenter__(self) -> PinnedIPAsyncTransport:
        await self._inner.__aenter__()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._inner.__aexit__(*exc)

    async def aclose(self) -> None:
        await self._inner.aclose()

    async def handle_async_request(
        self, request: httpx.Request
    ) -> httpx.Response:
        original_host = request.url.host.lower()
        scheme = request.url.scheme.lower()

        if scheme not in ALLOWED_SCHEMES:
            _audit_reject(str(request.url), f"scheme_not_allowed:{scheme!r}")
            raise SSRFGuardError(f"URL scheme not allowed: {scheme!r}")

        if original_host not in self._allowed_hosts:
            _audit_reject(
                str(request.url),
                f"host_not_in_allowlist:{original_host}",
            )
            raise SSRFGuardError(
                f"host not in SSRF allowlist: {original_host}"
            )

        if original_host != self._pinned_host:
            _audit_reject(
                str(request.url),
                f"host_pin_mismatch:{original_host}!={self._pinned_host}",
            )
            raise SSRFGuardError(
                "request host does not match the pinned hostname; "
                "cross-host redirect must be re-validated"
            )

        # Rewrite the URL so the connect target is the pinned IP literal.
        # ``httpcore`` will pass this directly to ``anyio.connect_tcp``,
        # which sees an IP literal and skips DNS entirely.
        port = request.url.port
        new_url = request.url.copy_with(host=self._pinned_ip_url_host)

        # Preserve the ``Host`` header so the upstream server routes the
        # request as if we'd connected by name.
        host_header = (
            original_host if port is None else f"{original_host}:{port}"
        )

        new_headers = request.headers.copy()
        new_headers["host"] = host_header

        new_extensions = dict(request.extensions)
        # SNI / cert validation still uses the original hostname.
        new_extensions["sni_hostname"] = original_host

        rewritten = httpx.Request(
            method=request.method,
            url=new_url,
            headers=new_headers,
            content=None,
            extensions=new_extensions,
        )
        # Preserve the body stream from the original request rather than
        # forcing httpx to rebuild it from ``content=None``.
        rewritten.stream = request.stream

        return await self._inner.handle_async_request(rewritten)


def build_pinned_async_client(
    url: str,
    *,
    timeout: float | httpx.Timeout = 30.0,
    follow_redirects: bool = False,
    allowed_hosts: Iterable[str] | None = None,
) -> tuple[httpx.AsyncClient, str]:
    """Return an ``httpx.AsyncClient`` whose transport is IP-pinned for ``url``.

    The returned client connects only to the *single* IP the URL
    resolved to at validation time, with the ``Host`` header and TLS
    SNI preserved. DNS rebinding has no effect on which host the client
    will actually reach.

    By default ``follow_redirects`` is ``False`` because the pinned
    transport binds to a single hostname and rejects cross-host
    redirects. If your caller must follow redirects, leave it ``False``
    and re-validate each ``Location`` URL with :func:`validate_audio_url`
    before issuing a new pinned request.

    Returns:
        ``(client, pinned_ip)`` — pass the client to ``async with`` and
        use ``client.stream("GET", url)`` (or similar) as usual. The
        ``pinned_ip`` is returned for log / audit purposes.
    """
    _, pinned_ip = validate_audio_url(url, allowed_hosts=allowed_hosts)
    parsed = urlparse(url)
    pinned_host = (parsed.hostname or "").lower()

    transport = PinnedIPAsyncTransport(
        pinned_host=pinned_host,
        pinned_ip=pinned_ip,
        allowed_hosts=allowed_hosts,
    )
    client = httpx.AsyncClient(
        transport=transport,
        timeout=timeout,
        follow_redirects=follow_redirects,
    )
    return client, pinned_ip


__all__ = [
    "ALLOWED_AUDIO_HOSTS",
    "ALLOWED_SCHEMES",
    "PinnedIPAsyncTransport",
    "SSRFGuardError",
    "build_pinned_async_client",
    "is_allowed_audio_url",
    "validate_audio_url",
]

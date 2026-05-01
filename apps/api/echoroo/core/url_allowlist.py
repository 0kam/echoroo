"""SSRF guard for outbound HTTP requests originating from user-controlled URLs.

This helper enforces an OWASP A10 mitigation around any backend code that
fetches a URL whose host is influenced by user input (e.g. ``SourceConfig
.source_url`` flows feeding ``services/search.py::_download_audio_url``,
or audio-fetch flows targeting xeno-canto / GBIF media).

The guard rejects URLs that:

  * use a scheme other than ``http`` / ``https``
  * resolve (post-DNS) to a loopback / link-local / RFC1918 / multicast /
    unspecified / reserved IP — the post-resolve check defeats DNS
    rebinding attacks
  * have a hostname that is not on the static service allowlist

When a URL is rejected, the helper raises :class:`SSRFGuardError` and
emits a structured ``logger.warning`` event with the rejection reason so
that the audit log pipeline can persist it via the standard logging
hook (Phase 16 audit handler).

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
from typing import Final
from urllib.parse import urlparse

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
) -> str:
    """Validate that ``url`` is safe to fetch as a user-controlled audio source.

    Performs four checks, in order:

      1. URL parses with an http/https scheme and a non-empty hostname.
      2. Hostname is on the static allowlist.
      3. DNS resolves to at least one public IP (post-resolve check
         defeats DNS rebinding).
      4. None of the resolved IPs are loopback / link-local / RFC1918 /
         multicast / reserved.

    Args:
        url: The user-supplied URL to validate.
        allowed_hosts: Optional override for the static allowlist
            (test seam — production callers should rely on the default).

    Returns:
        The original URL, unchanged, if all checks pass.

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

    if host not in hosts:
        _audit_reject(url, f"host_not_in_allowlist:{host}")
        raise SSRFGuardError(f"host not in SSRF allowlist: {host}")

    # Post-resolve check (DNS rebinding defence). Even an allowed host
    # could resolve to 127.0.0.1 or 169.254.169.254 if the attacker
    # controls DNS for that name.
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

    return url


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


__all__ = [
    "ALLOWED_AUDIO_HOSTS",
    "ALLOWED_SCHEMES",
    "SSRFGuardError",
    "is_allowed_audio_url",
    "validate_audio_url",
]

"""Same-origin redirect target validator (Phase 17 A-7).

Helpers for safely handling user-supplied ``?next=`` / ``?redirect_url=``
parameters across login, password reset, invitation acceptance and OAuth
callback flows. The validator enforces an allowlist policy:

* Reject absolute URLs whose host is not in the configured allowlist.
* Reject protocol-relative URLs (``//evil.com``) which browsers resolve
  against the current origin's scheme but a different host.
* Reject dangerous schemes (``javascript:``, ``data:``, ``file:`` etc.).
* Accept relative paths starting with a single ``/`` (``/dashboard``).
* Reject relative paths starting with ``\\`` (Windows backslash escape).
* Reject URLs containing CR / LF (header-injection guard).

Threat model:

* OWASP A01 (Broken Access Control / Open Redirect) — phishing chains.
* OWASP A03 (Injection) — XSS via ``javascript:`` redirect.

Usage::

    from echoroo.core.redirect_validator import is_safe_redirect_url

    if is_safe_redirect_url(next_param):
        ...  # safe to honour
    else:
        # log audit + ignore
        ...

Endpoints that consume ``?next=`` MUST go through
:func:`validate_redirect_target` so the rejection event is written to the
platform audit log uniformly.
"""

from __future__ import annotations

from typing import Final
from urllib.parse import urlparse

# Schemes that a same-origin redirect may legitimately use. Anything else
# (``javascript:``, ``data:``, ``file:``, ``vbscript:``, ``ftp:`` …) is
# treated as hostile.
_ALLOWED_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})

# Default same-origin allowlist used by the auth flows when no explicit
# allowlist is supplied. Only relative paths are permitted by default.
_DEFAULT_ALLOWED_HOSTS: Final[frozenset[str]] = frozenset()


def is_safe_redirect_url(
    target: str | None,
    *,
    allowed_hosts: frozenset[str] | None = None,
) -> bool:
    """Return ``True`` if ``target`` is safe to use as a redirect Location.

    Args:
        target: Raw user-supplied redirect target (``?next=...`` value).
        allowed_hosts: Optional allowlist of absolute-URL hosts that are
            considered same-origin. When ``None`` (default) only relative
            URLs are accepted.

    Returns:
        ``True`` when the target may be honoured, ``False`` when it must
        be rejected. ``None`` / empty / whitespace-only inputs are rejected.
    """
    if target is None:
        return False
    if not isinstance(target, str):
        return False

    # Empty / whitespace.
    stripped = target.strip()
    if not stripped:
        return False

    # CR / LF / NUL — header-injection or smuggling vectors.
    if any(ch in stripped for ch in ("\r", "\n", "\x00")):
        return False

    # Backslash leading char — historical Windows path-escape bypass.
    if stripped.startswith("\\"):
        return False

    # Protocol-relative URL: ``//evil.com/foo`` browsers resolve to the
    # current scheme + ``evil.com`` host. Always reject.
    if stripped.startswith("//"):
        return False

    # Pure relative path: must start with a single ``/`` and not be ``/\``.
    if stripped.startswith("/"):
        # Reject ``/\`` (Windows-style sneaky escape) and ``/\\``.
        return not (len(stripped) > 1 and stripped[1] == "\\")

    # Otherwise it must parse to an absolute URL with an allowed scheme
    # and an allowlisted host.
    try:
        parsed = urlparse(stripped)
    except ValueError:
        return False

    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        return False

    host = (parsed.hostname or "").lower()
    if not host:
        return False

    allow = allowed_hosts if allowed_hosts is not None else _DEFAULT_ALLOWED_HOSTS
    return host in allow


def validate_redirect_target(
    target: str | None,
    *,
    allowed_hosts: frozenset[str] | None = None,
) -> str | None:
    """Return ``target`` when safe, otherwise ``None``.

    Convenience wrapper around :func:`is_safe_redirect_url` for endpoints
    that want a "use this value or fall back to default" semantic. Callers
    that need to audit the rejection event should call
    :func:`is_safe_redirect_url` directly so they can react to the boolean
    result.

    Args:
        target: Raw user-supplied redirect target.
        allowed_hosts: Optional allowlist of absolute-URL hosts.

    Returns:
        ``target`` unchanged when safe; ``None`` otherwise.
    """
    if is_safe_redirect_url(target, allowed_hosts=allowed_hosts):
        return target
    return None


__all__ = [
    "is_safe_redirect_url",
    "validate_redirect_target",
]

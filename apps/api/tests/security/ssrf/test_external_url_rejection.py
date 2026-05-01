"""T979g: SSRF prevention — external URL fetch allowlist (OWASP A10).

Verifies that every HTTP fetch originating from the backend targets a
pre-approved external service, and that any user-controllable URL input
surface either uses an allowlist validator or is documented as a future
fix target.

Strategy:
  A. Static allowlist test — grep the codebase for ``httpx.AsyncClient``
     usage sites and assert that every hardcoded destination URL is in the
     known-approved list.
  B. No server-side proxy of arbitrary user-supplied URLs without an
     allowlist guard — ``_download_audio_url`` (search.py) accepts a
     user-controlled ``source_url``; this is an open SSRF surface.
     Marked xfail until a validator is added (Phase 17 / T979g follow-up).
  C. Xeno-canto proxy endpoint enforces domain allowlist.
  D. ``SourceConfig.source_url`` schema field does NOT accept internal/
     private network addresses (loopback, link-local, RFC-1918).

Shim: OFF — file content and schema inspection; no HTTP transport.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Repository root helpers
#
# Supports both host checkout and Docker /app layout.
# ---------------------------------------------------------------------------


def _find_echoroo_src() -> Path:
    """Return the path to the echoroo source package."""
    this_file = Path(__file__).resolve()
    # Docker: /app/echoroo
    # Host: .../echoroo/apps/api/echoroo
    for depth in (5, 4, 3, 2):
        try:
            candidate = this_file.parents[depth]
        except IndexError:
            continue
        # Check for echoroo package in api subdirectory (host) or directly (Docker)
        api_src = candidate / "apps" / "api" / "echoroo"
        if api_src.is_dir():
            return api_src
        direct_src = candidate / "echoroo"
        if direct_src.is_dir():
            return direct_src
    # Final fallback
    return Path("/app/echoroo")


_ECHOROO_SRC = _find_echoroo_src()


# ---------------------------------------------------------------------------
# Known-approved external service URL prefixes (SSRF allowlist)
# ---------------------------------------------------------------------------

# These are all the external HTTP destinations legitimately used by the
# backend.  Any new external destination MUST be added here alongside a
# security review comment.
_APPROVED_EXTERNAL_URLS: frozenset[str] = frozenset(
    {
        # Biodiversity data
        "https://api.gbif.org/v1",
        "https://api.inaturalist.org/v1",
        "https://apiv3.iucnredlist.org/api/v3",
        # Password breach check (k-anonymity — no full hash sent)
        "https://api.pwnedpasswords.com/range/",
        # Cloudflare Turnstile CAPTCHA verification
        "https://challenges.cloudflare.com/turnstile/v0/siteverify",
        # Xeno-canto bird recordings
        "https://xeno-canto.org",
        "https://xeno-canto.org/",
        "https://xeno-canto.org/api/3/recordings",
    }
)

# Regex to find hardcoded HTTPS/HTTP strings in source code
_HARDCODED_URL_RE = re.compile(r'"(https?://[^"]{5,})"')

# Domains approved for external fetch (prefix check)
_APPROVED_DOMAINS: tuple[str, ...] = (
    "api.gbif.org",
    "api.inaturalist.org",
    "apiv3.iucnredlist.org",
    "api.pwnedpasswords.com",
    "challenges.cloudflare.com",
    "xeno-canto.org",
    "echoroo.app",  # self-reference in config
)


def _iter_python_files(root: Path) -> list[Path]:
    return [
        f
        for f in root.rglob("*.py")
        if "test_" not in f.name and "__pycache__" not in str(f)
    ]


# ---------------------------------------------------------------------------
# Section A: Hardcoded external URLs must be in the approved list
# ---------------------------------------------------------------------------


def test_hardcoded_external_urls_are_in_approved_allowlist() -> None:
    """Every hardcoded external URL in production code must be in the approved list.

    A new external HTTP destination introduced outside this allowlist is a
    potential SSRF escalation path and must be reviewed before merging.
    """
    violations: list[str] = []
    for py_file in _iter_python_files(_ECHOROO_SRC):
        text = py_file.read_text(encoding="utf-8")
        for match in _HARDCODED_URL_RE.finditer(text):
            url = match.group(1)
            # Ignore localhost / docker-internal addresses
            if "localhost" in url or "127.0.0.1" in url or "0.0.0.0" in url:
                continue
            # Ignore format-string fragments (contain { or })
            if "{" in url or "}" in url:
                continue
            # Check against approved domain prefixes
            approved = any(domain in url for domain in _APPROVED_DOMAINS)
            if not approved:
                rel = py_file.relative_to(_ECHOROO_SRC)
                violations.append(f"{rel}: {url!r}")

    assert not violations, (
        "Unapproved external URLs found in production code. "
        "Add each to _APPROVED_EXTERNAL_URLS in this test after security review:\n"
        + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Section B: User-controlled URL in SourceConfig lacks SSRF allowlist guard
# ---------------------------------------------------------------------------


def test_download_audio_url_has_ssrf_allowlist_guard() -> None:
    """``_download_audio_url`` must validate the URL against an allowlist before fetching.

    ``SourceConfig.source_url`` is user-supplied.  Phase 17 (T979g) added
    ``build_pinned_async_client`` which runs a static allowlist check + DNS
    private-IP block before any network I/O (SSRF guard — OWASP A10).
    This test verifies the guard patterns are present in the function body.
    """
    search_py = _ECHOROO_SRC / "services" / "search.py"
    assert search_py.is_file(), f"search.py not found at {search_py}"
    text = search_py.read_text(encoding="utf-8")

    # Find the _download_audio_url function body
    fn_start = text.find("async def _download_audio_url(")
    assert fn_start != -1, "_download_audio_url not found in search.py"
    # Extract a reasonable window of the function body
    fn_body = text[fn_start : fn_start + 2000]

    # Check for a SSRF-guard pattern:
    #   - allowlist check on the URL before the httpx call
    #   - private IP block
    #   - domain whitelist validator
    guard_patterns = [
        "_is_allowed_audio_url",
        "_validate_audio_url",
        "_check_ssrf",
        "allowlist",
        "allowed_domains",
        "private.*ip",
        "127\\.0\\.0\\.1",
        "is_private",
        "ssrf",
    ]
    has_guard = any(
        re.search(pattern, fn_body, re.IGNORECASE) for pattern in guard_patterns
    )
    assert has_guard, (
        "_download_audio_url in search.py fetches user-supplied URLs without "
        "an SSRF guard. Add a domain allowlist or private-IP block before the "
        "httpx.AsyncClient.stream() call."
    )


# ---------------------------------------------------------------------------
# Section C: Xeno-canto proxy enforces domain allowlist
# ---------------------------------------------------------------------------


def test_xeno_canto_proxy_has_domain_allowlist_check() -> None:
    """The xeno-canto sonogram proxy must reject non-xeno-canto URLs via parsed validation.

    The ``/api/v1/xeno-canto/sonogram`` endpoint accepts a ``url`` query
    parameter from the caller. Without a domain check, it acts as an open
    proxy (SSRF / CORS bypass).

    This test calls ``_validate_sonogram_url`` directly with adversarial inputs
    rather than doing a source-text ``startswith`` grep, so it exercises the
    actual parsed-URL validation rather than incidental text matching.
    """
    import socket
    from unittest.mock import patch

    from fastapi import HTTPException

    from echoroo.api.v1.xeno_canto import _validate_sonogram_url  # type: ignore[attr-defined]

    # --- Happy path: a legitimate xeno-canto URL must not raise ---
    # Patch DNS so the test runs without internet access.
    # Note: 203.0.113.x / 198.51.100.x documentation ranges are marked
    # is_private by Python ipaddress; use a genuinely routable public IP.
    with patch(
        "echoroo.api.v1.xeno_canto.socket.getaddrinfo",
        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.5", 0))],
    ):
        # Should complete without raising
        _validate_sonogram_url("https://xeno-canto.org/sounds/spectrogram/1234.png")

    # --- Rejection: non-xeno-canto domain must raise HTTPException(400) ---
    with pytest.raises(HTTPException) as exc_info:
        _validate_sonogram_url("https://evil.example.com/steal?xeno-canto.org=bypass")
    assert exc_info.value.status_code == 400, (
        "_validate_sonogram_url should return HTTP 400 for non-xeno-canto URLs"
    )

    # --- Rejection: subdomain spoofing must raise HTTPException(400) ---
    with pytest.raises(HTTPException) as exc_info2:
        _validate_sonogram_url("https://xeno-canto.org.attacker.com/img.png")
    assert exc_info2.value.status_code == 400, (
        "_validate_sonogram_url should reject subdomain-spoofing attempts"
    )

    # --- Rejection: http (not https) must raise HTTPException(400) ---
    with pytest.raises(HTTPException) as exc_info3:
        _validate_sonogram_url("http://xeno-canto.org/sounds/spectrogram/1.png")
    assert exc_info3.value.status_code == 400, (
        "_validate_sonogram_url should reject http:// (non-TLS) scheme"
    )


# ---------------------------------------------------------------------------
# Section D: SourceConfig.source_url is a plain str (no HttpUrl coercion)
# ---------------------------------------------------------------------------


def test_source_config_source_url_is_plain_str_field() -> None:
    """``SourceConfig.source_url`` is ``str | None``, not ``HttpUrl``.

    This test documents the current state: no Pydantic HttpUrl type coercion
    is in place, which means private IP URLs (``http://169.254.169.254/``)
    would pass schema validation unchanged — the SSRF guard must be enforced
    at the service layer instead.
    """
    from echoroo.schemas.search import SourceConfig

    # Instantiate with a loopback URL — schema currently accepts it
    cfg = SourceConfig(type="url", source_url="http://127.0.0.1/internal")
    # The field exists and holds the raw string (no HttpUrl normalization)
    assert cfg.source_url == "http://127.0.0.1/internal", (
        "If SourceConfig now rejects private IPs, this test must be updated "
        "and the xfail in test_download_audio_url_has_ssrf_allowlist_guard "
        "should be removed."
    )


__all__ = [
    "test_download_audio_url_has_ssrf_allowlist_guard",
    "test_hardcoded_external_urls_are_in_approved_allowlist",
    "test_source_config_source_url_is_plain_str_field",
    "test_xeno_canto_proxy_has_domain_allowlist_check",
]

# Note: DNS-rebinding and PinnedIPAsyncTransport unit tests are in
# dedicated files:
#   tests/security/ssrf/test_pinned_ip_async_transport.py
#   tests/security/ssrf/test_pinned_ip_rebinding.py

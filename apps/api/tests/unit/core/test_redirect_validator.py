"""Unit tests for echoroo.core.redirect_validator (Phase 17 coverage uplift).

Targets the uncovered branches reported at 67.2% statement coverage:
  - None / non-string inputs (lines 68, 70)
  - Empty / whitespace-only string (line 75)
  - CR/LF/NUL injection (line 79)
  - Backslash leading character (line 83)
  - urlparse ValueError path (lines 99-100)
  - Empty host after parse (line 108)
  - validate_redirect_target wrapper returning target and None (lines 134-136)

These tests are purely in-process (no DB, no network).
"""

from __future__ import annotations

from echoroo.core.redirect_validator import is_safe_redirect_url, validate_redirect_target

# ---------------------------------------------------------------------------
# is_safe_redirect_url — None / non-string inputs
# ---------------------------------------------------------------------------


def test_none_input_returns_false() -> None:
    """None must be rejected (line 68)."""
    assert is_safe_redirect_url(None) is False


def test_non_string_integer_returns_false() -> None:
    """Non-string input (integer) must be rejected (line 70)."""
    assert is_safe_redirect_url(42) is False  # type: ignore[arg-type]


def test_non_string_list_returns_false() -> None:
    """Non-string input (list) must be rejected (line 70)."""
    assert is_safe_redirect_url(["/dashboard"]) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# is_safe_redirect_url — empty / whitespace-only
# ---------------------------------------------------------------------------


def test_empty_string_returns_false() -> None:
    """Empty string must be rejected (line 75)."""
    assert is_safe_redirect_url("") is False


def test_whitespace_only_returns_false() -> None:
    """Whitespace-only string must be rejected (line 75)."""
    assert is_safe_redirect_url("   ") is False
    assert is_safe_redirect_url("\t\n") is False


# ---------------------------------------------------------------------------
# is_safe_redirect_url — header injection (CR/LF/NUL)
# ---------------------------------------------------------------------------


def test_carriage_return_injection_returns_false() -> None:
    """CR character in target must be rejected (line 79)."""
    assert is_safe_redirect_url("/dashboard\rX-Injected: evil") is False


def test_line_feed_injection_returns_false() -> None:
    """LF character in target must be rejected (line 79)."""
    assert is_safe_redirect_url("/dashboard\nX-Injected: evil") is False


def test_nul_byte_injection_returns_false() -> None:
    """NUL byte in target must be rejected (line 79)."""
    assert is_safe_redirect_url("/dashboard\x00") is False


def test_crlf_in_absolute_url_returns_false() -> None:
    """CRLF injection in absolute URL must be rejected (line 79)."""
    assert is_safe_redirect_url("https://example.com/path\r\nX-Evil: 1") is False


# ---------------------------------------------------------------------------
# is_safe_redirect_url — backslash leading character
# ---------------------------------------------------------------------------


def test_backslash_start_returns_false() -> None:
    """Backslash-leading target must be rejected (line 83)."""
    assert is_safe_redirect_url("\\evil.com") is False


def test_backslash_double_returns_false() -> None:
    """Double-backslash must also be rejected (line 83)."""
    assert is_safe_redirect_url("\\\\evil.com") is False


# ---------------------------------------------------------------------------
# is_safe_redirect_url — protocol-relative URL
# ---------------------------------------------------------------------------


def test_protocol_relative_url_returns_false() -> None:
    """Protocol-relative URL //evil.com must be rejected."""
    assert is_safe_redirect_url("//evil.com/steal") is False


# ---------------------------------------------------------------------------
# is_safe_redirect_url — relative paths (happy and sad)
# ---------------------------------------------------------------------------


def test_simple_relative_path_returns_true() -> None:
    """Simple relative path /dashboard must be accepted."""
    assert is_safe_redirect_url("/dashboard") is True


def test_relative_path_with_query_returns_true() -> None:
    """Relative path with query string must be accepted."""
    assert is_safe_redirect_url("/projects/123?tab=recordings") is True


def test_relative_path_backslash_second_char_returns_false() -> None:
    """Path /\\ (Windows escape) must be rejected."""
    assert is_safe_redirect_url("/\\evil") is False


def test_relative_path_double_backslash_returns_false() -> None:
    """Path /\\\\ must also be rejected."""
    assert is_safe_redirect_url("/\\\\evil") is False


def test_relative_path_single_slash_only_returns_true() -> None:
    """Single slash / (root path) must be accepted."""
    assert is_safe_redirect_url("/") is True


# ---------------------------------------------------------------------------
# is_safe_redirect_url — absolute URL with allowed_hosts
# ---------------------------------------------------------------------------


def test_absolute_url_allowed_host_returns_true() -> None:
    """Absolute URL whose host is in allowed_hosts must be accepted."""
    result = is_safe_redirect_url(
        "https://app.echoroo.example.com/dashboard",
        allowed_hosts=frozenset({"app.echoroo.example.com"}),
    )
    assert result is True


def test_absolute_url_disallowed_host_returns_false() -> None:
    """Absolute URL whose host is NOT in allowed_hosts must be rejected."""
    result = is_safe_redirect_url(
        "https://attacker.example.com/steal",
        allowed_hosts=frozenset({"app.echoroo.example.com"}),
    )
    assert result is False


def test_absolute_url_no_allowed_hosts_returns_false() -> None:
    """Absolute URL with default empty allowed_hosts must be rejected."""
    assert is_safe_redirect_url("https://example.com/path") is False


def test_absolute_url_javascript_scheme_returns_false() -> None:
    """javascript: scheme must be rejected even if host is in allowlist."""
    result = is_safe_redirect_url(
        "javascript:alert(1)",
        allowed_hosts=frozenset({"evil.com"}),
    )
    assert result is False


def test_absolute_url_data_scheme_returns_false() -> None:
    """data: URI scheme must be rejected."""
    assert is_safe_redirect_url("data:text/html,<script>alert(1)</script>") is False


def test_absolute_url_ftp_scheme_returns_false() -> None:
    """ftp: scheme must be rejected."""
    result = is_safe_redirect_url(
        "ftp://example.com/file.txt",
        allowed_hosts=frozenset({"example.com"}),
    )
    assert result is False


def test_absolute_url_empty_host_returns_false() -> None:
    """URL that parses but yields an empty host must be rejected (line 108)."""
    # urlparse("https:///path") yields an empty netloc/hostname
    result = is_safe_redirect_url(
        "https:///some/path",
        allowed_hosts=frozenset({"example.com"}),
    )
    assert result is False


def test_malformed_ipv6_url_returns_false() -> None:
    """Malformed IPv6 bracket URL that causes urlparse ValueError must be rejected (lines 99-100)."""
    # urlparse raises ValueError for invalid IPv6 bracket syntax
    result = is_safe_redirect_url(
        "http://[invalid",
        allowed_hosts=frozenset({"example.com"}),
    )
    assert result is False


def test_absolute_url_http_scheme_allowed_host_returns_true() -> None:
    """http: scheme is also allowed for absolute URLs with an allowed host."""
    result = is_safe_redirect_url(
        "http://app.echoroo.example.com/dashboard",
        allowed_hosts=frozenset({"app.echoroo.example.com"}),
    )
    assert result is True


# ---------------------------------------------------------------------------
# validate_redirect_target — wrapper
# ---------------------------------------------------------------------------


def test_validate_redirect_target_safe_returns_target() -> None:
    """validate_redirect_target must return the original target for safe inputs (line 134-135)."""
    target = "/dashboard"
    result = validate_redirect_target(target)
    assert result == target


def test_validate_redirect_target_unsafe_returns_none() -> None:
    """validate_redirect_target must return None for unsafe inputs (line 136)."""
    result = validate_redirect_target("//evil.com/steal")
    assert result is None


def test_validate_redirect_target_none_returns_none() -> None:
    """validate_redirect_target must return None when input is None."""
    result = validate_redirect_target(None)
    assert result is None


def test_validate_redirect_target_absolute_safe_returns_target() -> None:
    """validate_redirect_target with allowed_hosts returns absolute target."""
    target = "https://app.echoroo.example.com/dashboard"
    result = validate_redirect_target(
        target,
        allowed_hosts=frozenset({"app.echoroo.example.com"}),
    )
    assert result == target


def test_validate_redirect_target_absolute_unsafe_returns_none() -> None:
    """validate_redirect_target returns None for absolute URL not in allowlist."""
    result = validate_redirect_target(
        "https://attacker.com/steal",
        allowed_hosts=frozenset({"app.echoroo.example.com"}),
    )
    assert result is None

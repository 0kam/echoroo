"""Coverage uplift unit tests for ``echoroo.services.email``.

Phase 17 §C Batch 6+7 (25-35pp gap): covers _safe_recipient_hash,
_sanitise_email_field, EmailHeaderInjectionError, and send_* functions
so the module clears the 85% threshold without touching production code.

Resend API calls are patched so no real HTTP calls are made.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import echoroo.services.email as mod
from echoroo.services.email import (
    EmailHeaderInjectionError,
    _safe_recipient_hash,
    _sanitise_email_field,
)

# ---------------------------------------------------------------------------
# _safe_recipient_hash
# ---------------------------------------------------------------------------


def test_safe_recipient_hash_hashes_non_empty_value() -> None:
    """_safe_recipient_hash returns a non-empty hash for valid input (line 46)."""
    result = _safe_recipient_hash("user@example.com")
    assert len(result) > 0
    assert result != "user@example.com"


def test_safe_recipient_hash_returns_missing_sentinel_for_none() -> None:
    """_safe_recipient_hash returns '<missing>' for None (line 42)."""
    result = _safe_recipient_hash(None)
    assert result == "<missing>"


def test_safe_recipient_hash_returns_missing_sentinel_for_empty() -> None:
    """_safe_recipient_hash returns '<missing>' for empty string (lines 42-43)."""
    result = _safe_recipient_hash("")
    assert result == "<missing>"


# ---------------------------------------------------------------------------
# _sanitise_email_field
# ---------------------------------------------------------------------------


def test_sanitise_email_field_normalises_and_returns() -> None:
    """_sanitise_email_field returns NFKC-normalised string (lines 80-88)."""
    result = _sanitise_email_field("  hello  ", field_name="test")
    assert result == "hello"


def test_sanitise_email_field_returns_empty_for_none() -> None:
    """_sanitise_email_field returns empty string for None (line 80)."""
    result = _sanitise_email_field(None, field_name="test")
    assert result == ""


def test_sanitise_email_field_raises_on_control_chars() -> None:
    """_sanitise_email_field raises EmailHeaderInjectionError on \\n (lines 84-86)."""
    with pytest.raises(EmailHeaderInjectionError):
        _sanitise_email_field("Subject\nBcc: attacker@evil.com", field_name="subject")


def test_sanitise_email_field_truncates_to_max_len() -> None:
    """_sanitise_email_field truncates to _EMAIL_FIELD_MAX_LEN (lines 87-88)."""
    long_string = "x" * (mod._EMAIL_FIELD_MAX_LEN + 100)
    result = _sanitise_email_field(long_string, field_name="ua")
    assert len(result) == mod._EMAIL_FIELD_MAX_LEN


def test_sanitise_email_field_converts_non_string() -> None:
    """_sanitise_email_field converts non-string via str() (line 82)."""
    result = _sanitise_email_field(12345, field_name="test")
    assert result == "12345"


# ---------------------------------------------------------------------------
# send_verification_email
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_verification_email_skips_when_no_api_key() -> None:
    """send_verification_email skips and warns when RESEND_API_KEY not set (lines 135)."""
    with (
        patch.object(mod.settings, "RESEND_API_KEY", ""),
        patch.object(mod.logger, "warning") as mock_warn,
    ):
        await mod.send_verification_email("user@example.com", "tok123")
    mock_warn.assert_called_once()


@pytest.mark.asyncio
async def test_send_verification_email_calls_resend_when_key_set() -> None:
    """send_verification_email calls resend.Emails.send when API key is configured (lines 187)."""
    with (
        patch.object(mod.settings, "RESEND_API_KEY", "re_test_key"),
        patch.object(mod.resend.Emails, "send") as mock_send,
    ):
        await mod.send_verification_email("user@example.com", "tok123")
    mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_send_verification_email_logs_exception_on_failure() -> None:
    """send_verification_email catches and logs Resend exception (lines 187)."""
    with (
        patch.object(mod.settings, "RESEND_API_KEY", "re_test_key"),
        patch.object(mod.resend.Emails, "send", side_effect=Exception("api error")),
        patch.object(mod.logger, "exception") as mock_exc,
    ):
        # Should NOT raise
        await mod.send_verification_email("user@example.com", "tok123")
    mock_exc.assert_called_once()


# ---------------------------------------------------------------------------
# send_password_reset_email
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_password_reset_email_skips_when_no_api_key() -> None:
    """send_password_reset_email skips when RESEND_API_KEY not set (line 225)."""
    with (
        patch.object(mod.settings, "RESEND_API_KEY", ""),
        patch.object(mod.logger, "warning") as mock_warn,
    ):
        await mod.send_password_reset_email("user@example.com", "reset123")
    mock_warn.assert_called_once()


@pytest.mark.asyncio
async def test_send_password_reset_email_calls_resend_when_key_set() -> None:
    """send_password_reset_email calls resend.Emails.send when API key configured (line 252)."""
    with (
        patch.object(mod.settings, "RESEND_API_KEY", "re_test_key"),
        patch.object(mod.resend.Emails, "send") as mock_send,
    ):
        await mod.send_password_reset_email("user@example.com", "reset123")
    mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_send_password_reset_email_logs_exception_on_failure() -> None:
    """send_password_reset_email catches and logs exception (lines 260-264)."""
    with (
        patch.object(mod.settings, "RESEND_API_KEY", "re_test_key"),
        patch.object(mod.resend.Emails, "send", side_effect=Exception("api error")),
        patch.object(mod.logger, "exception") as mock_exc,
    ):
        await mod.send_password_reset_email("user@example.com", "reset123")
    mock_exc.assert_called_once()


# ---------------------------------------------------------------------------
# _two_factor_reset_magic_link_url
# ---------------------------------------------------------------------------


def test_two_factor_reset_magic_link_url_constructs_url() -> None:
    """_two_factor_reset_magic_link_url builds URL with token (lines 196-198)."""
    url = mod._two_factor_reset_magic_link_url("magic-token-abc")
    assert "magic-token-abc" in url
    assert "two-factor-reset/confirm" in url


# ---------------------------------------------------------------------------
# send_2fa_reset_magic_link
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_2fa_reset_magic_link_skips_when_no_api_key() -> None:
    """send_2fa_reset_magic_link skips when RESEND_API_KEY not set (lines 218-225)."""
    with (
        patch.object(mod.settings, "RESEND_API_KEY", ""),
        patch.object(mod.logger, "warning") as mock_warn,
    ):
        await mod.send_2fa_reset_magic_link("user@example.com", "tok123")
    mock_warn.assert_called_once()


@pytest.mark.asyncio
async def test_send_2fa_reset_magic_link_calls_resend_when_key_set() -> None:
    """send_2fa_reset_magic_link calls resend when key is configured (lines 227-264)."""
    with (
        patch.object(mod.settings, "RESEND_API_KEY", "re_test_key"),
        patch.object(mod.resend.Emails, "send") as mock_send,
    ):
        await mod.send_2fa_reset_magic_link("user@example.com", "tok123")
    mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_send_2fa_reset_magic_link_reraises_on_send_failure() -> None:
    """send_2fa_reset_magic_link re-raises on send failure (lines 273-283)."""
    with (
        patch.object(mod.settings, "RESEND_API_KEY", "re_test_key"),
        patch.object(mod.resend.Emails, "send", side_effect=Exception("send error")),
        pytest.raises(Exception, match="send error"),
    ):
        await mod.send_2fa_reset_magic_link("user@example.com", "tok123")


# ---------------------------------------------------------------------------
# send_2fa_reset_dispatched
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_2fa_reset_dispatched_skips_when_no_api_key() -> None:
    """send_2fa_reset_dispatched skips when RESEND_API_KEY not set (lines 302-306)."""
    with (
        patch.object(mod.settings, "RESEND_API_KEY", ""),
        patch.object(mod.logger, "warning") as mock_warn,
    ):
        await mod.send_2fa_reset_dispatched("user@example.com", dispatched_at_iso="2026-01-01T00:00:00Z")
    mock_warn.assert_called_once()


@pytest.mark.asyncio
async def test_send_2fa_reset_dispatched_calls_resend_when_key_set() -> None:
    """send_2fa_reset_dispatched calls resend when key configured (lines 312-342)."""
    with (
        patch.object(mod.settings, "RESEND_API_KEY", "re_test_key"),
        patch.object(mod.resend.Emails, "send") as mock_send,
    ):
        await mod.send_2fa_reset_dispatched("user@example.com", dispatched_at_iso="2026-01-01T00:00:00Z")
    mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_send_2fa_reset_dispatched_reraises_on_failure() -> None:
    """send_2fa_reset_dispatched re-raises on send error (lines 344-352)."""
    with (
        patch.object(mod.settings, "RESEND_API_KEY", "re_test_key"),
        patch.object(mod.resend.Emails, "send", side_effect=Exception("smtp error")),
        pytest.raises(Exception, match="smtp error"),
    ):
        await mod.send_2fa_reset_dispatched("user@example.com", dispatched_at_iso="2026-01-01")


# ---------------------------------------------------------------------------
# send_api_key_scope_degrade_email
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_api_key_scope_degrade_skips_when_no_api_key() -> None:
    """send_api_key_scope_degrade_email skips when no key (lines 376-382)."""
    with (
        patch.object(mod.settings, "RESEND_API_KEY", ""),
        patch.object(mod.logger, "warning") as mock_warn,
    ):
        await mod.send_api_key_scope_degrade_email(
            to="user@example.com",
            api_key_prefix="ecr_abc123",
            created_at_iso="2025-01-01",
            degraded_at_iso="2025-07-01",
            grace_days_until_revoke=90,
        )
    mock_warn.assert_called_once()


@pytest.mark.asyncio
async def test_send_api_key_scope_degrade_calls_resend_when_key_set() -> None:
    """send_api_key_scope_degrade_email calls resend when key set (lines 388-419)."""
    with (
        patch.object(mod.settings, "RESEND_API_KEY", "re_test_key"),
        patch.object(mod.resend.Emails, "send") as mock_send,
    ):
        await mod.send_api_key_scope_degrade_email(
            to="user@example.com",
            api_key_prefix="ecr_abc123",
            created_at_iso="2025-01-01",
            degraded_at_iso="2025-07-01",
            grace_days_until_revoke=90,
        )
    mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_send_api_key_scope_degrade_reraises_on_failure() -> None:
    """send_api_key_scope_degrade_email re-raises on failure (lines 439-445)."""
    with (
        patch.object(mod.settings, "RESEND_API_KEY", "re_test_key"),
        patch.object(mod.resend.Emails, "send", side_effect=Exception("smtp")),
        pytest.raises(Exception, match="smtp"),
    ):
        await mod.send_api_key_scope_degrade_email(
            to="user@example.com",
            api_key_prefix="ecr_abc",
            created_at_iso="2025-01-01",
            degraded_at_iso="2025-07-01",
            grace_days_until_revoke=90,
        )


# ---------------------------------------------------------------------------
# send_api_key_revoke_email
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_api_key_revoke_skips_when_no_api_key() -> None:
    """send_api_key_revoke_email skips when no key (lines 404-406)."""
    with (
        patch.object(mod.settings, "RESEND_API_KEY", ""),
        patch.object(mod.logger, "warning") as mock_warn,
    ):
        await mod.send_api_key_revoke_email(
            to="user@example.com",
            api_key_prefix="ecr_abc123",
            created_at_iso="2025-01-01",
            revoked_at_iso="2025-10-01",
        )
    mock_warn.assert_called_once()


@pytest.mark.asyncio
async def test_send_api_key_revoke_calls_resend_when_key_set() -> None:
    """send_api_key_revoke_email calls resend when key set (lines 412-451)."""
    with (
        patch.object(mod.settings, "RESEND_API_KEY", "re_test_key"),
        patch.object(mod.resend.Emails, "send") as mock_send,
    ):
        await mod.send_api_key_revoke_email(
            to="user@example.com",
            api_key_prefix="ecr_abc123",
            created_at_iso="2025-01-01",
            revoked_at_iso="2025-10-01",
        )
    mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_send_api_key_revoke_reraises_on_failure() -> None:
    """send_api_key_revoke_email re-raises on failure."""
    with (
        patch.object(mod.settings, "RESEND_API_KEY", "re_test_key"),
        patch.object(mod.resend.Emails, "send", side_effect=Exception("smtp")),
        pytest.raises(Exception, match="smtp"),
    ):
        await mod.send_api_key_revoke_email(
            to="user@example.com",
            api_key_prefix="ecr_abc",
            created_at_iso="2025-01-01",
            revoked_at_iso="2025-10-01",
        )

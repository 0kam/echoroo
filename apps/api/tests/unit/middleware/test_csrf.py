"""Smoke tests for :mod:`echoroo.middleware.csrf` (T072)."""

from __future__ import annotations

import pytest

from echoroo.middleware.csrf import (
    CsrfTokenExpiredError,
    CsrfTokenMalformedError,
    CsrfTokenMismatchError,
    issue_csrf_token,
    verify_csrf_token,
)


def test_csrf_token_round_trip() -> None:
    """A token issued for a session must verify against that session."""
    token = issue_csrf_token(
        "session-abc",
        session_secret="deployment-secret-32-bytes-of-entropy",
        issued_at=10_000,
    )
    # Should not raise.
    verify_csrf_token(
        token,
        session_id="session-abc",
        session_secret="deployment-secret-32-bytes-of-entropy",
        now=10_500,
    )


def test_csrf_rejects_tampered() -> None:
    """A flipped byte in the HMAC half MUST be rejected."""
    token = issue_csrf_token(
        "session-abc",
        session_secret="deployment-secret-32-bytes-of-entropy",
        issued_at=10_000,
    )
    payload, mac = token.split(".", 1)
    # Flip the first character of the mac portion.
    flipped = ("A" if mac[0] != "A" else "B") + mac[1:]
    tampered = f"{payload}.{flipped}"
    with pytest.raises(CsrfTokenMismatchError):
        verify_csrf_token(
            tampered,
            session_id="session-abc",
            session_secret="deployment-secret-32-bytes-of-entropy",
            now=10_500,
        )


def test_csrf_rejects_wrong_session() -> None:
    """Token issued for session A must not verify against session B."""
    token = issue_csrf_token(
        "session-A",
        session_secret="deployment-secret-32-bytes-of-entropy",
        issued_at=10_000,
    )
    with pytest.raises(CsrfTokenMismatchError):
        verify_csrf_token(
            token,
            session_id="session-B",
            session_secret="deployment-secret-32-bytes-of-entropy",
            now=10_500,
        )


def test_csrf_rejects_expired() -> None:
    """Tokens older than the TTL must be rejected even if HMAC matches."""
    token = issue_csrf_token(
        "session-abc",
        session_secret="deployment-secret-32-bytes-of-entropy",
        issued_at=1_000,
    )
    with pytest.raises(CsrfTokenExpiredError):
        verify_csrf_token(
            token,
            session_id="session-abc",
            session_secret="deployment-secret-32-bytes-of-entropy",
            ttl_seconds=60,
            now=2_000,
        )


def test_csrf_rejects_malformed() -> None:
    """Garbage inputs must be flagged malformed, not raise unrelated errors."""
    with pytest.raises(CsrfTokenMalformedError):
        verify_csrf_token(
            "not-a-token",
            session_id="session",
            session_secret="x" * 32,
        )

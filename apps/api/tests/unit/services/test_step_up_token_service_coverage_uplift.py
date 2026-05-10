"""Coverage uplift unit tests for ``echoroo.services.step_up_token_service``.

Phase 17 §C medium-gap batch (95% permission-critical tier): targets
the small reject branches at lines 137, 172, 189, 192-193, 197, 207,
211, 215, 220 so the module clears the 95% threshold without touching
production code. All tests drive the production helpers directly so
the coverage hits are real production-path executions, not in-test
re-implementations.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import jwt
import pytest

from echoroo.core.settings import get_settings
from echoroo.services.step_up_token_service import (
    SCOPE_ADMIN_DESTRUCTIVE,
    STEP_UP_TOKEN_TTL_SECONDS,
    STEP_UP_TOKEN_TYPE,
    StepUpTokenExpiredError,
    StepUpTokenInvalidError,
    StepUpTokenScopeMismatchError,
    issue_step_up_token,
    verify_step_up_token,
)


def _settings() -> Any:
    return get_settings()


def _encode(payload: dict[str, Any]) -> str:
    s = _settings()
    return jwt.encode(payload, s.web_session_secret, algorithm=s.JWT_ALGORITHM)


def _base_payload(*, exp_offset: int = 60, **overrides: Any) -> dict[str, Any]:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(uuid4()),
        "type": STEP_UP_TOKEN_TYPE,
        "scope": SCOPE_ADMIN_DESTRUCTIVE,
        "ss": "stamp-1",
        "aid": "assertion-1",
        "jti": "jti-1",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=exp_offset)).timestamp()),
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# issue_step_up_token
# ---------------------------------------------------------------------------


def test_issue_step_up_token_round_trips_via_verify() -> None:
    """A freshly minted token decodes back to matching claims."""
    user_id = uuid4()
    token, expires_at = issue_step_up_token(
        user_id=user_id,
        security_stamp="ss-original",
        assertion_id="aid-original",
    )
    claims = verify_step_up_token(token)
    assert claims.user_id == user_id
    assert claims.scope == SCOPE_ADMIN_DESTRUCTIVE
    assert claims.security_stamp == "ss-original"
    assert claims.assertion_id == "aid-original"
    # Expiry is roughly the documented TTL — the JWT-encoded ``iat``/``exp``
    # are integer Unix seconds so the round-tripped issued_at differs from
    # ``now`` by sub-second microseconds.
    delta = expires_at - claims.issued_at
    assert abs(delta.total_seconds() - STEP_UP_TOKEN_TTL_SECONDS) <= 1


def test_issue_step_up_token_rejects_non_positive_ttl() -> None:
    """ttl_seconds <= 0 raises ValueError (line 137)."""
    with pytest.raises(ValueError, match="ttl_seconds must be positive"):
        issue_step_up_token(
            user_id=uuid4(),
            security_stamp="ss",
            assertion_id="aid",
            ttl_seconds=0,
        )
    with pytest.raises(ValueError):
        issue_step_up_token(
            user_id=uuid4(),
            security_stamp="ss",
            assertion_id="aid",
            ttl_seconds=-1,
        )


# ---------------------------------------------------------------------------
# verify_step_up_token — invalid input shapes
# ---------------------------------------------------------------------------


def test_verify_rejects_empty_token() -> None:
    """Empty / non-string token raises StepUpTokenInvalidError (line 172)."""
    with pytest.raises(StepUpTokenInvalidError, match="missing"):
        verify_step_up_token("")
    with pytest.raises(StepUpTokenInvalidError, match="missing"):
        verify_step_up_token(None)  # type: ignore[arg-type]


def test_verify_rejects_expired_token() -> None:
    """An ``exp`` claim in the past raises StepUpTokenExpiredError."""
    token = _encode(_base_payload(exp_offset=-60))
    with pytest.raises(StepUpTokenExpiredError, match="expired"):
        verify_step_up_token(token)


def test_verify_rejects_garbage_token() -> None:
    """A non-JWT string raises StepUpTokenInvalidError (catch InvalidTokenError)."""
    with pytest.raises(StepUpTokenInvalidError, match="invalid"):
        verify_step_up_token("not-a-jwt")


def test_verify_rejects_wrong_type_claim() -> None:
    """type != step_up raises StepUpTokenInvalidError."""
    payload = _base_payload(type="access")
    token = _encode(payload)
    with pytest.raises(StepUpTokenInvalidError, match="type mismatch"):
        verify_step_up_token(token)


def test_verify_rejects_missing_subject() -> None:
    """Missing or non-string subject raises StepUpTokenInvalidError."""
    payload = _base_payload()
    payload.pop("sub")
    token = _encode(payload)
    with pytest.raises(StepUpTokenInvalidError, match="subject missing"):
        verify_step_up_token(token)


def test_verify_rejects_invalid_uuid_subject() -> None:
    """Subject that is not a UUID raises StepUpTokenInvalidError (lines 192-193)."""
    payload = _base_payload(sub="not-a-uuid")
    token = _encode(payload)
    with pytest.raises(StepUpTokenInvalidError, match="subject invalid"):
        verify_step_up_token(token)


def test_verify_rejects_missing_scope() -> None:
    """Missing scope raises StepUpTokenInvalidError (line 197)."""
    payload = _base_payload()
    payload["scope"] = ""
    token = _encode(payload)
    with pytest.raises(StepUpTokenInvalidError, match="scope missing"):
        verify_step_up_token(token)


def test_verify_rejects_scope_mismatch() -> None:
    """Scope that doesn't match expected raises StepUpTokenScopeMismatchError."""
    payload = _base_payload(scope="other_scope")
    token = _encode(payload)
    with pytest.raises(StepUpTokenScopeMismatchError, match="scope mismatch"):
        verify_step_up_token(token)


def test_verify_rejects_missing_security_stamp() -> None:
    """Missing security_stamp raises StepUpTokenInvalidError (line 207)."""
    payload = _base_payload()
    payload.pop("ss")
    token = _encode(payload)
    with pytest.raises(StepUpTokenInvalidError, match="security stamp"):
        verify_step_up_token(token)


def test_verify_rejects_missing_assertion_id() -> None:
    """Missing assertion id raises StepUpTokenInvalidError (line 211)."""
    payload = _base_payload()
    payload["aid"] = ""
    token = _encode(payload)
    with pytest.raises(StepUpTokenInvalidError, match="assertion id"):
        verify_step_up_token(token)


def test_verify_rejects_missing_jti() -> None:
    """Missing jti raises StepUpTokenInvalidError (line 215)."""
    payload = _base_payload()
    payload["jti"] = ""
    token = _encode(payload)
    with pytest.raises(StepUpTokenInvalidError, match="jti"):
        verify_step_up_token(token)


def test_verify_rejects_missing_timestamps() -> None:
    """Missing/non-int iat raises StepUpTokenInvalidError (line 220).

    PyJWT requires ``exp`` to be numeric for its own validation, so to
    drive the late ``isinstance(iat_raw, int)`` check at line 219-220 we
    encode without an ``iat`` claim entirely. PyJWT does not reject a
    missing ``iat`` (it only validates ``exp`` / ``nbf`` by default).
    """
    payload = _base_payload()
    payload.pop("iat")
    token = _encode(payload)
    with pytest.raises(StepUpTokenInvalidError, match="timestamps"):
        verify_step_up_token(token)

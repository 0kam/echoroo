"""Contract test: WebAuthn assertion issues a step-up token (T984).

Phase 16 Batch 6g-3 wires the destructive-admin step-up flow:
``POST /web-api/v1/auth/2fa/webauthn/verify`` (and the legacy
``/2fa/webauthn/challenge`` complete branch that fronts it) MUST emit a
short-lived JWT with ``scope='admin_destructive'`` after a successful
WebAuthn authentication.  The token rides on both:

* The ``X-Step-Up-Token`` response header (so SPA fetch wrappers can
  capture it without parsing the body).
* The JSON body's ``step_up_token`` / ``step_up_expires_at`` /
  ``step_up_scope`` fields (for SSR / tooling).

This contract test exercises the **token issuance contract** at the
service-helper level (``issue_step_up_token`` / ``verify_step_up_token``)
plus the **schema contract** of
:class:`~echoroo.schemas.web_v1.auth.WebAuthnChallengeCompleteResponse`.
End-to-end ASGI exercise of the verify endpoint (with full WebAuthn
ceremony fixtures) is covered by ``tests/integration/api/web_v1/
test_auth_webauthn.py`` once the Phase 16 fixture catches up; here we
focus on the pure JWT contract so static checking + ruff + an in-memory
import is sufficient.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

from echoroo.core.settings import get_settings
from echoroo.schemas.web_v1.auth import WebAuthnChallengeCompleteResponse
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


def test_issue_step_up_token_returns_valid_jwt_with_required_claims() -> None:
    """A freshly-minted token decodes with all required claims set."""
    user_id = uuid4()
    token, expires_at = issue_step_up_token(
        user_id=user_id,
        security_stamp="stamp-" + ("a" * 50),
        assertion_id="cred-1",
    )
    assert isinstance(token, str)
    assert token.count(".") == 2  # JWT shape

    settings = get_settings()
    decoded = jwt.decode(
        token,
        settings.web_session_secret,
        algorithms=[settings.JWT_ALGORITHM],
    )
    assert decoded["sub"] == str(user_id)
    assert decoded["type"] == STEP_UP_TOKEN_TYPE
    assert decoded["scope"] == SCOPE_ADMIN_DESTRUCTIVE
    assert decoded["aid"] == "cred-1"
    assert decoded["ss"] == "stamp-" + ("a" * 50)
    assert isinstance(decoded["jti"], str) and decoded["jti"]
    # ``exp - iat`` MUST equal the configured TTL (5 min default).
    assert decoded["exp"] - decoded["iat"] == STEP_UP_TOKEN_TTL_SECONDS

    # ``expires_at`` is exactly TTL_SECONDS after issuance, give or take
    # the seconds it took to round-trip the call.
    delta = expires_at - datetime.now(UTC)
    assert timedelta(seconds=0) < delta <= timedelta(
        seconds=STEP_UP_TOKEN_TTL_SECONDS + 5
    )


def test_verify_step_up_token_round_trip_returns_claims() -> None:
    """``verify_step_up_token`` accepts what ``issue_step_up_token`` produced."""
    user_id = uuid4()
    token, expires_at = issue_step_up_token(
        user_id=user_id,
        security_stamp="stamp-fresh",
        assertion_id="aid-xyz",
    )
    claims = verify_step_up_token(token)
    assert claims.user_id == user_id
    assert claims.scope == SCOPE_ADMIN_DESTRUCTIVE
    assert claims.security_stamp == "stamp-fresh"
    assert claims.assertion_id == "aid-xyz"
    assert claims.expires_at == expires_at.replace(microsecond=0)


def test_verify_step_up_token_rejects_expired_token() -> None:
    """A token whose ``exp`` is in the past raises ``StepUpTokenExpiredError``."""
    settings = get_settings()
    past = datetime.now(UTC) - timedelta(seconds=600)
    payload = {
        "sub": str(uuid4()),
        "type": STEP_UP_TOKEN_TYPE,
        "scope": SCOPE_ADMIN_DESTRUCTIVE,
        "ss": "stamp-stale",
        "aid": "aid-stale",
        "jti": str(uuid4()),
        "iat": int(past.timestamp()) - 10,
        "exp": int(past.timestamp()),
    }
    expired_token = jwt.encode(
        payload, settings.web_session_secret, algorithm=settings.JWT_ALGORITHM
    )
    with pytest.raises(StepUpTokenExpiredError):
        verify_step_up_token(expired_token)


def test_verify_step_up_token_rejects_scope_mismatch() -> None:
    """A token whose ``scope`` claim differs from the gate's expected scope is rejected."""
    token, _ = issue_step_up_token(
        user_id=uuid4(),
        security_stamp="stamp",
        assertion_id="aid",
        scope="other_scope",
    )
    with pytest.raises(StepUpTokenScopeMismatchError):
        verify_step_up_token(token, expected_scope=SCOPE_ADMIN_DESTRUCTIVE)


def test_verify_step_up_token_rejects_wrong_signature() -> None:
    """A token signed with a different secret fails decode → ``StepUpTokenInvalidError``."""
    payload = {
        "sub": str(uuid4()),
        "type": STEP_UP_TOKEN_TYPE,
        "scope": SCOPE_ADMIN_DESTRUCTIVE,
        "ss": "stamp",
        "aid": "aid",
        "jti": str(uuid4()),
        "iat": int(datetime.now(UTC).timestamp()),
        "exp": int(datetime.now(UTC).timestamp()) + 300,
    }
    forged = jwt.encode(payload, "wrong-secret-not-the-real-one", algorithm="HS256")
    with pytest.raises(StepUpTokenInvalidError):
        verify_step_up_token(forged)


def test_verify_step_up_token_rejects_wrong_type_claim() -> None:
    """A JWT with ``type != 'step_up'`` (e.g. an interim token) is rejected."""
    settings = get_settings()
    interim_payload = {
        "sub": str(uuid4()),
        "type": "interim",  # not step_up
        "scope": SCOPE_ADMIN_DESTRUCTIVE,
        "ss": "stamp",
        "aid": "aid",
        "jti": str(uuid4()),
        "iat": int(datetime.now(UTC).timestamp()),
        "exp": int(datetime.now(UTC).timestamp()) + 300,
    }
    interim_token = jwt.encode(
        interim_payload,
        settings.web_session_secret,
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(StepUpTokenInvalidError):
        verify_step_up_token(interim_token)


def test_webauthn_challenge_complete_response_carries_step_up_fields() -> None:
    """The Pydantic schema accepts and exposes the new step_up fields."""
    response = WebAuthnChallengeCompleteResponse(
        access_token="aaa.bbb.ccc",
        expires_in=900,
        step_up_token="xxx.yyy.zzz",
        step_up_expires_at="2026-04-29T12:34:56+00:00",
        step_up_scope=SCOPE_ADMIN_DESTRUCTIVE,
    )
    assert response.step_up_token == "xxx.yyy.zzz"
    assert response.step_up_scope == SCOPE_ADMIN_DESTRUCTIVE
    serialised = response.model_dump()
    assert "step_up_token" in serialised
    assert "step_up_expires_at" in serialised
    assert "step_up_scope" in serialised


def test_webauthn_challenge_complete_response_rejects_extra_fields() -> None:
    """``extra='forbid'`` keeps the response surface honest."""
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        WebAuthnChallengeCompleteResponse(  # type: ignore[call-arg]
            access_token="a",
            expires_in=1,
            step_up_token="b",
            step_up_expires_at="2026-04-29T00:00:00+00:00",
            step_up_scope=SCOPE_ADMIN_DESTRUCTIVE,
            evil="inject",
        )

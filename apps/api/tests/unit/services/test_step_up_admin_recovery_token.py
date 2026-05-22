"""Unit tests for the ``admin_recovery``-scoped step-up token branch.

Covers spec/011 §FR-011-206 — the new AND-condition step-up surface
that gates admin password reset / self-reset / admin 2FA disable. The
existing ``admin_destructive`` branch is exercised by
``tests/contract/test_step_up_token_issuance.py`` +
``tests/unit/services/test_step_up_token_service_coverage_uplift.py``;
this file focuses on:

* issue + verify round-trip under the new scope,
* the ``factors`` invariant (password=True AND second_factor in
  {"totp", "webauthn"}) enforced at verify time,
* scope confusion (admin_destructive ↔ admin_recovery rejected
  both ways),
* security-stamp / TTL rotation revoking outstanding tokens (which
  is a service-level invariant, not a session-level one — the
  middleware layer adds a per-request session binding on top).

Every test drives the production helpers directly so coverage hits
match the real branch the middleware exercises.
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
    SCOPE_ADMIN_RECOVERY,
    STEP_UP_TOKEN_TTL_SECONDS,
    STEP_UP_TOKEN_TYPE,
    StepUpTokenExpiredError,
    StepUpTokenInvalidError,
    StepUpTokenScopeMismatchError,
    issue_admin_recovery_step_up_token,
    issue_step_up_token,
    verify_step_up_token,
)


def _settings() -> Any:
    return get_settings()


def _encode(payload: dict[str, Any]) -> str:
    s = _settings()
    return jwt.encode(payload, s.web_session_secret, algorithm=s.JWT_ALGORITHM)


def _recovery_payload(
    *,
    exp_offset: int = STEP_UP_TOKEN_TTL_SECONDS,
    factors: Any = None,
    scope: str = SCOPE_ADMIN_RECOVERY,
    **overrides: Any,
) -> dict[str, Any]:
    """Build a freshly-shaped admin_recovery JWT payload for hand-rolling.

    Test helpers prefer ``issue_admin_recovery_step_up_token`` when
    exercising the happy path; this builder is used for the negative
    cases that need to drift one specific claim (e.g. wrong scope,
    malformed factors) without bypassing the rest of the contract.
    """
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(uuid4()),
        "type": STEP_UP_TOKEN_TYPE,
        "scope": scope,
        "ss": "ss-recovery",
        "aid": "aid-recovery",
        "jti": "jti-recovery",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=exp_offset)).timestamp()),
    }
    if factors is not _UNSET:
        payload["factors"] = factors
    payload.update(overrides)
    return payload


_UNSET: Any = object()


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_issue_admin_recovery_round_trips_via_verify_totp() -> None:
    """Mint + verify under ``admin_recovery`` with ``second_factor='totp'``."""
    user_id = uuid4()
    token, expires_at = issue_admin_recovery_step_up_token(
        user_id=user_id,
        security_stamp="ss-fresh",
        assertion_id="aid-fresh",
        password_verified=True,
        second_factor="totp",
    )
    claims = verify_step_up_token(token, expected_scope=SCOPE_ADMIN_RECOVERY)
    assert claims.user_id == user_id
    assert claims.scope == SCOPE_ADMIN_RECOVERY
    assert claims.security_stamp == "ss-fresh"
    assert claims.assertion_id == "aid-fresh"
    assert claims.factors == {"password": True, "second_factor": "totp"}
    # Expiry sanity — JWT encodes integer seconds so we compare with a
    # one-second tolerance.
    delta = expires_at - claims.issued_at
    assert abs(delta.total_seconds() - STEP_UP_TOKEN_TTL_SECONDS) <= 1


def test_issue_admin_recovery_round_trips_via_verify_webauthn() -> None:
    """The ``second_factor='webauthn'`` arm also round-trips cleanly."""
    user_id = uuid4()
    token, _ = issue_admin_recovery_step_up_token(
        user_id=user_id,
        security_stamp="ss-w",
        assertion_id="aid-w",
        password_verified=True,
        second_factor="webauthn",
    )
    claims = verify_step_up_token(token, expected_scope=SCOPE_ADMIN_RECOVERY)
    assert claims.factors == {"password": True, "second_factor": "webauthn"}


def test_issue_admin_recovery_signed_payload_carries_factors_claim() -> None:
    """The ``factors`` claim is part of the *signed* payload, not a header."""
    token, _ = issue_admin_recovery_step_up_token(
        user_id=uuid4(),
        security_stamp="ss",
        assertion_id="aid",
        password_verified=True,
        second_factor="totp",
    )
    s = _settings()
    decoded = jwt.decode(
        token, s.web_session_secret, algorithms=[s.JWT_ALGORITHM]
    )
    assert decoded["scope"] == SCOPE_ADMIN_RECOVERY
    assert decoded["factors"] == {"password": True, "second_factor": "totp"}


def test_issue_admin_recovery_rejects_non_positive_ttl() -> None:
    """``ttl_seconds`` <= 0 is refused at issuance."""
    with pytest.raises(ValueError, match="ttl_seconds must be positive"):
        issue_admin_recovery_step_up_token(
            user_id=uuid4(),
            security_stamp="ss",
            assertion_id="aid",
            password_verified=True,
            second_factor="totp",
            ttl_seconds=0,
        )
    with pytest.raises(ValueError):
        issue_admin_recovery_step_up_token(
            user_id=uuid4(),
            security_stamp="ss",
            assertion_id="aid",
            password_verified=True,
            second_factor="totp",
            ttl_seconds=-1,
        )


def test_issue_admin_recovery_rejects_non_bool_password_verified() -> None:
    """The issuer MUST refuse non-:class:`bool` ``password_verified``.

    Without the strict ``isinstance(..., bool)`` guard, a caller bug
    (or downstream JSON deserialisation) that passes ``1``, ``"true"``,
    ``"false"``, ``[]``, etc. would be silently coerced into the
    literal ``True`` / ``False`` singleton by ``bool(...)`` and bypass
    the verifier's ``factors.password is True`` defence-in-depth
    check. The strict guard is the contract that keeps that defence
    meaningful.
    """
    for bad_value in (1, 0, "true", "false", "True", "False", [], [True], None):
        with pytest.raises(TypeError, match="password_verified must be a strict bool"):
            issue_admin_recovery_step_up_token(
                user_id=uuid4(),
                security_stamp="ss",
                assertion_id="aid",
                password_verified=bad_value,  # type: ignore[arg-type]
                second_factor="totp",
            )


# ---------------------------------------------------------------------------
# factors invariant — verify-time enforcement
# ---------------------------------------------------------------------------


def test_verify_admin_recovery_rejects_password_false() -> None:
    """``factors.password=False`` is refused even if second_factor is valid.

    The verifier MUST refuse so a caller bug that mints
    ``password_verified=False`` cannot smuggle a usable recovery token.
    """
    token, _ = issue_admin_recovery_step_up_token(
        user_id=uuid4(),
        security_stamp="ss",
        assertion_id="aid",
        password_verified=False,
        second_factor="totp",
    )
    with pytest.raises(StepUpTokenInvalidError):
        verify_step_up_token(token, expected_scope=SCOPE_ADMIN_RECOVERY)


def test_verify_admin_recovery_rejects_password_missing() -> None:
    """``factors`` mapping without a ``password`` key fails verify."""
    token = _encode(_recovery_payload(factors={"second_factor": "totp"}))
    with pytest.raises(StepUpTokenInvalidError):
        verify_step_up_token(token, expected_scope=SCOPE_ADMIN_RECOVERY)


def test_verify_admin_recovery_rejects_password_truthy_non_bool() -> None:
    """Only the literal ``True`` is accepted — ``1`` / ``"true"`` are not.

    Using ``is True`` rather than a truthy check prevents an attacker
    from smuggling ``"True"`` (a non-empty string) past the gate.
    """
    for value in (1, "true", "True", "yes", [True]):
        token = _encode(
            _recovery_payload(
                factors={"password": value, "second_factor": "totp"}
            )
        )
        with pytest.raises(StepUpTokenInvalidError):
            verify_step_up_token(token, expected_scope=SCOPE_ADMIN_RECOVERY)


def test_verify_admin_recovery_rejects_second_factor_missing() -> None:
    """``factors`` mapping without a ``second_factor`` key fails verify."""
    token = _encode(_recovery_payload(factors={"password": True}))
    with pytest.raises(StepUpTokenInvalidError):
        verify_step_up_token(token, expected_scope=SCOPE_ADMIN_RECOVERY)


@pytest.mark.parametrize("bad_factor", ["sms", "email", "", "TOTP", "webAuthN"])
def test_verify_admin_recovery_rejects_second_factor_out_of_contract(
    bad_factor: str,
) -> None:
    """Only ``"totp"`` and ``"webauthn"`` survive verify."""
    token = _encode(
        _recovery_payload(
            factors={"password": True, "second_factor": bad_factor}
        )
    )
    with pytest.raises(StepUpTokenInvalidError):
        verify_step_up_token(token, expected_scope=SCOPE_ADMIN_RECOVERY)


def test_verify_admin_recovery_rejects_second_factor_non_string() -> None:
    """Non-string second_factor (e.g. ``None``, ``int``) is rejected."""
    for value in (None, 1, True, ["totp"], {"x": "y"}):
        token = _encode(
            _recovery_payload(
                factors={"password": True, "second_factor": value}
            )
        )
        with pytest.raises(StepUpTokenInvalidError):
            verify_step_up_token(token, expected_scope=SCOPE_ADMIN_RECOVERY)


def test_verify_admin_recovery_rejects_factors_missing_entirely() -> None:
    """A token without a ``factors`` claim is refused under admin_recovery."""
    token = _encode(_recovery_payload(factors=_UNSET))
    with pytest.raises(StepUpTokenInvalidError):
        verify_step_up_token(token, expected_scope=SCOPE_ADMIN_RECOVERY)


def test_verify_admin_recovery_rejects_factors_not_mapping() -> None:
    """``factors`` must be a JSON object, not a string or list."""
    for value in ("password", ["password"], 1, True):
        token = _encode(_recovery_payload(factors=value))
        with pytest.raises(StepUpTokenInvalidError):
            verify_step_up_token(token, expected_scope=SCOPE_ADMIN_RECOVERY)


def test_verify_admin_recovery_rejects_factors_none_explicit() -> None:
    """``factors=None`` (legacy admin_destructive shape) is refused."""
    token = _encode(_recovery_payload(factors=None))
    with pytest.raises(StepUpTokenInvalidError):
        verify_step_up_token(token, expected_scope=SCOPE_ADMIN_RECOVERY)


def test_verify_admin_recovery_strips_unknown_factor_keys() -> None:
    """Extra keys in ``factors`` MUST NOT bleed into the surfaced claims.

    Defence-in-depth: even if a future caller writes additional fields
    into ``factors``, the verifier exposes only the contract-pinned
    pair so downstream code cannot accidentally key off attacker-
    controlled extras.
    """
    token = _encode(
        _recovery_payload(
            factors={
                "password": True,
                "second_factor": "totp",
                "smuggled": "value",
                "admin": True,
            }
        )
    )
    claims = verify_step_up_token(token, expected_scope=SCOPE_ADMIN_RECOVERY)
    assert claims.factors == {"password": True, "second_factor": "totp"}


# ---------------------------------------------------------------------------
# Scope confusion — both directions
# ---------------------------------------------------------------------------


def test_admin_destructive_token_rejected_when_recovery_expected() -> None:
    """A legacy ``admin_destructive`` token cannot be replayed as recovery."""
    token, _ = issue_step_up_token(
        user_id=uuid4(),
        security_stamp="ss",
        assertion_id="aid",
    )
    with pytest.raises(StepUpTokenScopeMismatchError):
        verify_step_up_token(token, expected_scope=SCOPE_ADMIN_RECOVERY)


def test_admin_recovery_token_rejected_when_destructive_expected() -> None:
    """A recovery token cannot be replayed against a destructive gate."""
    token, _ = issue_admin_recovery_step_up_token(
        user_id=uuid4(),
        security_stamp="ss",
        assertion_id="aid",
        password_verified=True,
        second_factor="totp",
    )
    with pytest.raises(StepUpTokenScopeMismatchError):
        verify_step_up_token(token, expected_scope=SCOPE_ADMIN_DESTRUCTIVE)


def test_admin_destructive_default_still_accepts_legacy_token() -> None:
    """Backwards compatibility: factors=None tokens still verify cleanly."""
    token, _ = issue_step_up_token(
        user_id=uuid4(),
        security_stamp="ss-bc",
        assertion_id="aid-bc",
    )
    # The default ``expected_scope`` is admin_destructive, so the bare
    # call MUST keep working. The legacy path leaves ``factors`` at
    # ``None`` to make the back-compat contract observable.
    claims = verify_step_up_token(token)
    assert claims.scope == SCOPE_ADMIN_DESTRUCTIVE
    assert claims.factors is None


def test_admin_destructive_path_ignores_smuggled_factors_claim() -> None:
    """A smuggled ``factors`` claim under admin_destructive is dropped.

    A buggy or malicious mint that injects ``factors`` into an
    admin_destructive token MUST NOT cause the verifier to *surface*
    those factors — the back-compat contract says ``factors=None`` for
    every non-recovery scope.
    """
    token = _encode(
        _recovery_payload(
            scope=SCOPE_ADMIN_DESTRUCTIVE,
            factors={"password": True, "second_factor": "totp"},
        )
    )
    claims = verify_step_up_token(token, expected_scope=SCOPE_ADMIN_DESTRUCTIVE)
    assert claims.factors is None


# ---------------------------------------------------------------------------
# Revocation — security_stamp rotation + TTL
# ---------------------------------------------------------------------------


def test_admin_recovery_token_revoked_by_security_stamp_rotation() -> None:
    """Rotating ``security_stamp`` invalidates the token at the gate.

    The service helper itself does not consult the user table — that
    check lives in :mod:`echoroo.middleware.step_up` — but the claim
    surface MUST expose the issuance-time ``ss`` value so the middleware
    can compare against the live row. This test pins that exposure.
    """
    token, _ = issue_admin_recovery_step_up_token(
        user_id=uuid4(),
        security_stamp="ss-before-rotation",
        assertion_id="aid",
        password_verified=True,
        second_factor="totp",
    )
    claims = verify_step_up_token(token, expected_scope=SCOPE_ADMIN_RECOVERY)
    # Middleware would compare ``claims.security_stamp`` to
    # ``current_user.security_stamp`` and refuse the request when the
    # two diverge — see ``middleware/step_up.py`` Phase 16 Batch 6h-0.
    assert claims.security_stamp == "ss-before-rotation"
    assert claims.security_stamp != "ss-after-rotation"


def test_admin_recovery_token_rejected_after_ttl_expiry() -> None:
    """A token whose ``exp`` is in the past raises ``StepUpTokenExpiredError``."""
    past = datetime.now(UTC) - timedelta(seconds=600)
    expired_payload = _recovery_payload(
        factors={"password": True, "second_factor": "totp"},
        iat=int(past.timestamp()) - 10,
        exp=int(past.timestamp()),
    )
    expired_token = _encode(expired_payload)
    with pytest.raises(StepUpTokenExpiredError):
        verify_step_up_token(
            expired_token, expected_scope=SCOPE_ADMIN_RECOVERY
        )


def test_admin_recovery_token_rejected_with_wrong_signature() -> None:
    """A token signed with a different secret is refused (signature gate)."""
    s = _settings()
    payload = _recovery_payload(
        factors={"password": True, "second_factor": "totp"}
    )
    forged = jwt.encode(payload, "not-the-real-secret", algorithm=s.JWT_ALGORITHM)
    with pytest.raises(StepUpTokenInvalidError):
        verify_step_up_token(forged, expected_scope=SCOPE_ADMIN_RECOVERY)


def test_admin_recovery_token_rejected_with_wrong_type_claim() -> None:
    """A JWT with ``type != 'step_up'`` is rejected even with valid factors."""
    payload = _recovery_payload(
        type="interim",  # smuggled non-step_up token
        factors={"password": True, "second_factor": "totp"},
    )
    token = _encode(payload)
    with pytest.raises(StepUpTokenInvalidError):
        verify_step_up_token(token, expected_scope=SCOPE_ADMIN_RECOVERY)

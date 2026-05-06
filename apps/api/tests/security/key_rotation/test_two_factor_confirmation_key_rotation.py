"""2FA reset confirmation HMAC key rotation tests (Phase 17 A-12 / FR-091b).

These tests verify the dedicated-key + env-driven ``kid``-versioning
contract for the admin 2FA reset confirmation token introduced in
Phase 17 backlog A-12 (Round 2). The threat model: an attacker who
compromises ``web_session_secret`` must NOT be able to forge admin-reset
confirmation tokens, because that signing key is decoupled and rotated
on its own cadence (OWASP A02 Cryptographic Failures).

Round 2 (Codex review fixes):

* The kid string is **env-driven** — both the kid embedded in newly
  issued tokens (``..._KID_NEW``) and the legacy kid accepted during
  the rotation grace window (``..._KID_OLD``) are env vars. No source
  bump is required to rotate. The ``KID_CURRENT`` / ``KID_LEGACY``
  constants are removed.
* The ``_OLD`` key now has a strong-secret guard equivalent to ``_NEW``
  in production / staging.

Coverage targets:

* Happy path: a freshly issued token verifies under the configured
  ``..._KID_NEW`` env var.
* Real-rotation grace path: a token issued before rotation (kid="v1",
  signed by the old secret) still verifies after rotation when both
  ``..._KID_OLD`` and ``..._HMAC_KEY_OLD`` are set; new tokens are
  issued under kid="v2" signed by the new secret.
* Grace closed: the same kid="v1" token is rejected after the operator
  unsets the ``_OLD`` envs.
* Unknown kid / missing kid / tampered payload+signature reject paths.
* Settings strong-secret guard: production / staging deployments reject
  the dev default + sub-32-char keys for BOTH ``_NEW`` and ``_OLD``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets as py_secrets
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.settings import Settings, get_settings
from echoroo.models.user import User
from echoroo.services.two_factor_confirmation_token import (
    PURPOSE_ADMIN_RESET_2FA,
    ConfirmationTokenInvalidError,
    consume_confirmation_token,
    issue_confirmation_token,
)


async def _make_user(db: AsyncSession, *, email_suffix: str) -> UUID:
    """Create a real users row so the FK on confirmation tokens is satisfied."""
    user = User(
        email=f"a12-{email_suffix}@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$a12-test",
        display_name=f"A12 {email_suffix}",
        security_stamp=py_secrets.token_hex(32),
        two_factor_enabled=True,
        two_factor_secret_encrypted=b"dummy-encrypted-secret",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user.id

# A pair of strong (>= 32 char) test keys. Distinct so we can detect
# accidental key reuse if the wrong slot is consulted during
# verification.
_NEW_KEY = "phase17-a12-new-key-32chars-strong-1234567890"
_OLD_KEY = "phase17-a12-old-key-32chars-strong-0987654321"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_settings_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per-test: clear the ``get_settings`` lru_cache + scrub _OLD env.

    The autouse parent ``conftest.py`` already drops AWS endpoint env
    vars; we additionally:

    * unset both ``_OLD`` env vars (key + kid) so each test starts from
      the no-grace-window baseline (tests that need the grace window
      opt in by setting them explicitly).
    * pin the ``_NEW`` env vars to ``_NEW_KEY`` / ``"v1"`` so the
      currently-issuing kid is deterministic.
    * clear the cache so the new env vars take effect.
    """
    monkeypatch.delenv(
        "TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY_OLD", raising=False
    )
    monkeypatch.delenv(
        "TWO_FACTOR_RESET_CONFIRMATION_HMAC_KID_OLD", raising=False
    )
    monkeypatch.setenv(
        "TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY", _NEW_KEY
    )
    monkeypatch.setenv(
        "TWO_FACTOR_RESET_CONFIRMATION_HMAC_KID_NEW", "v1"
    )
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Test helpers — manually craft a token under an explicit key + kid so we
# can exercise the verifier's grace-window and unknown-kid branches
# without touching the production signing path.
# ---------------------------------------------------------------------------


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _craft_token(
    *,
    user_id: str,
    nonce: str,
    expires_unix: int,
    kid: str | None,
    signing_key: str,
    purpose: str = PURPOSE_ADMIN_RESET_2FA,
) -> str:
    """Mint a wire-format token under arbitrary (kid, key) for tests.

    When ``kid`` is None the ``"k"`` claim is omitted entirely — used
    to exercise the missing-kid reject path.
    """
    payload: dict[str, object] = {
        "u": user_id,
        "p": purpose,
        "n": nonce,
        "x": expires_unix,
    }
    if kid is not None:
        payload["k"] = kid
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload_segment = _b64url_encode(raw)
    sig = hmac.new(
        signing_key.encode("utf-8"),
        payload_segment.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload_segment}.{sig}"


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_issued_with_v1_consumed_with_v1(
    db_session: AsyncSession,
) -> None:
    """A freshly issued token verifies under the configured _KID_NEW key."""
    user_id = await _make_user(db_session, email_suffix="happy")

    token, payload = await issue_confirmation_token(
        db_session, user_id=user_id
    )
    await db_session.commit()

    consumed = await consume_confirmation_token(
        db_session,
        token=token,
        expected_user_id=user_id,
    )
    assert consumed.user_id == user_id
    assert consumed.nonce == payload.nonce
    assert consumed.purpose == PURPOSE_ADMIN_RESET_2FA


# ---------------------------------------------------------------------------
# 2. Real rotation grace path (Round 2 C1 regression)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_real_rotation_grace_with_env_driven_kid(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real rotation: a kid="v1" token issued pre-rotation verifies
    post-rotation via the ``_OLD`` envs, while new tokens are minted
    with kid="v2".

    This is the regression test for Codex Round 1 C1 — the old design
    used hard-coded ``KID_CURRENT="v1"`` / ``KID_LEGACY="v_old"`` and
    so a real env-only rotation (which keeps wire kid="v1" for
    pre-rotation tokens) was silently broken.
    """
    # --- 1. Pre-rotation state: kid="v1" issuing on _NEW_KEY, no grace.
    #     (Already set by the autouse fixture.)
    user_id = await _make_user(db_session, email_suffix="rotation-grace")
    pre_token, pre_payload = await issue_confirmation_token(
        db_session, user_id=user_id
    )
    await db_session.commit()

    # Sanity: the issued token's wire kid is "v1".
    pre_payload_segment, _, _ = pre_token.partition(".")
    pre_decoded = json.loads(
        base64.urlsafe_b64decode(
            pre_payload_segment + "=" * (-len(pre_payload_segment) % 4)
        )
    )
    assert pre_decoded["k"] == "v1"

    # --- 2. Rotate via env vars only:
    #     _NEW becomes (kid="v2", key=_OLD_KEY-as-new), and the previous
    #     pair moves into the _OLD slot (kid="v1", key=_NEW_KEY).
    new_secret_b = "phase17-a12-rotation-secret-b-32chars-xyz"
    monkeypatch.setenv("TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY", new_secret_b)
    monkeypatch.setenv("TWO_FACTOR_RESET_CONFIRMATION_HMAC_KID_NEW", "v2")
    monkeypatch.setenv("TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY_OLD", _NEW_KEY)
    monkeypatch.setenv("TWO_FACTOR_RESET_CONFIRMATION_HMAC_KID_OLD", "v1")
    get_settings.cache_clear()

    # --- 3. Pre-rotation token (kid="v1", signed with _NEW_KEY) must
    #     still verify via the _OLD slot.
    consumed = await consume_confirmation_token(
        db_session,
        token=pre_token,
        expected_user_id=user_id,
    )
    assert consumed.nonce == pre_payload.nonce

    # --- 4. A token issued NOW carries kid="v2" and is signed by
    #     ``new_secret_b``.
    user_id_2 = await _make_user(db_session, email_suffix="rotation-new")
    post_token, _ = await issue_confirmation_token(
        db_session, user_id=user_id_2
    )
    await db_session.commit()
    post_payload_segment, _, _ = post_token.partition(".")
    post_decoded = json.loads(
        base64.urlsafe_b64decode(
            post_payload_segment + "=" * (-len(post_payload_segment) % 4)
        )
    )
    assert post_decoded["k"] == "v2"

    consumed_post = await consume_confirmation_token(
        db_session,
        token=post_token,
        expected_user_id=user_id_2,
    )
    assert consumed_post.user_id == user_id_2


# ---------------------------------------------------------------------------
# 3. Grace window open: legacy-kid token verifies via _OLD pair
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_with_legacy_kid_accepted_during_grace(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy-kid token verifies when both _OLD env vars are set."""
    monkeypatch.setenv(
        "TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY_OLD", _OLD_KEY
    )
    monkeypatch.setenv(
        "TWO_FACTOR_RESET_CONFIRMATION_HMAC_KID_OLD", "v_legacy"
    )
    get_settings.cache_clear()

    # Issue under _KID_NEW to establish the DB nonce row, then rewrite
    # the wire envelope to claim the legacy kid signed by _OLD_KEY.
    user_id = await _make_user(db_session, email_suffix="grace-open")
    _token, payload = await issue_confirmation_token(
        db_session, user_id=user_id
    )
    await db_session.commit()

    legacy_token = _craft_token(
        user_id=str(user_id),
        nonce=payload.nonce,
        expires_unix=int(payload.expires_at.timestamp()),
        kid="v_legacy",
        signing_key=_OLD_KEY,
    )

    consumed = await consume_confirmation_token(
        db_session,
        token=legacy_token,
        expected_user_id=user_id,
    )
    assert consumed.nonce == payload.nonce


# ---------------------------------------------------------------------------
# 4. Grace closed: same legacy-kid token rejected when _OLD is unset
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_with_legacy_kid_rejected_when_grace_closed(
    db_session: AsyncSession,
) -> None:
    """Legacy-kid token rejected when _OLD env vars are unset (grace expired)."""
    user_id = await _make_user(db_session, email_suffix="grace-closed")
    _token, payload = await issue_confirmation_token(
        db_session, user_id=user_id
    )
    await db_session.commit()

    legacy_token = _craft_token(
        user_id=str(user_id),
        nonce=payload.nonce,
        expires_unix=int(payload.expires_at.timestamp()),
        kid="v_legacy",
        signing_key=_OLD_KEY,
    )

    # Autouse fixture already unset _OLD env vars — verifier rejects.
    with pytest.raises(ConfirmationTokenInvalidError) as exc_info:
        await consume_confirmation_token(
            db_session,
            token=legacy_token,
            expected_user_id=user_id,
        )
    # Reject path is "kid is unknown or no longer accepted"
    assert "kid" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# 4b. Half-configured grace (only _KID_OLD set, _KEY_OLD missing) → reject
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_kid_rejected_when_only_kid_env_set(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An operator who sets only _KID_OLD without _KEY_OLD must NOT
    accidentally enable a half-configured grace path. The verifier
    requires BOTH envs to be set.
    """
    monkeypatch.setenv(
        "TWO_FACTOR_RESET_CONFIRMATION_HMAC_KID_OLD", "v_legacy"
    )
    # _KEY_OLD intentionally NOT set.
    get_settings.cache_clear()

    user_id = await _make_user(db_session, email_suffix="half-grace")
    _token, payload = await issue_confirmation_token(
        db_session, user_id=user_id
    )
    await db_session.commit()

    legacy_token = _craft_token(
        user_id=str(user_id),
        nonce=payload.nonce,
        expires_unix=int(payload.expires_at.timestamp()),
        kid="v_legacy",
        signing_key=_OLD_KEY,
    )

    with pytest.raises(ConfirmationTokenInvalidError) as exc_info:
        await consume_confirmation_token(
            db_session,
            token=legacy_token,
            expected_user_id=user_id,
        )
    assert "kid" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# 5. Unknown kid → reject
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_with_unknown_kid_rejected(
    db_session: AsyncSession,
) -> None:
    """Tokens claiming a kid the verifier does not know are rejected."""
    user_id = await _make_user(db_session, email_suffix="unknown-kid")
    _token, payload = await issue_confirmation_token(
        db_session, user_id=user_id
    )
    await db_session.commit()

    bad_token = _craft_token(
        user_id=str(user_id),
        nonce=payload.nonce,
        expires_unix=int(payload.expires_at.timestamp()),
        kid="v99",
        signing_key=_NEW_KEY,
    )

    with pytest.raises(ConfirmationTokenInvalidError) as exc_info:
        await consume_confirmation_token(
            db_session,
            token=bad_token,
            expected_user_id=user_id,
        )
    assert "kid" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# 6. Missing kid claim → reject (no implicit fallback)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_without_kid_claim_rejected(
    db_session: AsyncSession,
) -> None:
    """Tokens without a ``k`` claim are rejected — no legacy fallback."""
    user_id = await _make_user(db_session, email_suffix="no-kid")
    _token, payload = await issue_confirmation_token(
        db_session, user_id=user_id
    )
    await db_session.commit()

    bad_token = _craft_token(
        user_id=str(user_id),
        nonce=payload.nonce,
        expires_unix=int(payload.expires_at.timestamp()),
        kid=None,  # omit "k"
        signing_key=_NEW_KEY,
    )

    with pytest.raises(ConfirmationTokenInvalidError) as exc_info:
        await consume_confirmation_token(
            db_session,
            token=bad_token,
            expected_user_id=user_id,
        )
    assert "kid" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# 7. Tampered payload → reject
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tampered_payload_rejected(
    db_session: AsyncSession,
) -> None:
    """Mutating the payload while keeping the original signature fails."""
    user_id = await _make_user(db_session, email_suffix="tamper-payload")
    token, _ = await issue_confirmation_token(db_session, user_id=user_id)
    await db_session.commit()

    payload_segment, _, signature_segment = token.partition(".")
    # Flip a single byte in the base64 payload.
    flipped = ("A" if payload_segment[0] != "A" else "B") + payload_segment[1:]
    bad_token = f"{flipped}.{signature_segment}"

    with pytest.raises(ConfirmationTokenInvalidError):
        await consume_confirmation_token(
            db_session,
            token=bad_token,
            expected_user_id=user_id,
        )


# ---------------------------------------------------------------------------
# 8. Tampered signature → reject
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tampered_signature_rejected(
    db_session: AsyncSession,
) -> None:
    """Mutating one byte of the hex signature fails the HMAC compare."""
    user_id = await _make_user(db_session, email_suffix="tamper-sig")
    token, _ = await issue_confirmation_token(db_session, user_id=user_id)
    await db_session.commit()

    payload_segment, _, signature_segment = token.partition(".")
    # Flip the last hex char of the signature.
    last = signature_segment[-1]
    new_last = "0" if last != "0" else "1"
    bad_sig = signature_segment[:-1] + new_last
    bad_token = f"{payload_segment}.{bad_sig}"

    with pytest.raises(ConfirmationTokenInvalidError) as exc_info:
        await consume_confirmation_token(
            db_session,
            token=bad_token,
            expected_user_id=user_id,
        )
    assert "signature" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# 9. Settings strong-secret guard rejects weak production keys (_NEW)
# ---------------------------------------------------------------------------


def test_settings_strong_secret_guard_rejects_weak_2fa_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production / staging refuses dev defaults and short keys for the 2FA HMAC.

    The field uses ``validation_alias="TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY"``
    so the env var is the ONLY way to inject the value (kwargs by field
    name are silently ignored). Strong-secret guards for the other
    secrets are satisfied via env vars too so the validator reaches the
    A-12 branch we want to exercise.
    """
    # Set the strong-secret context for OTHER fields so the validator
    # reaches the new A-12 branch instead of failing earlier.
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 64)
    monkeypatch.setenv("S3_SECRET_KEY", "real-secret")

    # 1. Dev default literal must be rejected.
    monkeypatch.setenv(
        "TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY",
        "dev-two-factor-confirmation-hmac-change-in-production",
    )
    with pytest.raises(ValueError, match="two_factor_reset_confirmation_hmac_key"):
        Settings(web_session_secret="y" * 64)

    # 2. Sub-32-char custom key must also be rejected.
    monkeypatch.setenv("TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY", "short")
    with pytest.raises(ValueError, match="two_factor_reset_confirmation_hmac_key"):
        Settings(web_session_secret="y" * 64)

    # 3. A strong, custom key must be accepted.
    monkeypatch.setenv("TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY", "z" * 32)
    settings = Settings(web_session_secret="y" * 64)
    assert settings.two_factor_reset_confirmation_hmac_key == "z" * 32


# ---------------------------------------------------------------------------
# 10. Settings strong-secret guard rejects weak _OLD keys (Round 2 C2)
# ---------------------------------------------------------------------------


def test_settings_old_key_strong_secret_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_OLD``, when set, must also pass the strong-secret bar.

    Codex Round 1 C2: leaving a weak default in the ``_OLD`` slot during
    rotation lets an attacker forge tokens via the legacy verify path.
    """
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("JWT_SECRET_KEY", "x" * 64)
    monkeypatch.setenv("S3_SECRET_KEY", "real-secret")
    # Strong _NEW so we reach the _OLD branch.
    monkeypatch.setenv("TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY", "z" * 64)

    # 1. Dev default literal in _OLD must be rejected.
    monkeypatch.setenv(
        "TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY_OLD",
        "dev-two-factor-confirmation-hmac-change-in-production",
    )
    with pytest.raises(
        ValueError, match="two_factor_reset_confirmation_hmac_key_old"
    ):
        Settings(web_session_secret="y" * 64)

    # 2. Sub-32-char in _OLD must be rejected.
    monkeypatch.setenv(
        "TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY_OLD", "short"
    )
    with pytest.raises(
        ValueError, match="two_factor_reset_confirmation_hmac_key_old"
    ):
        Settings(web_session_secret="y" * 64)

    # 3. A strong _OLD value must be accepted.
    monkeypatch.setenv(
        "TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY_OLD", "w" * 48
    )
    settings = Settings(web_session_secret="y" * 64)
    assert settings.two_factor_reset_confirmation_hmac_key_old == "w" * 48

    # 4. _OLD unset / empty string is treated as "no rotation in
    #    progress" and does NOT trip the guard.
    monkeypatch.delenv("TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY_OLD")
    settings = Settings(web_session_secret="y" * 64)
    assert settings.two_factor_reset_confirmation_hmac_key_old is None

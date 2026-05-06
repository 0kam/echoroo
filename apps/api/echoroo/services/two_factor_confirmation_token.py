"""Confirmation tokens for the admin 2FA reset flow (Phase 17 A-11).

The admin reset endpoint (``POST /admin/users/{userId}/reset-2fa``)
requires the operator to attach a *confirmation token* that proves the
user already redeemed an emailed magic link in the last few minutes.
This module owns the lifecycle of that token:

* :func:`issue_confirmation_token` — call from the magic-link redeem
  handler. Generates a fresh nonce, persists a
  :class:`~echoroo.models.two_factor_reset_request.TwoFactorConfirmationToken`
  row with ``used_at = NULL``, and returns the encoded token string.
* :func:`consume_confirmation_token` — call from the admin reset
  handler BEFORE mutating any state. Verifies the HMAC signature, the
  embedded ``user_id`` / ``purpose`` / ``expires_at`` claims, and
  atomically flips the nonce row to ``used_at = now()``. Returns the
  consumed nonce string so the caller can audit it.

Why HMAC + DB nonce (instead of one or the other)?

* HMAC alone (à la JWT) makes the token self-contained and lets us
  ditch the DB row, but it leaves no audit trail and forces us to
  re-implement one-time-use with a Redis NX lock.
* DB nonce alone (opaque random string) requires a SELECT every redeem
  and offers no protection against an attacker who steals the
  ``two_factor_confirmation_tokens`` row contents — they could craft a
  token by simply quoting the nonce.

The combination gives us forensic auditability (the nonce is the
``confirmation_token_nonce`` recorded on
``two_factor_reset_requests``) AND tamper resistance (the HMAC binds
the nonce to the issuing user / purpose / expires_at and is signed by
``settings.two_factor_reset_confirmation_hmac_key``).

Token wire format
=================
``base64url(payload).hex_signature`` where ``payload`` is the
URL-safe-base64 of the canonical JSON:

    {"u": <user_id>, "p": <purpose>, "n": <nonce>,
     "x": <expires_unix>, "k": <kid>}

The signature is HMAC-SHA256 over ``payload`` (the base64 segment, not
the canonical JSON) using the key resolved from the ``k`` (kid) claim.
Hex encoding keeps it compact and avoids '+'/'/' padding.

Key rotation (Phase 17 backlog A-12 / FR-091b / OWASP A02)
==========================================================
The signing key is dedicated — separate from ``web_session_secret`` —
so a session-secret leak does NOT also forge admin-reset confirmation
tokens. The kid claim is **env-driven** (Round 2): both the kid string
embedded in newly issued tokens AND the kid accepted from previously
issued tokens during a rotation grace window are configured via
environment variables (``TWO_FACTOR_RESET_CONFIRMATION_HMAC_KID_NEW``
and ``TWO_FACTOR_RESET_CONFIRMATION_HMAC_KID_OLD``). This lets an
operator complete a rotation by changing env vars only — no source
bump required.

During a rotation, both ``_NEW`` and ``_OLD`` env pairs are set; the
verifier tries the current pair first then the legacy pair. Tokens
missing the ``k`` claim are rejected outright — no implicit fallback to
a default key (the 5 min TTL keeps the rolling-deploy blast radius
bounded). See ``docs/runbook/two_factor_confirmation_key_rotation.md``.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.settings import get_settings
from echoroo.models.two_factor_reset_request import TwoFactorConfirmationToken

#: Lifetime of a confirmation token. Short by design — the operator
#: should redeem the magic link, paste the token into the admin form,
#: and submit within minutes. Anything longer widens the window during
#: which a leaked token can be replayed.
CONFIRMATION_TOKEN_TTL = timedelta(minutes=5)

#: Logical purpose claim. Future flows (e.g. backup-code reset) can
#: use the same plumbing with a different purpose string.
PURPOSE_ADMIN_RESET_2FA = "admin_reset_2fa"

#: Nonce length in bytes — translates to 64 hex chars after
#: ``token_hex(32)`` so we can store the result in a ``VARCHAR(64)``
#: column without truncation.
_NONCE_BYTES = 32

class ConfirmationTokenError(Exception):
    """Base error for confirmation-token operations."""


class ConfirmationTokenInvalidError(ConfirmationTokenError):
    """Raised when the token signature, structure, or claims are invalid."""


class ConfirmationTokenExpiredError(ConfirmationTokenError):
    """Raised when the token's ``expires_at`` is in the past."""


class ConfirmationTokenAlreadyConsumedError(ConfirmationTokenError):
    """Raised when the nonce row was already marked ``used_at``."""


class ConfirmationTokenUserMismatchError(ConfirmationTokenError):
    """Raised when the embedded user_id does not match the expected target."""


@dataclass(frozen=True)
class ConfirmationTokenPayload:
    """Validated confirmation-token claims, returned by :func:`consume_confirmation_token`."""

    user_id: UUID
    purpose: str
    nonce: str
    expires_at: datetime


def _current_kid() -> str:
    """Return the kid string to embed in newly issued tokens.

    Read from ``settings.two_factor_reset_confirmation_hmac_kid_new`` so
    a rotation only requires env var changes (no source-code bump).
    """
    return get_settings().two_factor_reset_confirmation_hmac_kid_new


def _signing_key_for(kid: str) -> bytes | None:
    """Resolve the HMAC signing key for ``kid``; return ``None`` if unknown.

    The mapping is **fully env-driven** (Phase 17 A-12 Round 2) — the
    operator never has to touch source code to rotate. Resolution order:

      1. ``kid == settings.two_factor_reset_confirmation_hmac_kid_new``
         → ``settings.two_factor_reset_confirmation_hmac_key`` (the
         currently-issuing key; always configured and backed by a
         strong-secret guard in production / staging).

      2. ``kid == settings.two_factor_reset_confirmation_hmac_kid_old``
         → ``settings.two_factor_reset_confirmation_hmac_key_old`` —
         only when BOTH the legacy kid env AND the legacy key env are
         set (i.e. an active rotation grace window). Either one missing
         or empty closes the grace window and the verifier rejects.

      3. Otherwise → ``None`` (caller MUST reject the token).

    Rotation procedure (env only):

    * Start state: ``_KID_NEW="v1"``, ``_HMAC_KEY=secret_a``,
      ``_KID_OLD`` unset, ``_HMAC_KEY_OLD`` unset.
    * Step into rotation: ``_KID_NEW="v2"``, ``_HMAC_KEY=secret_b``,
      ``_KID_OLD="v1"``, ``_HMAC_KEY_OLD=secret_a``. New tokens carry
      ``k="v2"``; in-flight ``k="v1"`` tokens still verify via the
      legacy slot. Restart workers.
    * Close grace: unset ``_KID_OLD`` and ``_HMAC_KEY_OLD``. Restart
      workers. ``k="v1"`` tokens now reject as unknown.
    """
    settings = get_settings()
    new_kid = settings.two_factor_reset_confirmation_hmac_kid_new
    if kid == new_kid:
        return settings.two_factor_reset_confirmation_hmac_key.encode("utf-8")
    old_kid = settings.two_factor_reset_confirmation_hmac_kid_old
    old_key = settings.two_factor_reset_confirmation_hmac_key_old
    if old_kid and old_key and kid == old_kid:
        return old_key.encode("utf-8")
    # Unknown kid — either malformed/forged OR the operator has closed
    # the rotation grace window. Both cases fail closed.
    return None


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(encoded: str) -> bytes:
    padded = encoded + ("=" * (-len(encoded) % 4))
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _sign(payload_segment: str, *, kid: str) -> str:
    """Sign ``payload_segment`` with the key bound to ``kid``.

    Raises :class:`ConfirmationTokenInvalidError` when ``kid`` cannot be
    resolved to a configured key — this is the single fail-closed entry
    point for unknown / grace-expired key identifiers on the *signing*
    side. Verification has its own explicit reject path.
    """
    key = _signing_key_for(kid)
    if key is None:
        raise ConfirmationTokenInvalidError(
            f"unknown or unconfigured confirmation token kid: {kid!r}"
        )
    mac = hmac.new(key, payload_segment.encode("ascii"), hashlib.sha256)
    return mac.hexdigest()


def _serialize_payload(
    *,
    user_id: UUID,
    purpose: str,
    nonce: str,
    expires_at: datetime,
    kid: str,
) -> str:
    canonical: dict[str, Any] = {
        "u": str(user_id),
        "p": purpose,
        "n": nonce,
        "x": int(expires_at.timestamp()),
        "k": kid,
    }
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _b64url_encode(raw)


def _parse_payload(payload_segment: str) -> dict[str, Any]:
    try:
        raw = _b64url_decode(payload_segment)
    except (binascii.Error, ValueError) as exc:
        raise ConfirmationTokenInvalidError("payload is not valid base64url") from exc
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfirmationTokenInvalidError("payload is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise ConfirmationTokenInvalidError("payload is not a JSON object")
    return decoded


async def issue_confirmation_token(
    db: AsyncSession,
    *,
    user_id: UUID,
    purpose: str = PURPOSE_ADMIN_RESET_2FA,
    now: datetime | None = None,
) -> tuple[str, ConfirmationTokenPayload]:
    """Issue a fresh confirmation token bound to ``user_id`` / ``purpose``.

    The caller is responsible for ``await db.commit()`` — we add the
    nonce row to the session but do not commit, so the token write is
    atomic with whatever else the caller is doing (e.g. flipping the
    magic-link row to ``redeemed_at``).

    Returns the encoded token string AND the structured claims so the
    caller can echo ``expires_at`` back to the operator and stash the
    nonce in any audit envelope.
    """
    issued_at = now or datetime.now(UTC)
    expires_at = issued_at + CONFIRMATION_TOKEN_TTL
    nonce = secrets.token_hex(_NONCE_BYTES)

    db.add(
        TwoFactorConfirmationToken(
            user_id=user_id,
            nonce=nonce,
            purpose=purpose,
            expires_at=expires_at,
            issued_at=issued_at,
        )
    )

    issuing_kid = _current_kid()
    payload_segment = _serialize_payload(
        user_id=user_id,
        purpose=purpose,
        nonce=nonce,
        expires_at=expires_at,
        kid=issuing_kid,
    )
    signature = _sign(payload_segment, kid=issuing_kid)
    token = f"{payload_segment}.{signature}"
    return token, ConfirmationTokenPayload(
        user_id=user_id,
        purpose=purpose,
        nonce=nonce,
        expires_at=expires_at,
    )


async def consume_confirmation_token(
    db: AsyncSession,
    *,
    token: str,
    expected_user_id: UUID,
    expected_purpose: str = PURPOSE_ADMIN_RESET_2FA,
    now: datetime | None = None,
) -> ConfirmationTokenPayload:
    """Verify, atomically consume, and return the claims of ``token``.

    Failure modes (each raises a distinct subclass so the caller can
    map to the right HTTP status):

    * :class:`ConfirmationTokenInvalidError` — signature mismatch,
      malformed segments, missing claims, purpose mismatch.
    * :class:`ConfirmationTokenUserMismatchError` — the embedded
      ``user_id`` does not equal ``expected_user_id``.
    * :class:`ConfirmationTokenExpiredError` — ``expires_at < now()``.
    * :class:`ConfirmationTokenAlreadyConsumedError` — the nonce row
      was already marked ``used_at`` (covers replay).

    Atomic one-time-use is enforced by ``UPDATE ... WHERE used_at IS
    NULL RETURNING id``: a concurrent second redeem of the same nonce
    sees zero rows and we raise the consumed error.
    """
    if not isinstance(token, str) or "." not in token:
        raise ConfirmationTokenInvalidError("token is missing payload/signature segments")

    payload_segment, _, signature_segment = token.partition(".")
    if not payload_segment or not signature_segment:
        raise ConfirmationTokenInvalidError("token segments are empty")

    # Parse the payload BEFORE signature verification so we can resolve
    # the kid → key. We treat structural / claim errors as
    # ``ConfirmationTokenInvalidError`` regardless of which key would
    # have signed them, because a malformed envelope cannot be a valid
    # token under ANY key.
    decoded = _parse_payload(payload_segment)
    try:
        token_user_id = UUID(str(decoded["u"]))
        purpose = str(decoded["p"])
        nonce = str(decoded["n"])
        expires_unix = int(decoded["x"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfirmationTokenInvalidError("token claims are malformed") from exc

    # Phase 17 A-12: ``k`` (kid) is REQUIRED. Tokens minted before the
    # rotation contract landed do not exist in production (5 min TTL),
    # so there is no legacy unsigned-kid path to support. Rejecting
    # outright keeps the verifier simple and prevents an attacker from
    # downgrading to an implicit default key.
    raw_kid = decoded.get("k")
    if not isinstance(raw_kid, str) or not raw_kid:
        raise ConfirmationTokenInvalidError("token is missing kid claim")
    signing_key = _signing_key_for(raw_kid)
    if signing_key is None:
        # Either the kid is unknown to this build OR it points at the
        # legacy slot but the operator has unset the ``_OLD`` env var
        # (grace window closed). Both cases fail closed.
        raise ConfirmationTokenInvalidError(
            f"token kid {raw_kid!r} is unknown or no longer accepted"
        )
    expected_signature = hmac.new(
        signing_key, payload_segment.encode("ascii"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(expected_signature, signature_segment.lower()):
        raise ConfirmationTokenInvalidError("token signature mismatch")

    if purpose != expected_purpose:
        raise ConfirmationTokenInvalidError(
            f"token purpose mismatch (got {purpose!r}, expected {expected_purpose!r})"
        )
    if token_user_id != expected_user_id:
        raise ConfirmationTokenUserMismatchError(
            "token user_id does not match the target user"
        )

    expires_at = datetime.fromtimestamp(expires_unix, tz=UTC)
    current = now or datetime.now(UTC)
    if expires_at <= current:
        raise ConfirmationTokenExpiredError("token has expired")

    # Atomic one-time-use guard. Locate the row by nonce + user_id +
    # purpose so a token leaked across users / purposes still fails
    # closed even if the HMAC verifies (defence in depth).
    result = await db.execute(
        text(
            """
            UPDATE two_factor_confirmation_tokens
               SET used_at = :now
             WHERE nonce = :nonce
               AND user_id = :user_id
               AND purpose = :purpose
               AND used_at IS NULL
               AND expires_at > :now
            RETURNING id
            """
        ),
        {
            "now": current,
            "nonce": nonce,
            "user_id": expected_user_id,
            "purpose": expected_purpose,
        },
    )
    row = result.first()
    if row is None:
        # Either the row never existed (HMAC verified but the nonce was
        # forged), the row is already used, or it has expired in the
        # microseconds since the in-memory check above.
        existing = await db.execute(
            select(TwoFactorConfirmationToken).where(
                TwoFactorConfirmationToken.nonce == nonce
            )
        )
        record = existing.scalar_one_or_none()
        if record is None:
            raise ConfirmationTokenInvalidError("token nonce is not recognised")
        if record.used_at is not None:
            raise ConfirmationTokenAlreadyConsumedError("token has already been consumed")
        raise ConfirmationTokenExpiredError("token has expired")

    return ConfirmationTokenPayload(
        user_id=expected_user_id,
        purpose=expected_purpose,
        nonce=nonce,
        expires_at=expires_at,
    )


__all__ = [
    "CONFIRMATION_TOKEN_TTL",
    "ConfirmationTokenAlreadyConsumedError",
    "ConfirmationTokenError",
    "ConfirmationTokenExpiredError",
    "ConfirmationTokenInvalidError",
    "ConfirmationTokenPayload",
    "ConfirmationTokenUserMismatchError",
    "PURPOSE_ADMIN_RESET_2FA",
    "consume_confirmation_token",
    "issue_confirmation_token",
]

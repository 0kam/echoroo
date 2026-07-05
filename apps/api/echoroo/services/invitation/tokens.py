"""Hashing / token helpers (FR-051, FR-052, FR-055).

Token shape (FR-052, spec/011 NFR-011-010):

* The raw 256-bit token is generated with :func:`secrets.token_bytes`,
  base64url-encoded for the URL.
* The DB row stores the **SHA-256 hex digest** in ``token_hash`` so an
  attacker who reads the table cannot forge a redeem URL.
* The URL token is an HMAC-SHA-256 envelope (spec/011 step 6 widened it
  from 3-part to 4-part to carry a ``kid``)::

      {raw_token_b64u}.{expires_at_unix}.{kid}.{mac_b64u}

  MAC = ``HMAC-SHA-256(secret_for(kid), raw || "." || expires || "." || kid)``.
  Verification is constant-time (:func:`hmac.compare_digest`).
* During the rotation grace window verifiers also accept (a) 4-part
  envelopes whose ``kid`` matches ``INVITATION_TOKEN_KID_OLD`` and (b)
  3-part legacy envelopes signed under the legacy ``HMAC_KEY_OLD`` key
  while ``now < created_at + 7d + GRACE_HOURS``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import UTC, datetime, timedelta

from echoroo.core.settings import get_settings

from .errors import InvitationTokenInvalidError


def _b64u_encode(data: bytes) -> str:
    """URL-safe base64 with no padding (RFC 4648 §5)."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64u_decode(value: str) -> bytes:
    """Tolerant URL-safe base64 decoder (re-pads to multiple of 4)."""
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_token(raw_token_b64u: str) -> str:
    """Return the SHA-256 hex digest of the raw token (DB ``token_hash``)."""
    return hashlib.sha256(raw_token_b64u.encode("ascii")).hexdigest()


def _ensure_utc(value: datetime) -> datetime:
    """Return ``value`` converted to UTC.

    Naive datetimes are interpreted as UTC (defence in depth — every
    persisted ``expires_at`` is ``timestamptz`` so this branch should
    never fire in production). Aware datetimes are normalised via
    :meth:`datetime.astimezone`, which preserves the absolute instant
    (the prior implementation used ``replace(tzinfo=UTC)`` which would
    silently shift a non-UTC value by its offset).
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _mac_invitation_token_legacy(
    *,
    raw_token_b64u: str,
    expires_at_unix: int,
    hmac_secret: str,
) -> str:
    """Return the legacy 3-part HMAC over ``{raw}.{exp}``.

    Used during the spec/011 grace window to verify 3-part envelopes
    issued before the kid extension landed (NFR-011-010 path (b)).
    """
    payload = f"{raw_token_b64u}.{expires_at_unix}".encode("ascii")
    mac = hmac.new(hmac_secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return _b64u_encode(mac)


def _mac_invitation_token_v2(
    *,
    raw_token_b64u: str,
    expires_at_unix: int,
    kid: str,
    hmac_secret: str,
) -> str:
    """Return the 4-part HMAC over ``{raw}.{exp}.{kid}`` (spec/011 step 6).

    The MAC inputs cover the kid so an attacker cannot swap a 4-part
    envelope's ``kid`` slot to point at a more-permissive key without
    invalidating the signature.
    """
    payload = f"{raw_token_b64u}.{expires_at_unix}.{kid}".encode("ascii")
    mac = hmac.new(hmac_secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return _b64u_encode(mac)


def sign_invitation_token(
    *,
    raw_token_b64u: str,
    expires_at: datetime,
    hmac_secret: str | None = None,
) -> str:
    """Produce the 4-part ``{token}.{exp}.{kid}.{mac}`` envelope.

    The envelope is signed under the NEW kid declared in
    ``settings.INVITATION_TOKEN_KID_NEW`` with the matching HMAC key
    ``INVITATION_TOKEN_HMAC_KEY`` (spec/011 NFR-011-010). The
    ``hmac_secret`` keyword is preserved for backward compatibility with
    historical callers (it is now ignored — Step 6 routes the signing
    secret exclusively through the env-driven kid pair so a rotation
    only needs env var changes, never source bumps).
    """
    settings = get_settings()
    kid = settings.invitation_token_kid_new
    key = settings.invitation_token_hmac_key
    # ``hmac_secret`` is intentionally accepted but ignored — kept on the
    # signature so legacy unit tests that pre-date the env-driven
    # rotation keep parsing without a flag day.
    del hmac_secret
    expires_at_unix = int(_ensure_utc(expires_at).timestamp())
    mac = _mac_invitation_token_v2(
        raw_token_b64u=raw_token_b64u,
        expires_at_unix=expires_at_unix,
        kid=kid,
        hmac_secret=key,
    )
    return f"{raw_token_b64u}.{expires_at_unix}.{kid}.{mac}"


def verify_invitation_token(
    signed_token: str,
    *,
    hmac_secret: str | None = None,
    now: datetime | None = None,
) -> tuple[str, datetime]:
    """Decode and verify a signed invitation token (spec/011 NFR-011-010).

    Accepts either:

    * A 4-part envelope ``{raw}.{exp}.{kid}.{mac}`` whose ``kid`` matches
      ``INVITATION_TOKEN_KID_NEW`` (preferred) or ``INVITATION_TOKEN_KID_OLD``
      (during the rotation grace window). The HMAC key is routed by the
      kid so a stolen OLD-kid envelope cannot upgrade itself to NEW.
    * A 3-part legacy envelope ``{raw}.{exp}.{mac}`` whose MAC verifies
      under ``INVITATION_TOKEN_HMAC_KEY_OLD`` IFF
      ``now < expires_at + INVITATION_TOKEN_KID_GRACE_HOURS``. Legacy
      acceptance requires the ``_OLD`` slot to be configured — refusal
      to start is enforced by ``Settings._validate_production_secrets``.

    Returns ``(raw_token_b64u, expires_at)`` on success.

    Raises :class:`InvitationTokenInvalidError` on any failure (missing
    parts, unknown kid, MAC mismatch, expiry past, legacy envelope
    outside grace). The error class is deliberately narrow so the
    endpoint can map every signal to the same generic-invalid HTTP
    response (FR-055 / FR-011-107 enumeration mitigation). All MAC
    comparisons go through :func:`hmac.compare_digest` (NFR-011-003).
    """
    del hmac_secret  # legacy keyword preserved for compatibility (ignored)
    settings = get_settings()
    now_eff = now or datetime.now(UTC)

    parts = signed_token.split(".")
    if len(parts) == 4:
        raw_token_b64u, expires_at_str, kid, mac_b64u = parts
        try:
            expires_at_unix = int(expires_at_str)
        except ValueError as exc:
            raise InvitationTokenInvalidError(
                "invalid expiry component",
            ) from exc

        # Route by kid. We compute the candidate MAC ONLY for the
        # matching kid so a stolen OLD-kid envelope cannot probe the NEW
        # key (defence in depth — the MAC inputs already cover the kid,
        # so a swap would not verify, but routing keeps the timing
        # signature uniform).
        if kid == settings.invitation_token_kid_new:
            expected_key = settings.invitation_token_hmac_key
        elif (
            settings.invitation_token_kid_old is not None
            and kid == settings.invitation_token_kid_old
        ):
            old_key = settings.invitation_token_hmac_key_old
            if old_key is None:  # pragma: no cover — co-presence guard
                raise InvitationTokenInvalidError(
                    "invitation token signed under retired kid",
                )
            expected_key = old_key
        else:
            raise InvitationTokenInvalidError(
                "invitation token signed under unknown kid",
            )

        expected_mac = _mac_invitation_token_v2(
            raw_token_b64u=raw_token_b64u,
            expires_at_unix=expires_at_unix,
            kid=kid,
            hmac_secret=expected_key,
        )
        if not hmac.compare_digest(expected_mac, mac_b64u):
            raise InvitationTokenInvalidError(
                "invitation token signature mismatch",
            )

        expires_at = datetime.fromtimestamp(expires_at_unix, tz=UTC)
        if now_eff >= expires_at:
            raise InvitationTokenInvalidError("invitation token has expired")
        return raw_token_b64u, expires_at

    if len(parts) == 3:
        # Legacy 3-part envelope (spec/011 NFR-011-010 (b)): verify under
        # the OLD key during the grace window. ``KID_OLD`` MUST be set
        # for this path — the settings co-presence guard ensures it.
        old_key = settings.invitation_token_hmac_key_old
        if old_key is None:
            raise InvitationTokenInvalidError(
                "legacy invitation token rejected: rotation OLD key unset",
            )
        raw_token_b64u, expires_at_str, mac_b64u = parts
        try:
            expires_at_unix = int(expires_at_str)
        except ValueError as exc:
            raise InvitationTokenInvalidError(
                "invalid expiry component",
            ) from exc
        expected_mac = _mac_invitation_token_legacy(
            raw_token_b64u=raw_token_b64u,
            expires_at_unix=expires_at_unix,
            hmac_secret=old_key,
        )
        if not hmac.compare_digest(expected_mac, mac_b64u):
            raise InvitationTokenInvalidError(
                "invitation token signature mismatch",
            )
        expires_at = datetime.fromtimestamp(expires_at_unix, tz=UTC)
        # Reject past TTL + grace window. The grace window extends past
        # the envelope's ``expires_at`` so a 3-part token that was 1
        # minute from natural expiry at deploy time remains verifiable
        # until ``expires_at + GRACE_HOURS``.
        #
        # Equivalence with NFR-011-010(b)'s wording ("now < created_at +
        # 7d + GRACE_HOURS"): for any legitimately-issued legacy token
        # the envelope's ``expires_at`` equals ``created_at + 7d`` (the
        # canonical invitation TTL set at issuance), so the two
        # formulas yield the same admit/reject boundary. They diverge
        # only if an attacker controls the OLD HMAC key and re-signs an
        # envelope with a forged ``expires_at``; in that scenario the
        # system is already fully compromised (any unexpired raw token
        # plus the key lets the attacker accept) and the DB-row-time
        # formula buys no additional defence. We keep the envelope
        # formula because (a) the DB row is not yet fetched at this
        # validation layer (token-hash lookup happens in
        # ``redeem_invitation_token``) and (b) every existing caller
        # expects ``expires_at``-based behaviour.
        grace = timedelta(hours=settings.invitation_token_kid_grace_hours)
        if now_eff >= expires_at + grace:
            raise InvitationTokenInvalidError(
                "legacy invitation token outside grace window",
            )
        return raw_token_b64u, expires_at

    raise InvitationTokenInvalidError("malformed invitation token")

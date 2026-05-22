"""spec/011 NFR-011-010 — invitation token kid rotation security.

Verifies that ``services.invitation_service.{sign,verify}_invitation_token``
honours the env-driven kid rotation pattern from Phase 17 A-12:

* **Planned rotation** — a fresh deploy issues 4-part envelopes under
  ``INVITATION_TOKEN_KID_NEW`` and verifies them. Switching ``KID_NEW`` /
  ``HMAC_KEY`` (with the previous values dropped into ``_OLD``)
  continues to verify in-flight envelopes signed under the old kid for
  the active 7-day TTL plus the configured grace window.
* **Emergency rotation** — the same plan compressed: an operator rotates
  ``KID_NEW`` mid-flight, MUST keep ``_OLD`` populated, MUST drop both
  ``_OLD`` slots only after the grace window elapses.
* **Legacy 3-part envelopes within grace** — verifiers accept the
  ``{raw}.{exp}.{mac}`` shape iff the MAC verifies under
  ``HMAC_KEY_OLD`` and ``now < expires_at + GRACE_HOURS``.
* **Legacy 3-part envelopes outside grace** — rejected with the generic
  invalid error (FR-055 / FR-011-107 enumeration mitigation).
* **Kid mismatch** — a 4-part envelope whose ``kid`` field references a
  kid that is neither ``_NEW`` nor ``_OLD`` is rejected with the same
  generic error. (A swapped ``kid`` would also fail the MAC check
  because the MAC inputs include the kid; the explicit kid routing is
  defence in depth.)

All MAC comparisons in the service use :func:`hmac.compare_digest` to
satisfy NFR-011-003. The tests do not call the live ``compare_digest``
directly — they exercise the verifier surface end-to-end and assert
the public error class.
"""

from __future__ import annotations

import base64
import hashlib
import hmac as hmac_mod
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest

from echoroo.core.settings import get_settings
from echoroo.services.invitation_service import (
    InvitationTokenInvalidError,
    sign_invitation_token,
    verify_invitation_token,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_RAW_TOKEN = "raw-token-b64u-stub-for-tests-AAAA"
_NEW_HMAC_KEY = "spec011-step6-rotation-key-32chars-OK!!"
_OLD_HMAC_KEY = "spec011-step6-rotation-key-OLD-32chars!"
_THIRD_HMAC_KEY = "spec011-step6-rotation-key-XXX-32chars!"
_NEW_KID = "kid_new_step6"
_OLD_KID = "kid_old_step6"


def _b64u_encode(data: bytes) -> str:
    """Mirror of ``invitation_service._b64u_encode`` for hand-crafted envelopes."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _legacy_3part_envelope(*, raw: str, expires_at: datetime, key: str) -> str:
    """Build a legacy 3-part envelope under ``key``.

    Mirrors the pre-Step-6 ``sign_invitation_token`` exactly so the
    verifier under test sees the same byte sequence a pre-rotation
    deployment would have emitted.
    """
    exp = int(expires_at.replace(tzinfo=UTC).timestamp())
    payload = f"{raw}.{exp}".encode("ascii")
    mac = hmac_mod.new(key.encode("utf-8"), payload, hashlib.sha256).digest()
    return f"{raw}.{exp}.{_b64u_encode(mac)}"


def _v2_envelope_with_arbitrary_kid(
    *, raw: str, expires_at: datetime, kid: str, key: str
) -> str:
    """Sign a 4-part envelope under an arbitrary (kid, key) pair.

    Used to exercise the kid-routing branch: an attacker holding a
    forgery under a never-deployed kid MUST be rejected even when the
    MAC inputs are internally consistent.
    """
    exp = int(expires_at.replace(tzinfo=UTC).timestamp())
    payload = f"{raw}.{exp}.{kid}".encode("ascii")
    mac = hmac_mod.new(key.encode("utf-8"), payload, hashlib.sha256).digest()
    return f"{raw}.{exp}.{kid}.{_b64u_encode(mac)}"


@pytest.fixture(autouse=True)
def _isolate_invitation_token_env(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Reset the env between cases so the lru_cache'd Settings reloads cleanly."""
    for name in (
        "INVITATION_TOKEN_KID_NEW",
        "INVITATION_TOKEN_KID_OLD",
        "INVITATION_TOKEN_HMAC_KEY",
        "INVITATION_TOKEN_HMAC_KEY_OLD",
        "INVITATION_TOKEN_KID_GRACE_HOURS",
    ):
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _activate_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    kid_new: str = _NEW_KID,
    hmac_key: str = _NEW_HMAC_KEY,
    kid_old: str | None = None,
    hmac_key_old: str | None = None,
    grace_hours: int = 24,
) -> None:
    """Apply env + drop the Settings lru_cache."""
    monkeypatch.setenv("INVITATION_TOKEN_KID_NEW", kid_new)
    monkeypatch.setenv("INVITATION_TOKEN_HMAC_KEY", hmac_key)
    if kid_old is not None:
        monkeypatch.setenv("INVITATION_TOKEN_KID_OLD", kid_old)
    if hmac_key_old is not None:
        monkeypatch.setenv("INVITATION_TOKEN_HMAC_KEY_OLD", hmac_key_old)
    monkeypatch.setenv(
        "INVITATION_TOKEN_KID_GRACE_HOURS", str(grace_hours)
    )
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Planned + emergency rotation — 4-part envelope round-trip
# ---------------------------------------------------------------------------


def test_planned_rotation_new_kid_envelope_round_trips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fresh-deploy 4-part envelope verifies under the current NEW kid."""
    _activate_settings(monkeypatch)
    expires_at = datetime.now(UTC) + timedelta(days=1)
    envelope = sign_invitation_token(
        raw_token_b64u=_RAW_TOKEN, expires_at=expires_at,
    )
    assert envelope.count(".") == 3, (
        f"expected 4-part envelope, got {envelope!r}"
    )
    raw, exp = verify_invitation_token(envelope)
    assert raw == _RAW_TOKEN
    # Wall-clock equality is allowed to drift by the int-truncated
    # second boundary; assert with a 2s tolerance.
    assert abs((exp - expires_at).total_seconds()) <= 2


def test_planned_rotation_old_kid_envelope_still_verifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An envelope signed under the previous kid keeps verifying after rotation.

    Scenario: an admin issued an invitation pre-rotation. The operator
    later rotated to ``KID_NEW`` and dropped the prior key into
    ``HMAC_KEY_OLD``. The recipient opens the URL during the 7-day TTL
    plus grace window — the verifier MUST route on the envelope's
    embedded kid and accept.
    """
    # Pre-rotation: sign with the OLD kid.
    _activate_settings(
        monkeypatch,
        kid_new=_OLD_KID,
        hmac_key=_OLD_HMAC_KEY,
    )
    expires_at = datetime.now(UTC) + timedelta(days=6)
    envelope = sign_invitation_token(
        raw_token_b64u=_RAW_TOKEN, expires_at=expires_at,
    )
    # Post-rotation: the prior kid moves into ``_OLD``.
    _activate_settings(
        monkeypatch,
        kid_new=_NEW_KID,
        hmac_key=_NEW_HMAC_KEY,
        kid_old=_OLD_KID,
        hmac_key_old=_OLD_HMAC_KEY,
    )
    raw, _ = verify_invitation_token(envelope)
    assert raw == _RAW_TOKEN


def test_emergency_rotation_compressed_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Emergency rotation: drop the previous key into ``_OLD`` and re-issue.

    Compressed variant of the planned rotation test — the operator
    cycles the key urgently (e.g. suspected leak) but MUST keep
    ``HMAC_KEY_OLD`` populated for as long as in-flight tokens exist.
    """
    _activate_settings(
        monkeypatch,
        kid_new="urgent-prev",
        hmac_key=_OLD_HMAC_KEY,
    )
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    envelope = sign_invitation_token(
        raw_token_b64u=_RAW_TOKEN, expires_at=expires_at,
    )

    # Emergency rotation: ``KID_NEW`` flips, prior key moves to ``_OLD``.
    _activate_settings(
        monkeypatch,
        kid_new="urgent-current",
        hmac_key=_NEW_HMAC_KEY,
        kid_old="urgent-prev",
        hmac_key_old=_OLD_HMAC_KEY,
    )
    raw, _ = verify_invitation_token(envelope)
    assert raw == _RAW_TOKEN


# ---------------------------------------------------------------------------
# Legacy 3-part envelopes (pre-Step-6)
# ---------------------------------------------------------------------------


def test_legacy_3part_envelope_within_grace_verifies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pre-Step-6 3-part envelope still verifies during the grace window."""
    _activate_settings(
        monkeypatch,
        kid_new=_NEW_KID,
        hmac_key=_NEW_HMAC_KEY,
        kid_old=_OLD_KID,
        hmac_key_old=_OLD_HMAC_KEY,
        grace_hours=24,
    )
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    legacy = _legacy_3part_envelope(
        raw=_RAW_TOKEN, expires_at=expires_at, key=_OLD_HMAC_KEY,
    )
    raw, _ = verify_invitation_token(legacy)
    assert raw == _RAW_TOKEN


def test_legacy_3part_envelope_outside_grace_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 3-part envelope whose expiry + grace has passed is rejected."""
    _activate_settings(
        monkeypatch,
        kid_new=_NEW_KID,
        hmac_key=_NEW_HMAC_KEY,
        kid_old=_OLD_KID,
        hmac_key_old=_OLD_HMAC_KEY,
        grace_hours=1,
    )
    # Envelope expired 5 hours ago; grace window is 1 hour → 4 hours
    # past the grace cutoff.
    stale_expires_at = datetime.now(UTC) - timedelta(hours=5)
    legacy = _legacy_3part_envelope(
        raw=_RAW_TOKEN, expires_at=stale_expires_at, key=_OLD_HMAC_KEY,
    )
    with pytest.raises(InvitationTokenInvalidError):
        verify_invitation_token(legacy)


def test_legacy_3part_envelope_when_old_key_unset_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Once the operator closes rotation (drops ``_OLD``) legacy tokens die.

    The destruction is intentional — when the grace window has fully
    elapsed and the operator unsets ``HMAC_KEY_OLD`` to remove the
    secondary key from the live process, any remaining 3-part
    envelopes MUST be rejected. This mirrors the security-review
    expectation that rotation closure flips legacy tokens into the
    same generic-invalid bucket as forgeries.
    """
    _activate_settings(monkeypatch)  # no _OLD slots
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    legacy = _legacy_3part_envelope(
        raw=_RAW_TOKEN, expires_at=expires_at, key=_OLD_HMAC_KEY,
    )
    with pytest.raises(InvitationTokenInvalidError):
        verify_invitation_token(legacy)


# ---------------------------------------------------------------------------
# Kid mismatch — 4-part envelope with unknown / forged kid
# ---------------------------------------------------------------------------


def test_4part_envelope_with_unknown_kid_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 4-part envelope whose kid is neither ``_NEW`` nor ``_OLD`` is rejected.

    The third-party kid is unrouted at the verifier even though the
    envelope's internal MAC is consistent with the third-party key.
    """
    _activate_settings(
        monkeypatch,
        kid_new=_NEW_KID,
        hmac_key=_NEW_HMAC_KEY,
        kid_old=_OLD_KID,
        hmac_key_old=_OLD_HMAC_KEY,
    )
    expires_at = datetime.now(UTC) + timedelta(days=1)
    forged = _v2_envelope_with_arbitrary_kid(
        raw=_RAW_TOKEN,
        expires_at=expires_at,
        kid="never-deployed-kid",
        key=_THIRD_HMAC_KEY,
    )
    with pytest.raises(InvitationTokenInvalidError):
        verify_invitation_token(forged)


def test_4part_envelope_with_swapped_kid_label_fails_mac(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-labelling a known envelope to point at the NEW kid fails MAC.

    The MAC inputs include the kid (``{raw}.{exp}.{kid}``), so the
    attacker who tries to upgrade an OLD-signed envelope by editing the
    kid field gets a MAC mismatch under the NEW key.
    """
    _activate_settings(
        monkeypatch,
        kid_new=_NEW_KID,
        hmac_key=_NEW_HMAC_KEY,
        kid_old=_OLD_KID,
        hmac_key_old=_OLD_HMAC_KEY,
    )
    expires_at = datetime.now(UTC) + timedelta(hours=1)
    # Sign under OLD kid…
    legitimate = _v2_envelope_with_arbitrary_kid(
        raw=_RAW_TOKEN, expires_at=expires_at, kid=_OLD_KID, key=_OLD_HMAC_KEY,
    )
    # …and swap the kid slot to NEW. The MAC was over the OLD inputs.
    parts = legitimate.split(".")
    parts[2] = _NEW_KID
    forged = ".".join(parts)
    with pytest.raises(InvitationTokenInvalidError):
        verify_invitation_token(forged)


# ---------------------------------------------------------------------------
# Generic shape failures
# ---------------------------------------------------------------------------


def test_malformed_envelope_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two-part or five-part envelopes never verify."""
    _activate_settings(monkeypatch)
    for malformed in (
        "only.two",
        "a.b.c.d.e",
        "",
        "totally-not-a-token",
    ):
        with pytest.raises(InvitationTokenInvalidError):
            verify_invitation_token(malformed)

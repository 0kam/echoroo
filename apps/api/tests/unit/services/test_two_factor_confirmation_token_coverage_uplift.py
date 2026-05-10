"""Coverage uplift unit tests for ``echoroo.services.two_factor_confirmation_token``.

Phase 17 §C easy-win batch 1: covers the parser and verifier reject
branches that the existing security suite does not exercise:

    * Line 200 — :func:`_sign` with an unknown ``kid``.
    * Lines 229-230 — :func:`_parse_payload` with non-base64 input.
    * Line 236 — :func:`_parse_payload` with a JSON value that is not an
                 object.
    * Line 320 — :func:`consume_confirmation_token` with empty payload /
                 signature segments.
    * Lines 333-334 — :func:`consume_confirmation_token` with malformed
                       claim types.
    * Line 359 — purpose mismatch reject.
    * Lines 405-410 — atomic-guard branches when the row exists, was used,
                       or has expired.

All branches that need a database use an in-memory mock; we never hit
PostgreSQL, so the tests are fast and free of fixture coupling.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.core.settings import get_settings
from echoroo.services import two_factor_confirmation_token as mod
from echoroo.services.two_factor_confirmation_token import (
    PURPOSE_ADMIN_RESET_2FA,
    ConfirmationTokenAlreadyConsumedError,
    ConfirmationTokenExpiredError,
    ConfirmationTokenInvalidError,
    consume_confirmation_token,
)

_NEW_KEY = "phase17-c-batch1-new-key-32chars-strong-1234567"


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin _NEW envs and clear the legacy slot so tests are deterministic."""
    monkeypatch.delenv("TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY_OLD", raising=False)
    monkeypatch.delenv("TWO_FACTOR_RESET_CONFIRMATION_HMAC_KID_OLD", raising=False)
    monkeypatch.setenv("TWO_FACTOR_RESET_CONFIRMATION_HMAC_KEY", _NEW_KEY)
    monkeypatch.setenv("TWO_FACTOR_RESET_CONFIRMATION_HMAC_KID_NEW", "v1")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _craft(
    *,
    user_id: str,
    nonce: str,
    expires_unix: int,
    kid: str | None,
    signing_key: str,
    purpose: str = PURPOSE_ADMIN_RESET_2FA,
) -> str:
    payload: dict[str, object] = {
        "u": user_id,
        "p": purpose,
        "n": nonce,
        "x": expires_unix,
    }
    if kid is not None:
        payload["k"] = kid
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload_segment = _b64url(raw)
    sig = hmac.new(
        signing_key.encode("utf-8"),
        payload_segment.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload_segment}.{sig}"


def test_sign_with_unknown_kid_raises_invalid() -> None:
    """_sign raises ConfirmationTokenInvalidError on unknown kid (line 200)."""
    with pytest.raises(ConfirmationTokenInvalidError):
        mod._sign("payload", kid="unknown-kid-not-in-env")


def test_parse_payload_rejects_non_base64() -> None:
    """_parse_payload raises on garbage that is not valid base64url
    (lines 229-230).
    """
    with pytest.raises(ConfirmationTokenInvalidError) as excinfo:
        mod._parse_payload("!!!not-base64!!!")
    assert "base64" in str(excinfo.value).lower()


def test_parse_payload_rejects_non_object_json() -> None:
    """_parse_payload raises when the JSON value decodes to a non-dict
    (line 236).
    """
    # JSON value "[1, 2, 3]" is valid JSON but not an object.
    payload = _b64url(b"[1, 2, 3]")
    with pytest.raises(ConfirmationTokenInvalidError) as excinfo:
        mod._parse_payload(payload)
    assert "object" in str(excinfo.value).lower()


@pytest.mark.asyncio
async def test_consume_rejects_token_with_empty_segments() -> None:
    """A token of "." (empty payload + empty signature) raises invalid
    (line 320).
    """
    with pytest.raises(ConfirmationTokenInvalidError) as excinfo:
        await consume_confirmation_token(
            MagicMock(),
            token=".",
            expected_user_id=uuid4(),
        )
    assert "empty" in str(excinfo.value).lower()


@pytest.mark.asyncio
async def test_consume_rejects_malformed_claims() -> None:
    """A token whose ``x`` claim is not int-coercible raises invalid
    (lines 333-334).
    """
    payload_dict = {
        "u": str(uuid4()),
        "p": PURPOSE_ADMIN_RESET_2FA,
        "n": "abc",
        "x": "not-an-int",
        "k": "v1",
    }
    raw = json.dumps(payload_dict, sort_keys=True, separators=(",", ":")).encode("utf-8")
    payload_segment = _b64url(raw)
    sig = hmac.new(
        _NEW_KEY.encode("utf-8"),
        payload_segment.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    token = f"{payload_segment}.{sig}"

    with pytest.raises(ConfirmationTokenInvalidError) as excinfo:
        await consume_confirmation_token(
            MagicMock(),
            token=token,
            expected_user_id=uuid4(),
        )
    assert "malformed" in str(excinfo.value).lower()


@pytest.mark.asyncio
async def test_consume_rejects_purpose_mismatch() -> None:
    """A token whose ``p`` claim differs from the expected purpose raises
    invalid (line 359).
    """
    user_id = uuid4()
    expires_unix = int((datetime.now(UTC) + timedelta(minutes=5)).timestamp())
    token = _craft(
        user_id=str(user_id),
        nonce="abc",
        expires_unix=expires_unix,
        kid="v1",
        signing_key=_NEW_KEY,
        purpose="some_other_purpose",
    )
    with pytest.raises(ConfirmationTokenInvalidError) as excinfo:
        await consume_confirmation_token(
            MagicMock(),
            token=token,
            expected_user_id=user_id,
            expected_purpose=PURPOSE_ADMIN_RESET_2FA,
        )
    assert "purpose" in str(excinfo.value).lower()


@pytest.mark.asyncio
async def test_consume_raises_invalid_when_nonce_row_missing() -> None:
    """When HMAC verifies but the nonce row never existed, raise invalid
    (lines 405-407).
    """
    user_id = uuid4()
    expires_unix = int((datetime.now(UTC) + timedelta(minutes=5)).timestamp())
    token = _craft(
        user_id=str(user_id),
        nonce="missing-nonce",
        expires_unix=expires_unix,
        kid="v1",
        signing_key=_NEW_KEY,
    )

    # First execute (UPDATE RETURNING) — no row affected.
    update_result = MagicMock()
    update_result.first.return_value = None
    # Second execute (SELECT existing) — also missing.
    select_result = MagicMock()
    select_result.scalar_one_or_none.return_value = None

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[update_result, select_result])

    with pytest.raises(ConfirmationTokenInvalidError) as excinfo:
        await consume_confirmation_token(
            db,
            token=token,
            expected_user_id=user_id,
        )
    assert "nonce" in str(excinfo.value).lower()


@pytest.mark.asyncio
async def test_consume_raises_already_consumed_when_row_used() -> None:
    """When the row was already consumed, raise AlreadyConsumed (line 408-409)."""
    user_id = uuid4()
    expires_unix = int((datetime.now(UTC) + timedelta(minutes=5)).timestamp())
    token = _craft(
        user_id=str(user_id),
        nonce="abc",
        expires_unix=expires_unix,
        kid="v1",
        signing_key=_NEW_KEY,
    )
    update_result = MagicMock()
    update_result.first.return_value = None
    select_result = MagicMock()
    used_record = SimpleNamespace(used_at=datetime.now(UTC))
    select_result.scalar_one_or_none.return_value = used_record

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[update_result, select_result])

    with pytest.raises(ConfirmationTokenAlreadyConsumedError):
        await consume_confirmation_token(
            db,
            token=token,
            expected_user_id=user_id,
        )


@pytest.mark.asyncio
async def test_consume_raises_expired_when_row_present_but_unused() -> None:
    """When the row exists with used_at=None but the UPDATE missed (e.g. expired
    in the gap), raise Expired (line 410).
    """
    user_id = uuid4()
    expires_unix = int((datetime.now(UTC) + timedelta(minutes=5)).timestamp())
    token = _craft(
        user_id=str(user_id),
        nonce="abc",
        expires_unix=expires_unix,
        kid="v1",
        signing_key=_NEW_KEY,
    )
    update_result = MagicMock()
    update_result.first.return_value = None
    select_result = MagicMock()
    fresh_record = SimpleNamespace(used_at=None)
    select_result.scalar_one_or_none.return_value = fresh_record

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[update_result, select_result])

    with pytest.raises(ConfirmationTokenExpiredError):
        await consume_confirmation_token(
            db,
            token=token,
            expected_user_id=user_id,
        )

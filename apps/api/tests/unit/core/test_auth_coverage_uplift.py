"""Coverage uplift unit tests for ``echoroo.core.auth``.

Phase 17 §C easy-win batch 1: covers the in-memory token-store helpers
(lines 239-256), pure-function helpers (lines 321, 585-605), the JWT
verifier reject branches (lines 681-701, 795-800), and the extra-claims
reserved-name skip (lines 648-652) so the module clears the 85% threshold
without touching production code.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import jwt
import pytest

from echoroo.core import auth as mod
from echoroo.core.auth import (
    ACCESS_TOKEN_TYPE,
    DEFAULT_MEDIA_TTL,
    MEDIA_TOKEN_TYP,
    MEDIA_TOKEN_TYPE,
    REFRESH_TOKEN_TYPE,
    InMemoryTokenStore,
    InvalidTokenError,
    SqlTokenStore,
    StaleTokenError,
    issue_access_token,
    issue_media_token,
    issue_refresh_token,
    verify_access_token,
    verify_media_token,
)

# ---------------------------------------------------------------------------
# InMemoryTokenStore
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_in_memory_store_get_family_state_returns_none_when_missing() -> None:
    """get_family_state() returns None for an unknown family."""
    store = InMemoryTokenStore()
    assert await store.get_family_state("unknown-family") is None


@pytest.mark.asyncio
async def test_in_memory_store_get_family_state_returns_snapshot() -> None:
    """get_family_state() returns a stable snapshot copy (lines 239-242)."""
    store = InMemoryTokenStore()
    await store.mark_consumed("fam1", "jti1")
    state = await store.get_family_state("fam1")
    assert state is not None
    assert state["revoked"] is False
    assert "jti1" in state["consumed_jtis"]
    # Mutating the returned dict must NOT affect store internals.
    state["consumed_jtis"].add("forged")
    fresh = await store.get_family_state("fam1")
    assert fresh is not None
    assert "forged" not in fresh["consumed_jtis"]


@pytest.mark.asyncio
async def test_in_memory_store_mark_and_is_consumed_round_trip() -> None:
    """mark_consumed + is_consumed round-trip (lines 248-256)."""
    store = InMemoryTokenStore()
    assert await store.is_consumed("fam2", "jti1") is False  # missing family branch
    await store.mark_consumed("fam2", "jti1")
    assert await store.is_consumed("fam2", "jti1") is True
    assert await store.is_consumed("fam2", "jti-missing") is False


# ---------------------------------------------------------------------------
# SqlTokenStore._to_uuid
# ---------------------------------------------------------------------------


def test_sql_token_store_to_uuid_passthrough_when_already_uuid() -> None:
    """_to_uuid returns the UUID unchanged when given a UUID (line 320 branch)."""
    src = uuid4()
    assert SqlTokenStore._to_uuid(src) is src


def test_sql_token_store_to_uuid_parses_string() -> None:
    """_to_uuid coerces a UUID string (line 322)."""
    src = uuid4()
    assert SqlTokenStore._to_uuid(str(src)) == src


# ---------------------------------------------------------------------------
# invalidate_stamp
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_invalidate_stamp_rotates_and_stages_session_add() -> None:
    """invalidate_stamp() rotates the stamp and calls session.add (lines 585-592)."""
    user = MagicMock()
    user.security_stamp = "old-stamp"
    user.id = uuid4()
    session = MagicMock()
    session.add = MagicMock()

    new_stamp = await mod.invalidate_stamp(user=user, session=session)
    assert new_stamp != "old-stamp"
    assert user.security_stamp == new_stamp
    session.add.assert_called_once_with(user)


@pytest.mark.asyncio
async def test_invalidate_stamp_writes_audit_when_provided() -> None:
    """invalidate_stamp() emits a platform audit event when audit is provided
    (lines 594-603).
    """
    user = MagicMock()
    user.security_stamp = "old"
    user.id = uuid4()
    audit = MagicMock()
    audit.write_platform_event = AsyncMock()

    await mod.invalidate_stamp(user=user, session=None, audit=audit)
    audit.write_platform_event.assert_awaited_once()
    call = audit.write_platform_event.await_args
    assert call.kwargs["action"] == "auth.security_stamp_rotated"


@pytest.mark.asyncio
async def test_invalidate_stamp_returns_new_stamp() -> None:
    """invalidate_stamp() returns the new stamp string (line 605)."""
    user = MagicMock()
    user.security_stamp = "old"
    user.id = uuid4()
    new_stamp = await mod.invalidate_stamp(user=user, session=None)
    assert isinstance(new_stamp, str)
    assert len(new_stamp) == 64  # token_hex(32) → 64 hex chars


# ---------------------------------------------------------------------------
# issue_access_token / verify_access_token
# ---------------------------------------------------------------------------


def test_issue_access_token_skips_reserved_extra_claims() -> None:
    """Reserved claim names in extra_claims are silently dropped (lines 648-652)."""
    user_id = uuid4()
    extras = {
        "sub": "should-be-dropped",
        "ss": "should-be-dropped",
        "jti": "should-be-dropped",
        "type": "fake",
        "iat": 0,
        "exp": 0,
        # Non-reserved keys pass through.
        "is_superuser": True,
    }
    token = issue_access_token(
        user_id=user_id,
        security_stamp="stamp",
        extra_claims=extras,
    )
    decoded = jwt.decode(token, options={"verify_signature": False})
    assert decoded["sub"] == str(user_id)
    assert decoded["ss"] == "stamp"
    assert decoded["type"] == ACCESS_TOKEN_TYPE
    assert decoded["is_superuser"] is True


def test_verify_access_token_raises_invalid_when_wrong_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A token whose ``type`` is not ACCESS raises InvalidTokenError (line 687)."""
    user_id = uuid4()
    refresh, _ = issue_refresh_token(user_id=user_id)
    with pytest.raises(InvalidTokenError, match="not an access token"):
        verify_access_token(refresh)


def test_verify_access_token_raises_invalid_for_expired_token() -> None:
    """An expired access token raises InvalidTokenError (lines 681-682)."""
    user_id = uuid4()
    past = datetime.now(UTC) - timedelta(hours=2)
    token = issue_access_token(
        user_id=user_id,
        security_stamp="ss",
        ttl=timedelta(minutes=15),
        now=past,
    )
    with pytest.raises(InvalidTokenError, match="expired"):
        verify_access_token(token)


def test_verify_access_token_raises_invalid_for_garbage_token() -> None:
    """A garbage token raises InvalidTokenError (lines 683-684)."""
    with pytest.raises(InvalidTokenError, match="invalid"):
        verify_access_token("not.a.token")


def test_verify_access_token_raises_invalid_when_sub_not_uuid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A token whose ``sub`` is not UUID-coercible raises invalid
    (lines 700-701).
    """
    settings = mod.settings

    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "not-a-uuid",
            "ss": "ss",
            "jti": "jti",
            "type": ACCESS_TOKEN_TYPE,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(InvalidTokenError, match="sub is not a UUID"):
        verify_access_token(token)


def test_verify_access_token_raises_invalid_when_claims_missing() -> None:
    """A token missing ``ss`` raises InvalidTokenError (line 694)."""
    settings = mod.settings

    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            # Intentionally omit ss
            "jti": "jti",
            "type": ACCESS_TOKEN_TYPE,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=5)).timestamp()),
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(InvalidTokenError, match="missing required claims"):
        verify_access_token(token)


# ---------------------------------------------------------------------------
# media-token issue / verify
# ---------------------------------------------------------------------------


def test_issue_and_verify_media_token_round_trip() -> None:
    """Media tokens bind user, security stamp, resource, scope, and expiry."""
    user_id = uuid4()
    project_id = uuid4()
    recording_id = uuid4()
    token = issue_media_token(
        user_id=user_id,
        security_stamp="media-stamp",
        project_id=project_id,
        resource_type="recording",
        resource_id=recording_id,
        scope="spectrogram",
    )

    decoded = jwt.decode(token, options={"verify_signature": False})
    assert decoded["type"] == MEDIA_TOKEN_TYPE
    assert decoded["typ"] == MEDIA_TOKEN_TYP
    assert decoded["project_id"] == str(project_id)
    assert decoded["rtype"] == "recording"
    assert decoded["recording_id"] == str(recording_id)
    assert decoded["scope"] == "spectrogram"

    claims = verify_media_token(
        token,
        current_security_stamp="media-stamp",
        project_id=project_id,
        resource_type="recording",
        resource_id=recording_id,
        scope="spectrogram",
    )
    assert claims.user_id == user_id
    assert claims.project_id == project_id
    assert claims.resource_type == "recording"
    assert claims.resource_id == recording_id
    assert claims.scope == "spectrogram"


def test_issue_and_verify_clip_download_media_token_round_trip() -> None:
    """Clip-bound download tokens carry resource_type=clip + the clip id."""
    user_id = uuid4()
    project_id = uuid4()
    clip_id = uuid4()
    token = issue_media_token(
        user_id=user_id,
        security_stamp="clip-stamp",
        project_id=project_id,
        resource_type="clip",
        resource_id=clip_id,
        scope="download",
    )

    decoded = jwt.decode(token, options={"verify_signature": False})
    assert decoded["rtype"] == "clip"
    assert decoded["recording_id"] == str(clip_id)
    assert decoded["scope"] == "download"

    claims = verify_media_token(
        token,
        current_security_stamp="clip-stamp",
        project_id=project_id,
        resource_type="clip",
        resource_id=clip_id,
        scope="download",
    )
    assert claims.resource_type == "clip"
    assert claims.resource_id == clip_id
    assert claims.scope == "download"


def test_verify_media_token_rejects_path_scope_and_stamp_mismatch() -> None:
    """Media tokens are not reusable across paths, scopes, or stamp rotation."""
    user_id = uuid4()
    project_id = uuid4()
    recording_id = uuid4()
    token = issue_media_token(
        user_id=user_id,
        security_stamp="media-stamp",
        project_id=project_id,
        resource_type="recording",
        resource_id=recording_id,
        scope="playback",
        ttl=DEFAULT_MEDIA_TTL,
    )

    with pytest.raises(InvalidTokenError, match="scope mismatch"):
        verify_media_token(
            token,
            current_security_stamp="media-stamp",
            project_id=project_id,
            resource_type="recording",
            resource_id=recording_id,
            scope="spectrogram",
        )
    with pytest.raises(InvalidTokenError, match="path mismatch"):
        verify_media_token(
            token,
            current_security_stamp="media-stamp",
            project_id=uuid4(),
            resource_type="recording",
            resource_id=recording_id,
            scope="playback",
        )
    with pytest.raises(StaleTokenError):
        verify_media_token(
            token,
            current_security_stamp="rotated",
            project_id=project_id,
            resource_type="recording",
            resource_id=recording_id,
            scope="playback",
        )


def test_verify_media_token_rejects_resource_type_mismatch() -> None:
    """A recording token cannot verify as a clip token (and vice versa)."""
    resource_id = uuid4()
    project_id = uuid4()
    token = issue_media_token(
        user_id=uuid4(),
        security_stamp="stamp",
        project_id=project_id,
        resource_type="recording",
        resource_id=resource_id,
        scope="download",
    )
    with pytest.raises(InvalidTokenError, match="resource type mismatch"):
        verify_media_token(
            token,
            current_security_stamp="stamp",
            project_id=project_id,
            resource_type="clip",
            resource_id=resource_id,
            scope="download",
        )


def test_verify_media_token_rejects_access_token_type() -> None:
    """Full access JWTs must not verify as media tokens."""
    token = issue_access_token(user_id=uuid4(), security_stamp="stamp")
    with pytest.raises(InvalidTokenError, match="not a media token"):
        verify_media_token(
            token,
            current_security_stamp="stamp",
            project_id=uuid4(),
            resource_type="recording",
            resource_id=uuid4(),
            scope="audio",
        )


# ---------------------------------------------------------------------------
# refresh-token decode rejects
# ---------------------------------------------------------------------------


def test_decode_refresh_raises_invalid_when_claims_missing() -> None:
    """A refresh token whose ``family`` is non-string raises invalid (line 795)."""
    settings = mod.settings

    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": str(uuid4()),
            "jti": "jti",
            "family": 12345,  # not a string
            "type": REFRESH_TOKEN_TYPE,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(days=7)).timestamp()),
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(InvalidTokenError, match="missing required claims"):
        mod._decode_refresh(token)


def test_decode_refresh_raises_invalid_when_sub_not_uuid() -> None:
    """A refresh token whose ``sub`` is not UUID-coercible raises invalid
    (lines 799-800).
    """
    settings = mod.settings

    now = datetime.now(UTC)
    token = jwt.encode(
        {
            "sub": "not-a-uuid",
            "jti": "jti",
            "family": "fam",
            "type": REFRESH_TOKEN_TYPE,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(days=7)).timestamp()),
        },
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(InvalidTokenError, match="sub is not a UUID"):
        mod._decode_refresh(token)

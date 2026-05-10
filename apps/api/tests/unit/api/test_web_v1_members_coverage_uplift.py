"""Coverage uplift unit tests for ``echoroo.api.web_v1.projects._members``.

Phase 17 §C Batch 9a (35-50pp gap range): covers the accept and decline
invitation handlers so the module clears the 85% threshold.

Missing lines: 86,156-157,162-163,171-175,188,192-194,198,205,209,216-217,
              224-225,232-233,238-239,243-245,249,251-253,336,339,343,346
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from echoroo.api.web_v1.projects._members import (
    accept_project_invitation,
    decline_project_invitation,
)
from echoroo.services.invitation_service import (
    InvitationConflictError,
    InvitationEmailMismatchError,
    InvitationInfraUnavailableError,
    InvitationStateError,
    InvitationTokenInvalidError,
)


def _make_request() -> MagicMock:
    req = MagicMock()
    req.headers = {
        "user-agent": "test-agent",
        "x-request-id": "req-123",
    }
    req.client = MagicMock()
    req.client.host = "127.0.0.1"
    return req


@pytest.mark.asyncio
async def test_accept_project_invitation_raises_401_when_unauthenticated() -> None:
    """accept_project_invitation raises 401 when current_user is None (lines 156-157)."""
    with pytest.raises(HTTPException) as exc_info:
        await accept_project_invitation(
            project_id=uuid4(),
            token="some-token",
            request=_make_request(),
            current_user=None,
            db=MagicMock(),
            idempotency_key="key-123",
        )
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_accept_project_invitation_raises_400_for_blank_idempotency_key() -> None:
    """accept_project_invitation raises 400 for blank idempotency key (lines 162-163)."""
    current_user = MagicMock()
    current_user.id = uuid4()
    current_user.email = "user@example.com"

    with pytest.raises(HTTPException) as exc_info:
        await accept_project_invitation(
            project_id=uuid4(),
            token="some-token",
            request=_make_request(),
            current_user=current_user,
            db=MagicMock(),
            idempotency_key="   ",  # blank
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_accept_project_invitation_raises_404_on_token_not_found() -> None:
    """accept_project_invitation raises 404 when token not found (lines 192-193)."""
    current_user = MagicMock()
    current_user.id = uuid4()
    current_user.email = "user@example.com"

    with (
        patch("echoroo.api.web_v1.projects._members.get_settings") as mock_settings,
        patch(
            "echoroo.api.web_v1.projects._members.get_redis_connection",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "echoroo.api.web_v1.projects._members.accept_invitation",
            new=AsyncMock(side_effect=InvitationTokenInvalidError("token not found")),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        mock_settings.return_value.web_session_secret = "secret"
        await accept_project_invitation(
            project_id=uuid4(),
            token="invalid-token",
            request=_make_request(),
            current_user=current_user,
            db=MagicMock(),
            idempotency_key="key-123",
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_accept_project_invitation_raises_410_on_expired_token() -> None:
    """accept_project_invitation raises 410 for expired signature (lines 198-202)."""
    current_user = MagicMock()
    current_user.id = uuid4()
    current_user.email = "user@example.com"

    with (
        patch("echoroo.api.web_v1.projects._members.get_settings") as mock_settings,
        patch(
            "echoroo.api.web_v1.projects._members.get_redis_connection",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "echoroo.api.web_v1.projects._members.accept_invitation",
            new=AsyncMock(side_effect=InvitationTokenInvalidError("expired signature")),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        mock_settings.return_value.web_session_secret = "secret"
        await accept_project_invitation(
            project_id=uuid4(),
            token="expired-token",
            request=_make_request(),
            current_user=current_user,
            db=MagicMock(),
            idempotency_key="key-123",
        )

    assert exc_info.value.status_code == 410


@pytest.mark.asyncio
async def test_accept_project_invitation_raises_403_on_email_mismatch() -> None:
    """accept_project_invitation raises 403 on email mismatch (lines 205-209)."""
    current_user = MagicMock()
    current_user.id = uuid4()
    current_user.email = "other@example.com"

    with (
        patch("echoroo.api.web_v1.projects._members.get_settings") as mock_settings,
        patch(
            "echoroo.api.web_v1.projects._members.get_redis_connection",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "echoroo.api.web_v1.projects._members.accept_invitation",
            new=AsyncMock(side_effect=InvitationEmailMismatchError("email mismatch")),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        mock_settings.return_value.web_session_secret = "secret"
        await accept_project_invitation(
            project_id=uuid4(),
            token="token",
            request=_make_request(),
            current_user=current_user,
            db=MagicMock(),
            idempotency_key="key-123",
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_accept_project_invitation_raises_410_on_state_error() -> None:
    """accept_project_invitation raises 410 on InvitationStateError (lines 216-217)."""
    current_user = MagicMock()
    current_user.id = uuid4()
    current_user.email = "user@example.com"

    with (
        patch("echoroo.api.web_v1.projects._members.get_settings") as mock_settings,
        patch(
            "echoroo.api.web_v1.projects._members.get_redis_connection",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "echoroo.api.web_v1.projects._members.accept_invitation",
            new=AsyncMock(side_effect=InvitationStateError("already accepted")),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        mock_settings.return_value.web_session_secret = "secret"
        await accept_project_invitation(
            project_id=uuid4(),
            token="token",
            request=_make_request(),
            current_user=current_user,
            db=MagicMock(),
            idempotency_key="key-123",
        )

    assert exc_info.value.status_code == 410


@pytest.mark.asyncio
async def test_accept_project_invitation_raises_409_on_conflict() -> None:
    """accept_project_invitation raises 409 on InvitationConflictError (lines 224-225)."""
    current_user = MagicMock()
    current_user.id = uuid4()
    current_user.email = "user@example.com"

    with (
        patch("echoroo.api.web_v1.projects._members.get_settings") as mock_settings,
        patch(
            "echoroo.api.web_v1.projects._members.get_redis_connection",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "echoroo.api.web_v1.projects._members.accept_invitation",
            new=AsyncMock(side_effect=InvitationConflictError("conflict")),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        mock_settings.return_value.web_session_secret = "secret"
        await accept_project_invitation(
            project_id=uuid4(),
            token="token",
            request=_make_request(),
            current_user=current_user,
            db=MagicMock(),
            idempotency_key="key-123",
        )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_accept_project_invitation_raises_503_on_infra_unavailable() -> None:
    """accept_project_invitation raises 503 on InvitationInfraUnavailableError (lines 232-233)."""
    current_user = MagicMock()
    current_user.id = uuid4()
    current_user.email = "user@example.com"

    with (
        patch("echoroo.api.web_v1.projects._members.get_settings") as mock_settings,
        patch(
            "echoroo.api.web_v1.projects._members.get_redis_connection",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "echoroo.api.web_v1.projects._members.accept_invitation",
            new=AsyncMock(side_effect=InvitationInfraUnavailableError("redis down")),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        mock_settings.return_value.web_session_secret = "secret"
        await accept_project_invitation(
            project_id=uuid4(),
            token="token",
            request=_make_request(),
            current_user=current_user,
            db=MagicMock(),
            idempotency_key="key-123",
        )

    assert exc_info.value.status_code == 503


@pytest.mark.asyncio
async def test_accept_project_invitation_happy_path_member() -> None:
    """accept_project_invitation returns member payload for MEMBER kind (lines 238-245)."""
    from echoroo.models.enums import ProjectInvitationKind

    current_user = MagicMock()
    current_user.id = uuid4()
    current_user.email = "user@example.com"
    db = MagicMock()
    db.commit = AsyncMock()

    member_id = uuid4()
    invitation = MagicMock()
    invitation.kind = ProjectInvitationKind.MEMBER
    invitation.project_id = uuid4()
    member = MagicMock()
    member.id = member_id
    outcome = MagicMock()
    outcome.invitation = invitation
    outcome.member = member
    outcome.trusted_user = None

    with (
        patch("echoroo.api.web_v1.projects._members.get_settings") as mock_settings,
        patch(
            "echoroo.api.web_v1.projects._members.get_redis_connection",
            new=AsyncMock(return_value=MagicMock()),
        ),
        patch(
            "echoroo.api.web_v1.projects._members.accept_invitation",
            new=AsyncMock(return_value=outcome),
        ),
        patch(
            "echoroo.api.web_v1.projects._members.invitation_service.trigger_post_commit_side_effects",
            new=AsyncMock(),
        ),
    ):
        mock_settings.return_value.web_session_secret = "secret"
        result = await accept_project_invitation(
            project_id=uuid4(),
            token="valid-token",
            request=_make_request(),
            current_user=current_user,
            db=db,
            idempotency_key="key-123",
        )

    assert result["kind"] == "member"
    assert "member_id" in result


# ---------------------------------------------------------------------------
# Decline endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decline_project_invitation_raises_401_when_unauthenticated() -> None:
    """decline_project_invitation raises 401 when current_user is None (line 336)."""
    with pytest.raises(HTTPException) as exc_info:
        await decline_project_invitation(
            project_id=uuid4(),
            token="token",
            request=_make_request(),
            current_user=None,
            db=MagicMock(),
        )
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_decline_project_invitation_raises_404_on_token_invalid() -> None:
    """decline_project_invitation raises 404 on InvitationTokenInvalidError (line 339)."""
    current_user = MagicMock()
    current_user.id = uuid4()
    current_user.email = "user@example.com"

    with (
        patch("echoroo.api.web_v1.projects._members.get_settings") as mock_settings,
        patch(
            "echoroo.api.web_v1.projects._members.decline_invitation_by_recipient",
            new=AsyncMock(side_effect=InvitationTokenInvalidError("not found")),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        mock_settings.return_value.web_session_secret = "secret"
        await decline_project_invitation(
            project_id=uuid4(),
            token="bad-token",
            request=_make_request(),
            current_user=current_user,
            db=MagicMock(),
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_decline_project_invitation_raises_404_on_email_mismatch() -> None:
    """decline_project_invitation raises 404 on email mismatch (line 343)."""
    current_user = MagicMock()
    current_user.id = uuid4()
    current_user.email = "other@example.com"

    with (
        patch("echoroo.api.web_v1.projects._members.get_settings") as mock_settings,
        patch(
            "echoroo.api.web_v1.projects._members.decline_invitation_by_recipient",
            new=AsyncMock(side_effect=InvitationEmailMismatchError("mismatch")),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        mock_settings.return_value.web_session_secret = "secret"
        await decline_project_invitation(
            project_id=uuid4(),
            token="token",
            request=_make_request(),
            current_user=current_user,
            db=MagicMock(),
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_decline_project_invitation_raises_410_on_state_error() -> None:
    """decline_project_invitation raises 410 on InvitationStateError (line 346)."""
    current_user = MagicMock()
    current_user.id = uuid4()
    current_user.email = "user@example.com"

    with (
        patch("echoroo.api.web_v1.projects._members.get_settings") as mock_settings,
        patch(
            "echoroo.api.web_v1.projects._members.decline_invitation_by_recipient",
            new=AsyncMock(side_effect=InvitationStateError("already accepted")),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        mock_settings.return_value.web_session_secret = "secret"
        await decline_project_invitation(
            project_id=uuid4(),
            token="token",
            request=_make_request(),
            current_user=current_user,
            db=MagicMock(),
        )

    assert exc_info.value.status_code == 410

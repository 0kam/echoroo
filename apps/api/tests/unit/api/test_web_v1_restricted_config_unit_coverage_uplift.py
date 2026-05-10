"""Coverage uplift unit tests for ``echoroo.api.web_v1.projects._restricted_config``.

Phase 17 §C medium-gap batch: targets ``_client_ip`` (line 71),
``update_project_restricted_config`` early-401 branch (line 147), the
RESTRICTED-only 422 branch (line 165, 172), the per-X-Forwarded-For
header (line 199), and the role-resolution lines 204 / 207-209 so the
module clears the 85% threshold without touching production code.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from echoroo.api.web_v1.projects import _restricted_config as mod
from echoroo.models.enums import ProjectVisibility


def _request_with(headers: dict[str, str] | None = None) -> MagicMock:
    req = MagicMock()
    req.headers = headers or {}
    req.client = SimpleNamespace(host="1.2.3.4")
    return req


def test_client_ip_uses_forwarded_for_first_value() -> None:
    """``_client_ip`` returns the first hop in X-Forwarded-For (line 71)."""
    req = _request_with({"x-forwarded-for": "10.0.0.1, 10.0.0.2"})
    assert mod._client_ip(req) == "10.0.0.1"


def test_client_ip_falls_back_to_request_client_host() -> None:
    """``_client_ip`` falls back to request.client.host."""
    req = _request_with({})
    assert mod._client_ip(req) == "1.2.3.4"


def test_client_ip_returns_unknown_without_client() -> None:
    """``_client_ip`` returns 'unknown' when request.client is None."""
    req = _request_with({})
    req.client = None
    assert mod._client_ip(req) == "unknown"


def test_user_agent_returns_value_or_empty() -> None:
    """``_user_agent`` returns header or empty string."""
    assert mod._user_agent(_request_with({"user-agent": "ua"})) == "ua"
    assert mod._user_agent(_request_with({})) == ""


def test_request_id_returns_value_or_empty() -> None:
    """``_request_id`` returns header or empty string."""
    assert mod._request_id(_request_with({"x-request-id": "abc"})) == "abc"
    assert mod._request_id(_request_with({})) == ""


@pytest.mark.asyncio
async def test_update_project_restricted_config_rejects_unauthenticated() -> None:
    """No current_user → 401 (lines 146-150)."""
    db = MagicMock()
    request = _request_with()
    with pytest.raises(HTTPException) as exc_info:
        await mod.update_project_restricted_config(
            project_id=uuid4(),
            payload=MagicMock(),
            request=request,
            current_user=None,
            db=db,
        )
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_update_project_restricted_config_rejects_non_restricted_visibility() -> None:
    """Public project visibility → 422 ERR_RESTRICTED_CONFIG_NOT_APPLICABLE (lines 165-181)."""
    project = SimpleNamespace(
        id=uuid4(),
        visibility=ProjectVisibility.PUBLIC,
    )
    user = MagicMock()
    user.id = uuid4()
    db = MagicMock()
    request = _request_with()
    payload = MagicMock()

    with patch.object(mod, "gate_action", new=AsyncMock(return_value=project)), \
            pytest.raises(HTTPException) as exc_info:
        await mod.update_project_restricted_config(
            project_id=uuid4(),
            payload=payload,
            request=request,
            current_user=user,
            db=db,
        )
    assert exc_info.value.status_code == 422
    assert isinstance(exc_info.value.detail, dict)
    assert exc_info.value.detail.get("error") == "ERR_RESTRICTED_CONFIG_NOT_APPLICABLE"


@pytest.mark.asyncio
async def test_update_project_restricted_config_happy_path() -> None:
    """Restricted project + Owner principal traverses the full mutation path
    (lines 183, 199, 204, 207, 210-212)."""
    project = SimpleNamespace(
        id=uuid4(),
        visibility=ProjectVisibility.RESTRICTED,
    )
    user = MagicMock()
    user.id = uuid4()
    db = MagicMock()
    db.commit = AsyncMock()

    request = _request_with({"x-request-id": "req-1", "user-agent": "ua-1"})
    payload = MagicMock()

    outcome = MagicMock()
    outcome.project = MagicMock()

    sentinel_response = MagicMock()
    fake_response_cls = MagicMock()
    fake_response_cls.model_validate = MagicMock(return_value=sentinel_response)

    with patch.object(mod, "gate_action", new=AsyncMock(return_value=project)), \
            patch.object(mod, "update_restricted_config", new=AsyncMock(return_value=outcome)), \
            patch.object(mod, "trigger_post_commit_side_effects", new=AsyncMock()), \
            patch.object(mod, "scrub_owner_email_for_visibility"), \
            patch.object(mod, "resolve_current_user_role", new=AsyncMock(return_value="Owner")), \
            patch.object(mod, "ProjectResponse", fake_response_cls):
        result = await mod.update_project_restricted_config(
            project_id=uuid4(),
            payload=payload,
            request=request,
            current_user=user,
            db=db,
        )
    assert result is sentinel_response
    db.commit.assert_awaited_once()

"""Coverage uplift unit tests for ``echoroo.api.v1.setup``.

Phase 17 §C easy-win batch 1: covers the ``initialize_setup`` body
(lines 75-77) using a mocked service / DB so the module clears the 85%
threshold without touching production code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import Response

from echoroo.api.v1 import setup as mod
from echoroo.schemas.setup import SetupCompleteResponse, SetupInitializeRequest


def _setup_response() -> SetupCompleteResponse:
    """Return a minimal setup-complete response for the route unit test."""
    return SetupCompleteResponse.model_validate(
        {
            "user": {
                "id": uuid4(),
                "email": "admin@example.com",
                "display_name": "Admin",
                "email_verified_at": None,
                "two_factor_enabled": True,
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
            },
            "totp_secret_base32": "A" * 32,
            "totp_provisioning_uri": "otpauth://totp/Echoroo:admin@example.com",
            "bootstrap_token": "B" * 32,
            "bootstrap_token_expires_at": "2026-01-02T00:00:00Z",
            "webauthn_registration_url": "/admin/webauthn/register?token=" + "B" * 32,
        }
    )


@pytest.mark.asyncio
async def test_initialize_setup_invokes_service_and_returns_user_response() -> None:
    """initialize_setup() builds SetupService and returns its response."""
    response = _setup_response()
    service_instance = MagicMock()
    service_instance.initialize_setup = AsyncMock(return_value=response)

    db = MagicMock()
    http_response = Response()
    http_request = MagicMock()
    http_request.headers = {
        "x-request-id": "req-1",
        "x-forwarded-for": "203.0.113.10, 10.0.0.1",
        "user-agent": "pytest",
    }
    http_request.client = MagicMock(host="127.0.0.1")
    request = SetupInitializeRequest(
        email="admin@example.com",
        password="StrongPassw0rd!!",
        display_name="Admin",
    )

    with patch.object(mod, "SetupService", return_value=service_instance) as svc_cls:
        result = await mod.initialize_setup(
            request=http_request,
            response=http_response,
            payload=request,
            db=db,
        )

    svc_cls.assert_called_once_with(db)
    service_instance.initialize_setup.assert_awaited_once_with(
        request,
        request_id="req-1",
        ip="203.0.113.10",
        user_agent="pytest",
    )
    assert result == response
    assert http_response.headers["Cache-Control"] == "no-store, no-cache, max-age=0"
    assert http_response.headers["Pragma"] == "no-cache"
    assert http_response.headers["Expires"] == "0"


@pytest.mark.asyncio
async def test_get_setup_status_invokes_service() -> None:
    """get_setup_status() builds SetupService and returns its status."""
    sentinel = MagicMock()
    service_instance = MagicMock()
    service_instance.get_setup_status = AsyncMock(return_value=sentinel)
    db = MagicMock()
    with patch.object(mod, "SetupService", return_value=service_instance):
        result = await mod.get_setup_status(db=db)
    assert result is sentinel

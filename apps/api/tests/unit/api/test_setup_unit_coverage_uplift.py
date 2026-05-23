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


# ---------------------------------------------------------------------------
# Header / client extraction helpers — these were uncovered branches when
# the route was first introduced (T996 coverage gate flagged setup.py at
# 83.3%). Pinning each branch keeps the helpers testable without standing
# up a real ASGI client.
# ---------------------------------------------------------------------------


def _request_with(headers: dict[str, str] | None, *, client_host: str | None) -> MagicMock:
    """Build a minimal Request stand-in for the header / client helpers."""
    req = MagicMock()
    req.headers = headers or {}
    req.client = MagicMock(host=client_host) if client_host is not None else None
    return req


def test_client_ip_uses_first_xff_token_when_header_present() -> None:
    """``X-Forwarded-For: a, b`` resolves to ``a`` even when client.host differs."""
    req = _request_with(
        {"x-forwarded-for": "203.0.113.10, 10.0.0.1"},
        client_host="127.0.0.1",
    )
    assert mod._client_ip(req) == "203.0.113.10"


def test_client_ip_falls_back_to_request_client_host_when_no_xff() -> None:
    """No XFF header → use the socket peer host."""
    req = _request_with({}, client_host="198.51.100.7")
    assert mod._client_ip(req) == "198.51.100.7"


def test_client_ip_returns_unknown_when_no_client_and_no_xff() -> None:
    """Background tasks / lifespan requests have no client; surface 'unknown'."""
    req = _request_with({}, client_host=None)
    assert mod._client_ip(req) == "unknown"


def test_client_ip_falls_back_to_unknown_when_xff_is_blank() -> None:
    """``X-Forwarded-For: , 10.0.0.1`` would otherwise return the empty
    string; we normalize that to 'unknown' so audit rows stay queryable."""
    req = _request_with({"x-forwarded-for": ", 10.0.0.1"}, client_host="127.0.0.1")
    assert mod._client_ip(req) == "unknown"


def test_request_id_extracts_correlation_header() -> None:
    """``x-request-id`` flows straight through to the audit payload."""
    req = _request_with({"x-request-id": "req-42"}, client_host="127.0.0.1")
    assert mod._request_id(req) == "req-42"


def test_request_id_is_empty_string_when_header_missing() -> None:
    """No header → empty string, never ``None`` (audit schema rejects None)."""
    req = _request_with({}, client_host="127.0.0.1")
    assert mod._request_id(req) == ""


def test_user_agent_extracts_header() -> None:
    """``user-agent`` header is captured verbatim."""
    req = _request_with({"user-agent": "Mozilla/5.0"}, client_host="127.0.0.1")
    assert mod._user_agent(req) == "Mozilla/5.0"


def test_user_agent_is_empty_string_when_header_missing() -> None:
    """No user-agent → empty string for consistency with _request_id."""
    req = _request_with({}, client_host="127.0.0.1")
    assert mod._user_agent(req) == ""


@pytest.mark.asyncio
async def test_initialize_setup_passes_through_non_403_http_exceptions() -> None:
    """A 500 or 422 from the service must NOT be rewritten to the generic
    403 detail — only 403 is rewritten to 'Setup not available' to avoid
    leaking liveness; other status codes propagate untouched."""
    from fastapi import HTTPException, status as st

    service_instance = MagicMock()
    service_instance.initialize_setup = AsyncMock(
        side_effect=HTTPException(
            status_code=st.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Audit chain unavailable; setup not finalized",
        )
    )
    db = MagicMock()
    http_response = Response()
    http_request = _request_with({"x-request-id": "r-1"}, client_host="127.0.0.1")
    payload = SetupInitializeRequest(
        email="admin@example.com",
        password="StrongPassw0rd!!",
        display_name="Admin",
    )

    with patch.object(mod, "SetupService", return_value=service_instance):
        with pytest.raises(HTTPException) as excinfo:
            await mod.initialize_setup(
                request=http_request,
                response=http_response,
                payload=payload,
                db=db,
            )

    assert excinfo.value.status_code == st.HTTP_500_INTERNAL_SERVER_ERROR
    assert excinfo.value.detail == "Audit chain unavailable; setup not finalized"


@pytest.mark.asyncio
async def test_initialize_setup_403_detail_is_replaced_with_generic_message() -> None:
    """The service may raise 403 with a precise reason; the route MUST
    rewrite it to the generic 'Setup not available' so an unauthenticated
    probe can't tell whether users already exist vs the flag has been set."""
    from fastapi import HTTPException, status as st

    service_instance = MagicMock()
    service_instance.initialize_setup = AsyncMock(
        side_effect=HTTPException(
            status_code=st.HTTP_403_FORBIDDEN,
            detail="Internal reason: setup_completed=True",
            headers={"X-Audit-Reason": "setup_completed_flag"},
        )
    )
    db = MagicMock()
    http_response = Response()
    http_request = _request_with({}, client_host="127.0.0.1")
    payload = SetupInitializeRequest(
        email="admin@example.com",
        password="StrongPassw0rd!!",
        display_name="Admin",
    )

    with patch.object(mod, "SetupService", return_value=service_instance):
        with pytest.raises(HTTPException) as excinfo:
            await mod.initialize_setup(
                request=http_request,
                response=http_response,
                payload=payload,
                db=db,
            )

    assert excinfo.value.status_code == st.HTTP_403_FORBIDDEN
    assert excinfo.value.detail == "Setup not available"
    # Headers from the original exception (e.g. WWW-Authenticate) must
    # carry through so middleware-level decisions still see them.
    assert excinfo.value.headers == {"X-Audit-Reason": "setup_completed_flag"}

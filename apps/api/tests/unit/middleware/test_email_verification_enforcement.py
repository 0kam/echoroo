"""Unit tests for email verification enforcement middleware."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from echoroo.middleware import email_verification_enforcement as middleware_mod


def _request(path: str, *, method: str = "POST") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "root_path": "",
            "scheme": "http",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 12345),
            "headers": [],
            "query_string": b"",
        }
    )


async def _call_next(_request: Request) -> Response:
    return JSONResponse({"ok": True})


@pytest.fixture(autouse=True)
def _enable_enforcement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        middleware_mod,
        "get_settings",
        lambda: SimpleNamespace(EMAIL_VERIFICATION_ENFORCEMENT_ENABLED=True),
    )


def test_rejects_empty_enforcement_prefixes() -> None:
    with pytest.raises(ValueError, match="enforcement_prefixes"):
        middleware_mod.EmailVerificationEnforcementMiddleware(
            app=AsyncMock(),
            enforcement_prefixes=(),
        )


@pytest.mark.asyncio
async def test_dispatch_skips_paths_outside_enforcement_prefixes() -> None:
    middleware = middleware_mod.EmailVerificationEnforcementMiddleware(app=AsyncMock())
    call_next = AsyncMock(side_effect=_call_next)

    response = await middleware.dispatch(_request("/public"), call_next)

    assert response.status_code == 200
    call_next.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_skips_allowlisted_path() -> None:
    middleware = middleware_mod.EmailVerificationEnforcementMiddleware(
        app=AsyncMock(),
        enforcement_prefixes=("/",),
    )
    call_next = AsyncMock(side_effect=_call_next)

    response = await middleware.dispatch(_request("/health"), call_next)

    assert response.status_code == 200
    call_next.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_skips_public_auth_path() -> None:
    middleware = middleware_mod.EmailVerificationEnforcementMiddleware(app=AsyncMock())
    call_next = AsyncMock(side_effect=_call_next)

    response = await middleware.dispatch(_request("/web-api/v1/auth/login"), call_next)

    assert response.status_code == 200
    call_next.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_skips_when_request_has_no_principal() -> None:
    middleware = middleware_mod.EmailVerificationEnforcementMiddleware(app=AsyncMock())
    call_next = AsyncMock(side_effect=_call_next)

    response = await middleware.dispatch(_request("/web-api/v1/protected"), call_next)

    assert response.status_code == 200
    call_next.assert_awaited_once()


@pytest.mark.asyncio
async def test_dispatch_allows_verified_user() -> None:
    user_id = uuid4()
    request = _request("/web-api/v1/protected")
    request.state.principal = SimpleNamespace(user_id=user_id)
    middleware = middleware_mod.EmailVerificationEnforcementMiddleware(app=AsyncMock())
    middleware._load_user = AsyncMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(
            deleted_at=None,
            email_verified_at=datetime.now(UTC),
        )
    )
    call_next = AsyncMock(side_effect=_call_next)

    response = await middleware.dispatch(request, call_next)

    assert response.status_code == 200
    middleware._load_user.assert_awaited_once_with(user_id)  # type: ignore[attr-defined]
    call_next.assert_awaited_once()

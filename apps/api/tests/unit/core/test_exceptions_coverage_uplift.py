"""Coverage uplift unit tests for ``echoroo.core.exceptions``.

Phase 17 §C easy-win batch 1: targets the exception class ``__init__``
bodies plus the ``app_exception_handler`` and ``_is_license_field_error``
helpers (lines 15-17, 24-25, 32, 39, 46, 53, 60, 78, 129) so the module
clears the 85% threshold without touching production code.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, status

from echoroo.core.exceptions import (
    AppException,
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    NotFoundError,
    RateLimitError,
    ValidationError,
    _is_license_field_error,
    _path_is_license_route,
    app_exception_handler,
    http_exception_handler,
)


def test_app_exception_default_status() -> None:
    """AppException stores message + defaults status to 500 (lines 15-17)."""
    err = AppException("boom")
    assert err.message == "boom"
    assert err.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert str(err) == "boom"


def test_app_exception_custom_status() -> None:
    """AppException accepts an explicit status code."""
    err = AppException("teapot", status_code=418)
    assert err.status_code == 418


def test_not_found_error_formats_message() -> None:
    """NotFoundError renders resource + identifier (lines 24-25)."""
    err = NotFoundError("Project", "abc-123")
    assert err.status_code == status.HTTP_404_NOT_FOUND
    assert "Project" in err.message
    assert "abc-123" in err.message


def test_authentication_error_default_message() -> None:
    """AuthenticationError defaults to 401 (line 32)."""
    err = AuthenticationError()
    assert err.status_code == status.HTTP_401_UNAUTHORIZED
    assert err.message == "Authentication failed"


def test_authentication_error_custom_message() -> None:
    """AuthenticationError accepts a custom message."""
    err = AuthenticationError("token expired")
    assert err.message == "token expired"


def test_authorization_error_default() -> None:
    """AuthorizationError defaults to 403 (line 39)."""
    err = AuthorizationError()
    assert err.status_code == status.HTTP_403_FORBIDDEN
    assert err.message == "Permission denied"


def test_validation_error_uses_422() -> None:
    """ValidationError surfaces a 422 (line 46)."""
    err = ValidationError("bad input")
    assert err.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert err.message == "bad input"


def test_conflict_error_uses_409() -> None:
    """ConflictError surfaces a 409 (line 53)."""
    err = ConflictError("duplicate email")
    assert err.status_code == status.HTTP_409_CONFLICT
    assert err.message == "duplicate email"


def test_rate_limit_error_default() -> None:
    """RateLimitError defaults to 429 + canned message (line 60)."""
    err = RateLimitError()
    assert err.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert err.message == "Rate limit exceeded"


@pytest.mark.asyncio
async def test_app_exception_handler_emits_envelope() -> None:
    """app_exception_handler returns a JSONResponse with error+message (line 78)."""
    request = MagicMock()
    err = NotFoundError("User", "u-1")
    response = await app_exception_handler(request, err)
    assert response.status_code == status.HTTP_404_NOT_FOUND
    body = json.loads(response.body)
    assert body["error"] == "NotFoundError"
    assert "User" in body["message"]


def test_is_license_field_error_rejects_non_sequence() -> None:
    """_is_license_field_error returns False for non-list/tuple loc (line 129)."""
    assert _is_license_field_error(None) is False
    assert _is_license_field_error("license") is False
    assert _is_license_field_error(42) is False


def test_is_license_field_error_detects_license_in_loc() -> None:
    """_is_license_field_error returns True when 'license' is in the loc tuple."""
    assert _is_license_field_error(("body", "license")) is True
    assert _is_license_field_error(["body", "license"]) is True
    assert _is_license_field_error(("body", "name")) is False


def test_path_is_license_route_matches_known_paths() -> None:
    """_path_is_license_route matches POST /projects + PATCH /projects/{id}/license."""
    assert _path_is_license_route("/api/v1/projects") is True
    assert _path_is_license_route("/web-api/v1/projects") is True
    assert _path_is_license_route(
        "/api/v1/projects/aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa/license"
    ) is True
    assert _path_is_license_route("/api/v1/datasets") is False


@pytest.mark.asyncio
async def test_http_exception_handler_emits_dict_envelope_when_contract_coded() -> None:
    """When detail is a dict containing 'error', the body is passed through as-is."""
    request = MagicMock()
    exc = HTTPException(
        status_code=403,
        detail={"error": "ERR_FORBIDDEN", "message": "no access"},
    )
    response = await http_exception_handler(request, exc)
    body = json.loads(response.body)
    assert body == {"error": "ERR_FORBIDDEN", "message": "no access"}


@pytest.mark.asyncio
async def test_http_exception_handler_wraps_string_detail() -> None:
    """String detail keeps the legacy {"detail": ...} envelope."""
    request = MagicMock()
    exc = HTTPException(status_code=404, detail="not found")
    response = await http_exception_handler(request, exc)
    body = json.loads(response.body)
    assert body == {"detail": "not found"}

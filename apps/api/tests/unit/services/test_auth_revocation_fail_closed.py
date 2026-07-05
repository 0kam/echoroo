"""W4-2 SFR-2 — legacy token-revocation fail-closed behaviour.

The legacy Redis-backed revocation path in
:class:`echoroo.services.auth.AuthService` historically failed OPEN: when
Redis was unavailable, :meth:`is_token_revoked` returned ``False`` (accept
the request) and :meth:`revoke_user_tokens` silently no-op'd (a logout
that reported success without revoking anything).

These pure-unit tests pin the new fail-closed contract:

* ``is_token_revoked`` raises HTTP 503 when Redis is unavailable (both the
  ``None`` connection path and the read-error path) while
  ``ECHOROO_AUTH_REVOCATION_FAIL_CLOSED`` is active (the default).
* The dev-only escape hatch (flag = ``False``) restores the historical
  fail-open ``return False`` / silent no-op behaviour.
* ``revoke_user_tokens`` raises HTTP 503 when it cannot persist the marker.
* :func:`echoroo.api.v1.recordings.get_current_user_flexible` propagates a
  503 (infrastructure outage) instead of downgrading the caller to Guest,
  while a 401/403 (bad credential) still falls through to Guest.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, status

from echoroo.services import auth as auth_module
from echoroo.services.auth import AuthService

pytestmark = pytest.mark.asyncio


class _BoomRedis:
    """Redis double whose ``get`` / ``set`` always raise."""

    async def get(self, key: str) -> str | None:  # noqa: ARG002
        raise RuntimeError("redis read failed")

    async def set(self, key: str, value: str, ex: int | None = None) -> None:  # noqa: ARG002
        raise RuntimeError("redis write failed")


def _service() -> AuthService:
    # is_token_revoked / revoke_user_tokens never touch the DB, so a mock
    # session is sufficient for these pure-unit tests.
    return AuthService(MagicMock())


async def _return_none() -> None:
    return None


# ---------------------------------------------------------------------------
# is_token_revoked — fail-closed (default)
# ---------------------------------------------------------------------------


async def test_is_token_revoked_raises_503_when_redis_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_module.settings, "ECHOROO_AUTH_REVOCATION_FAIL_CLOSED", True)
    svc = _service()
    monkeypatch.setattr(svc, "_get_redis", _return_none)

    with pytest.raises(HTTPException) as exc_info:
        await svc.is_token_revoked(uuid4())

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


async def test_is_token_revoked_raises_503_on_redis_read_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_module.settings, "ECHOROO_AUTH_REVOCATION_FAIL_CLOSED", True)
    svc = _service()

    async def _boom_redis() -> _BoomRedis:
        return _BoomRedis()

    monkeypatch.setattr(svc, "_get_redis", _boom_redis)

    with pytest.raises(HTTPException) as exc_info:
        await svc.is_token_revoked(uuid4())

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


# ---------------------------------------------------------------------------
# is_token_revoked — dev-only fail-open escape hatch
# ---------------------------------------------------------------------------


async def test_is_token_revoked_fail_open_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_module.settings, "ECHOROO_AUTH_REVOCATION_FAIL_CLOSED", False)
    svc = _service()
    monkeypatch.setattr(svc, "_get_redis", _return_none)

    assert await svc.is_token_revoked(uuid4()) is False


async def test_is_token_revoked_fail_open_on_read_error_returns_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_module.settings, "ECHOROO_AUTH_REVOCATION_FAIL_CLOSED", False)
    svc = _service()

    async def _boom_redis() -> _BoomRedis:
        return _BoomRedis()

    monkeypatch.setattr(svc, "_get_redis", _boom_redis)

    assert await svc.is_token_revoked(uuid4()) is False


# ---------------------------------------------------------------------------
# revoke_user_tokens / logout — write path must not silently succeed
# ---------------------------------------------------------------------------


async def test_revoke_user_tokens_raises_503_when_redis_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_module.settings, "ECHOROO_AUTH_REVOCATION_FAIL_CLOSED", True)
    svc = _service()
    monkeypatch.setattr(svc, "_get_redis", _return_none)

    with pytest.raises(HTTPException) as exc_info:
        await svc.revoke_user_tokens(uuid4())

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


async def test_revoke_user_tokens_fail_open_is_silent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_module.settings, "ECHOROO_AUTH_REVOCATION_FAIL_CLOSED", False)
    svc = _service()
    monkeypatch.setattr(svc, "_get_redis", _return_none)

    # No exception — historical silent no-op preserved under the escape hatch.
    await svc.revoke_user_tokens(uuid4())


# ---------------------------------------------------------------------------
# get_current_user_flexible — 503 must propagate, 401/403 falls through
# ---------------------------------------------------------------------------


async def test_flexible_current_user_propagates_503(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echoroo.api.v1 import recordings

    async def _raise_503(self: AuthService, token: str) -> None:  # noqa: ARG001
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    monkeypatch.setattr(AuthService, "get_current_user", _raise_503)

    with pytest.raises(HTTPException) as exc_info:
        await recordings.get_current_user_flexible(
            request=MagicMock(), db=MagicMock(), token="not-an-api-token", credentials=None
        )

    assert exc_info.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


async def test_flexible_current_user_401_falls_through_to_guest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from echoroo.api.v1 import recordings

    async def _raise_401(self: AuthService, token: str) -> None:  # noqa: ARG001
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    monkeypatch.setattr(AuthService, "get_current_user", _raise_401)

    result = await recordings.get_current_user_flexible(
        request=MagicMock(), db=MagicMock(), token="not-an-api-token", credentials=None
    )

    assert result is None

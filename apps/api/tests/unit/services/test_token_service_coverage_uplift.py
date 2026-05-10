"""Coverage uplift unit tests for ``echoroo.services.token``.

Phase 17 §C Batch 6+7 (25-35pp gap): covers TokenService stub methods
(_raise_phase4_stub, list_tokens, create_token, revoke_token,
authenticate_by_token, get_token_by_id) so the module clears the 85%
threshold without touching production code.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, status

from echoroo.schemas.token import APITokenCreateRequest
from echoroo.services.token import TokenService, _raise_phase4_stub


def test_raise_phase4_stub_raises_501() -> None:
    """_raise_phase4_stub() always raises HTTP 501 (line 26, 40, 44)."""
    with pytest.raises(HTTPException) as exc_info:
        _raise_phase4_stub()
    assert exc_info.value.status_code == status.HTTP_501_NOT_IMPLEMENTED
    assert "Phase 4" in str(exc_info.value.detail)


def test_token_service_init() -> None:
    """TokenService.__init__ stores the db session (line 45)."""
    db = MagicMock()
    service = TokenService(db)
    assert service.db is db


def test_generate_token_format() -> None:
    """_generate_token() returns a string with the prefix (line 49)."""
    service = TokenService(MagicMock())
    token = service._generate_token()
    assert token.startswith(TokenService.TOKEN_PREFIX)
    assert len(token) > len(TokenService.TOKEN_PREFIX)


def test_hash_token_produces_hex_digest() -> None:
    """_hash_token() returns a 64-char hex SHA256 hash (lines 57-58)."""
    service = TokenService(MagicMock())
    hashed = service._hash_token("ecr_test_token")
    assert len(hashed) == 64
    assert all(c in "0123456789abcdef" for c in hashed)


def test_hash_token_is_deterministic() -> None:
    """_hash_token() produces the same hash for the same input."""
    service = TokenService(MagicMock())
    assert service._hash_token("abc") == service._hash_token("abc")


@pytest.mark.asyncio
async def test_list_tokens_raises_501() -> None:
    """list_tokens() always raises HTTP 501 (lines 64-65, 69-70)."""
    service = TokenService(MagicMock())
    with pytest.raises(HTTPException) as exc_info:
        await service.list_tokens(uuid4())
    assert exc_info.value.status_code == status.HTTP_501_NOT_IMPLEMENTED


@pytest.mark.asyncio
async def test_create_token_raises_501() -> None:
    """create_token() always raises HTTP 501 (lines 74-75, 79-80)."""
    service = TokenService(MagicMock())
    request = APITokenCreateRequest(name="test-token")
    with pytest.raises(HTTPException) as exc_info:
        await service.create_token(uuid4(), request)
    assert exc_info.value.status_code == status.HTTP_501_NOT_IMPLEMENTED


@pytest.mark.asyncio
async def test_revoke_token_raises_501() -> None:
    """revoke_token() always raises HTTP 501 (line 40, 44)."""
    service = TokenService(MagicMock())
    with pytest.raises(HTTPException) as exc_info:
        await service.revoke_token(uuid4(), uuid4())
    assert exc_info.value.status_code == status.HTTP_501_NOT_IMPLEMENTED


@pytest.mark.asyncio
async def test_authenticate_by_token_raises_501() -> None:
    """authenticate_by_token() always raises HTTP 501."""
    service = TokenService(MagicMock())
    with pytest.raises(HTTPException) as exc_info:
        await service.authenticate_by_token("ecr_sometoken")
    assert exc_info.value.status_code == status.HTTP_501_NOT_IMPLEMENTED


@pytest.mark.asyncio
async def test_get_token_by_id_raises_501() -> None:
    """get_token_by_id() always raises HTTP 501."""
    service = TokenService(MagicMock())
    with pytest.raises(HTTPException) as exc_info:
        await service.get_token_by_id(uuid4(), uuid4())
    assert exc_info.value.status_code == status.HTTP_501_NOT_IMPLEMENTED

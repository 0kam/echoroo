"""The chunk rate-limit bucket is per authenticated user, never per path or client IP."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from echoroo.middleware.rate_limit import _chunk_bucket_identifier


@pytest.mark.asyncio
async def test_identifier_uses_principal_user_id() -> None:
    user_id = uuid4()
    request = SimpleNamespace(
        state=SimpleNamespace(principal=SimpleNamespace(user_id=user_id)),
        client=SimpleNamespace(host="10.0.0.1"),
    )
    assert await _chunk_bucket_identifier(request) == f"upload-chunk:user:{user_id}"


@pytest.mark.asyncio
async def test_identifier_falls_back_to_client_host_without_principal() -> None:
    request = SimpleNamespace(state=SimpleNamespace(principal=None), client=SimpleNamespace(host="10.0.0.1"))
    assert await _chunk_bucket_identifier(request) == "upload-chunk:anon:10.0.0.1"
    request = SimpleNamespace(state=SimpleNamespace(), client=None)
    assert await _chunk_bucket_identifier(request) == "upload-chunk:anon:unknown"

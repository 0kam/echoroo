"""Coverage uplift unit tests for ``echoroo.core.redis``.

Phase 17 §C heavy-gap batch: targets the ``close_redis_connection`` cleanup
branch (lines 49-51) so the module clears the 85% threshold without
touching production code.

The module owns a single global ``_redis_client`` cache and exposes two
async helpers — ``get_redis_connection`` (already covered by integration
tests) and ``close_redis_connection`` (the close/None-reset path is the
gap). The test injects a stub client so the close path runs without a
real Redis instance.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from echoroo.core import redis as redis_mod


@pytest.mark.asyncio
async def test_close_redis_connection_closes_and_resets_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """close_redis_connection() awaits client.close() then resets the global (lines 49-51)."""
    fake_client = AsyncMock()
    fake_client.close = AsyncMock()
    monkeypatch.setattr(redis_mod, "_redis_client", fake_client)

    await redis_mod.close_redis_connection()

    fake_client.close.assert_awaited_once()
    assert redis_mod._redis_client is None


@pytest.mark.asyncio
async def test_close_redis_connection_no_op_when_already_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """close_redis_connection() with no live client is a safe no-op."""
    monkeypatch.setattr(redis_mod, "_redis_client", None)

    # Should not raise even if there's nothing to close.
    await redis_mod.close_redis_connection()

    assert redis_mod._redis_client is None

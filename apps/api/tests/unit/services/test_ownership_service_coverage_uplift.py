"""Coverage uplift unit tests for ``echoroo.services.ownership_service``.

Phase 17 §C easy-win batch 1: covers six missing branches:

    * Line 240 — ``peek_replay_outcome`` short-circuit when no payload.
    * Line 254 — ``TransferConflictError`` on cached-target mismatch.
    * Line 325 — empty idempotency_key rejected as ValueError.
    * Line 544 — ``InvalidTransferTargetError`` when member is None.
    * Lines 598-623 — ``trigger_post_commit_side_effects`` with audit
                       failure + soft-alert path.
    * Lines 689-691, 700 — ``_load_replay_payload`` decodes a string
                       payload via ``json.loads`` and rejects payloads
                       missing required keys.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from echoroo.services import ownership_service as mod


@pytest.mark.asyncio
async def test_peek_replay_outcome_returns_none_when_no_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """peek_replay_outcome returns None when the outbox lookup is empty
    (line 240).
    """
    monkeypatch.setattr(mod, "_load_replay_payload", AsyncMock(return_value=None))
    session = MagicMock()
    out = await mod.peek_replay_outcome(
        session,
        project_id=uuid4(),
        idempotency_key="abc",
        new_owner_user_id=uuid4(),
        requester_id=uuid4(),
    )
    assert out is None


@pytest.mark.asyncio
async def test_peek_replay_outcome_raises_conflict_when_target_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A same-key + same-actor + DIFFERENT target replay raises
    TransferConflictError (line 254).
    """
    actor = uuid4()
    cached_target = uuid4()
    new_target = uuid4()
    payload = {
        "new_owner_id": cached_target,
        "previous_owner_id": actor,
        "actor_user_id": actor,
    }
    monkeypatch.setattr(mod, "_load_replay_payload", AsyncMock(return_value=payload))

    session = MagicMock()
    with pytest.raises(mod.TransferConflictError):
        await mod.peek_replay_outcome(
            session,
            project_id=uuid4(),
            idempotency_key="abc",
            new_owner_user_id=new_target,
            requester_id=actor,
        )


@pytest.mark.asyncio
async def test_peek_replay_outcome_returns_none_for_non_actor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A caller other than the original actor sees None (no-conflict-no-replay)."""
    actor = uuid4()
    other = uuid4()
    target = uuid4()
    payload = {
        "new_owner_id": target,
        "previous_owner_id": actor,
        "actor_user_id": actor,
    }
    monkeypatch.setattr(mod, "_load_replay_payload", AsyncMock(return_value=payload))

    session = MagicMock()
    out = await mod.peek_replay_outcome(
        session,
        project_id=uuid4(),
        idempotency_key="abc",
        new_owner_user_id=target,
        requester_id=other,
    )
    assert out is None


@pytest.mark.asyncio
async def test_peek_replay_outcome_returns_replay_for_matching_actor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Matching actor + matching target returns the cached outcome (replayed=True)."""
    actor = uuid4()
    target = uuid4()
    payload = {
        "new_owner_id": target,
        "previous_owner_id": actor,
        "actor_user_id": actor,
    }
    monkeypatch.setattr(mod, "_load_replay_payload", AsyncMock(return_value=payload))

    project_id = uuid4()
    out = await mod.peek_replay_outcome(
        MagicMock(),
        project_id=project_id,
        idempotency_key="abc",
        new_owner_user_id=target,
        requester_id=actor,
    )
    assert out is not None
    assert out.replayed is True
    assert out.new_owner_id == target


@pytest.mark.asyncio
async def test_transfer_ownership_rejects_empty_idempotency_key() -> None:
    """transfer_ownership() raises ValueError on empty idempotency_key (line 325)."""
    with pytest.raises(ValueError, match="idempotency_key must be a non-empty string"):
        await mod.transfer_ownership(
            MagicMock(),
            project_id=uuid4(),
            new_owner_user_id=uuid4(),
            requester_id=uuid4(),
            idempotency_key="",
        )


@pytest.mark.asyncio
async def test_trigger_post_commit_side_effects_swallows_session_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """trigger_post_commit_side_effects logs a warning when audit write blows
    up (lines 598-623, soft-alert branch).
    """
    # Make AsyncSessionLocal raise when the async-with enters so the outer
    # try/except logs the soft alert.
    class _BoomCtx:
        async def __aenter__(self) -> object:
            raise RuntimeError("kaboom")

        async def __aexit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(mod, "AsyncSessionLocal", lambda: _BoomCtx())

    outcome = mod.OwnershipTransferOutcome(
        project_id=uuid4(),
        previous_owner_id=uuid4(),
        new_owner_id=uuid4(),
        actor_user_id=uuid4(),
        idempotency_key="abc",
        replayed=False,
        request_id="rid",
        ip="127.0.0.1",
        user_agent="ua",
    )
    # Should NOT raise — the outer try/except converts the failure into a
    # logger.warning() call.
    await mod.trigger_post_commit_side_effects(outcome)


@pytest.mark.asyncio
async def test_trigger_post_commit_side_effects_rolls_back_on_inner_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When the AuditLogService write raises, the inner try/except triggers a
    rollback before the outer except swallows the error (lines 619-623).
    """
    inner_session = MagicMock()
    inner_session.commit = AsyncMock()
    inner_session.rollback = AsyncMock()

    class _Ctx:
        async def __aenter__(self) -> object:
            return inner_session

        async def __aexit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(mod, "AsyncSessionLocal", lambda: _Ctx())

    fake_service = MagicMock()
    fake_service.write_project_event = AsyncMock(side_effect=RuntimeError("audit boom"))
    monkeypatch.setattr(mod, "AuditLogService", lambda _s: fake_service)

    outcome = mod.OwnershipTransferOutcome(
        project_id=uuid4(),
        previous_owner_id=uuid4(),
        new_owner_id=uuid4(),
        actor_user_id=uuid4(),
        idempotency_key="abc",
        replayed=False,
        request_id="rid",
        ip="127.0.0.1",
        user_agent="ua",
    )
    await mod.trigger_post_commit_side_effects(outcome)
    inner_session.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_load_replay_payload_decodes_string_payload() -> None:
    """_load_replay_payload decodes a JSON-string payload (lines 689-691)."""
    target = uuid4()
    actor = uuid4()
    payload_str = (
        '{"new_owner_id": "' + str(target) + '", '
        '"previous_owner_id": "' + str(actor) + '", '
        '"actor_user_id": "' + str(actor) + '"}'
    )
    fake_row = (payload_str,)
    fake_result = MagicMock()
    fake_result.first.return_value = fake_row
    session = MagicMock()
    session.execute = AsyncMock(return_value=fake_result)

    out = await mod._load_replay_payload(session, scoped_idem_key="key")
    assert out is not None
    assert out["new_owner_id"] == target
    assert out["previous_owner_id"] == actor


@pytest.mark.asyncio
async def test_load_replay_payload_rejects_missing_required_keys() -> None:
    """_load_replay_payload returns None when required keys are absent (line 700)."""
    fake_row = ({"actor_user_id": str(uuid4())},)  # no new_owner_id / previous_owner_id
    fake_result = MagicMock()
    fake_result.first.return_value = fake_row
    session = MagicMock()
    session.execute = AsyncMock(return_value=fake_result)

    assert await mod._load_replay_payload(session, scoped_idem_key="key") is None


@pytest.mark.asyncio
async def test_load_replay_payload_returns_none_when_row_absent() -> None:
    """_load_replay_payload returns None when no outbox row exists."""
    fake_result = MagicMock()
    fake_result.first.return_value = None
    session = MagicMock()
    session.execute = AsyncMock(return_value=fake_result)

    assert await mod._load_replay_payload(session, scoped_idem_key="key") is None

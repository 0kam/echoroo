"""Unit tests for :func:`build_pre_transfer_action_summary` (spec/011 T022).

The helper is consulted by the SU bootstrap ownership-transfer SAVEPOINT
branch (T502 / FR-011-123) to capture the prior owner's audit-event
history on a project. The query is read-only against
``project_audit_log`` so the unit suite inserts synthetic audit rows
directly (bypassing :class:`AuditLogService` and its chain-hash
machinery — that writer is covered by its own tests).

Coverage:

* Empty range → ``{"summary": []}``.
* Mixed destructive + non-destructive rows → only destructive entries
  preserve ``target_id`` (R6).
* Rows authored by other actors / scoped to other projects are
  EXCLUDED.
* Rows outside ``[since, until)`` are EXCLUDED (inclusive lower,
  exclusive upper bound).
* Destructive row missing ``target_id`` in detail → entry has only
  ``action`` + ``occurred_at`` (no ``target_id`` key).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.services import audit_service
from echoroo.services.audit_service import (
    DESTRUCTIVE_ACTIONS,
    build_pre_transfer_action_summary,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers (mirror the user_banner unit-test pattern)
# ---------------------------------------------------------------------------


def _stub_pii_hash(value: str) -> str:
    """Deterministic PII-hash stub keyed by raw value.

    The audit helper computes ``actor_user_id_hash`` via
    :func:`compute_pii_hash` when filtering rows. Patching the module
    binding so the stub is returned ensures the unit suite never
    reaches out to KMS and that synthetic rows we insert with the
    same stub hash match the WHERE clause.
    """
    return f"hash:{value}"


@pytest.fixture(autouse=True)
def _patch_pii_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace KMS-backed ``compute_pii_hash`` with the deterministic stub."""
    monkeypatch.setattr(audit_service, "compute_pii_hash", _stub_pii_hash)


async def _ensure_project(session: AsyncSession) -> UUID:
    """Insert a minimal Public project row (FK target for audit rows)."""
    project_id = uuid4()
    owner_id = uuid4()
    await session.execute(
        sa.text(
            """
            INSERT INTO users (id, email, password_hash, security_stamp)
            VALUES (:id, :email, 'x', :stamp)
            """
        ),
        {
            "id": str(owner_id),
            "email": f"owner-{owner_id}@example.com",
            "stamp": "s" * 64,
        },
    )
    await session.execute(
        sa.text(
            """
            INSERT INTO licenses (id, name, short_name, created_at, updated_at)
            VALUES ('cc-by', 'Creative Commons Attribution', 'CC-BY', now(), now())
            ON CONFLICT (id) DO NOTHING
            """
        )
    )
    await session.execute(
        sa.text(
            """
            INSERT INTO projects (id, name, visibility, license_id, status, owner_id)
            VALUES (:id, :name, 'public', 'cc-by', 'active', :owner_id)
            """
        ),
        {
            "id": str(project_id),
            "name": f"summary-test-{project_id}",
            "owner_id": str(owner_id),
        },
    )
    return project_id


async def _insert_audit_row(
    session: AsyncSession,
    *,
    project_id: UUID,
    actor_user_id: UUID,
    action: str,
    occurred_at: datetime,
    detail: dict[str, Any] | None = None,
) -> UUID:
    """Insert one ``project_audit_log`` row with chain columns stubbed."""
    row_id = uuid4()
    actor_hash = _stub_pii_hash(str(actor_user_id))
    await session.execute(
        sa.text(
            """
            INSERT INTO project_audit_log
              (id, created_at, actor_user_id_hash, project_id, action,
               detail, request_id, ip_hash, user_agent_hash,
               prev_hash, row_hash)
            VALUES
              (:id, :created_at, :actor_hash, :project_id, :action,
               CAST(:detail AS JSONB), 'test-req', 'ip-hash', 'ua-hash',
               :prev_hash, :row_hash)
            """
        ),
        {
            "id": str(row_id),
            "created_at": occurred_at,
            "actor_hash": actor_hash,
            "project_id": str(project_id),
            "action": action,
            "detail": json.dumps(detail or {}),
            "prev_hash": "0" * 64,
            "row_hash": "f" * 64,
        },
    )
    return row_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_empty_range_returns_empty_summary(db_session: AsyncSession) -> None:
    """No audit rows in range → ``{"summary": []}``."""
    project_id = await _ensure_project(db_session)
    actor_id = uuid4()
    since = datetime.now(UTC) - timedelta(hours=1)
    until = datetime.now(UTC)

    result = await build_pre_transfer_action_summary(
        db_session,
        project_id=project_id,
        actor_user_id=actor_id,
        since=since,
        until=until,
    )

    assert result == {"summary": []}


async def test_mixed_rows_only_destructive_preserves_target_id(
    db_session: AsyncSession,
) -> None:
    """Destructive rows surface ``target_id``; non-destructive ones do not."""
    project_id = await _ensure_project(db_session)
    actor_id = uuid4()
    base_time = datetime.now(UTC) - timedelta(minutes=30)

    # 1. Destructive action with target_id in detail.
    destructive_target_id = uuid4()
    await _insert_audit_row(
        db_session,
        project_id=project_id,
        actor_user_id=actor_id,
        action="dataset.delete",
        occurred_at=base_time,
        detail={"target_id": str(destructive_target_id), "comment": "cleanup"},
    )
    # 2. Non-destructive action with target_id in detail (target_id MUST be
    #    dropped because the action is not in DESTRUCTIVE_ACTIONS).
    non_destructive_target_id = uuid4()
    await _insert_audit_row(
        db_session,
        project_id=project_id,
        actor_user_id=actor_id,
        action="project.invitation.create",
        occurred_at=base_time + timedelta(minutes=1),
        detail={"target_id": str(non_destructive_target_id)},
    )

    result = await build_pre_transfer_action_summary(
        db_session,
        project_id=project_id,
        actor_user_id=actor_id,
        since=base_time - timedelta(minutes=1),
        until=base_time + timedelta(minutes=10),
    )

    summary = result["summary"]
    assert len(summary) == 2
    # Order is ascending by created_at — destructive lands first.
    destructive_entry = summary[0]
    assert destructive_entry["action"] == "dataset.delete"
    assert destructive_entry["target_id"] == str(destructive_target_id)
    non_destructive_entry = summary[1]
    assert non_destructive_entry["action"] == "project.invitation.create"
    assert "target_id" not in non_destructive_entry


async def test_other_actor_rows_excluded(db_session: AsyncSession) -> None:
    """Audit rows authored by a different actor MUST NOT surface."""
    project_id = await _ensure_project(db_session)
    actor_id = uuid4()
    other_actor_id = uuid4()
    base_time = datetime.now(UTC) - timedelta(minutes=10)

    await _insert_audit_row(
        db_session,
        project_id=project_id,
        actor_user_id=other_actor_id,
        action="project.delete",
        occurred_at=base_time,
        detail={"target_id": str(uuid4())},
    )

    result = await build_pre_transfer_action_summary(
        db_session,
        project_id=project_id,
        actor_user_id=actor_id,
        since=base_time - timedelta(minutes=1),
        until=base_time + timedelta(minutes=1),
    )

    assert result == {"summary": []}


async def test_other_project_rows_excluded(db_session: AsyncSession) -> None:
    """Audit rows scoped to a different project MUST NOT surface."""
    target_project = await _ensure_project(db_session)
    other_project = await _ensure_project(db_session)
    actor_id = uuid4()
    base_time = datetime.now(UTC) - timedelta(minutes=10)

    await _insert_audit_row(
        db_session,
        project_id=other_project,
        actor_user_id=actor_id,
        action="recording.delete",
        occurred_at=base_time,
        detail={"target_id": str(uuid4())},
    )

    result = await build_pre_transfer_action_summary(
        db_session,
        project_id=target_project,
        actor_user_id=actor_id,
        since=base_time - timedelta(minutes=1),
        until=base_time + timedelta(minutes=1),
    )

    assert result == {"summary": []}


async def test_rows_outside_date_range_excluded(db_session: AsyncSession) -> None:
    """Rows outside ``[since, until)`` are excluded (inclusive lower bound)."""
    project_id = await _ensure_project(db_session)
    actor_id = uuid4()
    base_time = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=1)

    # Before since (excluded).
    await _insert_audit_row(
        db_session,
        project_id=project_id,
        actor_user_id=actor_id,
        action="project.delete",
        occurred_at=base_time - timedelta(minutes=10),
        detail={"target_id": str(uuid4())},
    )
    # At since exactly (INCLUDED — lower bound is inclusive).
    at_since_target_id = uuid4()
    await _insert_audit_row(
        db_session,
        project_id=project_id,
        actor_user_id=actor_id,
        action="dataset.delete",
        occurred_at=base_time,
        detail={"target_id": str(at_since_target_id)},
    )
    # At until exactly (EXCLUDED — upper bound is exclusive).
    until = base_time + timedelta(minutes=10)
    await _insert_audit_row(
        db_session,
        project_id=project_id,
        actor_user_id=actor_id,
        action="recording.delete",
        occurred_at=until,
        detail={"target_id": str(uuid4())},
    )

    result = await build_pre_transfer_action_summary(
        db_session,
        project_id=project_id,
        actor_user_id=actor_id,
        since=base_time,
        until=until,
    )

    summary = result["summary"]
    assert len(summary) == 1
    assert summary[0]["action"] == "dataset.delete"
    assert summary[0]["target_id"] == str(at_since_target_id)


async def test_destructive_row_without_target_id_omits_target(
    db_session: AsyncSession,
) -> None:
    """A destructive row whose detail lacks ``target_id`` surfaces without it."""
    project_id = await _ensure_project(db_session)
    actor_id = uuid4()
    base_time = datetime.now(UTC) - timedelta(minutes=5)

    await _insert_audit_row(
        db_session,
        project_id=project_id,
        actor_user_id=actor_id,
        action="project.visibility.update",
        occurred_at=base_time,
        detail={"reason": "ops-cleanup"},  # NO target_id key
    )

    result = await build_pre_transfer_action_summary(
        db_session,
        project_id=project_id,
        actor_user_id=actor_id,
        since=base_time - timedelta(minutes=1),
        until=base_time + timedelta(minutes=1),
    )

    summary = result["summary"]
    assert len(summary) == 1
    entry = summary[0]
    assert entry["action"] == "project.visibility.update"
    assert "target_id" not in entry
    assert set(entry.keys()) == {"action", "occurred_at"}


async def test_destructive_actions_constant_includes_base_six(
    db_session: AsyncSession,
) -> None:
    """T021 base 6 entries must all be members of DESTRUCTIVE_ACTIONS.

    Sanity check that the constant was actually extended in this PR.
    """
    expected_base = frozenset(
        {
            "project.delete",
            "dataset.delete",
            "recording.delete",
            "project.acl.update",
            "project.permission.elevate",
            "project.visibility.update",
        }
    )
    assert expected_base <= DESTRUCTIVE_ACTIONS
    # Also confirm the Step 5 admin password reset entries survived
    # alongside the new base set.
    assert "platform.user.password_reset_by_superuser" in DESTRUCTIVE_ACTIONS
    assert "platform.user.password_reset_self" in DESTRUCTIVE_ACTIONS

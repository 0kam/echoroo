"""Phase 17 §C PR-D coverage uplift — ``echoroo.services.superuser_approval_service``.

The existing ``tests/integration/test_taxon_override_audit.py`` suite
covers the happy path — approve / reject with the audit hooks landing
rows in a real Postgres ``echoroo_test`` DB. This uplift fills the
defensive branches the integration suite does not exercise:

* :func:`approve_taxon_override` — wrong direction (stricter) + wrong
  status (already applied) raise :class:`ValueError`.
* :func:`reject_taxon_override` — same two preconditions.
* :func:`trigger_apply_post_commit_audit` — outer ``except`` swallows
  audit-session failures and emits a warning log instead of bubbling.
* :func:`trigger_decision_post_commit_audit` — both project-scope and
  platform-scope audit writes are independently wrapped, so a
  failure on either path is logged + swallowed.
* :func:`_load_override` — missing override raises ``ValueError``.

Pure unit tests; the ORM session is replaced by an in-process
:class:`_StubSession`, and ``AsyncSessionLocal`` is patched module-
locally to drive the failure branches.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest

from echoroo.models.enums import (
    TaxonOverrideApprovalStatus,
    TaxonOverrideDirection,
)
from echoroo.services import superuser_approval_service as svc
from echoroo.services.superuser_approval_service import (
    TaxonOverrideApplyOutcome,
    TaxonOverrideDecisionOutcome,
    _load_override,
    approve_taxon_override,
    reject_taxon_override,
    trigger_apply_post_commit_audit,
    trigger_decision_post_commit_audit,
)

# ---------------------------------------------------------------------------
# In-process ORM stubs — the precondition tests never actually need a DB
# round-trip; they only need ``_load_override`` to return a configurable
# override row.
# ---------------------------------------------------------------------------


class _StubOverride:
    """Duck-typed :class:`ProjectTaxonSensitivityOverride`."""

    def __init__(
        self,
        *,
        direction: TaxonOverrideDirection,
        approval_status: TaxonOverrideApprovalStatus,
    ) -> None:
        self.id = uuid4()
        self.project_id = uuid4()
        self.taxon_id = "taxon:00001"
        self.sensitivity_h3_res = 9
        self.direction = direction
        self.approval_status = approval_status
        self.approved_by_id: Any = None
        self.approved_at: Any = None
        self.rejected_reason: Any = None


class _StubResult:
    """Mirror of SQLAlchemy ``Result`` with ``scalar_one_or_none`` only."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _StubSession:
    """Captures ``execute`` invocations + serves a canned override row."""

    def __init__(self, override: Any | None) -> None:
        self._override = override
        self.executed: list[Any] = []

    async def execute(self, _stmt: Any, *_args: Any, **_kwargs: Any) -> _StubResult:
        self.executed.append(_stmt)
        return _StubResult(self._override)


# ---------------------------------------------------------------------------
# approve_taxon_override — preconditions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_rejects_stricter_override() -> None:
    """Stricter overrides do not traverse the workflow."""
    override = _StubOverride(
        direction=TaxonOverrideDirection.STRICTER,
        approval_status=TaxonOverrideApprovalStatus.APPLIED,
    )
    session = _StubSession(override)
    with pytest.raises(ValueError, match="only looser overrides"):
        await approve_taxon_override(
            session,  # type: ignore[arg-type]
            override_id=override.id,
            approver_superuser_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_approve_rejects_already_applied_override() -> None:
    """Already-applied looser override cannot be approved again."""
    override = _StubOverride(
        direction=TaxonOverrideDirection.LOOSER,
        approval_status=TaxonOverrideApprovalStatus.APPLIED,
    )
    session = _StubSession(override)
    with pytest.raises(ValueError, match="cannot approve"):
        await approve_taxon_override(
            session,  # type: ignore[arg-type]
            override_id=override.id,
            approver_superuser_id=uuid4(),
        )


# ---------------------------------------------------------------------------
# reject_taxon_override — preconditions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reject_rejects_stricter_override() -> None:
    override = _StubOverride(
        direction=TaxonOverrideDirection.STRICTER,
        approval_status=TaxonOverrideApprovalStatus.APPLIED,
    )
    session = _StubSession(override)
    with pytest.raises(ValueError, match="only looser overrides"):
        await reject_taxon_override(
            session,  # type: ignore[arg-type]
            override_id=override.id,
            approver_superuser_id=uuid4(),
            rejected_reason="not allowed",
        )


@pytest.mark.asyncio
async def test_reject_rejects_already_rejected_override() -> None:
    override = _StubOverride(
        direction=TaxonOverrideDirection.LOOSER,
        approval_status=TaxonOverrideApprovalStatus.REJECTED,
    )
    session = _StubSession(override)
    with pytest.raises(ValueError, match="cannot reject"):
        await reject_taxon_override(
            session,  # type: ignore[arg-type]
            override_id=override.id,
            approver_superuser_id=uuid4(),
            rejected_reason="duplicate ticket",
        )


# ---------------------------------------------------------------------------
# _load_override — missing row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_override_raises_value_error_when_missing() -> None:
    session = _StubSession(None)
    with pytest.raises(ValueError, match="not found"):
        await _load_override(session, uuid4())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# trigger_apply_post_commit_audit — outer-except path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_apply_audit_swallows_session_open_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """If ``AsyncSessionLocal()`` itself raises, the helper warns + returns.

    The post-commit hook MUST be soft-fail (FR-088): a hiccup in the
    audit chain cannot rollback a domain mutation that has already
    committed.
    """
    project_id = uuid4()
    actor_id = uuid4()
    outcome = TaxonOverrideApplyOutcome(
        override=_StubOverride(  # type: ignore[arg-type]
            direction=TaxonOverrideDirection.LOOSER,
            approval_status=TaxonOverrideApprovalStatus.PENDING_SUPERUSER_APPROVAL,
        ),
        actor_user_id=actor_id,
        project_id=project_id,
        audit_action="project.taxon_override.request_looser",
        audit_detail={"override_id": str(uuid4())},
    )

    @asynccontextmanager
    async def _failing_factory() -> Any:
        raise RuntimeError("audit session unreachable")
        yield None  # pragma: no cover - unreachable

    with patch.object(svc, "AsyncSessionLocal", _failing_factory), caplog.at_level("WARNING"):
        # MUST NOT raise.
        await trigger_apply_post_commit_audit(outcome)

    # The warning log path was hit.
    assert any(
        "audit write failed" in record.getMessage() for record in caplog.records
    )


@pytest.mark.asyncio
async def test_apply_audit_swallows_inner_failure_via_rollback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """When the inner write raises, the helper rolls back + warns + returns.

    Drives the ``except Exception: await audit_session.rollback(); raise``
    path inside the inner ``try`` (lines 493-495), then the outer ``except``
    path (lines 496-505).
    """
    rollback_calls: list[None] = []

    class _BoomSession:
        async def commit(self) -> None:  # pragma: no cover - never reached
            return None

        async def rollback(self) -> None:
            rollback_calls.append(None)

        async def __aenter__(self) -> _BoomSession:
            return self

        async def __aexit__(self, *_a: Any) -> None:
            return None

    @asynccontextmanager
    async def _factory() -> Any:
        async with _BoomSession() as s:
            yield s

    class _BoomService:
        def __init__(self, session: Any) -> None:
            self._session = session

        async def write_project_event(self, **_kwargs: Any) -> None:
            raise RuntimeError("hash chain prev row missing")

    outcome = TaxonOverrideApplyOutcome(
        override=_StubOverride(  # type: ignore[arg-type]
            direction=TaxonOverrideDirection.LOOSER,
            approval_status=TaxonOverrideApprovalStatus.PENDING_SUPERUSER_APPROVAL,
        ),
        actor_user_id=uuid4(),
        project_id=uuid4(),
        audit_action="project.taxon_override.request_looser",
        audit_detail={"override_id": str(uuid4())},
    )

    with (
        patch.object(svc, "AsyncSessionLocal", _factory),
        patch.object(svc, "AuditLogService", _BoomService),
        caplog.at_level("WARNING"),
    ):
        await trigger_apply_post_commit_audit(outcome)

    # The rollback was invoked, and the warning log path was hit.
    assert rollback_calls == [None]
    assert any(
        "audit write failed" in record.getMessage() for record in caplog.records
    )


# ---------------------------------------------------------------------------
# trigger_decision_post_commit_audit — both project + platform soft-alert
# branches.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decision_audit_logs_warning_when_project_session_open_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Project-scope + platform-scope writes share the same outer ``except``
    + ``logger.warning`` envelope. Two factories — one per call — let us
    flip both branches in a single test by mutating a counter.
    """
    project_id = uuid4()
    override_id = uuid4()
    outcome = TaxonOverrideDecisionOutcome(
        override=_StubOverride(  # type: ignore[arg-type]
            direction=TaxonOverrideDirection.LOOSER,
            approval_status=TaxonOverrideApprovalStatus.APPLIED,
        ),
        actor_user_id=uuid4(),
        project_id=project_id,
        decision="approved",
        project_audit_action="project.taxon_override.approve_looser",
        project_audit_detail={"override_id": str(override_id)},
        platform_audit_action="platform.project.taxon_override.approve_looser",
        platform_audit_detail={
            "project_id": str(project_id),
            "override_id": str(override_id),
        },
    )

    @asynccontextmanager
    async def _failing_factory() -> Any:
        raise RuntimeError("audit session unreachable")
        yield None  # pragma: no cover

    with patch.object(svc, "AsyncSessionLocal", _failing_factory), caplog.at_level("WARNING"):
        # Both project + platform attempts will fail; the helper
        # MUST swallow each independently and warn.
        await trigger_decision_post_commit_audit(outcome)

    project_failures = [
        r for r in caplog.records if "project_audit_log" in r.getMessage()
    ]
    platform_failures = [
        r for r in caplog.records if "platform_audit_log" in r.getMessage()
    ]
    assert project_failures, "project_audit_log warning not emitted"
    assert platform_failures, "platform_audit_log warning not emitted"


@pytest.mark.asyncio
async def test_decision_audit_swallows_inner_failure_via_rollback() -> None:
    """Drives the inner ``try/except`` → rollback path on both halves.

    Each call to the patched ``AuditLogService`` raises, exercising the
    ``await ...rollback(); raise`` branch (lines 535-537 + 565-567).
    """
    project_id = uuid4()
    override_id = uuid4()
    outcome = TaxonOverrideDecisionOutcome(
        override=_StubOverride(  # type: ignore[arg-type]
            direction=TaxonOverrideDirection.LOOSER,
            approval_status=TaxonOverrideApprovalStatus.APPLIED,
        ),
        actor_user_id=uuid4(),
        project_id=project_id,
        decision="approved",
        project_audit_action="project.taxon_override.approve_looser",
        project_audit_detail={"override_id": str(override_id)},
        platform_audit_action="platform.project.taxon_override.approve_looser",
        platform_audit_detail={
            "project_id": str(project_id),
            "override_id": str(override_id),
        },
    )

    rollbacks: list[str] = []

    class _BoomSession:
        def __init__(self, label: str) -> None:
            self._label = label

        async def commit(self) -> None:  # pragma: no cover - never reached
            return None

        async def rollback(self) -> None:
            rollbacks.append(self._label)

        async def __aenter__(self) -> _BoomSession:
            return self

        async def __aexit__(self, *_a: Any) -> None:
            return None

    counter = {"n": 0}

    @asynccontextmanager
    async def _factory() -> Any:
        counter["n"] += 1
        label = "project" if counter["n"] == 1 else "platform"
        async with _BoomSession(label) as s:
            yield s

    class _BoomService:
        def __init__(self, session: Any) -> None:
            self._session = session

        async def write_project_event(self, **_kwargs: Any) -> None:
            raise RuntimeError("project audit boom")

        async def write_platform_event(self, **_kwargs: Any) -> None:
            raise RuntimeError("platform audit boom")

    with (
        patch.object(svc, "AsyncSessionLocal", _factory),
        patch.object(svc, "AuditLogService", _BoomService),
    ):
        await trigger_decision_post_commit_audit(outcome)

    # Both halves rolled back independently.
    assert rollbacks == ["project", "platform"]

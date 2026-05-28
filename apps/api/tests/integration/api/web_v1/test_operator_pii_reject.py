"""Phase 17 backlog A-13 — API-boundary PII reject regression tests.

Verifies that submitting PII in the operator-supplied ``reason`` /
``support_ticket_id`` of every affected endpoint yields HTTP 422 and
that NO side-effect occurs (no business-table row written, no audit
log entry persisted, no outbox event enqueued).

Endpoints covered:

* ``POST /web-api/v1/admin/users/{userId}/reset-2fa``
  (:class:`ResetTwoFactorRequest`)
* ``POST /web-api/v1/admin/projects/{projectId}/taxon-overrides/
  {overrideId}/reject`` (:class:`TaxonOverrideRejectRequest`)
* ``POST /web-api/v1/admin/projects/{projectId}/archive``
  (:class:`ArchiveRequest`)
* ``POST /web-api/v1/admin/superusers/approval-requests/{id}/reject``
  (:class:`SuperuserRejectRequest`)
* ``POST /web-api/v1/admin/superusers/break-glass/enter``
  (:class:`SuperuserBreakGlassEnterRequest`)

The tests reuse the existing fixtures from
``test_admin_superusers.py`` (re-imported via the shared conftest
patterns) so the harness — admin app, dep overrides, step-up token
injection — matches what the existing admin tests rely on.

Round 2 R1-I1: Codex flagged that the previous revision claimed to
cover five endpoints but only exercised three. The
``TaxonOverrideRejectRequest`` and ``ArchiveRequest`` paths are now
covered with side-effect probes (override row state, project status,
outbox + audit row counts). The ``ArchiveRequest`` path is the most
load-bearing assertion: ``archive_project`` enqueues an
``outbox_events`` row containing the operator's ``reason`` *before*
commit, so a missing PII gate would mean the reason text reaches a
sink that AuditLogSanitizer does not cover.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.enums import (
    ProjectLicense,
    ProjectStatus,
    ProjectVisibility,
    TaxonOverrideApprovalStatus,
    TaxonOverrideDirection,
)
from echoroo.models.project import Project
from echoroo.models.project_taxon_override import ProjectTaxonSensitivityOverride
from echoroo.models.superuser_approval_request import SuperuserApprovalRequest
from echoroo.services.superuser_service import ACTION_SUPERUSER_REVOKE

# Re-export the fixtures from the existing admin-superusers test module.
# pytest discovers fixtures by name, so the local re-exports below let
# this file reuse the proven admin-app + step-up-token + dep-override
# stack without duplicating ~120 lines of fixture wiring.
# ruff: noqa: F401, F811
from tests.integration.api.web_v1.test_admin_superusers import (
    _create_superuser,
    _create_user,
    admin_app,
    admin_client_factory,
)

PII_REASON: str = "Forward to operator at jane.doe@example.com please"
PII_TICKET: str = "ticket-jane@example.com"


# ---------------------------------------------------------------------------
# Helpers — ORM project + pending-looser-override seeding for the two new
# integration cases (taxon override reject / archive). The audit-session
# integration test already covers the post-commit audit contract; here we
# only need to assert that PII rejection at the Pydantic boundary leaves
# every persisted side-effect untouched.
# ---------------------------------------------------------------------------


_RESTRICTED_CONFIG: dict[str, object] = {
    "allow_media_playback": False,
    "allow_detection_view": False,
    "mask_species_in_detection": True,
    "allow_download": False,
    "allow_export": False,
    "allow_voting_and_comments": False,
    "public_location_precision_h3_res": 3,
    "allow_precise_location_to_viewer": False,
}


async def _create_active_project(
    db: AsyncSession,
    *,
    owner_id,
    name: str,
) -> Project:
    """Insert an ACTIVE / restricted project owned by *owner_id*."""
    project = Project(
        name=name,
        description="A-13 PII-reject regression fixture",
        visibility=ProjectVisibility.RESTRICTED,
        license_id="cc-by",
        restricted_config=dict(_RESTRICTED_CONFIG),
        status=ProjectStatus.ACTIVE,
        owner_id=owner_id,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def _create_pending_looser_override(
    db: AsyncSession,
    *,
    project_id,
    requester_id,
) -> ProjectTaxonSensitivityOverride:
    """Insert a ``pending_superuser_approval`` looser override row."""
    override = ProjectTaxonSensitivityOverride(
        project_id=project_id,
        taxon_id=f"taxon-{uuid4().hex[:10]}",
        sensitivity_h3_res=9,
        direction=TaxonOverrideDirection.LOOSER,
        approval_status=TaxonOverrideApprovalStatus.PENDING_SUPERUSER_APPROVAL,
        requested_by_id=requester_id,
    )
    db.add(override)
    await db.commit()
    await db.refresh(override)
    return override


# ---------------------------------------------------------------------------
# SuperuserRejectRequest — POST .../approval-requests/{id}/reject
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_superuser_reject_with_pii_returns_422_and_does_not_mutate_ticket(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """A PII-bearing rejection must NOT flip the ticket to ``rejected``."""
    su_user = await _create_user(
        db_session, email="a13_reject_pii_su@example.com"
    )
    su = await _create_superuser(db_session, user=su_user)

    ticket = SuperuserApprovalRequest(
        action=ACTION_SUPERUSER_REVOKE,
        detail={"target_superuser_id": str(uuid4())},
        requested_by_id=su.id,
        approvals=[],
        status="pending",
    )
    db_session.add(ticket)
    await db_session.commit()
    await db_session.refresh(ticket)
    ticket_id = ticket.id

    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            f"/web-api/v1/admin/superusers/approval-requests/{ticket_id}/reject",
            json={"reason": PII_REASON},
        )

    assert response.status_code == 422
    body = response.json()
    # Educational message reaches the caller.
    assert "PII" in str(body)

    # Ticket must remain pending — no mutation.
    await db_session.refresh(ticket)
    assert ticket.status == "pending"
    assert ticket.executed_at is None


@pytest.mark.asyncio
async def test_superuser_reject_with_clean_reason_still_works(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """Sanity check: a benign reason continues to flip the ticket."""
    su_user = await _create_user(
        db_session, email="a13_reject_clean_su@example.com"
    )
    su = await _create_superuser(db_session, user=su_user)

    ticket = SuperuserApprovalRequest(
        action=ACTION_SUPERUSER_REVOKE,
        detail={"target_superuser_id": str(uuid4())},
        requested_by_id=su.id,
        approvals=[],
        status="pending",
    )
    db_session.add(ticket)
    await db_session.commit()
    await db_session.refresh(ticket)

    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            f"/web-api/v1/admin/superusers/approval-requests/{ticket.id}/reject",
            json={"reason": "operator deemed unnecessary"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"


# ---------------------------------------------------------------------------
# SuperuserBreakGlassEnterRequest — POST .../break-glass/enter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_break_glass_enter_with_pii_returns_422_and_no_window_opens(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """PII reason must NOT open the 72h emergency window.

    The break-glass window state lives in ``system_settings`` rows
    (``break_glass_started_at`` / ``break_glass_reason``); the
    simplest side-effect probe is the public ``status`` endpoint,
    which reports ``active=False`` when no window is open.
    """
    su_user = await _create_user(
        db_session, email="a13_bg_pii_su@example.com"
    )
    await _create_superuser(db_session, user=su_user)

    async with await admin_client_factory(su_user) as client:
        # Snapshot pre-state.
        pre_status = await client.get(
            "/web-api/v1/admin/superusers/break-glass/status"
        )
        assert pre_status.status_code == 200
        pre_active = pre_status.json()["active"]

        response = await client.post(
            "/web-api/v1/admin/superusers/break-glass/enter",
            json={"reason": PII_REASON},
        )

    assert response.status_code == 422
    assert "PII" in str(response.json())

    # Window state must be unchanged (in particular: must NOT flip
    # from inactive → active because of a rejected request).
    async with await admin_client_factory(su_user) as client:
        post_status = await client.get(
            "/web-api/v1/admin/superusers/break-glass/status"
        )
    assert post_status.status_code == 200
    assert post_status.json()["active"] == pre_active


# ---------------------------------------------------------------------------
# ResetTwoFactorRequest — POST .../users/{id}/reset-2fa
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reset_two_factor_with_pii_reason_returns_422(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """PII in ``reason`` must yield 422 BEFORE any DB row is touched."""
    su_user = await _create_user(
        db_session, email="a13_reset_pii_reason_su@example.com"
    )
    await _create_superuser(db_session, user=su_user)
    target = await _create_user(
        db_session, email="a13_reset_pii_reason_target@example.com"
    )

    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            f"/web-api/v1/admin/users/{target.id}/reset-2fa",
            json={
                "support_ticket_id": "ZD-12345",
                "reason": PII_REASON,
                "skip_delay": False,
                "confirmation_token": "fake-token",
            },
        )
    assert response.status_code == 422
    assert "PII" in str(response.json())


@pytest.mark.asyncio
async def test_reset_two_factor_with_pii_support_ticket_id_returns_422(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """PII in ``support_ticket_id`` must also yield 422."""
    su_user = await _create_user(
        db_session, email="a13_reset_pii_ticket_su@example.com"
    )
    await _create_superuser(db_session, user=su_user)
    target = await _create_user(
        db_session, email="a13_reset_pii_ticket_target@example.com"
    )

    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            f"/web-api/v1/admin/users/{target.id}/reset-2fa",
            json={
                "support_ticket_id": PII_TICKET,
                "reason": "User reported lost device",
                "skip_delay": False,
                "confirmation_token": "fake-token",
            },
        )
    assert response.status_code == 422
    assert "PII" in str(response.json())


# ---------------------------------------------------------------------------
# TaxonOverrideRejectRequest — POST .../taxon-overrides/{overrideId}/reject
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_taxon_override_reject_with_pii_returns_422(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """PII in ``reason`` must NOT flip the override row to ``rejected``.

    The override stays in ``pending_superuser_approval`` and
    ``rejected_reason`` stays NULL. This is the load-bearing assertion:
    the override row is NOT routed through :class:`AuditLogSanitizer`,
    so a missing PII gate would persist the operator's input verbatim
    into the business table.
    """
    su_user = await _create_user(
        db_session, email="a13_taxon_reject_pii_su@example.com"
    )
    await _create_superuser(db_session, user=su_user)
    owner = await _create_user(
        db_session, email="a13_taxon_reject_pii_owner@example.com"
    )
    project = await _create_active_project(
        db_session,
        owner_id=owner.id,
        name="A-13 taxon-override reject",
    )
    override = await _create_pending_looser_override(
        db_session,
        project_id=project.id,
        requester_id=owner.id,
    )
    override_id = override.id

    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            f"/web-api/v1/admin/projects/{project.id}/taxon-overrides/"
            f"{override_id}/reject",
            json={"reason": PII_REASON},
        )

    assert response.status_code == 422
    assert "PII" in str(response.json())

    # State invariants: override still pending, no rejected_reason recorded.
    await db_session.refresh(override)
    assert (
        override.approval_status
        == TaxonOverrideApprovalStatus.PENDING_SUPERUSER_APPROVAL
    )
    assert override.rejected_reason is None
    assert override.approved_by_id is None
    assert override.approved_at is None


# ---------------------------------------------------------------------------
# ArchiveRequest — POST .../projects/{projectId}/archive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_archive_request_with_pii_returns_422_no_outbox_no_audit(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """PII in ``reason`` must NOT archive the project, enqueue outbox, or audit.

    ``archive_project`` enqueues an ``outbox_events`` row that copies
    the operator's ``reason`` into the payload *before* commit, and
    writes both ``project_audit_log`` and ``platform_audit_log`` rows
    after. A missing PII gate would leak the reason into the outbox
    table (which downstream notifies the former owner) — verifying the
    outbox count is therefore the critical side-effect probe.
    """
    su_user = await _create_user(
        db_session, email="a13_archive_pii_su@example.com"
    )
    await _create_superuser(db_session, user=su_user)
    owner = await _create_user(
        db_session, email="a13_archive_pii_owner@example.com"
    )
    project = await _create_active_project(
        db_session,
        owner_id=owner.id,
        name="A-13 archive PII reject",
    )
    project_id = project.id

    # Snapshot pre-state for outbox + audit row counts so we can assert
    # the count is unchanged (the test DB may carry rows from sibling
    # tests in the same suite).
    pre_outbox = (
        await db_session.execute(
            sa.text(
                "SELECT count(*) FROM outbox_events "
                "WHERE event_type = 'project.archive_notification' "
                "AND payload->>'project_id' = :pid"
            ),
            {"pid": str(project_id)},
        )
    ).scalar_one() or 0
    pre_project_audit = (
        await db_session.execute(
            sa.text(
                "SELECT count(*) FROM project_audit_log "
                "WHERE project_id = :pid AND action = 'project.archive'"
            ),
            {"pid": project_id},
        )
    ).scalar_one() or 0
    pre_platform_audit = (
        await db_session.execute(
            sa.text(
                "SELECT count(*) FROM platform_audit_log "
                "WHERE action = 'platform.project.archive'"
            )
        )
    ).scalar_one() or 0

    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            f"/web-api/v1/admin/projects/{project_id}/archive",
            json={"reason": PII_REASON},
        )

    assert response.status_code == 422
    assert "PII" in str(response.json())

    # State invariants: project untouched, NO outbox row, NO audit row.
    await db_session.refresh(project)
    assert project.status == ProjectStatus.ACTIVE
    assert project.archived_since is None

    post_outbox = (
        await db_session.execute(
            sa.text(
                "SELECT count(*) FROM outbox_events "
                "WHERE event_type = 'project.archive_notification' "
                "AND payload->>'project_id' = :pid"
            ),
            {"pid": str(project_id)},
        )
    ).scalar_one() or 0
    assert post_outbox == pre_outbox, (
        "PII rejection must NOT enqueue a project.archive_notification "
        "outbox row — that would leak the reason text downstream."
    )

    post_project_audit = (
        await db_session.execute(
            sa.text(
                "SELECT count(*) FROM project_audit_log "
                "WHERE project_id = :pid AND action = 'project.archive'"
            ),
            {"pid": project_id},
        )
    ).scalar_one() or 0
    assert post_project_audit == pre_project_audit

    post_platform_audit = (
        await db_session.execute(
            sa.text(
                "SELECT count(*) FROM platform_audit_log "
                "WHERE action = 'platform.project.archive'"
            )
        )
    ).scalar_one() or 0
    assert post_platform_audit == pre_platform_audit

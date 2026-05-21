"""Phase 13 P1 R3 follow-up — taxon override audit session contract (FR-088 / FR-093).

Codex flagged the original Phase 13 P1 R3 commit `b207a961`:
:class:`AuditLogService` issues
``SET TRANSACTION ISOLATION LEVEL SERIALIZABLE`` as the FIRST statement
on its session — PostgreSQL rejects the upgrade once any other SQL has
run on the connection (see ``apps/api/echoroo/services/audit_service.py:201``).
The previous implementation of ``approve_taxon_override`` /
``reject_taxon_override`` (and ``apply_taxon_override``) wrote the audit
row inside the same caller-owned session that had already issued
``SELECT`` / ``UPDATE`` against the override + ``superuser_approval_requests``
rows, which would fail at runtime against real PostgreSQL.

The fix mirrors :mod:`echoroo.services.ownership_service` and
:mod:`echoroo.services.trusted_service`: the mutation helpers return an
outcome dataclass; the endpoint commits the main TX and then invokes
``trigger_*_post_commit_audit`` which spins up a fresh
:class:`AsyncSessionLocal` for the audit write.

Test infrastructure
-------------------
This module spins up a throwaway PostgreSQL container via
``testcontainers`` and runs ``alembic upgrade head`` against it so the
audit log tables (which are NOT in :class:`Base.metadata` — they are
defined directly in the baseline migration) actually exist. This
mirrors :mod:`tests.integration.test_audit_serializable_isolation` and
:mod:`tests.integration.test_baseline_migration`.

The tests are skipped when ``testcontainers`` is unavailable so CI
environments without Docker still collect green.
"""

from __future__ import annotations

import subprocess
import uuid
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

try:
    from testcontainers.postgres import PostgresContainer
except ImportError:  # pragma: no cover — dev extra; matches sibling tests
    PostgresContainer = None  # type: ignore[assignment,misc]


API_ROOT = Path(__file__).resolve().parents[2]
ALEMBIC_INI = API_ROOT / "alembic.ini"


# ---------------------------------------------------------------------------
# Shared container + alembic-upgraded DB fixtures (mirrors
# ``test_audit_serializable_isolation`` so the two suites can share the
# spin-up cost when run together).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_container() -> Iterator[object]:
    """Spin up a throwaway PostgreSQL 16 container for the audit tests."""
    if PostgresContainer is None:
        pytest.skip("testcontainers not installed")
    container = PostgresContainer("pgvector/pgvector:pg16")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="module")
def upgraded_async_url(pg_container: object) -> str:
    """Run ``alembic upgrade head`` and return the asyncpg DSN."""
    sync_url = pg_container.get_connection_url()  # type: ignore[attr-defined]
    sync_url = sync_url.replace("postgresql+psycopg2://", "postgresql://")
    env = {
        "DATABASE_URL": sync_url.replace("postgresql://", "postgresql+asyncpg://"),
        "ALEMBIC_SYNC_URL": sync_url,
        # spec/011 NFR-011-010: Settings validator now refuses an empty
        # invitation-token kid / HMAC at every boot, so the subprocess
        # that loads echoroo.core.settings must carry both values too.
        "INVITATION_TOKEN_KID_NEW": "test-kid",
        "INVITATION_TOKEN_HMAC_KEY": "test-invitation-hmac-key-32-chars-min-padding-xxxxxxxx",
    }
    result = subprocess.run(
        ["uv", "run", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
        cwd=str(API_ROOT),
        env={**env, "PATH": __import__("os").environ.get("PATH", "")},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(
            "alembic upgrade head failed.\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return sync_url.replace("postgresql://", "postgresql+asyncpg://")


@pytest.fixture
async def session_factory(
    upgraded_async_url: str,
) -> Any:
    """Yield a sessionmaker bound to the upgraded throwaway DB.

    Uses :class:`NullPool` so each session checks out a fresh
    connection — the audit writer requires that the connection has not
    previously issued any SQL when ``SET TRANSACTION ISOLATION LEVEL
    SERIALIZABLE`` runs.
    """
    engine = create_async_engine(upgraded_async_url, echo=False, poolclass=NullPool)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
async def patched_audit_session(
    monkeypatch: pytest.MonkeyPatch,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Redirect the service module's ``AsyncSessionLocal`` to the upgraded DB.

    The post-commit hooks instantiate ``AsyncSessionLocal()`` to get a
    *fresh* connection. We replace the module-level binding with a
    callable returning an async context manager that opens a session
    against the same upgraded DB so the audit rows are visible to the
    test's verification SELECTs.
    """
    import echoroo.services.superuser_approval_service as svc_mod

    @asynccontextmanager
    async def _factory() -> Any:
        async with session_factory() as s:
            yield s

    monkeypatch.setattr(svc_mod, "AsyncSessionLocal", _factory)


# ---------------------------------------------------------------------------
# Seed helpers — drive raw SQL throughout because the test DB has the
# *baseline* schema (no ORM Base.metadata.create_all). ORM model imports
# can therefore stay scoped to the service module under test.
# ---------------------------------------------------------------------------


def _u(prefix: str) -> str:
    """Return a unique-per-run identifier with a stable prefix."""
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


async def _create_user(session: AsyncSession, *, email: str) -> uuid.UUID:
    """Insert a minimal ``users`` row and return its id."""
    user_id = uuid.uuid4()
    await session.execute(
        sa.text(
            """
            INSERT INTO users (id, email, password_hash, display_name,
                              security_stamp, created_at, updated_at)
            VALUES (:id, :email, :pw, :name, :stamp, NOW(), NOW())
            """
        ),
        {
            "id": user_id,
            "email": email,
            "pw": "$argon2id$v=19$m=65536,t=3,p=4$test",
            "name": f"User {email}",
            "stamp": "0" * 64,
        },
    )
    return user_id


async def _create_project(session: AsyncSession, *, owner_id: uuid.UUID) -> uuid.UUID:
    """Insert a minimal ``projects`` row and return its id.

    The baseline schema marks ``visibility`` and ``license`` as
    ``NOT NULL`` enums; we set them to legitimate values that the
    permissions code does not touch in this test.
    """
    project_id = uuid.uuid4()
    # ck_projects_restricted_config_shape (apps/api/echoroo/models/project.py)
    # requires every Restricted project to carry the 8 toggle keys. Pass the
    # canonical "all-locked-down" defaults so the row passes the constraint;
    # taxon_override audit logic does not consume any of these toggles.
    restricted_config = (
        '{"allow_media_playback": false,'
        ' "allow_detection_view": false,'
        ' "mask_species_in_detection": false,'
        ' "allow_download": false,'
        ' "allow_export": false,'
        ' "allow_voting_and_comments": false,'
        ' "public_location_precision_h3_res": 3,'
        ' "allow_precise_location_to_viewer": false}'
    )
    await session.execute(
        sa.text(
            """
            INSERT INTO projects (id, name, description, visibility,
                                 license, owner_id, status,
                                 restricted_config, created_at, updated_at)
            VALUES (:id, :name, :desc, 'restricted', 'CC-BY', :owner_id,
                    'active', CAST(:cfg AS JSONB), NOW(), NOW())
            """
        ),
        {
            "id": project_id,
            "name": _u("phase13-r3-audit"),
            "desc": "Phase 13 P1 R3 follow-up audit session contract",
            "owner_id": owner_id,
            "cfg": restricted_config,
        },
    )
    return project_id


async def _create_superuser_row(
    session: AsyncSession, *, user_id: uuid.UUID
) -> uuid.UUID:
    """Insert a ``superusers`` row for *user_id* and return its id."""
    new_id = uuid.uuid4()
    await session.execute(
        sa.text(
            """
            INSERT INTO superusers (id, user_id, added_by_id, added_at)
            VALUES (:id, :user_id, :user_id, NOW())
            """
        ),
        {"id": new_id, "user_id": user_id},
    )
    return new_id


async def _create_pending_looser_override(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    requester_id: uuid.UUID,
) -> tuple[uuid.UUID, str]:
    """Insert a pending looser override + matching approval ticket.

    Returns ``(override_id, taxon_id)``.
    """
    override_id = uuid.uuid4()
    taxon_id = _u("taxon")
    await session.execute(
        sa.text(
            """
            INSERT INTO project_taxon_sensitivity_overrides
                (id, project_id, taxon_id, sensitivity_h3_res, direction,
                 approval_status, requested_by_id, created_at, updated_at)
            VALUES (:id, :project_id, :taxon_id, 9, 'looser',
                    'pending_superuser_approval', :requester_id, NOW(), NOW())
            """
        ),
        {
            "id": override_id,
            "project_id": project_id,
            "taxon_id": taxon_id,
            "requester_id": requester_id,
        },
    )
    detail_json = (
        '{"override_id": "' + str(override_id) + '", '
        '"project_id": "' + str(project_id) + '", '
        '"taxon_id": "' + taxon_id + '", '
        '"sensitivity_h3_res": 9}'
    )
    await session.execute(
        sa.text(
            """
            INSERT INTO superuser_approval_requests
                (action, detail, requesting_user_id, status, created_at, updated_at)
            VALUES ('project.taxon_override.approve_looser',
                    CAST(:detail AS JSONB),
                    :requesting_user_id, 'pending', NOW(), NOW())
            """
        ),
        {"detail": detail_json, "requesting_user_id": requester_id},
    )
    return override_id, taxon_id


# ---------------------------------------------------------------------------
# Tests — use the alembic-upgraded DB so the audit log tables exist.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approve_post_commit_audit_writes_in_fresh_session(
    session_factory: async_sessionmaker[AsyncSession],
    patched_audit_session: None,
) -> None:
    """Approve flow: domain mutation in caller TX, audit rows in fresh sessions.

    Asserts:
      * ``approve_taxon_override`` returns a
        :class:`TaxonOverrideDecisionOutcome` with the expected fields.
      * After ``trigger_decision_post_commit_audit`` runs, BOTH a
        ``project_audit_log`` row (action
        ``project.taxon_override.approve_looser``) and a
        ``platform_audit_log`` row (action
        ``platform.project.taxon_override.approve_looser``) are
        persisted.
      * The override's ``approval_status`` is ``applied``.
    """
    from echoroo.services.superuser_approval_service import (
        TaxonOverrideDecisionOutcome,
        approve_taxon_override,
        trigger_decision_post_commit_audit,
    )

    async with session_factory() as setup:
        owner_id = await _create_user(setup, email=_u("approve_owner") + "@example.com")
        approver_user_id = await _create_user(
            setup, email=_u("approve_su") + "@example.com"
        )
        project_id = await _create_project(setup, owner_id=owner_id)
        approver_su_id = await _create_superuser_row(setup, user_id=approver_user_id)
        override_id, _taxon = await _create_pending_looser_override(
            setup, project_id=project_id, requester_id=owner_id
        )
        await setup.commit()

    # Drive the service in a session that has already run SQL — proves
    # the audit write is NOT issued on this session (otherwise PostgreSQL
    # would reject SET TRANSACTION SERIALIZABLE inside the audit writer).
    async with session_factory() as caller_session:
        await caller_session.execute(sa.text("SELECT 1"))

        outcome: TaxonOverrideDecisionOutcome = await approve_taxon_override(
            caller_session,
            override_id=override_id,
            approver_superuser_id=approver_su_id,
            actor_user_id=approver_user_id,
            request_id="req-approve-1",
            ip="203.0.113.1",
            user_agent="phase13-r3-test",
        )
        await caller_session.commit()

    assert outcome.decision == "approved"
    assert outcome.actor_user_id == approver_user_id
    assert outcome.project_id == project_id
    assert outcome.project_audit_action == "project.taxon_override.approve_looser"
    assert outcome.platform_audit_action == "platform.project.taxon_override.approve_looser"

    # Post-commit hook: writes BOTH audit rows in fresh sessions.
    await trigger_decision_post_commit_audit(outcome)

    async with session_factory() as verify:
        project_action_count = await verify.execute(
            sa.text(
                "SELECT count(*) FROM project_audit_log "
                "WHERE action = :action AND project_id = :project_id"
            ),
            {
                "action": "project.taxon_override.approve_looser",
                "project_id": project_id,
            },
        )
        assert (project_action_count.scalar_one() or 0) >= 1

        platform_action_count = await verify.execute(
            sa.text(
                "SELECT count(*) FROM platform_audit_log WHERE action = :action"
            ),
            {"action": "platform.project.taxon_override.approve_looser"},
        )
        assert (platform_action_count.scalar_one() or 0) >= 1

        override_status = await verify.execute(
            sa.text(
                "SELECT approval_status FROM project_taxon_sensitivity_overrides "
                "WHERE id = :id"
            ),
            {"id": override_id},
        )
        assert override_status.scalar_one() == "applied"


@pytest.mark.asyncio
async def test_reject_post_commit_audit_writes_in_fresh_session(
    session_factory: async_sessionmaker[AsyncSession],
    patched_audit_session: None,
) -> None:
    """Reject flow mirrors approve flow with ``rejected_reason`` carried through."""
    from echoroo.services.superuser_approval_service import (
        reject_taxon_override,
        trigger_decision_post_commit_audit,
    )

    async with session_factory() as setup:
        owner_id = await _create_user(setup, email=_u("reject_owner") + "@example.com")
        approver_user_id = await _create_user(
            setup, email=_u("reject_su") + "@example.com"
        )
        project_id = await _create_project(setup, owner_id=owner_id)
        approver_su_id = await _create_superuser_row(setup, user_id=approver_user_id)
        override_id, _taxon = await _create_pending_looser_override(
            setup, project_id=project_id, requester_id=owner_id
        )
        await setup.commit()

    reason = "Insufficient evidence for relaxation"

    async with session_factory() as caller_session:
        await caller_session.execute(sa.text("SELECT 1"))

        outcome = await reject_taxon_override(
            caller_session,
            override_id=override_id,
            approver_superuser_id=approver_su_id,
            actor_user_id=approver_user_id,
            rejected_reason=reason,
            request_id="req-reject-1",
            ip="203.0.113.2",
            user_agent="phase13-r3-test",
        )
        await caller_session.commit()

    assert outcome.decision == "rejected"
    assert outcome.project_audit_action == "project.taxon_override.reject_looser"
    assert outcome.platform_audit_action == "platform.project.taxon_override.reject_looser"
    assert outcome.project_audit_detail.get("rejected_reason") == reason
    assert outcome.platform_audit_detail.get("rejected_reason") == reason

    await trigger_decision_post_commit_audit(outcome)

    async with session_factory() as verify:
        project_count = await verify.execute(
            sa.text(
                "SELECT count(*) FROM project_audit_log "
                "WHERE action = :action AND project_id = :project_id"
            ),
            {
                "action": "project.taxon_override.reject_looser",
                "project_id": project_id,
            },
        )
        assert (project_count.scalar_one() or 0) >= 1

        platform_count = await verify.execute(
            sa.text(
                "SELECT count(*) FROM platform_audit_log WHERE action = :action"
            ),
            {"action": "platform.project.taxon_override.reject_looser"},
        )
        assert (platform_count.scalar_one() or 0) >= 1

        status_row = await verify.execute(
            sa.text(
                "SELECT approval_status, rejected_reason "
                "FROM project_taxon_sensitivity_overrides WHERE id = :id"
            ),
            {"id": override_id},
        )
        approval_status, rejected_reason = status_row.first()  # type: ignore[misc]
        assert approval_status == "rejected"
        assert rejected_reason == reason


@pytest.mark.asyncio
async def test_approve_taxon_override_does_not_emit_audit_in_caller_session(
    session_factory: async_sessionmaker[AsyncSession],
    patched_audit_session: None,
) -> None:
    """Phase 13 P1 R3 contract: NO audit row is written in the caller's TX.

    Counts ``project_audit_log`` rows for the relevant project BEFORE
    ``approve_taxon_override`` runs and immediately after the caller
    commits (BEFORE ``trigger_decision_post_commit_audit`` fires). The
    counts MUST be equal — the audit row only lands when the post-commit
    helper runs in a fresh session.
    """
    from echoroo.services.superuser_approval_service import (
        approve_taxon_override,
        trigger_decision_post_commit_audit,
    )

    async with session_factory() as setup:
        owner_id = await _create_user(setup, email=_u("noaudit_owner") + "@example.com")
        approver_user_id = await _create_user(
            setup, email=_u("noaudit_su") + "@example.com"
        )
        project_id = await _create_project(setup, owner_id=owner_id)
        approver_su_id = await _create_superuser_row(setup, user_id=approver_user_id)
        override_id, _taxon = await _create_pending_looser_override(
            setup, project_id=project_id, requester_id=owner_id
        )
        await setup.commit()

    async with session_factory() as count_session:
        before_count = await count_session.execute(
            sa.text(
                "SELECT count(*) FROM project_audit_log "
                "WHERE project_id = :project_id"
            ),
            {"project_id": project_id},
        )
        before = before_count.scalar_one() or 0

    async with session_factory() as caller_session:
        # Force non-trivial prior history on the connection so a buggy
        # in-TX audit write would fail PostgreSQL's SET TRANSACTION
        # check during ``approve_taxon_override``.
        await caller_session.execute(sa.text("SELECT 1"))
        outcome = await approve_taxon_override(
            caller_session,
            override_id=override_id,
            approver_superuser_id=approver_su_id,
            actor_user_id=approver_user_id,
        )
        await caller_session.commit()

    async with session_factory() as count_session:
        after_count = await count_session.execute(
            sa.text(
                "SELECT count(*) FROM project_audit_log "
                "WHERE project_id = :project_id"
            ),
            {"project_id": project_id},
        )
        after = after_count.scalar_one() or 0

    assert after == before, (
        "approve_taxon_override must not write a project_audit_log row in the "
        "caller-owned session — that would violate the AuditLogService "
        "fresh-session contract"
    )

    # Now fire the post-commit hook — the row must appear.
    await trigger_decision_post_commit_audit(outcome)

    async with session_factory() as count_session:
        post_hook_count = await count_session.execute(
            sa.text(
                "SELECT count(*) FROM project_audit_log "
                "WHERE project_id = :project_id"
            ),
            {"project_id": project_id},
        )
        post_hook = post_hook_count.scalar_one() or 0

    assert post_hook == before + 1, (
        "trigger_decision_post_commit_audit must add exactly one project "
        "audit row after the caller commits"
    )


@pytest.mark.asyncio
async def test_apply_post_commit_audit_writes_in_fresh_session(
    session_factory: async_sessionmaker[AsyncSession],
    patched_audit_session: None,
) -> None:
    """``apply_taxon_override`` defers the audit row exactly like approve/reject."""
    from echoroo.models.enums import TaxonOverrideDirection
    from echoroo.services.superuser_approval_service import (
        TaxonOverrideApplyOutcome,
        apply_taxon_override,
        trigger_apply_post_commit_audit,
    )

    async with session_factory() as setup:
        owner_id = await _create_user(setup, email=_u("apply_owner") + "@example.com")
        project_id = await _create_project(setup, owner_id=owner_id)
        await setup.commit()

    async with session_factory() as caller_session:
        await caller_session.execute(sa.text("SELECT 1"))
        outcome: TaxonOverrideApplyOutcome = await apply_taxon_override(
            caller_session,
            project_id=project_id,
            taxon_id=_u("apply_taxon"),
            direction=TaxonOverrideDirection.STRICTER,
            sensitivity_h3_res=5,
            requester_id=owner_id,
            request_id="req-apply-1",
            ip="203.0.113.3",
            user_agent="phase13-r3-test",
        )
        await caller_session.commit()

    assert outcome.audit_action == "project.taxon_override.create_stricter"
    assert outcome.actor_user_id == owner_id
    assert outcome.project_id == project_id
    assert outcome.audit_detail.get("override_id") is not None

    await trigger_apply_post_commit_audit(outcome)

    async with session_factory() as verify:
        action_count = await verify.execute(
            sa.text(
                "SELECT count(*) FROM project_audit_log "
                "WHERE action = :action AND project_id = :project_id"
            ),
            {
                "action": "project.taxon_override.create_stricter",
                "project_id": project_id,
            },
        )
        assert (action_count.scalar_one() or 0) >= 1

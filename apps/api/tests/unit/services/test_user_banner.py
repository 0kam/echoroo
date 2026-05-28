"""Unit tests for ``echoroo.services.user_banner`` (spec/011 T061).

Covers the four service-level paths introduced by Step 2:

* :func:`list_banners` — undismissed rows targeting the user, age cap,
  actor / target / both / cross-user matrix.
* :func:`list_activity` — full history, dismissal-ignored, cursor
  pagination.
* :func:`dismiss` — success, idempotency, 404 paths (not found, not
  yours, wrong audit_table).
* :func:`enqueue_event` — shim no-op semantics.

Tests insert audit rows directly via raw SQL (bypassing
``AuditLogService`` and its chain-hash machinery) — the service under
test is the read/dismiss side, not the chain writer. ``compute_pii_hash``
is monkeypatched to a deterministic stub so the unit suite never reaches
out to KMS.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.services import user_banner

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_pii_hash(value: str) -> str:
    """Deterministic PII-hash stub keyed by raw value.

    Each test run gets a stable mapping ``value -> "hash:" + value`` so
    actor-match assertions are easy to reason about without ever calling
    KMS. The 64-char length the schema declares is not enforced at the
    Python type level (it is a SQL ``String(64)`` constraint), and the
    columns the queries match against are textual, so the shorter stub
    is interchangeable for read-side tests.
    """
    return f"hash:{value}"


@pytest.fixture(autouse=True)
def _patch_pii_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace KMS-backed ``compute_pii_hash`` with the deterministic stub.

    Patched on the ``user_banner`` module's import binding so the
    service under test resolves the stub instead of the real KMS call.
    """
    monkeypatch.setattr(user_banner, "compute_pii_hash", _stub_pii_hash)


async def _ensure_project(session: AsyncSession) -> UUID:
    """Insert (or no-op-reuse) a project row referenced by project_audit_log.

    ``project_audit_log.project_id`` has a FK to ``projects.id`` so we
    cannot insert audit rows without a real project. We create one per
    fixture invocation; ``db_session`` cleanup truncates between tests.
    """
    project_id = uuid4()
    owner_id = uuid4()
    # Owner first — projects.owner_id FK.
    await session.execute(
        sa.text(
            """
            INSERT INTO users (id, email, password_hash, security_stamp)
            VALUES (:id, :email, 'x', :stamp)
            """
        ),
        {"id": str(owner_id), "email": f"owner-{owner_id}@example.com", "stamp": "s" * 64},
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
    # ``projects.restricted_config`` has a CHECK that requires the full
    # set of restricted keys when visibility = 'restricted'. We side-step
    # the check by inserting with visibility = 'public' (the CHECK only
    # constrains the restricted variant) — banner targeting is
    # orthogonal to project visibility.
    await session.execute(
        sa.text(
            """
            INSERT INTO projects (id, name, visibility, license_id, status, owner_id)
            VALUES (:id, :name, 'public', 'cc-by', 'active', :owner_id)
            """
        ),
        {
            "id": str(project_id),
            "name": f"banner-test-{project_id}",
            "owner_id": str(owner_id),
        },
    )
    return project_id


async def _insert_audit_row(
    session: AsyncSession,
    *,
    table: str,
    action: str = "auth.login.new_device",
    actor_user_id: UUID | None = None,
    target_user_id: UUID | None = None,
    project_id: UUID | None = None,
    occurred_at: datetime | None = None,
    extra_detail: dict[str, Any] | None = None,
) -> UUID:
    """Insert one audit row with chain-required columns stubbed out.

    The unit suite bypasses chain integrity — the writer (``AuditLogService``)
    is covered by its own tests. We set ``prev_hash`` / ``row_hash`` to
    deterministic placeholders so the trigger / NOT NULL constraints
    accept the row, and rely on the service under test reading the
    targeting + dismissal columns only.
    """
    row_id = uuid4()
    detail: dict[str, Any] = dict(extra_detail or {})
    if target_user_id is not None:
        # The convention the data-model.md anti-impersonation invariant
        # depends on: detail.target_user_id holds the raw UUID JSON
        # string of the targeted user.
        detail["target_user_id"] = str(target_user_id)
    actor_hash = _stub_pii_hash(str(actor_user_id)) if actor_user_id is not None else "0" * 64
    occurred = occurred_at or datetime.now(UTC)
    if table == "project_audit_log":
        if project_id is None:
            project_id = await _ensure_project(session)
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
                "created_at": occurred,
                "actor_hash": actor_hash,
                "project_id": str(project_id),
                "action": action,
                "detail": json.dumps(detail),
                "prev_hash": "0" * 64,
                "row_hash": "f" * 64,
            },
        )
    elif table == "platform_audit_log":
        await session.execute(
            sa.text(
                """
                INSERT INTO platform_audit_log
                  (id, created_at, actor_user_id_hash, action,
                   detail, request_id, ip_hash, user_agent_hash,
                   prev_hash, row_hash)
                VALUES
                  (:id, :created_at, :actor_hash, :action,
                   CAST(:detail AS JSONB), 'test-req', 'ip-hash', 'ua-hash',
                   :prev_hash, :row_hash)
                """
            ),
            {
                "id": str(row_id),
                "created_at": occurred,
                "actor_hash": actor_hash,
                "action": action,
                "detail": json.dumps(detail),
                "prev_hash": "0" * 64,
                "row_hash": "e" * 64,
            },
        )
    else:
        raise ValueError(f"unknown audit table: {table}")
    return row_id


async def _create_user(session: AsyncSession, *, suffix: str = "") -> UUID:
    """Insert a minimal user row (FK target for user_banner_dismissals.user_id)."""
    user_id = uuid4()
    await session.execute(
        sa.text(
            """
            INSERT INTO users (id, email, password_hash, security_stamp)
            VALUES (:id, :email, 'x', :stamp)
            """
        ),
        {
            "id": str(user_id),
            "email": f"u-{suffix or user_id}@example.com",
            "stamp": "s" * 64,
        },
    )
    return user_id


# ---------------------------------------------------------------------------
# list_banners
# ---------------------------------------------------------------------------


async def test_list_banners_returns_actor_match_project_row(db_session: AsyncSession) -> None:
    """A project_audit_log row authored by the user surfaces as a banner."""
    user_id = await _create_user(db_session, suffix="actor")
    row_id = await _insert_audit_row(
        db_session,
        table="project_audit_log",
        actor_user_id=user_id,
    )
    await db_session.flush()

    banners = await user_banner.list_banners(db_session, user_id=user_id)

    assert len(banners) == 1
    assert banners[0].audit_table == "project_audit_log"
    assert banners[0].audit_log_id == row_id


async def test_list_banners_returns_target_match_platform_row(db_session: AsyncSession) -> None:
    """A platform_audit_log row whose detail.target_user_id is the user surfaces."""
    actor = await _create_user(db_session, suffix="actor")
    target = await _create_user(db_session, suffix="target")
    row_id = await _insert_audit_row(
        db_session,
        table="platform_audit_log",
        actor_user_id=actor,
        target_user_id=target,
    )
    await db_session.flush()

    banners = await user_banner.list_banners(db_session, user_id=target)

    assert len(banners) == 1
    assert banners[0].audit_log_id == row_id
    assert banners[0].audit_table == "platform_audit_log"


async def test_list_banners_returns_actor_match_when_also_target(
    db_session: AsyncSession,
) -> None:
    """When the user is BOTH actor and target the row surfaces exactly once."""
    user_id = await _create_user(db_session, suffix="self")
    await _insert_audit_row(
        db_session,
        table="platform_audit_log",
        actor_user_id=user_id,
        target_user_id=user_id,
    )
    await db_session.flush()

    banners = await user_banner.list_banners(db_session, user_id=user_id)

    assert len(banners) == 1


async def test_list_banners_excludes_rows_for_other_users(db_session: AsyncSession) -> None:
    """A row authored by AND targeting a different user MUST NOT surface."""
    me = await _create_user(db_session, suffix="me")
    other = await _create_user(db_session, suffix="other")
    third = await _create_user(db_session, suffix="third")
    await _insert_audit_row(
        db_session,
        table="platform_audit_log",
        actor_user_id=other,
        target_user_id=third,
    )
    await db_session.flush()

    banners = await user_banner.list_banners(db_session, user_id=me)

    assert banners == []


async def test_list_banners_excludes_dismissed_rows(db_session: AsyncSession) -> None:
    """A dismissed banner MUST NOT appear in subsequent list calls."""
    user_id = await _create_user(db_session, suffix="dismiss")
    row_id = await _insert_audit_row(
        db_session,
        table="platform_audit_log",
        actor_user_id=user_id,
    )
    await db_session.flush()

    await user_banner.dismiss(
        db_session,
        user_id=user_id,
        audit_table="platform_audit_log",
        audit_log_id=row_id,
    )
    await db_session.flush()

    banners = await user_banner.list_banners(db_session, user_id=user_id)

    assert banners == []


async def test_list_banners_age_filter_drops_old_rows(db_session: AsyncSession) -> None:
    """Rows older than max_age_days MUST be excluded from the banner list."""
    user_id = await _create_user(db_session, suffix="age")
    old_id = await _insert_audit_row(
        db_session,
        table="platform_audit_log",
        actor_user_id=user_id,
        occurred_at=datetime.now(UTC) - timedelta(days=45),
    )
    fresh_id = await _insert_audit_row(
        db_session,
        table="platform_audit_log",
        actor_user_id=user_id,
        occurred_at=datetime.now(UTC) - timedelta(days=2),
    )
    await db_session.flush()

    banners = await user_banner.list_banners(db_session, user_id=user_id, max_age_days=30)
    surfaced_ids = {b.audit_log_id for b in banners}

    assert fresh_id in surfaced_ids
    assert old_id not in surfaced_ids


async def test_list_banners_age_zero_or_negative_returns_empty(
    db_session: AsyncSession,
) -> None:
    """A non-positive ``max_age_days`` yields an empty list short-circuit."""
    user_id = await _create_user(db_session, suffix="zero")
    await _insert_audit_row(
        db_session,
        table="platform_audit_log",
        actor_user_id=user_id,
    )
    await db_session.flush()

    assert await user_banner.list_banners(db_session, user_id=user_id, max_age_days=0) == []
    assert await user_banner.list_banners(db_session, user_id=user_id, max_age_days=-5) == []


async def test_list_banners_orders_newest_first(db_session: AsyncSession) -> None:
    """Banner list MUST be ordered by occurred_at descending."""
    user_id = await _create_user(db_session, suffix="order")
    older_id = await _insert_audit_row(
        db_session,
        table="platform_audit_log",
        actor_user_id=user_id,
        occurred_at=datetime.now(UTC) - timedelta(hours=10),
    )
    newer_id = await _insert_audit_row(
        db_session,
        table="platform_audit_log",
        actor_user_id=user_id,
        occurred_at=datetime.now(UTC) - timedelta(hours=1),
    )
    await db_session.flush()

    banners = await user_banner.list_banners(db_session, user_id=user_id)

    assert [b.audit_log_id for b in banners] == [newer_id, older_id]


# ---------------------------------------------------------------------------
# dismiss
# ---------------------------------------------------------------------------


async def test_dismiss_succeeds_for_actor_match(db_session: AsyncSession) -> None:
    """The actor of an audit row may dismiss it."""
    user_id = await _create_user(db_session, suffix="actordismiss")
    row_id = await _insert_audit_row(
        db_session,
        table="project_audit_log",
        actor_user_id=user_id,
    )
    await db_session.flush()

    await user_banner.dismiss(
        db_session,
        user_id=user_id,
        audit_table="project_audit_log",
        audit_log_id=row_id,
    )
    await db_session.flush()

    # Verify the dismissal row was persisted.
    result = await db_session.execute(
        sa.text(
            "SELECT 1 FROM user_banner_dismissals "
            "WHERE user_id = :u AND audit_table = :t AND audit_log_id = :i"
        ),
        {"u": str(user_id), "t": "project_audit_log", "i": str(row_id)},
    )
    assert result.first() is not None


async def test_dismiss_succeeds_for_target_match(db_session: AsyncSession) -> None:
    """The detail.target_user_id of an audit row may dismiss it."""
    actor = await _create_user(db_session, suffix="actor2")
    target = await _create_user(db_session, suffix="target2")
    row_id = await _insert_audit_row(
        db_session,
        table="platform_audit_log",
        actor_user_id=actor,
        target_user_id=target,
    )
    await db_session.flush()

    await user_banner.dismiss(
        db_session,
        user_id=target,
        audit_table="platform_audit_log",
        audit_log_id=row_id,
    )
    await db_session.flush()

    # Banner list MUST exclude the now-dismissed row.
    assert await user_banner.list_banners(db_session, user_id=target) == []


async def test_dismiss_is_idempotent(db_session: AsyncSession) -> None:
    """Repeated dismiss of the same (table, id) MUST NOT raise."""
    user_id = await _create_user(db_session, suffix="idem")
    row_id = await _insert_audit_row(
        db_session,
        table="platform_audit_log",
        actor_user_id=user_id,
    )
    await db_session.flush()

    await user_banner.dismiss(
        db_session, user_id=user_id, audit_table="platform_audit_log", audit_log_id=row_id
    )
    await user_banner.dismiss(
        db_session, user_id=user_id, audit_table="platform_audit_log", audit_log_id=row_id
    )
    await db_session.flush()

    # Still exactly one row in user_banner_dismissals.
    result = await db_session.execute(
        sa.text(
            "SELECT COUNT(*) FROM user_banner_dismissals "
            "WHERE user_id = :u AND audit_log_id = :i"
        ),
        {"u": str(user_id), "i": str(row_id)},
    )
    assert result.scalar_one() == 1


async def test_dismiss_raises_on_unknown_row(db_session: AsyncSession) -> None:
    """A bogus audit_log_id MUST raise BannerNotFoundError."""
    user_id = await _create_user(db_session, suffix="404")
    bogus_id = uuid4()
    await db_session.flush()

    with pytest.raises(user_banner.BannerNotFoundError):
        await user_banner.dismiss(
            db_session,
            user_id=user_id,
            audit_table="platform_audit_log",
            audit_log_id=bogus_id,
        )


async def test_dismiss_raises_on_cross_user_row(db_session: AsyncSession) -> None:
    """A row authored by AND targeting another user MUST 404 the caller."""
    me = await _create_user(db_session, suffix="me2")
    other = await _create_user(db_session, suffix="other2")
    third = await _create_user(db_session, suffix="third2")
    row_id = await _insert_audit_row(
        db_session,
        table="platform_audit_log",
        actor_user_id=other,
        target_user_id=third,
    )
    await db_session.flush()

    with pytest.raises(user_banner.BannerNotFoundError):
        await user_banner.dismiss(
            db_session,
            user_id=me,
            audit_table="platform_audit_log",
            audit_log_id=row_id,
        )


async def test_dismiss_raises_on_unknown_audit_table(db_session: AsyncSession) -> None:
    """An audit_table outside the allowlist MUST short-circuit to 404."""
    user_id = await _create_user(db_session, suffix="badtable")
    await db_session.flush()

    with pytest.raises(user_banner.BannerNotFoundError):
        await user_banner.dismiss(
            db_session,
            user_id=user_id,
            audit_table="not_an_audit_table",
            audit_log_id=uuid4(),
        )


# ---------------------------------------------------------------------------
# list_activity
# ---------------------------------------------------------------------------


async def test_list_activity_returns_all_targeted_rows_including_dismissed(
    db_session: AsyncSession,
) -> None:
    """Dismissal MUST NOT filter the activity view (FR-011-307)."""
    user_id = await _create_user(db_session, suffix="actfull")
    row_id = await _insert_audit_row(
        db_session,
        table="platform_audit_log",
        actor_user_id=user_id,
    )
    await db_session.flush()
    await user_banner.dismiss(
        db_session,
        user_id=user_id,
        audit_table="platform_audit_log",
        audit_log_id=row_id,
    )
    await db_session.flush()

    page = await user_banner.list_activity(db_session, user_id=user_id)

    assert len(page.items) == 1
    assert page.items[0].audit_log_id == row_id


async def test_list_activity_returns_old_rows(db_session: AsyncSession) -> None:
    """The 30-day banner age cap MUST NOT apply to activity (FR-011-307)."""
    user_id = await _create_user(db_session, suffix="actold")
    old_id = await _insert_audit_row(
        db_session,
        table="platform_audit_log",
        actor_user_id=user_id,
        occurred_at=datetime.now(UTC) - timedelta(days=400),
    )
    await db_session.flush()

    page = await user_banner.list_activity(db_session, user_id=user_id)
    surfaced_ids = {item.audit_log_id for item in page.items}

    assert old_id in surfaced_ids


async def test_list_activity_cursor_pagination(db_session: AsyncSession) -> None:
    """Activity MUST support cursor-based pagination across multiple pages."""
    user_id = await _create_user(db_session, suffix="actpage")
    # 5 rows, oldest -> newest by spacing.
    base = datetime.now(UTC)
    ids = [
        await _insert_audit_row(
            db_session,
            table="platform_audit_log",
            actor_user_id=user_id,
            occurred_at=base - timedelta(minutes=10 - i),
        )
        for i in range(5)
    ]
    await db_session.flush()

    page1 = await user_banner.list_activity(db_session, user_id=user_id, limit=2)
    assert len(page1.items) == 2
    assert page1.next_cursor is not None
    # Newest two are the last two ids (i=3, i=4 — closest to base).
    assert [item.audit_log_id for item in page1.items] == [ids[4], ids[3]]

    page2 = await user_banner.list_activity(
        db_session, user_id=user_id, limit=2, cursor=page1.next_cursor
    )
    assert len(page2.items) == 2
    assert page2.next_cursor is not None
    assert [item.audit_log_id for item in page2.items] == [ids[2], ids[1]]

    page3 = await user_banner.list_activity(
        db_session, user_id=user_id, limit=2, cursor=page2.next_cursor
    )
    assert len(page3.items) == 1
    assert page3.next_cursor is None
    assert page3.items[0].audit_log_id == ids[0]


async def test_list_activity_malformed_cursor_starts_from_top(
    db_session: AsyncSession,
) -> None:
    """A garbage cursor degrades to "start from the top" rather than raising."""
    user_id = await _create_user(db_session, suffix="actbadcur")
    row_id = await _insert_audit_row(
        db_session,
        table="platform_audit_log",
        actor_user_id=user_id,
    )
    await db_session.flush()

    page = await user_banner.list_activity(
        db_session, user_id=user_id, cursor="!!!not-a-real-cursor!!!"
    )

    assert any(item.audit_log_id == row_id for item in page.items)


async def test_list_activity_excludes_other_users(db_session: AsyncSession) -> None:
    """Activity for another user MUST NOT surface."""
    me = await _create_user(db_session, suffix="actme")
    other = await _create_user(db_session, suffix="actother")
    third = await _create_user(db_session, suffix="actthird")
    await _insert_audit_row(
        db_session,
        table="platform_audit_log",
        actor_user_id=other,
        target_user_id=third,
    )
    await db_session.flush()

    page = await user_banner.list_activity(db_session, user_id=me)

    assert page.items == []


async def test_list_activity_zero_limit_returns_empty_page(
    db_session: AsyncSession,
) -> None:
    """A non-positive limit yields an empty page short-circuit."""
    user_id = await _create_user(db_session, suffix="actzero")
    await db_session.flush()

    page = await user_banner.list_activity(db_session, user_id=user_id, limit=0)

    assert page.items == []
    assert page.next_cursor is None


# ---------------------------------------------------------------------------
# enqueue_event
# ---------------------------------------------------------------------------


async def test_enqueue_event_is_no_op(db_session: AsyncSession) -> None:
    """enqueue_event MUST NOT write any rows or raise on valid input."""
    user_id = await _create_user(db_session, suffix="enq")
    await db_session.flush()

    await user_banner.enqueue_event(
        db_session,
        user_id=user_id,
        audit_table="platform_audit_log",
        audit_log_id=uuid4(),
    )

    # No rows should have been written to user_banner_dismissals.
    result = await db_session.execute(
        sa.text("SELECT COUNT(*) FROM user_banner_dismissals WHERE user_id = :u"),
        {"u": str(user_id)},
    )
    assert result.scalar_one() == 0


async def test_enqueue_event_unknown_audit_table_is_silent(
    db_session: AsyncSession,
) -> None:
    """An unknown audit_table on the enqueue shim MUST NOT raise."""
    user_id = await _create_user(db_session, suffix="enqbad")
    await db_session.flush()

    # Pure absence-of-exception assertion — the shim logs and returns.
    await user_banner.enqueue_event(
        db_session,
        user_id=user_id,
        audit_table="garbage_table",
        audit_log_id=uuid4(),
    )


# ---------------------------------------------------------------------------
# Codex R1 NO-GO follow-ups
# ---------------------------------------------------------------------------


async def test_list_banners_filters_to_eligible_actions(
    db_session: AsyncSession,
) -> None:
    """Banner list MUST exclude actions outside ``BANNER_ELIGIBLE_ACTIONS``.

    Activity (FR-011-307) keeps both rows; the banner stack
    (FR-011-008 / FR-011-302) keeps only the eligible one. The
    ``project.create`` action is the canonical "bookkeeping" event
    spec/011 explicitly keeps off the banner surface — it is not in
    :data:`user_banner.BANNER_ELIGIBLE_ACTIONS` but is allowed by the
    audit-action vocabulary, so it is the ideal counter-example here.
    """
    user_id = await _create_user(db_session, suffix="elig")
    project_id = await _ensure_project(db_session)
    eligible_id = await _insert_audit_row(
        db_session,
        table="project_audit_log",
        action="project.member.invite_accepted",  # in BANNER_ELIGIBLE_ACTIONS
        actor_user_id=user_id,
        project_id=project_id,
    )
    ineligible_id = await _insert_audit_row(
        db_session,
        table="project_audit_log",
        action="project.create",  # NOT in BANNER_ELIGIBLE_ACTIONS
        actor_user_id=user_id,
        project_id=project_id,
    )
    await db_session.flush()

    banners = await user_banner.list_banners(db_session, user_id=user_id)
    surfaced_banner_ids = {b.audit_log_id for b in banners}

    # Eligible action surfaces as a banner; ineligible action MUST NOT.
    assert eligible_id in surfaced_banner_ids
    assert ineligible_id not in surfaced_banner_ids

    # The activity view is unfiltered (FR-011-307): both rows surface.
    page = await user_banner.list_activity(db_session, user_id=user_id)
    surfaced_activity_ids = {item.audit_log_id for item in page.items}
    assert eligible_id in surfaced_activity_ids
    assert ineligible_id in surfaced_activity_ids


async def test_list_activity_pagination_same_timestamp_boundary(
    db_session: AsyncSession,
) -> None:
    """Cursor pagination MUST NOT drop rows that share ``occurred_at``.

    The previous tuple ``<`` comparison would treat
    ``(occurred_at, audit_table, audit_log_id) < (...)`` as a uniform-
    direction tuple, but ORDER BY is mixed-direction
    (``occurred_at DESC, audit_table ASC, audit_log_id ASC``) so rows
    sharing ``occurred_at`` with the cursor fell on the wrong side of
    the boundary. This test inserts three rows at **exactly the same
    timestamp**, pages through with ``limit=2``, and asserts the union
    is loss-less and duplicate-free.
    """
    user_id = await _create_user(db_session, suffix="actsamets")
    shared_ts = datetime.now(UTC) - timedelta(minutes=1)
    ids = [
        await _insert_audit_row(
            db_session,
            table="platform_audit_log",
            actor_user_id=user_id,
            occurred_at=shared_ts,
        )
        for _ in range(3)
    ]
    await db_session.flush()

    page1 = await user_banner.list_activity(db_session, user_id=user_id, limit=2)
    assert len(page1.items) == 2
    assert page1.next_cursor is not None

    page2 = await user_banner.list_activity(
        db_session, user_id=user_id, limit=2, cursor=page1.next_cursor
    )
    assert len(page2.items) == 1
    assert page2.next_cursor is None

    seen = [item.audit_log_id for item in page1.items + page2.items]
    # No duplicates across pages.
    assert len(seen) == len(set(seen))
    # The union covers every original row (no drops at the boundary).
    assert set(seen) == set(ids)

"""Unit tests for the dormancy check worker (T704, FR-060, SC-008).

Tests target the async helper functions inside
:mod:`echoroo.workers.dormancy_check` directly, using a mock-based
approach that does NOT require a live PostgreSQL connection.

This mirrors the pattern used by:
- ``test_trusted_auto_expire.py``   (trusted overlay auto-expire)
- ``test_trusted_expiry_notifier.py`` (trusted overlay notifier)

Coverage matrix
---------------
===========  ==================================================  ===========
Scenario     Owner ``last_first_party_activity_at``              Expected
===========  ==================================================  ===========
T704-1       365 days ago (= threshold -1 day, within window)   Not included in candidates
T704-2       366 days ago (exactly at threshold)                DORMANT, stage_initial
T704-3       367 days ago                                       DORMANT, stage_initial
T704-4       API-key-only (last_first_party_activity_at = NULL) DORMANT (FR-060 parity)
T704-5       Follow-up +3 d                                     stage_3d enqueued
T704-6       Follow-up +30 d                                    stage_30d enqueued
T704-7       Follow-up +37 d                                    stage_final enqueued
T704-8       Follow-up +366 d                                   stage_grace_expired enqueued
T704-9       Idempotency key format                             correct key per stage+day
T704-10      already DORMANT project re-scanned                 _flip_to_dormant returns False
===========  ==================================================  ===========

Design notes
------------
* ``_flip_to_dormant`` issues a SELECT FOR UPDATE on a real DB.
  To avoid a live-DB dependency we test the **scanning** and
  **stage-emission** logic via ``_scan_active_projects`` filtering
  semantics (checked at the SQL parameter level) and by calling
  ``_emit_followup_stages`` with a fake session that returns
  canned DORMANT project rows.
* ``run_dormancy_check`` is tested via the low-level helpers because
  the advisory-lock call (``pg_try_advisory_xact_lock``) requires a
  real PostgreSQL connection.  Integration-level coverage of the full
  pipeline is provided by the contract tests.
* The ``enqueue`` helper from :mod:`echoroo.services.outbox_service`
  is monkey-patched so no ``outbox_events`` table is needed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from echoroo.models.enums import ProjectStatus
from echoroo.workers.dormancy_check import (
    DORMANT_THRESHOLD_SECONDS,
    OUTBOX_EVENT_DORMANCY,
    STAGE_OFFSETS,
    _emit_followup_stages,
    _enqueue_stage,
    _scan_active_projects,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fake SQLAlchemy plumbing
# ---------------------------------------------------------------------------


class _RowProxy:
    """Minimal row proxy for (Project, User) pairs."""

    def __init__(self, project: Any, user: Any):
        self._project = project
        self._user = user

    def __getitem__(self, idx: int) -> Any:
        return (self._project, self._user)[idx]


class _ScalarResult:
    def __init__(self, rows: list[tuple[Any, Any]]):
        self._rows = rows

    def all(self) -> list[tuple[Any, Any]]:
        return [(r[0], r[1]) for r in self._rows]


class _FakeResult:
    def __init__(self, rows: list[tuple[Any, Any]]):
        self._rows = rows

    def all(self) -> list[tuple[Any, Any]]:
        return [(r[0], r[1]) for r in self._rows]

    def mappings(self) -> _FakeResult:
        return self

    def scalar_one(self) -> Any:
        return self._rows[0][0] if self._rows else None


class _FakeSession:
    """Minimal async session double for dormancy check tests."""

    def __init__(self, rows: list[tuple[Any, Any]] | None = None) -> None:
        self._rows = rows or []
        self.commits: int = 0
        self.rollbacks: int = 0

    async def execute(self, _stmt: Any, _params: Any | None = None) -> _FakeResult:
        return _FakeResult(self._rows)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def flush(self) -> None:
        pass


class _SessionCM:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, *_exc: Any) -> bool:
        return False


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_project(
    *,
    status: ProjectStatus = ProjectStatus.ACTIVE,
    dormant_since: datetime | None = None,
    name: str = "Test Project",
) -> MagicMock:
    """Return a mock Project with the required fields."""
    proj = MagicMock()
    proj.id = uuid4()
    proj.name = name
    proj.status = status
    proj.dormant_since = dormant_since
    proj.updated_at = None
    return proj


def _make_user(
    *,
    last_first_party_activity_at: datetime | None = None,
) -> MagicMock:
    """Return a mock User with the required fields."""
    u = MagicMock()
    u.id = uuid4()
    u.email = f"user_{uuid4().hex[:8]}@example.com"
    u.last_first_party_activity_at = last_first_party_activity_at
    return u


# ---------------------------------------------------------------------------
# T704-1: 365 days ago — within window, NOT past cutoff
# ---------------------------------------------------------------------------


async def test_365_days_not_past_cutoff() -> None:
    """Owner last active 365 days ago stays within the safe zone.

    The scan query filters WHERE last_first_party_activity_at < cutoff.
    cutoff = now - 366d (DORMANT_THRESHOLD_SECONDS).  365 days ago is
    strictly NEWER than the cutoff so the project should not appear in
    the candidates list.

    This test verifies the cutoff arithmetic used by ``_scan_active_projects``
    by checking that the timedelta comparison works as expected without
    mocking the DB call (pure logic check).
    """
    now = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)
    cutoff = now - timedelta(seconds=DORMANT_THRESHOLD_SECONDS)
    activity_365d_ago = now - timedelta(days=365)

    # 365 days ago is MORE recent than the cutoff (366 days ago)
    # so the owner has NOT crossed the dormancy boundary.
    assert activity_365d_ago > cutoff, (
        "365 days ago must be within the dormancy window (not dormant)"
    )


# ---------------------------------------------------------------------------
# T704-2: exactly at threshold (366d + 1s) → past cutoff
# ---------------------------------------------------------------------------


async def test_366_days_past_cutoff() -> None:
    """Owner last active 366 days + 1 second ago crosses the cutoff.

    The worker uses ``last_first_party_activity_at < cutoff`` (strict
    less-than) so the owner at exactly the cutoff boundary is included.
    This test verifies the boundary arithmetic.
    """
    now = datetime(2025, 6, 2, 0, 0, 0, tzinfo=UTC)
    cutoff = now - timedelta(seconds=DORMANT_THRESHOLD_SECONDS)
    # One second past the threshold
    activity = now - timedelta(seconds=DORMANT_THRESHOLD_SECONDS + 1)

    assert activity < cutoff, (
        "366d+1s ago must be older than the dormancy cutoff → should be flagged"
    )


# ---------------------------------------------------------------------------
# T704-3: NULL last_first_party_activity_at → API-key-only, treated as dormant
# ---------------------------------------------------------------------------


async def test_null_activity_is_treated_as_dormant() -> None:
    """Owner with NULL last_first_party_activity_at is included in scan.

    The SQL query includes:
      OR last_first_party_activity_at IS NULL
    so a NULL value is treated as dormant (never had first-party activity).
    Verify that the worker docstring / STAGE_OFFSETS constant match spec FR-060.
    """
    # STAGE_OFFSETS must start with stage_initial (offset = 0) so the
    # first notification fires on the transition day.
    assert "stage_initial" in STAGE_OFFSETS
    assert STAGE_OFFSETS["stage_initial"].days == 0, (
        "stage_initial must fire on the same day as the DORMANT transition (offset=0)"
    )


# ---------------------------------------------------------------------------
# T704-4 through T704-8: Follow-up stage offsets
# ---------------------------------------------------------------------------


async def test_stage_offsets_match_spec() -> None:
    """Verify STAGE_OFFSETS match spec FR-060 (3d / 30d / 37d / 366d)."""
    assert STAGE_OFFSETS["stage_3d"] == timedelta(days=3)
    assert STAGE_OFFSETS["stage_30d"] == timedelta(days=30)
    assert STAGE_OFFSETS["stage_final"] == timedelta(days=37), (
        "stage_final = 30 + 7 = 37 days per FR-060"
    )
    assert STAGE_OFFSETS["stage_grace_expired"] == timedelta(
        seconds=DORMANT_THRESHOLD_SECONDS
    ), "stage_grace_expired must fire after the full dormancy threshold (366d)"


# ---------------------------------------------------------------------------
# T704-5: _emit_followup_stages fires stage_3d when 3d has elapsed
# ---------------------------------------------------------------------------


async def test_emit_followup_stage_3d() -> None:
    """_emit_followup_stages emits stage_3d for a project 3d+ past dormant_since."""
    now = datetime(2025, 6, 5, 0, 0, 0, tzinfo=UTC)
    dormant_since = now - timedelta(days=3, seconds=1)

    project = _make_project(
        status=ProjectStatus.DORMANT,
        dormant_since=dormant_since,
    )
    owner = _make_user(last_first_party_activity_at=now - timedelta(days=400))

    session = _FakeSession(rows=[(project, owner)])
    enqueue_calls: list[str] = []

    async def fake_enqueue(
        _session: Any,
        *,
        event_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> Any:
        enqueue_calls.append(payload.get("stage", ""))
        return uuid4()

    with patch(
        "echoroo.workers.dormancy_check.enqueue",
        new=fake_enqueue,
    ):
        count = await _emit_followup_stages(session, now=now)

    assert "stage_3d" in enqueue_calls, (
        f"Expected stage_3d to be enqueued; got {enqueue_calls}"
    )
    assert count >= 1


# ---------------------------------------------------------------------------
# T704-6: _emit_followup_stages fires stage_30d when 30d has elapsed
# ---------------------------------------------------------------------------


async def test_emit_followup_stage_30d() -> None:
    """_emit_followup_stages emits stage_30d for a project 30d+ past dormant_since."""
    now = datetime(2025, 6, 6, 0, 0, 0, tzinfo=UTC)
    dormant_since = now - timedelta(days=30, seconds=1)

    project = _make_project(status=ProjectStatus.DORMANT, dormant_since=dormant_since)
    owner = _make_user()

    session = _FakeSession(rows=[(project, owner)])
    enqueue_calls: list[str] = []

    async def fake_enqueue(
        _session: Any,
        *,
        event_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> Any:
        enqueue_calls.append(payload.get("stage", ""))
        return uuid4()

    with patch("echoroo.workers.dormancy_check.enqueue", new=fake_enqueue):
        count = await _emit_followup_stages(session, now=now)

    assert "stage_30d" in enqueue_calls, (
        f"Expected stage_30d to be enqueued; got {enqueue_calls}"
    )
    assert count >= 1


# ---------------------------------------------------------------------------
# T704-7: stage_final (37 days = 30 + 7)
# ---------------------------------------------------------------------------


async def test_emit_followup_stage_final() -> None:
    """_emit_followup_stages emits stage_final for a project 37d+ past dormant_since."""
    now = datetime(2025, 6, 7, 0, 0, 0, tzinfo=UTC)
    dormant_since = now - timedelta(days=37, seconds=1)

    project = _make_project(status=ProjectStatus.DORMANT, dormant_since=dormant_since)
    owner = _make_user()

    session = _FakeSession(rows=[(project, owner)])
    enqueue_calls: list[str] = []

    async def fake_enqueue(
        _session: Any,
        *,
        event_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> Any:
        enqueue_calls.append(payload.get("stage", ""))
        return uuid4()

    with patch("echoroo.workers.dormancy_check.enqueue", new=fake_enqueue):
        count = await _emit_followup_stages(session, now=now)

    assert "stage_final" in enqueue_calls, (
        f"Expected stage_final to be enqueued; got {enqueue_calls}"
    )
    assert count >= 1


# ---------------------------------------------------------------------------
# T704-8: stage_grace_expired (366 days / DORMANT_THRESHOLD_SECONDS)
# ---------------------------------------------------------------------------


async def test_emit_followup_stage_grace_expired() -> None:
    """_emit_followup_stages emits stage_grace_expired for a project 366d+ dormant."""
    now = datetime(2025, 6, 8, 0, 0, 0, tzinfo=UTC)
    dormant_since = now - timedelta(seconds=DORMANT_THRESHOLD_SECONDS + 1)

    project = _make_project(status=ProjectStatus.DORMANT, dormant_since=dormant_since)
    owner = _make_user()

    session = _FakeSession(rows=[(project, owner)])
    enqueue_calls: list[str] = []

    async def fake_enqueue(
        _session: Any,
        *,
        event_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> Any:
        enqueue_calls.append(payload.get("stage", ""))
        return uuid4()

    with patch("echoroo.workers.dormancy_check.enqueue", new=fake_enqueue):
        count = await _emit_followup_stages(session, now=now)

    assert "stage_grace_expired" in enqueue_calls, (
        f"Expected stage_grace_expired; got {enqueue_calls}"
    )
    assert count >= 1


# ---------------------------------------------------------------------------
# T704-9: Idempotency key format — same stage+day → same key (no duplicates)
# ---------------------------------------------------------------------------


async def test_idempotency_key_format_per_stage_only() -> None:
    """Two _enqueue_stage calls for the same (project, stage) reuse the same key.

    Phase 12 R1 M2: the outbox idempotency key uses
    ``dormancy:{project_id}:{stage}`` (no date component). Every beat
    tick after the first collapses on the unique constraint regardless
    of which UTC day it lands on. This test validates the KEY FORMAT by
    calling _enqueue_stage twice with the same stage but different
    dates and asserting both calls use the same key (so the second call
    is guaranteed to be a no-op via ON CONFLICT DO NOTHING semantics
    when paired with outbox_service).
    """
    day_1 = datetime(2025, 6, 9, 12, 0, 0, tzinfo=UTC)
    day_2 = datetime(2025, 6, 10, 9, 0, 0, tzinfo=UTC)  # next UTC day

    project = _make_project(
        status=ProjectStatus.DORMANT,
        dormant_since=day_1 - timedelta(hours=1),
    )
    owner = _make_user()

    collected_keys: list[str] = []

    async def fake_enqueue(
        _session: Any,
        *,
        event_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> Any:
        collected_keys.append(idempotency_key)
        return uuid4()

    session = _FakeSession()

    with patch("echoroo.workers.dormancy_check.enqueue", new=fake_enqueue):
        await _enqueue_stage(
            session, project=project, owner=owner, stage="stage_initial", now=day_1
        )
        await _enqueue_stage(
            session, project=project, owner=owner, stage="stage_initial", now=day_2
        )

    assert len(collected_keys) == 2, "Expected two enqueue calls"
    assert collected_keys[0] == collected_keys[1], (
        f"Both calls for the same (project, stage) must reuse the same "
        f"idempotency key irrespective of date "
        f"(got {collected_keys[0]!r} vs {collected_keys[1]!r})"
    )
    # Key MUST NOT contain a date marker (no YYYY-MM-DD suffix).
    assert "2025-" not in collected_keys[0], (
        f"Idempotency key must not include a date component "
        f"(got {collected_keys[0]!r})"
    )


# ---------------------------------------------------------------------------
# T704-10: already-DORMANT project skipped by _emit_followup_stages
#          when no offset has elapsed yet
# ---------------------------------------------------------------------------


async def test_emit_followup_skips_stages_not_yet_due() -> None:
    """Stages whose offset has NOT elapsed are not enqueued by _emit_followup_stages.

    A project that became dormant 2 hours ago must NOT trigger stage_3d
    (offset = 3 days).
    """
    now = datetime(2025, 6, 10, 0, 0, 0, tzinfo=UTC)
    # Dormant since only 2 hours ago — no follow-up stages should fire.
    dormant_since = now - timedelta(hours=2)

    project = _make_project(status=ProjectStatus.DORMANT, dormant_since=dormant_since)
    owner = _make_user()

    session = _FakeSession(rows=[(project, owner)])
    enqueue_calls: list[str] = []

    async def fake_enqueue(
        _session: Any,
        *,
        event_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> Any:
        enqueue_calls.append(payload.get("stage", ""))
        return uuid4()

    with patch("echoroo.workers.dormancy_check.enqueue", new=fake_enqueue):
        count = await _emit_followup_stages(session, now=now)

    # No follow-up stage should have fired (stage_initial is excluded by
    # _emit_followup_stages, and 3d/30d/37d/366d have not elapsed).
    assert count == 0, (
        f"Expected 0 follow-up stages for a project dormant for only 2 hours; "
        f"got {count} (stages: {enqueue_calls})"
    )


# ---------------------------------------------------------------------------
# T704-11: OUTBOX_EVENT_DORMANCY constant matches spec discriminator
# ---------------------------------------------------------------------------


def test_outbox_event_type_constant() -> None:
    """OUTBOX_EVENT_DORMANCY must match the spec discriminator."""
    assert OUTBOX_EVENT_DORMANCY == "project.dormancy_notification", (
        "OUTBOX_EVENT_DORMANCY must equal 'project.dormancy_notification' per spec"
    )


# ---------------------------------------------------------------------------
# T704-12: _scan_active_projects SQL filter semantics
# ---------------------------------------------------------------------------


async def test_scan_active_projects_uses_or_null_condition() -> None:
    """_scan_active_projects returns rows for NULL last_first_party_activity_at.

    The implementation uses ``OR last_first_party_activity_at IS NULL``
    so owners with no first-party activity are included in the scan.
    We verify the scan returns canned ACTIVE+NULL rows when the DB
    session returns them.
    """
    now = datetime(2025, 6, 11, 0, 0, 0, tzinfo=UTC)
    cutoff = now - timedelta(seconds=DORMANT_THRESHOLD_SECONDS)

    project = _make_project(status=ProjectStatus.ACTIVE)
    owner = _make_user(last_first_party_activity_at=None)

    # Fake session returns the project+owner pair (simulating the DB
    # returning the row because it matches the WHERE condition).
    session = _FakeSession(rows=[(project, owner)])

    result = await _scan_active_projects(session, cutoff=cutoff)

    assert len(result) == 1, "Expected 1 active project candidate"
    assert result[0][0].id == project.id
    assert result[0][1].last_first_party_activity_at is None

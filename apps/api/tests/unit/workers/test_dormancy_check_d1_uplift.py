"""Phase 17 §D-1 mutation-score uplift for ``echoroo.workers.dormancy_check``.

The PR #53 baseline measured the per-module mutation score for this
module at **40.2 %** (68 killed / 101 survived) which is below the
phased target of 80 %. This file targets the four functions that
together account for 97/101 of surviving mutants:

* ``_enqueue_stage`` (44 surviving): payload field composition,
  idempotency key shape, ``stage not in STAGE_OFFSETS`` guard,
  ``dormant_since is None`` guard, ``OUTBOX_EVENT_DORMANCY``
  discriminator, kwargs forwarded to :func:`enqueue`.
* ``_scan_active_projects`` (27 surviving): time-window cutoff
  semantics, ``ProjectStatus.ACTIVE`` filter, ``GREATEST``-based
  cutoff metric, ``COALESCE`` fallback to ``users.created_at``,
  query shape (single round-trip with no eager loader on owner).
* ``_emit_followup_stages`` (26 surviving): ``stage_initial`` skip,
  ``elapsed < offset`` strict less-than, ``dormant_since is None``
  defensive skip, multi-stage dispatch within a single project,
  enqueue-count return, ``ProjectStatus.DORMANT`` filter.
* ``_sanitise_field`` (4 surviving): ``None`` → ``""`` shortcut,
  NFKC normalisation, control-char rejection, hard-cap truncation.

The tests are deliberately mock-based (no live PostgreSQL) so they can
run in the unit-test job. Each test carries a one-line docstring per
the PR #54 / #55 conventions and uses parametrize for boundary
sweeps where the matrix is dense (offsets, cutoff seconds, control
characters).
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from echoroo.models.enums import ProjectStatus
from echoroo.workers.dormancy_check import (
    OUTBOX_EVENT_DORMANCY,
    STAGE_OFFSETS,
    DormancyPayloadError,
    _emit_followup_stages,
    _enqueue_stage,
    _sanitise_field,
    _scan_active_projects,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _normalize_sql(stmt: Any) -> str:
    """Compile a SQLAlchemy statement against the postgresql dialect with
    literal-bound parameters, then collapse whitespace and lowercase so
    structural assertions can match without whitespace noise.
    """
    compiled = stmt.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )
    return re.sub(r"\s+", " ", str(compiled)).strip().lower()


pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Lightweight SQLAlchemy + project/user doubles
# ---------------------------------------------------------------------------


class _Project:
    """Plain attribute container that quacks like ``echoroo.models.Project``."""

    def __init__(
        self,
        *,
        id: UUID | None = None,
        name: str = "Default Project",
        status: ProjectStatus = ProjectStatus.ACTIVE,
        dormant_since: datetime | None = None,
        owner_id: UUID | None = None,
    ) -> None:
        self.id = id or uuid4()
        self.name = name
        self.status = status
        self.dormant_since = dormant_since
        self.updated_at: datetime | None = None
        self.owner_id = owner_id or uuid4()


class _User:
    """Plain attribute container for owner doubles."""

    def __init__(
        self,
        *,
        id: UUID | None = None,
        email: str = "owner@example.com",
        last_first_party_activity_at: datetime | None = None,
    ) -> None:
        self.id = id or uuid4()
        self.email = email
        self.last_first_party_activity_at = last_first_party_activity_at


class _CapturedExecute:
    """Records the SQL statement passed to ``session.execute``."""

    def __init__(self, rows: list[tuple[Any, Any]]) -> None:
        self._rows = rows
        self.statements: list[Any] = []

    async def execute(self, stmt: Any, params: Any | None = None) -> Any:
        self.statements.append(stmt)
        return _Result(self._rows)


class _Result:
    def __init__(self, rows: list[tuple[Any, Any]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, Any]]:
        return [(r[0], r[1]) for r in self._rows]


class _NoopSession:
    """Minimal async session used by ``_enqueue_stage`` tests."""

    async def execute(self, _stmt: Any, _params: Any | None = None) -> Any:
        return _Result([])


def _capture_enqueue() -> tuple[list[dict[str, Any]], Any]:
    """Return ``(captured_calls_list, fake_enqueue_coroutine)``."""
    calls: list[dict[str, Any]] = []

    async def fake_enqueue(
        session: Any,
        *,
        event_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
    ) -> UUID:
        calls.append(
            {
                "session": session,
                "event_type": event_type,
                "payload": payload,
                "idempotency_key": idempotency_key,
            }
        )
        return uuid4()

    return calls, fake_enqueue


# ===========================================================================
# Section A — _sanitise_field (4 mutants)
# ===========================================================================


class TestSanitiseField:
    """Coverage for ``_sanitise_field`` boundary behaviour."""

    async def test_none_returns_empty_string_not_none(self) -> None:
        """None input MUST yield empty string (not 'None' or None)."""
        assert _sanitise_field(None, field_name="x") == ""

    async def test_none_is_not_str_none(self) -> None:
        """None must NOT degrade to the literal string 'None'."""
        assert _sanitise_field(None, field_name="x") != "None"

    async def test_str_passthrough_with_strip(self) -> None:
        """Plain strings are NFKC-normalised and stripped of surround whitespace."""
        assert _sanitise_field("  hello  ", field_name="x") == "hello"

    async def test_nfkc_normalises_fullwidth(self) -> None:
        """NFKC folds full-width digits to ASCII (mutant on normalisation form)."""
        # full-width "ABC" → ASCII "ABC"
        assert _sanitise_field("ＡＢＣ", field_name="x") == "ABC"

    async def test_uuid_input_is_str_coerced(self) -> None:
        """Non-string inputs are coerced via str() (kills 'raw = repr(value)')."""
        u = uuid4()
        assert _sanitise_field(u, field_name="x") == str(u)

    async def test_int_input_is_str_coerced(self) -> None:
        """Integer input becomes its decimal representation."""
        assert _sanitise_field(42, field_name="x") == "42"

    @pytest.mark.parametrize(
        "bad",
        [
            "abc\x00def",  # NUL
            "abc\x07def",  # BEL
            "abc\x1fdef",  # unit separator
            "line1\rline2",  # CR
        ],
    )
    async def test_control_chars_raise_dormancy_payload_error(self, bad: str) -> None:
        """Control chars MUST raise ``DormancyPayloadError`` (not silently strip)."""
        with pytest.raises(DormancyPayloadError):
            _sanitise_field(bad, field_name="badfield")

    async def test_control_char_message_includes_field_name(self) -> None:
        """The error message embeds the offending field_name (kills name mutation)."""
        with pytest.raises(DormancyPayloadError) as exc:
            _sanitise_field("\x00", field_name="MY_FIELD")
        assert "MY_FIELD" in str(exc.value)

    async def test_truncation_at_max_field_len(self) -> None:
        """Input above the 500-char cap is truncated to exactly 500 chars."""
        result = _sanitise_field("x" * 700, field_name="x")
        assert len(result) == 500

    async def test_truncation_keeps_prefix_not_suffix(self) -> None:
        """Truncation slices [:500] (kills the [-500:] mutation)."""
        # Mark the start with 'A' and the part beyond 500 with 'B'.
        payload = "A" * 500 + "B" * 200
        result = _sanitise_field(payload, field_name="x")
        assert result.startswith("A")
        assert "B" not in result

    async def test_exactly_500_chars_is_not_truncated(self) -> None:
        """Boundary: len == 500 must remain unchanged (kills > vs >= mutation)."""
        s = "x" * 500
        result = _sanitise_field(s, field_name="x")
        assert result == s
        assert len(result) == 500

    async def test_empty_string_returns_empty(self) -> None:
        """Empty string input yields empty string (no error)."""
        assert _sanitise_field("", field_name="x") == ""

    async def test_dormancy_payload_error_is_value_error_subclass(self) -> None:
        """``DormancyPayloadError`` MUST inherit from ``ValueError``."""
        assert issubclass(DormancyPayloadError, ValueError)


# ===========================================================================
# Section B — _enqueue_stage (44 mutants)
# ===========================================================================


class TestEnqueueStage:
    """Coverage for ``_enqueue_stage`` payload + idempotency-key shape."""

    @pytest.fixture
    def now(self) -> datetime:
        return datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)

    @pytest.fixture
    def dormant_since(self, now: datetime) -> datetime:
        return now - timedelta(days=10)

    @pytest.mark.parametrize(
        "bad_stage",
        [
            "stage_unknown",
            "",
            "STAGE_INITIAL",  # case-sensitive — uppercase variant is invalid
            "stage_initial ",  # trailing space variant
            "0",
            "stage_3D",
        ],
    )
    async def test_unknown_stage_raises_value_error(
        self, bad_stage: str, now: datetime, dormant_since: datetime
    ) -> None:
        """Stages outside STAGE_OFFSETS MUST raise ``ValueError`` BEFORE any DB work."""
        project = _Project(dormant_since=dormant_since)
        owner = _User()
        _, fake = _capture_enqueue()
        with (
            patch("echoroo.workers.dormancy_check.enqueue", new=fake),
            pytest.raises(ValueError, match="unknown dormancy stage"),
        ):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage=bad_stage,
                now=now,
            )

    async def test_unknown_stage_message_repr_quotes_input(
        self, now: datetime, dormant_since: datetime
    ) -> None:
        """Error message uses repr (quoted) of the bad stage (kills str-format mutation)."""
        project = _Project(dormant_since=dormant_since)
        owner = _User()
        with (
            patch(
                "echoroo.workers.dormancy_check.enqueue",
                new=_capture_enqueue()[1],
            ),
            pytest.raises(ValueError) as exc,
        ):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage="bogus",
                now=now,
            )
        assert "'bogus'" in str(exc.value)

    @pytest.mark.parametrize("stage", list(STAGE_OFFSETS.keys()))
    async def test_known_stages_all_dispatch(
        self, stage: str, now: datetime, dormant_since: datetime
    ) -> None:
        """Every key in STAGE_OFFSETS must reach the enqueue helper exactly once."""
        project = _Project(dormant_since=dormant_since)
        owner = _User()
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage=stage,
                now=now,
            )
        assert len(calls) == 1
        assert calls[0]["payload"]["stage"] == stage

    async def test_event_type_uses_outbox_constant(
        self, now: datetime, dormant_since: datetime
    ) -> None:
        """``event_type`` MUST equal ``OUTBOX_EVENT_DORMANCY`` (kills literal swap)."""
        project = _Project(dormant_since=dormant_since)
        owner = _User()
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage="stage_initial",
                now=now,
            )
        assert calls[0]["event_type"] == OUTBOX_EVENT_DORMANCY
        assert calls[0]["event_type"] == "project.dormancy_notification"

    async def test_payload_contains_all_required_keys(
        self, now: datetime, dormant_since: datetime
    ) -> None:
        """Payload keys MUST be the spec-mandated set (kills key-rename mutations)."""
        project = _Project(name="My Proj", dormant_since=dormant_since)
        owner = _User(email="o@example.com")
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage="stage_initial",
                now=now,
            )
        payload = calls[0]["payload"]
        assert set(payload.keys()) == {
            "stage",
            "project_id",
            "project_name",
            "owner_user_id",
            "owner_email",
            "dormant_since",
            "evaluated_at",
        }

    async def test_payload_project_id_value(
        self, now: datetime, dormant_since: datetime
    ) -> None:
        """``project_id`` field equals str(project.id) (kills owner.id swap)."""
        project = _Project(dormant_since=dormant_since)
        owner = _User()
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage="stage_initial",
                now=now,
            )
        assert calls[0]["payload"]["project_id"] == str(project.id)
        assert calls[0]["payload"]["project_id"] != str(owner.id)

    async def test_payload_owner_user_id_value(
        self, now: datetime, dormant_since: datetime
    ) -> None:
        """``owner_user_id`` field equals str(owner.id) (kills project.id swap)."""
        project = _Project(dormant_since=dormant_since)
        owner = _User()
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage="stage_initial",
                now=now,
            )
        assert calls[0]["payload"]["owner_user_id"] == str(owner.id)
        assert calls[0]["payload"]["owner_user_id"] != str(project.id)

    async def test_payload_owner_email_value(
        self, now: datetime, dormant_since: datetime
    ) -> None:
        """``owner_email`` field carries the user's email (kills name swap)."""
        project = _Project(name="ProjName", dormant_since=dormant_since)
        owner = _User(email="alice@example.com")
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage="stage_initial",
                now=now,
            )
        assert calls[0]["payload"]["owner_email"] == "alice@example.com"
        assert calls[0]["payload"]["project_name"] == "ProjName"

    async def test_payload_evaluated_at_is_iso_of_now(
        self, dormant_since: datetime
    ) -> None:
        """``evaluated_at`` MUST be the ISO of the supplied ``now`` (not project.dormant_since)."""
        now = datetime(2025, 12, 25, 6, 30, 15, tzinfo=UTC)
        project = _Project(dormant_since=dormant_since)
        owner = _User()
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage="stage_initial",
                now=now,
            )
        assert calls[0]["payload"]["evaluated_at"] == now.isoformat()
        assert calls[0]["payload"]["evaluated_at"] != dormant_since.isoformat()

    async def test_payload_dormant_since_is_iso_of_project_dormant_since(
        self, now: datetime, dormant_since: datetime
    ) -> None:
        """``dormant_since`` MUST be the ISO of project.dormant_since (not now)."""
        project = _Project(dormant_since=dormant_since)
        owner = _User()
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage="stage_initial",
                now=now,
            )
        assert calls[0]["payload"]["dormant_since"] == dormant_since.isoformat()

    async def test_idempotency_key_format(
        self, now: datetime, dormant_since: datetime
    ) -> None:
        """Key MUST follow ``dormancy:{project_id}:{dormant_since_unix}:{stage}``."""
        project = _Project(dormant_since=dormant_since)
        owner = _User()
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage="stage_30d",
                now=now,
            )
        expected = (
            f"dormancy:{project.id}:{int(dormant_since.timestamp())}:stage_30d"
        )
        assert calls[0]["idempotency_key"] == expected

    async def test_idempotency_key_starts_with_dormancy_prefix(
        self, now: datetime, dormant_since: datetime
    ) -> None:
        """Key prefix MUST be the literal ``dormancy:`` (kills prefix swap)."""
        project = _Project(dormant_since=dormant_since)
        owner = _User()
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage="stage_initial",
                now=now,
            )
        assert calls[0]["idempotency_key"].startswith("dormancy:")

    async def test_idempotency_key_contains_stage_suffix(
        self, now: datetime, dormant_since: datetime
    ) -> None:
        """Stage label MUST appear at the suffix (kills suffix swap)."""
        project = _Project(dormant_since=dormant_since)
        owner = _User()
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage="stage_grace_expired",
                now=now,
            )
        assert calls[0]["idempotency_key"].endswith(":stage_grace_expired")

    async def test_idempotency_key_changes_with_stage(
        self, now: datetime, dormant_since: datetime
    ) -> None:
        """Different stages on the same project MUST produce distinct keys."""
        project = _Project(dormant_since=dormant_since)
        owner = _User()
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            for stage in ("stage_initial", "stage_30d", "stage_final"):
                await _enqueue_stage(
                    _NoopSession(),
                    project=project,
                    owner=owner,
                    stage=stage,
                    now=now,
                )
        keys = [c["idempotency_key"] for c in calls]
        assert len(set(keys)) == 3

    async def test_idempotency_key_changes_with_dormant_since(
        self, now: datetime
    ) -> None:
        """Different dormant_since on same project+stage MUST produce distinct keys."""
        project_a = _Project(dormant_since=datetime(2025, 1, 1, tzinfo=UTC))
        project_b = _Project(
            id=project_a.id,
            dormant_since=datetime(2025, 6, 1, tzinfo=UTC),
        )
        owner = _User()
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _enqueue_stage(
                _NoopSession(),
                project=project_a,
                owner=owner,
                stage="stage_initial",
                now=now,
            )
            await _enqueue_stage(
                _NoopSession(),
                project=project_b,
                owner=owner,
                stage="stage_initial",
                now=now,
            )
        assert calls[0]["idempotency_key"] != calls[1]["idempotency_key"]

    async def test_idempotency_key_stable_across_now_jitter(self) -> None:
        """Identical (project, dormant_since, stage) MUST yield identical keys regardless of now."""
        dormant = datetime(2025, 3, 15, 0, 0, 0, tzinfo=UTC)
        project = _Project(dormant_since=dormant)
        owner = _User()
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage="stage_initial",
                now=datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC),
            )
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage="stage_initial",
                now=datetime(2025, 6, 2, 23, 59, 59, tzinfo=UTC),
            )
        assert calls[0]["idempotency_key"] == calls[1]["idempotency_key"]

    async def test_idempotency_key_uses_unix_seconds_int(
        self, now: datetime
    ) -> None:
        """Key embeds int(timestamp()) — sub-second jitter must NOT change the key."""
        base = datetime(2025, 4, 1, 0, 0, 0, tzinfo=UTC)
        project_a = _Project(dormant_since=base)
        project_b = _Project(
            id=project_a.id,
            dormant_since=base + timedelta(microseconds=500_000),
        )
        owner = _User()
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            for p in (project_a, project_b):
                await _enqueue_stage(
                    _NoopSession(),
                    project=p,
                    owner=owner,
                    stage="stage_initial",
                    now=now,
                )
        # Both fall in the same UNIX second → identical keys.
        assert calls[0]["idempotency_key"] == calls[1]["idempotency_key"]

    async def test_dormant_since_iso_field_uses_iso_format(
        self, now: datetime
    ) -> None:
        """``dormant_since`` payload field uses ISO-8601 with the +00:00 offset."""
        dormant = datetime(2025, 4, 1, 12, 30, 45, tzinfo=UTC)
        project = _Project(dormant_since=dormant)
        owner = _User()
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage="stage_initial",
                now=now,
            )
        assert calls[0]["payload"]["dormant_since"] == "2025-04-01T12:30:45+00:00"

    async def test_session_forwarded_to_enqueue(
        self, now: datetime, dormant_since: datetime
    ) -> None:
        """Caller's session is forwarded as the first positional arg of enqueue."""
        project = _Project(dormant_since=dormant_since)
        owner = _User()
        sess = _NoopSession()
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _enqueue_stage(
                sess,
                project=project,
                owner=owner,
                stage="stage_initial",
                now=now,
            )
        assert calls[0]["session"] is sess

    async def test_dormant_since_none_raises_value_error_directly(
        self, now: datetime
    ) -> None:
        """Direct guard test: ``_enqueue_stage(dormant_since=None)`` MUST raise
        ``ValueError`` and MUST NOT reach the ``enqueue`` helper.

        The follow-up-stage path filters NULL dormant_since rows BEFORE
        invoking ``_enqueue_stage`` — but the function carries its own
        defensive guard (idempotency-key construction divides by
        ``project.dormant_since.timestamp()``). This test exercises that
        guard directly so a mutant that drops or weakens the guard is
        caught even when the upstream filter would normally hide it.
        """
        project = _Project(dormant_since=None)
        owner = _User()
        calls, fake = _capture_enqueue()
        with (
            patch("echoroo.workers.dormancy_check.enqueue", new=fake),
            pytest.raises(ValueError, match="dormant_since"),
        ):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage="stage_30d",
                now=now,
            )
        # The guard fires BEFORE any enqueue call.
        assert calls == []


# ===========================================================================
# Section C — _scan_active_projects (27 mutants)
# ===========================================================================


class TestScanActiveProjects:
    """Coverage for ``_scan_active_projects`` SQL filter shape."""

    async def test_returns_empty_for_no_rows(self) -> None:
        """Empty DB result returns an empty list (kills None-vs-[] mutation)."""
        cap = _CapturedExecute(rows=[])
        result = await _scan_active_projects(
            cap,  # type: ignore[arg-type]
            cutoff=datetime(2025, 1, 1, tzinfo=UTC),
        )
        assert result == []
        assert isinstance(result, list)

    async def test_returns_project_owner_pairs_in_order(self) -> None:
        """Returned tuples carry (Project, User) in that order (kills index swap)."""
        p1 = _Project()
        u1 = _User()
        p2 = _Project()
        u2 = _User()
        cap = _CapturedExecute(rows=[(p1, u1), (p2, u2)])
        result = await _scan_active_projects(
            cap,  # type: ignore[arg-type]
            cutoff=datetime(2025, 1, 1, tzinfo=UTC),
        )
        assert len(result) == 2
        assert result[0][0] is p1
        assert result[0][1] is u1
        assert result[1][0] is p2
        assert result[1][1] is u2

    async def test_executes_exactly_one_statement(self) -> None:
        """Single round-trip — exactly one execute call (kills extra-call mutations)."""
        cap = _CapturedExecute(rows=[])
        await _scan_active_projects(
            cap,  # type: ignore[arg-type]
            cutoff=datetime(2025, 1, 1, tzinfo=UTC),
        )
        assert len(cap.statements) == 1

    async def test_statement_is_a_select(self) -> None:
        """The executed statement is a sqlalchemy SELECT (kills DELETE/UPDATE mutations)."""
        cap = _CapturedExecute(rows=[])
        await _scan_active_projects(
            cap,  # type: ignore[arg-type]
            cutoff=datetime(2025, 1, 1, tzinfo=UTC),
        )
        stmt = cap.statements[0]
        # The statement is a Select instance.
        assert isinstance(stmt, sa.sql.Select)

    async def test_statement_filters_active_status(self) -> None:
        """Compiled SQL contains a status = ACTIVE clause (kills status mutation)."""
        cap = _CapturedExecute(rows=[])
        await _scan_active_projects(
            cap,  # type: ignore[arg-type]
            cutoff=datetime(2025, 1, 1, tzinfo=UTC),
        )
        compiled = str(
            cap.statements[0].compile(compile_kwargs={"literal_binds": True})
        )
        # ProjectStatus.ACTIVE serialises as the enum value 'active'.
        assert "active" in compiled.lower()

    async def test_statement_uses_greatest(self) -> None:
        """Compiled SQL uses GREATEST() for the cutoff metric (kills LEAST swap)."""
        cap = _CapturedExecute(rows=[])
        await _scan_active_projects(
            cap,  # type: ignore[arg-type]
            cutoff=datetime(2025, 1, 1, tzinfo=UTC),
        )
        compiled = str(
            cap.statements[0].compile(compile_kwargs={"literal_binds": True})
        )
        assert "greatest" in compiled.lower()

    async def test_statement_uses_coalesce_to_created_at(self) -> None:
        """Cutoff metric falls back to created_at via COALESCE (kills NULL leak)."""
        cap = _CapturedExecute(rows=[])
        await _scan_active_projects(
            cap,  # type: ignore[arg-type]
            cutoff=datetime(2025, 1, 1, tzinfo=UTC),
        )
        compiled = str(
            cap.statements[0].compile(compile_kwargs={"literal_binds": True})
        )
        compiled_lower = compiled.lower()
        assert "coalesce" in compiled_lower
        assert "created_at" in compiled_lower

    async def test_statement_uses_strict_less_than_cutoff(self) -> None:
        """Cutoff filter uses ``< cutoff`` strict less-than (kills <= swap)."""
        cap = _CapturedExecute(rows=[])
        await _scan_active_projects(
            cap,  # type: ignore[arg-type]
            cutoff=datetime(2025, 1, 1, tzinfo=UTC),
        )
        compiled = str(
            cap.statements[0].compile(compile_kwargs={"literal_binds": True})
        )
        # Compiled form is ``GREATEST(...) < '2025-01-01...'``; ensure the
        # ``<`` operator is present and ``<=`` is NOT.
        assert " < " in compiled
        assert " <= " not in compiled

    async def test_statement_joins_users_on_owner_id(self) -> None:
        """Join predicate is ``users.id = projects.owner_id`` (kills join column swap)."""
        cap = _CapturedExecute(rows=[])
        await _scan_active_projects(
            cap,  # type: ignore[arg-type]
            cutoff=datetime(2025, 1, 1, tzinfo=UTC),
        )
        compiled = str(
            cap.statements[0].compile(compile_kwargs={"literal_binds": True})
        )
        compiled_lower = compiled.lower()
        assert "owner_id" in compiled_lower
        # Both tables present.
        assert "users" in compiled_lower
        assert "projects" in compiled_lower

    @pytest.mark.parametrize(
        "cutoff_dt",
        [
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2025, 6, 15, tzinfo=UTC),
            datetime(2026, 12, 31, tzinfo=UTC),
        ],
    )
    async def test_cutoff_value_appears_in_compiled_sql(
        self, cutoff_dt: datetime
    ) -> None:
        """Cutoff datetime is bound into the SQL (kills cutoff drop mutation)."""
        cap = _CapturedExecute(rows=[])
        await _scan_active_projects(
            cap,  # type: ignore[arg-type]
            cutoff=cutoff_dt,
        )
        compiled = str(
            cap.statements[0].compile(compile_kwargs={"literal_binds": True})
        )
        assert str(cutoff_dt.year) in compiled

    async def test_sql_predicate_shape_is_exact(self) -> None:
        """Strict structural assertions on the compiled SQL — kills wrong-predicate /
        wrong-join-side / wrong-cutoff mutants that survive the substring-only checks.

        Compiles against the real ``postgresql`` dialect with ``literal_binds=True``
        so bound parameters are inlined, then collapses whitespace + lowercases
        so the matchers don't drift on cosmetic SQL formatting.
        """
        cutoff_dt = datetime(2025, 6, 15, 12, 34, 56, tzinfo=UTC)
        cap = _CapturedExecute(rows=[])
        await _scan_active_projects(
            cap,  # type: ignore[arg-type]
            cutoff=cutoff_dt,
        )
        sql = _normalize_sql(cap.statements[0])

        # Status filter is exact: ``projects.status = 'active'``. Kills mutants
        # that swap the column or the literal value (e.g. dormant/archived).
        assert "projects.status = 'active'" in sql

        # Inner JOIN predicate is ``users.id = projects.owner_id`` in that
        # order. Kills join-column-swap mutants (e.g. users.id = projects.id).
        assert "join users on users.id = projects.owner_id" in sql

        # Cutoff metric is ``GREATEST(COALESCE(last_login_at, created_at),
        # COALESCE(last_first_party_activity_at, created_at))`` exactly.
        # Kills LEAST swap, COALESCE-drop, and column-swap mutants.
        assert (
            "greatest(coalesce(users.last_login_at, users.created_at), "
            "coalesce(users.last_first_party_activity_at, users.created_at))"
        ) in sql

        # Cutoff is rendered as a full ISO-8601 timestamp (year + month + day
        # + at least the time portion start). Kills mutants that drop the
        # cutoff into a year-only constant or strip the time component.
        assert re.search(r"< '20\d\d-\d\d-\d\d", sql) is not None
        # And specifically the supplied cutoff appears verbatim.
        assert "< '2025-06-15 12:34:56" in sql


# ===========================================================================
# Section D — _emit_followup_stages (26 mutants)
# ===========================================================================


class TestEmitFollowupStages:
    """Coverage for ``_emit_followup_stages`` dispatch logic."""

    async def test_empty_dormant_set_returns_zero(self) -> None:
        """No DORMANT projects → 0 enqueued, no enqueue calls."""
        cap = _CapturedExecute(rows=[])
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            count = await _emit_followup_stages(
                cap,  # type: ignore[arg-type]
                now=datetime(2025, 6, 1, tzinfo=UTC),
            )
        assert count == 0
        assert calls == []

    async def test_skips_project_with_null_dormant_since(self) -> None:
        """Defensive: DORMANT row missing dormant_since must be skipped."""
        now = datetime(2025, 6, 1, tzinfo=UTC)
        project = _Project(status=ProjectStatus.DORMANT, dormant_since=None)
        owner = _User()
        cap = _CapturedExecute(rows=[(project, owner)])
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            count = await _emit_followup_stages(
                cap,  # type: ignore[arg-type]
                now=now,
            )
        assert count == 0
        assert calls == []

    async def test_skips_stage_initial_even_if_due(self) -> None:
        """``stage_initial`` is owned by the flip path; never enqueued here."""
        now = datetime(2025, 6, 1, tzinfo=UTC)
        # 0 elapsed → stage_initial offset (0d) IS satisfied, but skip code path
        # forbids it. The other stages (3d/30d/37d/366d) have not elapsed.
        project = _Project(
            status=ProjectStatus.DORMANT,
            dormant_since=now,  # exactly now → 0 elapsed
        )
        owner = _User()
        cap = _CapturedExecute(rows=[(project, owner)])
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            count = await _emit_followup_stages(
                cap,  # type: ignore[arg-type]
                now=now,
            )
        # No follow-up stage fires (initial is excluded, others not yet due).
        assert count == 0
        stages = [c["payload"]["stage"] for c in calls]
        assert "stage_initial" not in stages

    async def test_elapsed_strictly_less_than_offset_is_skipped(self) -> None:
        """``elapsed < offset`` is a STRICT skip (kills <= swap)."""
        now = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)
        # exactly 3d - 1us: stage_3d (3d) NOT due, but stage_initial offset 0
        # is due (and skipped). All later offsets clearly not due.
        project = _Project(
            status=ProjectStatus.DORMANT,
            dormant_since=now - timedelta(days=3) + timedelta(microseconds=1),
        )
        owner = _User()
        cap = _CapturedExecute(rows=[(project, owner)])
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            count = await _emit_followup_stages(
                cap,  # type: ignore[arg-type]
                now=now,
            )
        assert count == 0
        assert calls == []

    async def test_elapsed_equal_to_offset_dispatches(self) -> None:
        """``elapsed == offset`` IS due (kills strict-greater swap).

        At exactly 3d elapsed, only ``stage_3d`` fires — ``stage_initial`` is
        skipped by code, and ``stage_30d`` / ``stage_final`` /
        ``stage_grace_expired`` are not yet due. Strict equality assertions
        kill mutants that fire extra stages or fail to fire at the exact
        boundary.
        """
        now = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)
        project = _Project(
            status=ProjectStatus.DORMANT,
            dormant_since=now - timedelta(days=3),  # exactly 3d
        )
        owner = _User()
        cap = _CapturedExecute(rows=[(project, owner)])
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            count = await _emit_followup_stages(
                cap,  # type: ignore[arg-type]
                now=now,
            )
        stages = [c["payload"]["stage"] for c in calls]
        # Exactly 3d elapsed → only stage_3d fires.
        assert stages == ["stage_3d"]
        assert count == 1
        assert len(calls) == 1

    async def test_multiple_stages_fire_for_old_dormancy(self) -> None:
        """A project dormant 400d fires every follow-up stage (3/30/37/366)."""
        now = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)
        project = _Project(
            status=ProjectStatus.DORMANT,
            dormant_since=now - timedelta(days=400),
        )
        owner = _User()
        cap = _CapturedExecute(rows=[(project, owner)])
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            count = await _emit_followup_stages(
                cap,  # type: ignore[arg-type]
                now=now,
            )
        stages = sorted(c["payload"]["stage"] for c in calls)
        assert stages == sorted(
            ["stage_3d", "stage_30d", "stage_final", "stage_grace_expired"]
        )
        assert count == 4

    async def test_count_equals_enqueue_invocation_count(self) -> None:
        """Returned count equals the number of enqueue calls (kills off-by-one)."""
        now = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)
        project = _Project(
            status=ProjectStatus.DORMANT,
            dormant_since=now - timedelta(days=35),  # 3d + 30d due, 37d/366d not
        )
        owner = _User()
        cap = _CapturedExecute(rows=[(project, owner)])
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            count = await _emit_followup_stages(
                cap,  # type: ignore[arg-type]
                now=now,
            )
        assert count == len(calls)
        assert count == 2

    async def test_multiple_projects_aggregate_count(self) -> None:
        """Counts aggregate across multiple DORMANT projects (kills inner reset)."""
        now = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)
        p_old = _Project(
            status=ProjectStatus.DORMANT,
            dormant_since=now - timedelta(days=400),  # 4 follow-ups due
        )
        p_recent = _Project(
            status=ProjectStatus.DORMANT,
            dormant_since=now - timedelta(days=5),  # only stage_3d due
        )
        owner = _User()
        cap = _CapturedExecute(rows=[(p_old, owner), (p_recent, owner)])
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            count = await _emit_followup_stages(
                cap,  # type: ignore[arg-type]
                now=now,
            )
        assert count == 5
        assert len(calls) == 5

    async def test_null_project_does_not_short_circuit_loop(self) -> None:
        """A NULL-dormant_since project is skipped but does NOT break the loop."""
        now = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)
        bad = _Project(status=ProjectStatus.DORMANT, dormant_since=None)
        good = _Project(
            status=ProjectStatus.DORMANT,
            dormant_since=now - timedelta(days=400),
        )
        owner = _User()
        cap = _CapturedExecute(rows=[(bad, owner), (good, owner)])
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            count = await _emit_followup_stages(
                cap,  # type: ignore[arg-type]
                now=now,
            )
        # The bad row contributes 0; the good row contributes 4.
        assert count == 4
        assert all(c["payload"]["project_id"] == str(good.id) for c in calls)

    async def test_statement_filters_dormant_status(self) -> None:
        """SQL filters by ``ProjectStatus.DORMANT`` (kills status swap)."""
        cap = _CapturedExecute(rows=[])
        with patch(
            "echoroo.workers.dormancy_check.enqueue", new=_capture_enqueue()[1]
        ):
            await _emit_followup_stages(
                cap,  # type: ignore[arg-type]
                now=datetime(2025, 6, 1, tzinfo=UTC),
            )
        compiled = str(
            cap.statements[0].compile(compile_kwargs={"literal_binds": True})
        )
        assert "dormant" in compiled.lower()

    async def test_now_is_forwarded_as_evaluated_at(self) -> None:
        """``now`` reaches each enqueue call as ``evaluated_at`` (kills now-swap)."""
        now = datetime(2025, 6, 1, 12, 34, 56, tzinfo=UTC)
        project = _Project(
            status=ProjectStatus.DORMANT,
            dormant_since=now - timedelta(days=400),
        )
        owner = _User()
        cap = _CapturedExecute(rows=[(project, owner)])
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _emit_followup_stages(
                cap,  # type: ignore[arg-type]
                now=now,
            )
        for c in calls:
            assert c["payload"]["evaluated_at"] == now.isoformat()

    async def test_per_episode_idempotency_keys_are_distinct_across_stages(
        self,
    ) -> None:
        """Within one project, each stage produces a distinct idempotency key."""
        now = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)
        project = _Project(
            status=ProjectStatus.DORMANT,
            dormant_since=now - timedelta(days=400),
        )
        owner = _User()
        cap = _CapturedExecute(rows=[(project, owner)])
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _emit_followup_stages(
                cap,  # type: ignore[arg-type]
                now=now,
            )
        keys = {c["idempotency_key"] for c in calls}
        # 4 distinct keys for the 4 follow-up stages.
        assert len(keys) == 4

    async def test_per_episode_idempotency_keys_share_dormant_since_unix(
        self,
    ) -> None:
        """All stages share the same ``dormant_since_unix`` segment."""
        now = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)
        dormant = now - timedelta(days=400)
        project = _Project(
            status=ProjectStatus.DORMANT, dormant_since=dormant
        )
        owner = _User()
        cap = _CapturedExecute(rows=[(project, owner)])
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _emit_followup_stages(
                cap,  # type: ignore[arg-type]
                now=now,
            )
        unix = str(int(dormant.timestamp()))
        for c in calls:
            assert unix in c["idempotency_key"]


# ===========================================================================
# Section E — Round 2 strict-equality uplift (PR #56 mutation feedback)
# ===========================================================================
#
# PR #56 first mutation run: 74.6 % (126 killed / 43 survived). The
# remaining survivors concentrate in ``_enqueue_stage`` (22) and
# ``_emit_followup_stages`` (16). The Round-2 cases below pin the
# production behaviour with **exact equality** (full dict, full call
# tuple, exact idempotency-key segments) and add boundary parametrize
# sweeps around every numeric offset constant in :data:`STAGE_OFFSETS`.
#
# The tests are intentionally regression-style: they freeze the current
# spec-compliant behaviour so any literal/operator/identifier mutation
# in the underlying functions immediately breaks at least one assertion.


class TestEnqueueStageStrictEquality:
    """Round-2 strict-equality assertions for ``_enqueue_stage``."""

    @pytest.fixture
    def now(self) -> datetime:
        return datetime(2025, 6, 1, 12, 0, 0, tzinfo=UTC)

    @pytest.fixture
    def dormant_since(self, now: datetime) -> datetime:
        return now - timedelta(days=10)

    async def test_full_payload_exact_equality(
        self, now: datetime, dormant_since: datetime
    ) -> None:
        """Every payload key + value pinned to its exact spec value.

        Kills mutations that swap a single key, drop a key, swap a value
        from project.id → owner.id, or otherwise tamper with the dict
        literal in ``_enqueue_stage``.
        """
        project_id = UUID("12345678-1234-5678-1234-567812345678")
        owner_id = UUID("87654321-4321-8765-4321-876543218765")
        project = _Project(
            id=project_id,
            name="My Test Project",
            dormant_since=dormant_since,
        )
        owner = _User(id=owner_id, email="alice@example.com")
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage="stage_30d",
                now=now,
            )
        assert calls[0]["payload"] == {
            "stage": "stage_30d",
            "project_id": str(project_id),
            "project_name": "My Test Project",
            "owner_user_id": str(owner_id),
            "owner_email": "alice@example.com",
            "dormant_since": dormant_since.isoformat(),
            "evaluated_at": now.isoformat(),
        }

    async def test_full_enqueue_call_kwargs_exact(
        self, now: datetime, dormant_since: datetime
    ) -> None:
        """The captured call carries exactly the spec-mandated kwarg keys.

        Kills mutations that rename one of ``event_type`` /
        ``payload`` / ``idempotency_key`` to something else and mutations
        that supply a positional payload or extra unrecognised kwargs.
        """
        project = _Project(dormant_since=dormant_since)
        owner = _User()
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage="stage_initial",
                now=now,
            )
        # Captured call shape: keys are the four expected names exactly.
        assert set(calls[0].keys()) == {
            "session",
            "event_type",
            "payload",
            "idempotency_key",
        }

    async def test_only_one_enqueue_call(
        self, now: datetime, dormant_since: datetime
    ) -> None:
        """Exactly one ``enqueue`` invocation per ``_enqueue_stage`` call.

        Kills mutations that double-emit (e.g. an extra `await enqueue(`
        slipped in by a duplicated-statement mutator).
        """
        project = _Project(dormant_since=dormant_since)
        owner = _User()
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage="stage_initial",
                now=now,
            )
        assert len(calls) == 1

    async def test_payload_values_are_all_strings(
        self, now: datetime, dormant_since: datetime
    ) -> None:
        """Every payload value is a ``str`` (kills sanitiser-bypass mutations).

        ``_sanitise_field`` returns ``str``; any mutation that bypasses
        the sanitiser (e.g. uses ``project.id`` directly as a UUID
        object) breaks this invariant.
        """
        project = _Project(dormant_since=dormant_since)
        owner = _User()
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage="stage_initial",
                now=now,
            )
        for key, value in calls[0]["payload"].items():
            assert isinstance(value, str), f"{key} must be str, got {type(value)}"

    async def test_idempotency_key_has_exactly_three_colons(
        self, now: datetime, dormant_since: datetime
    ) -> None:
        """Key shape ``dormancy:{pid}:{unix}:{stage}`` has exactly three ``:``.

        Kills separator-mutation (``;`` / ``-`` / ``_``) or extra-segment
        mutations.
        """
        project = _Project(dormant_since=dormant_since)
        owner = _User()
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage="stage_initial",
                now=now,
            )
        assert calls[0]["idempotency_key"].count(":") == 3

    async def test_idempotency_key_segments_exact(
        self, now: datetime, dormant_since: datetime
    ) -> None:
        """Each ``:``-separated segment is the exact spec value."""
        project_id = UUID("00000000-0000-0000-0000-000000000001")
        project = _Project(id=project_id, dormant_since=dormant_since)
        owner = _User()
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage="stage_final",
                now=now,
            )
        segments = calls[0]["idempotency_key"].split(":")
        assert segments[0] == "dormancy"
        assert segments[1] == str(project_id)
        assert segments[2] == str(int(dormant_since.timestamp()))
        assert segments[3] == "stage_final"

    async def test_idempotency_key_segment_count_is_four(
        self, now: datetime, dormant_since: datetime
    ) -> None:
        """``str.split(':')`` yields exactly four segments."""
        project = _Project(dormant_since=dormant_since)
        owner = _User()
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage="stage_initial",
                now=now,
            )
        segments = calls[0]["idempotency_key"].split(":")
        assert len(segments) == 4

    async def test_event_type_is_not_other_outbox_discriminators(
        self, now: datetime, dormant_since: datetime
    ) -> None:
        """``event_type`` is dormancy-specific (kills swap to siblings)."""
        project = _Project(dormant_since=dormant_since)
        owner = _User()
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage="stage_initial",
                now=now,
            )
        et = calls[0]["event_type"]
        # Must be the dormancy discriminator and NOT any neighbour from
        # the outbox event family.
        assert et == "project.dormancy_notification"
        assert et != "project.archived"
        assert et != "project.dormancy"
        assert et != "dormancy.notification"
        assert "dormancy" in et
        assert et.startswith("project.")

    async def test_project_name_round_trips_through_payload(
        self, now: datetime, dormant_since: datetime
    ) -> None:
        """``project_name`` is taken from ``project.name`` (kills swap to email/id)."""
        project = _Project(name="UniqueProjName_ABC123", dormant_since=dormant_since)
        owner = _User(email="someone@example.org")
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage="stage_initial",
                now=now,
            )
        assert calls[0]["payload"]["project_name"] == "UniqueProjName_ABC123"
        assert calls[0]["payload"]["project_name"] != owner.email
        assert calls[0]["payload"]["project_name"] != str(project.id)

    async def test_stage_field_round_trips_unchanged(
        self, now: datetime, dormant_since: datetime
    ) -> None:
        """payload['stage'] equals the input stage exactly (no normalisation drift)."""
        project = _Project(dormant_since=dormant_since)
        owner = _User()
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage="stage_grace_expired",
                now=now,
            )
        assert calls[0]["payload"]["stage"] == "stage_grace_expired"

    async def test_evaluated_at_not_equal_to_dormant_since(
        self, dormant_since: datetime
    ) -> None:
        """``evaluated_at`` and ``dormant_since`` payload fields are distinct.

        Kills mutations that read ``project.dormant_since`` for the
        ``evaluated_at`` field (or vice versa).
        """
        # Pick a now that differs from dormant_since by hours/minutes/sec
        # — not a whole-day boundary — so accidental swaps surface.
        now = datetime(2025, 7, 4, 9, 15, 33, tzinfo=UTC)
        project = _Project(dormant_since=dormant_since)
        owner = _User()
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage="stage_initial",
                now=now,
            )
        payload = calls[0]["payload"]
        assert payload["evaluated_at"] == now.isoformat()
        assert payload["dormant_since"] == dormant_since.isoformat()
        assert payload["evaluated_at"] != payload["dormant_since"]

    async def test_empty_project_name_payload_is_empty_string(
        self, now: datetime, dormant_since: datetime
    ) -> None:
        """An empty project.name yields empty ``project_name`` (kills 'None' fallback)."""
        project = _Project(name="", dormant_since=dormant_since)
        owner = _User()
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage="stage_initial",
                now=now,
            )
        assert calls[0]["payload"]["project_name"] == ""

    async def test_idempotency_key_unix_segment_is_int_string(
        self, now: datetime, dormant_since: datetime
    ) -> None:
        """The unix segment is an integer-looking string (kills float coercion)."""
        # Choose a dormant_since with non-zero microseconds to exercise
        # the int() truncation. The unix segment must NOT carry a
        # fractional dot.
        dormant = dormant_since + timedelta(microseconds=123_456)
        project = _Project(dormant_since=dormant)
        owner = _User()
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _enqueue_stage(
                _NoopSession(),
                project=project,
                owner=owner,
                stage="stage_initial",
                now=now,
            )
        unix_segment = calls[0]["idempotency_key"].split(":")[2]
        assert unix_segment.isdigit()
        assert "." not in unix_segment
        assert unix_segment == str(int(dormant.timestamp()))


class TestEmitFollowupStagesBoundaries:
    """Round-2 boundary parametrize for ``_emit_followup_stages`` offsets."""

    @pytest.mark.parametrize(
        ("days_elapsed", "expected_stages"),
        [
            # stage_3d boundary (offset = 3d).
            (2, []),
            (3, ["stage_3d"]),
            (4, ["stage_3d"]),
            # stage_30d boundary (offset = 30d).
            (29, ["stage_3d"]),
            (30, ["stage_3d", "stage_30d"]),
            (31, ["stage_3d", "stage_30d"]),
            # stage_final boundary (offset = 37d).
            (36, ["stage_3d", "stage_30d"]),
            (37, ["stage_3d", "stage_30d", "stage_final"]),
            (38, ["stage_3d", "stage_30d", "stage_final"]),
            # stage_grace_expired boundary (offset = 366d == 31_622_400s).
            (365, ["stage_3d", "stage_30d", "stage_final"]),
            (
                366,
                ["stage_3d", "stage_30d", "stage_final", "stage_grace_expired"],
            ),
            (
                367,
                ["stage_3d", "stage_30d", "stage_final", "stage_grace_expired"],
            ),
        ],
    )
    async def test_offset_boundaries_exact(
        self, days_elapsed: int, expected_stages: list[str]
    ) -> None:
        """Each offset boundary fires exactly the expected stage set.

        Kills mutations on every numeric offset constant (3, 30, 37,
        DORMANT_THRESHOLD_SECONDS) and the ``elapsed >= offset`` /
        ``elapsed < offset`` operator.
        """
        now = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)
        project = _Project(
            status=ProjectStatus.DORMANT,
            dormant_since=now - timedelta(days=days_elapsed),
        )
        owner = _User()
        cap = _CapturedExecute(rows=[(project, owner)])
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            count = await _emit_followup_stages(
                cap,  # type: ignore[arg-type]
                now=now,
            )
        actual_stages = sorted(c["payload"]["stage"] for c in calls)
        assert actual_stages == sorted(expected_stages)
        assert count == len(expected_stages)

    async def test_off_by_one_microsecond_below_offset_skipped(self) -> None:
        """``elapsed = offset - 1us`` MUST skip (kills ``<`` → ``<=`` mutation)."""
        now = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)
        # Exactly 30d - 1us → stage_30d NOT due, but stage_3d IS due.
        project = _Project(
            status=ProjectStatus.DORMANT,
            dormant_since=now - timedelta(days=30) + timedelta(microseconds=1),
        )
        owner = _User()
        cap = _CapturedExecute(rows=[(project, owner)])
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            count = await _emit_followup_stages(
                cap,  # type: ignore[arg-type]
                now=now,
            )
        stages = sorted(c["payload"]["stage"] for c in calls)
        assert stages == ["stage_3d"]
        assert count == 1

    async def test_off_by_one_microsecond_at_offset_fires(self) -> None:
        """``elapsed = offset + 1us`` fires (kills ``<`` → ``<`` lift mutations).

        At exactly 30d+1us, both stage_3d and stage_30d are due, but
        stage_final (37d) and stage_grace_expired (366d) are not.
        """
        now = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)
        project = _Project(
            status=ProjectStatus.DORMANT,
            dormant_since=now - timedelta(days=30) - timedelta(microseconds=1),
        )
        owner = _User()
        cap = _CapturedExecute(rows=[(project, owner)])
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            count = await _emit_followup_stages(
                cap,  # type: ignore[arg-type]
                now=now,
            )
        stages = sorted(c["payload"]["stage"] for c in calls)
        assert stages == ["stage_30d", "stage_3d"]
        assert count == 2

    async def test_zero_days_dormant_yields_zero_followups(self) -> None:
        """0 days elapsed → no follow-ups (stage_initial excluded, others not due)."""
        now = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)
        project = _Project(
            status=ProjectStatus.DORMANT,
            dormant_since=now,  # 0d elapsed
        )
        owner = _User()
        cap = _CapturedExecute(rows=[(project, owner)])
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            count = await _emit_followup_stages(
                cap,  # type: ignore[arg-type]
                now=now,
            )
        assert count == 0
        assert calls == []

    async def test_count_increments_by_one_per_enqueue(self) -> None:
        """The ``enqueued`` counter increments by exactly 1 per dispatch.

        Kills mutations that change ``enqueued += 1`` to ``+= 2`` or
        ``-= 1`` or that move the increment outside the loop body.
        """
        now = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)
        # Exactly 37d elapsed → stage_3d, stage_30d, stage_final fire (3).
        project = _Project(
            status=ProjectStatus.DORMANT,
            dormant_since=now - timedelta(days=37),
        )
        owner = _User()
        cap = _CapturedExecute(rows=[(project, owner)])
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            count = await _emit_followup_stages(
                cap,  # type: ignore[arg-type]
                now=now,
            )
        assert count == 3
        assert len(calls) == 3
        assert count == len(calls)

    async def test_each_stage_payload_carries_correct_stage_field(self) -> None:
        """payload['stage'] matches the stage label for each dispatched call."""
        now = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)
        project = _Project(
            status=ProjectStatus.DORMANT,
            dormant_since=now - timedelta(days=400),
        )
        owner = _User()
        cap = _CapturedExecute(rows=[(project, owner)])
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _emit_followup_stages(
                cap,  # type: ignore[arg-type]
                now=now,
            )
        # Each call's payload['stage'] is one of the four follow-up stages.
        stages_in_payload = {c["payload"]["stage"] for c in calls}
        expected = {"stage_3d", "stage_30d", "stage_final", "stage_grace_expired"}
        assert stages_in_payload == expected
        # And NEVER includes stage_initial.
        assert "stage_initial" not in stages_in_payload

    async def test_each_stage_idempotency_key_carries_correct_stage(self) -> None:
        """Idempotency key suffix matches the stage label for each call."""
        now = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)
        project = _Project(
            status=ProjectStatus.DORMANT,
            dormant_since=now - timedelta(days=400),
        )
        owner = _User()
        cap = _CapturedExecute(rows=[(project, owner)])
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _emit_followup_stages(
                cap,  # type: ignore[arg-type]
                now=now,
            )
        for c in calls:
            stage_label = c["payload"]["stage"]
            assert c["idempotency_key"].endswith(f":{stage_label}")

    async def test_distinct_owners_routed_correctly(self) -> None:
        """Two DORMANT projects with distinct owners produce distinct owner_email payloads.

        Kills mutations that pin the owner reference outside the loop
        (e.g. always reads owner from the first row).
        """
        now = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)
        project_a = _Project(
            status=ProjectStatus.DORMANT,
            dormant_since=now - timedelta(days=400),
        )
        project_b = _Project(
            status=ProjectStatus.DORMANT,
            dormant_since=now - timedelta(days=400),
        )
        owner_a = _User(email="alice@example.com")
        owner_b = _User(email="bob@example.com")
        cap = _CapturedExecute(rows=[(project_a, owner_a), (project_b, owner_b)])
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            await _emit_followup_stages(
                cap,  # type: ignore[arg-type]
                now=now,
            )
        emails_for_a = {
            c["payload"]["owner_email"]
            for c in calls
            if c["payload"]["project_id"] == str(project_a.id)
        }
        emails_for_b = {
            c["payload"]["owner_email"]
            for c in calls
            if c["payload"]["project_id"] == str(project_b.id)
        }
        assert emails_for_a == {"alice@example.com"}
        assert emails_for_b == {"bob@example.com"}

    async def test_stage_initial_offset_is_zero(self) -> None:
        """``STAGE_OFFSETS['stage_initial']`` is exactly 0 days.

        Pins the constant: kills mutations that change the stage_initial
        offset away from 0 (which would change which follow-up stage
        gets accidentally re-fired by the followup path).
        """
        assert STAGE_OFFSETS["stage_initial"] == timedelta(days=0)
        assert STAGE_OFFSETS["stage_initial"].total_seconds() == 0

    async def test_stage_offset_constants_exact(self) -> None:
        """All STAGE_OFFSETS values pinned to spec literals.

        Kills any constant mutation in the dict literal: 3 → 4, 30 →
        31, 37 → 36, etc.
        """
        assert STAGE_OFFSETS["stage_3d"] == timedelta(days=3)
        assert STAGE_OFFSETS["stage_30d"] == timedelta(days=30)
        assert STAGE_OFFSETS["stage_final"] == timedelta(days=37)
        # stage_grace_expired uses DORMANT_THRESHOLD_SECONDS (366d).
        assert (
            STAGE_OFFSETS["stage_grace_expired"].total_seconds() == 31_622_400
        )

    async def test_stage_offsets_keys_exact(self) -> None:
        """STAGE_OFFSETS contains exactly five keys in the spec set.

        Kills mutations that drop a stage key from the dict (which would
        also silence its dispatch in the followup loop).
        """
        assert set(STAGE_OFFSETS.keys()) == {
            "stage_initial",
            "stage_3d",
            "stage_30d",
            "stage_final",
            "stage_grace_expired",
        }
        assert len(STAGE_OFFSETS) == 5

    async def test_followup_does_not_emit_stage_initial_for_old_dormancy(
        self,
    ) -> None:
        """Even for very-old projects, ``stage_initial`` is never re-emitted.

        Kills mutations that drop the ``if stage == 'stage_initial':
        continue`` guard (which would re-emit stage_initial for every
        DORMANT project on every beat tick).
        """
        now = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)
        project = _Project(
            status=ProjectStatus.DORMANT,
            # Very old — every offset is satisfied.
            dormant_since=now - timedelta(days=10_000),
        )
        owner = _User()
        cap = _CapturedExecute(rows=[(project, owner)])
        calls, fake = _capture_enqueue()
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            count = await _emit_followup_stages(
                cap,  # type: ignore[arg-type]
                now=now,
            )
        stages = [c["payload"]["stage"] for c in calls]
        # Initial stage is NOT among the dispatched follow-ups even
        # though its offset (0d) is technically satisfied.
        assert "stage_initial" not in stages
        # All four follow-up stages fire.
        assert count == 4
        assert sorted(stages) == sorted(
            ["stage_3d", "stage_30d", "stage_final", "stage_grace_expired"]
        )

    async def test_dormant_since_none_skips_silently_without_raising(
        self,
    ) -> None:
        """A NULL dormant_since is skipped without surfacing an exception.

        Kills mutations that change ``continue`` to ``raise`` or that
        drop the ``project.dormant_since is None`` guard entirely (which
        would crash on ``now - None``).
        """
        now = datetime(2025, 6, 1, 0, 0, 0, tzinfo=UTC)
        project = _Project(
            status=ProjectStatus.DORMANT,
            dormant_since=None,
        )
        owner = _User()
        cap = _CapturedExecute(rows=[(project, owner)])
        calls, fake = _capture_enqueue()
        # The function MUST return cleanly (no exception).
        with patch("echoroo.workers.dormancy_check.enqueue", new=fake):
            count = await _emit_followup_stages(
                cap,  # type: ignore[arg-type]
                now=now,
            )
        assert count == 0
        assert calls == []

"""Unit tests for the dormancy notification payload + idempotency-key helpers.

Targets the pure helpers introduced in Phase 17 §D-1-bis to lift the
mutation score for :mod:`echoroo.workers.dormancy_check` from 74.6% to
>=80%. These tests pin every literal that the dispatcher and the
FR-076a outbox contract depend on:

* The seven payload field names + their value sources.
* The ``_sanitise_field`` invocation per field (so the NFKC + control
  + length contract cannot regress).
* The exact idempotency-key format
  ``dormancy:{project_id}:{dormant_since_unix}:{stage}``, including
  separator strictness and UNIX-second embedding.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest

from echoroo.workers._dormancy_events import (
    build_notification_payload,
    compute_idempotency_key,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_project(
    *,
    project_id: UUID | None = None,
    name: str = "Sample Project",
    dormant_since: datetime | None = None,
) -> SimpleNamespace:
    """Build a Project-shaped attribute carrier (no ORM dependency)."""
    return SimpleNamespace(
        id=project_id or uuid4(),
        name=name,
        dormant_since=dormant_since,
    )


def _make_owner(
    *,
    user_id: UUID | None = None,
    email: str = "owner@example.com",
) -> SimpleNamespace:
    """Build a User-shaped attribute carrier."""
    return SimpleNamespace(
        id=user_id or uuid4(),
        email=email,
    )


# ---------------------------------------------------------------------------
# build_notification_payload
# ---------------------------------------------------------------------------


def test_build_notification_payload_contains_all_fields() -> None:
    """The payload must surface exactly the seven canonical fields."""
    now = datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC)
    dormant_since = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)
    project = _make_project(dormant_since=dormant_since)
    owner = _make_owner()

    payload = build_notification_payload(
        stage="stage_initial",
        project=project,
        owner=owner,
        now=now,
    )

    assert set(payload.keys()) == {
        "stage",
        "project_id",
        "project_name",
        "owner_user_id",
        "owner_email",
        "dormant_since",
        "evaluated_at",
    }


def test_build_notification_payload_field_values_pinned() -> None:
    """Every payload field must originate from the right model attribute."""
    project_id = UUID("11111111-2222-3333-4444-555555555555")
    user_id = UUID("66666666-7777-8888-9999-aaaaaaaaaaaa")
    dormant_since = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)
    now = datetime(2026, 5, 9, 12, 30, 0, tzinfo=UTC)
    project = _make_project(
        project_id=project_id,
        name="Tropical Forest Survey",
        dormant_since=dormant_since,
    )
    owner = _make_owner(user_id=user_id, email="owner@example.com")

    payload = build_notification_payload(
        stage="stage_30d",
        project=project,
        owner=owner,
        now=now,
    )

    assert payload["stage"] == "stage_30d"
    assert payload["project_id"] == str(project_id)
    assert payload["project_name"] == "Tropical Forest Survey"
    assert payload["owner_user_id"] == str(user_id)
    assert payload["owner_email"] == "owner@example.com"
    assert payload["dormant_since"] == dormant_since.isoformat()
    assert payload["evaluated_at"] == now.isoformat()


def test_build_notification_payload_dormant_since_iso_when_set() -> None:
    """``dormant_since`` is the ISO-8601 representation when populated."""
    dormant_since = datetime(2026, 1, 15, 9, 45, 30, tzinfo=UTC)
    project = _make_project(dormant_since=dormant_since)
    owner = _make_owner()
    now = datetime(2026, 5, 9, tzinfo=UTC)

    payload = build_notification_payload(
        stage="stage_3d",
        project=project,
        owner=owner,
        now=now,
    )

    assert payload["dormant_since"] == "2026-01-15T09:45:30+00:00"


def test_build_notification_payload_dormant_since_empty_when_none() -> None:
    """``dormant_since=None`` collapses to the empty string (not ``"None"``)."""
    project = _make_project(dormant_since=None)
    owner = _make_owner()
    now = datetime(2026, 5, 9, tzinfo=UTC)

    payload = build_notification_payload(
        stage="stage_initial",
        project=project,
        owner=owner,
        now=now,
    )

    assert payload["dormant_since"] == ""


def test_build_notification_payload_evaluated_at_uses_now_iso() -> None:
    """``evaluated_at`` must be ``now.isoformat()`` exactly (not str(now))."""
    now = datetime(2026, 5, 9, 12, 0, 0, 123456, tzinfo=UTC)
    project = _make_project(dormant_since=datetime(2026, 4, 1, tzinfo=UTC))
    owner = _make_owner()

    payload = build_notification_payload(
        stage="stage_final",
        project=project,
        owner=owner,
        now=now,
    )

    assert payload["evaluated_at"] == now.isoformat()
    assert payload["evaluated_at"] != str(now)


def test_build_notification_payload_invokes_sanitise_field_per_field() -> None:
    """Every field value passes through :func:`sanitise_field` with the right name."""
    dormant_since = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)
    project = _make_project(
        project_id=UUID("11111111-2222-3333-4444-555555555555"),
        name="Project X",
        dormant_since=dormant_since,
    )
    owner = _make_owner(
        user_id=UUID("66666666-7777-8888-9999-aaaaaaaaaaaa"),
        email="alice@example.com",
    )
    now = datetime(2026, 5, 9, tzinfo=UTC)

    with patch(
        "echoroo.workers._dormancy_events.sanitise_field",
        side_effect=lambda _value, *, field_name: f"<sanitised:{field_name}>",
    ) as spy:
        payload = build_notification_payload(
            stage="stage_initial",
            project=project,
            owner=owner,
            now=now,
        )

    field_names = {call.kwargs["field_name"] for call in spy.call_args_list}
    assert field_names == {
        "stage",
        "project_id",
        "project_name",
        "owner_user_id",
        "owner_email",
        "dormant_since",
        "evaluated_at",
    }
    # Every value in the returned payload was produced by the spy:
    for field_name, returned in payload.items():
        assert returned == f"<sanitised:{field_name}>"


def test_build_notification_payload_stage_value_passed_to_sanitiser() -> None:
    """The ``stage`` argument is the value flowing into the ``stage`` field."""
    project = _make_project(dormant_since=datetime(2026, 4, 1, tzinfo=UTC))
    owner = _make_owner()
    now = datetime(2026, 5, 9, tzinfo=UTC)

    with patch(
        "echoroo.workers._dormancy_events.sanitise_field",
        side_effect=lambda value, *, field_name: f"{field_name}={value}",
    ) as spy:
        build_notification_payload(
            stage="stage_grace_expired",
            project=project,
            owner=owner,
            now=now,
        )

    stage_calls = [
        call for call in spy.call_args_list if call.kwargs["field_name"] == "stage"
    ]
    assert len(stage_calls) == 1
    assert stage_calls[0].args[0] == "stage_grace_expired"


# ---------------------------------------------------------------------------
# compute_idempotency_key
# ---------------------------------------------------------------------------


def test_compute_idempotency_key_format() -> None:
    """The exact format ``dormancy:{project_id}:{unix}:{stage}`` is pinned."""
    project_id = UUID("11111111-2222-3333-4444-555555555555")
    dormant_since = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)

    key = compute_idempotency_key(
        project_id=project_id,
        dormant_since=dormant_since,
        stage="stage_initial",
    )

    expected_unix = int(dormant_since.timestamp())
    assert (
        key
        == f"dormancy:11111111-2222-3333-4444-555555555555:{expected_unix}:stage_initial"
    )


def test_compute_idempotency_key_starts_with_dormancy_prefix() -> None:
    """The literal ``dormancy`` prefix is mandatory (mutation: prefix change)."""
    key = compute_idempotency_key(
        project_id=uuid4(),
        dormant_since=datetime(2026, 4, 1, tzinfo=UTC),
        stage="stage_3d",
    )
    assert key.startswith("dormancy:")
    # Defence against silent mutation to e.g. "dormant:" or "outbox:":
    assert not key.startswith("dormant:")
    assert not key.startswith("outbox:")


def test_compute_idempotency_key_has_exactly_three_colons() -> None:
    """Format pin: ``prefix:project_id:unix:stage`` → exactly 3 separators."""
    project_id = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    dormant_since = datetime(2026, 4, 1, tzinfo=UTC)

    key = compute_idempotency_key(
        project_id=project_id,
        dormant_since=dormant_since,
        stage="stage_30d",
    )

    # UUID has hyphens (not colons), so the only colons are the field
    # separators between the four key segments.
    assert key.count(":") == 3


def test_compute_idempotency_key_embeds_dormant_since_unix() -> None:
    """The third segment must be the UNIX-second timestamp of dormant_since."""
    project_id = uuid4()
    dormant_since = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)

    key = compute_idempotency_key(
        project_id=project_id,
        dormant_since=dormant_since,
        stage="stage_30d",
    )

    segments = key.split(":")
    assert segments[0] == "dormancy"
    assert segments[1] == str(project_id)
    assert segments[2] == str(int(dormant_since.timestamp()))
    assert segments[3] == "stage_30d"


def test_compute_idempotency_key_unix_is_integer_not_iso() -> None:
    """The timestamp segment is INT seconds, never an ISO string."""
    dormant_since = datetime(2026, 4, 1, 0, 0, 0, tzinfo=UTC)
    project_id = uuid4()

    key = compute_idempotency_key(
        project_id=project_id,
        dormant_since=dormant_since,
        stage="stage_initial",
    )

    third_segment = key.split(":")[2]
    # Must parse cleanly as an integer:
    assert int(third_segment) == int(dormant_since.timestamp())
    # Must NOT be the ISO repr (defence against dormant_since.isoformat()
    # mutation):
    assert third_segment != dormant_since.isoformat()
    assert "T" not in third_segment


def test_compute_idempotency_key_distinct_per_episode() -> None:
    """Different ``dormant_since`` (same project + stage) → different key."""
    project_id = uuid4()
    first_episode = datetime(2026, 1, 1, tzinfo=UTC)
    second_episode = datetime(2026, 4, 1, tzinfo=UTC)

    key_first = compute_idempotency_key(
        project_id=project_id,
        dormant_since=first_episode,
        stage="stage_3d",
    )
    key_second = compute_idempotency_key(
        project_id=project_id,
        dormant_since=second_episode,
        stage="stage_3d",
    )

    assert key_first != key_second


def test_compute_idempotency_key_distinct_per_stage() -> None:
    """Same project + episode, different stage → different key."""
    project_id = uuid4()
    dormant_since = datetime(2026, 4, 1, tzinfo=UTC)

    keys = {
        compute_idempotency_key(
            project_id=project_id,
            dormant_since=dormant_since,
            stage=stage,
        )
        for stage in (
            "stage_initial",
            "stage_3d",
            "stage_30d",
            "stage_final",
            "stage_grace_expired",
        )
    }
    assert len(keys) == 5


def test_compute_idempotency_key_stable_within_episode() -> None:
    """Same project + dormant_since + stage → identical key (FR-076a dedupe)."""
    project_id = uuid4()
    dormant_since = datetime(2026, 4, 1, tzinfo=UTC)

    key_a = compute_idempotency_key(
        project_id=project_id,
        dormant_since=dormant_since,
        stage="stage_30d",
    )
    key_b = compute_idempotency_key(
        project_id=project_id,
        dormant_since=dormant_since,
        stage="stage_30d",
    )

    assert key_a == key_b


def test_compute_idempotency_key_unix_uses_seconds_not_microseconds() -> None:
    """``int(dormant_since.timestamp())`` discards sub-second precision."""
    project_id = uuid4()
    dormant_since = datetime(2026, 4, 1, 12, 30, 45, 123456, tzinfo=UTC)

    key = compute_idempotency_key(
        project_id=project_id,
        dormant_since=dormant_since,
        stage="stage_initial",
    )

    segments = key.split(":")
    expected = int(dormant_since.timestamp())
    assert segments[2] == str(expected)
    # Defence against ``dormant_since.timestamp()`` mutation (float):
    assert "." not in segments[2]


@pytest.mark.parametrize(
    "stage",
    [
        "stage_initial",
        "stage_3d",
        "stage_30d",
        "stage_final",
        "stage_grace_expired",
    ],
)
def test_compute_idempotency_key_stage_appears_at_tail(stage: str) -> None:
    """Stage is the trailing segment for every legal stage value."""
    key = compute_idempotency_key(
        project_id=uuid4(),
        dormant_since=datetime(2026, 4, 1, tzinfo=UTC),
        stage=stage,
    )
    assert key.endswith(f":{stage}")
    # Note: ``stage_30d`` happens to end with ``stage_3d``'s suffix
    # (modulo the trailing ``0d``), so only assert the leading-colon
    # boundary at the suffix to ensure a clean delimiter.

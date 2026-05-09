"""Unit tests for dormancy follow-up stage scheduling helper.

Targets the pure :func:`compute_ready_stages` helper introduced in
Phase 17 §D-1-bis to lift the mutation score for
:mod:`echoroo.workers.dormancy_check` from 74.6% to >=80%. Boundary
cases for every offset are pinned via parametrize so an off-by-one or
operator-flip mutation cannot survive.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from echoroo.workers._dormancy_stage_schedule import (
    DORMANT_THRESHOLD_SECONDS,
    STAGE_OFFSETS,
    compute_ready_stages,
)

# ---------------------------------------------------------------------------
# Constants under test (re-pinned to defend against accidental table edits)
# ---------------------------------------------------------------------------


_NOW = datetime(2026, 5, 9, 12, 0, 0, tzinfo=UTC)


def _dormant_since(elapsed: timedelta) -> datetime:
    """Helper: return ``_NOW - elapsed`` so callers can think in elapsed time."""
    return _NOW - elapsed


# ---------------------------------------------------------------------------
# STAGE_OFFSETS table integrity (separate from the function under test)
# ---------------------------------------------------------------------------


def test_stage_offsets_keys_pinned() -> None:
    """The five canonical stage names + declaration order are pinned."""
    assert list(STAGE_OFFSETS.keys()) == [
        "stage_initial",
        "stage_3d",
        "stage_30d",
        "stage_final",
        "stage_grace_expired",
    ]


def test_stage_offsets_values_pinned() -> None:
    """Each offset literal is pinned (FR-060: 0/3/30/37/366d)."""
    assert STAGE_OFFSETS["stage_initial"] == timedelta(days=0)
    assert STAGE_OFFSETS["stage_3d"] == timedelta(days=3)
    assert STAGE_OFFSETS["stage_30d"] == timedelta(days=30)
    assert STAGE_OFFSETS["stage_final"] == timedelta(days=37)
    assert STAGE_OFFSETS["stage_grace_expired"] == timedelta(
        seconds=DORMANT_THRESHOLD_SECONDS
    )


def test_dormant_threshold_seconds_pinned() -> None:
    """FR-060 grace threshold = 366 d = 31_622_400 s."""
    assert DORMANT_THRESHOLD_SECONDS == 31_622_400
    assert DORMANT_THRESHOLD_SECONDS == 366 * 24 * 60 * 60


# ---------------------------------------------------------------------------
# compute_ready_stages — empty-result envelope
# ---------------------------------------------------------------------------


def test_compute_ready_stages_zero_elapsed_returns_empty() -> None:
    """``now == dormant_since`` → no follow-up stages ready (initial is skipped)."""
    ready = compute_ready_stages(now=_NOW, dormant_since=_NOW)
    assert ready == []


def test_compute_ready_stages_returns_list_type() -> None:
    """The return type is a concrete ``list[str]`` (not generator/tuple)."""
    ready = compute_ready_stages(
        now=_NOW, dormant_since=_dormant_since(timedelta(days=3))
    )
    assert isinstance(ready, list)


def test_compute_ready_stages_skips_stage_initial_always() -> None:
    """``stage_initial`` is owned by ``_flip_to_dormant``; never returned here."""
    # Even with a fully-elapsed grace window, stage_initial must NOT
    # appear in the follow-up list.
    ready = compute_ready_stages(
        now=_NOW,
        dormant_since=_dormant_since(timedelta(days=400)),
    )
    assert "stage_initial" not in ready


# ---------------------------------------------------------------------------
# compute_ready_stages — boundary tests per offset (parametrized)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("elapsed", "expected"),
    [
        # stage_3d boundary
        (timedelta(days=3) - timedelta(seconds=1), []),
        (timedelta(days=3), ["stage_3d"]),
        (timedelta(days=3) + timedelta(seconds=1), ["stage_3d"]),
        # stage_30d boundary
        (timedelta(days=30) - timedelta(seconds=1), ["stage_3d"]),
        (timedelta(days=30), ["stage_3d", "stage_30d"]),
        (timedelta(days=30) + timedelta(seconds=1), ["stage_3d", "stage_30d"]),
        # stage_final boundary (37d = 30 + 7)
        (
            timedelta(days=37) - timedelta(seconds=1),
            ["stage_3d", "stage_30d"],
        ),
        (
            timedelta(days=37),
            ["stage_3d", "stage_30d", "stage_final"],
        ),
        (
            timedelta(days=37) + timedelta(seconds=1),
            ["stage_3d", "stage_30d", "stage_final"],
        ),
        # stage_grace_expired boundary (366d)
        (
            timedelta(seconds=DORMANT_THRESHOLD_SECONDS) - timedelta(seconds=1),
            ["stage_3d", "stage_30d", "stage_final"],
        ),
        (
            timedelta(seconds=DORMANT_THRESHOLD_SECONDS),
            ["stage_3d", "stage_30d", "stage_final", "stage_grace_expired"],
        ),
        (
            timedelta(seconds=DORMANT_THRESHOLD_SECONDS) + timedelta(seconds=1),
            ["stage_3d", "stage_30d", "stage_final", "stage_grace_expired"],
        ),
    ],
)
def test_compute_ready_stages_boundaries(
    elapsed: timedelta, expected: list[str]
) -> None:
    """Every offset boundary fires inclusively (``elapsed >= offset``)."""
    ready = compute_ready_stages(
        now=_NOW,
        dormant_since=_NOW - elapsed,
    )
    assert ready == expected


def test_compute_ready_stages_full_grace_returns_all_followups() -> None:
    """At the 366-day mark every follow-up stage is ready (no stage_initial)."""
    ready = compute_ready_stages(
        now=_NOW,
        dormant_since=_dormant_since(
            timedelta(seconds=DORMANT_THRESHOLD_SECONDS) + timedelta(days=1)
        ),
    )
    assert ready == [
        "stage_3d",
        "stage_30d",
        "stage_final",
        "stage_grace_expired",
    ]


def test_compute_ready_stages_preserves_declaration_order() -> None:
    """The result mirrors :data:`STAGE_OFFSETS` declaration order."""
    ready = compute_ready_stages(
        now=_NOW,
        dormant_since=_dormant_since(timedelta(days=400)),
    )
    expected_order = [
        stage for stage in STAGE_OFFSETS if stage != "stage_initial"
    ]
    assert ready == expected_order


def test_compute_ready_stages_no_duplicate_entries() -> None:
    """Each ready stage appears at most once."""
    ready = compute_ready_stages(
        now=_NOW,
        dormant_since=_dormant_since(timedelta(days=400)),
    )
    assert len(ready) == len(set(ready))


def test_compute_ready_stages_negative_elapsed_returns_empty() -> None:
    """``now < dormant_since`` (clock skew) → empty list, never raises."""
    ready = compute_ready_stages(
        now=_NOW,
        dormant_since=_NOW + timedelta(days=1),
    )
    assert ready == []

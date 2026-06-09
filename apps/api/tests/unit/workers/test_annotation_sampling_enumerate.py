"""Unit tests for the pure segment-enumeration helper of the annotation sampler.

The Celery task ``sample_annotation_segments`` delegates candidate-segment
enumeration to the pure :func:`_enumerate_segments` helper (no DB, no RNG) so
the ``fixed`` vs ``whole_recording`` branching can be tested in isolation.

Covers:
    - whole_recording: exactly one segment per surviving recording, spanning the
      full time-expanded duration, capped by the caller's sampling (not here).
    - whole_recording: applies the same time_expansion factor as the fixed path.
    - whole_recording: time-of-day filter still excludes recordings.
    - fixed: contiguous non-overlapping slots (regression — unchanged behaviour).
"""

from __future__ import annotations

from datetime import UTC, datetime
from datetime import time as dt_time
from uuid import uuid4
from zoneinfo import ZoneInfo

from echoroo.workers.annotation_sampling_tasks import _enumerate_segments

_UTC = ZoneInfo("UTC")


def test_whole_recording_one_segment_per_recording_full_duration() -> None:
    """Each recording yields exactly one (0, effective_duration) segment."""
    rec_a = uuid4()
    rec_b = uuid4()
    rows = [
        (rec_a, 1800.0, 1.0, datetime(2026, 6, 9, 6, 0, tzinfo=UTC)),
        (rec_b, 300.0, 1.0, datetime(2026, 6, 9, 7, 0, tzinfo=UTC)),
    ]

    slots = _enumerate_segments(
        rows,
        segment_mode="whole_recording",
        segment_length=None,
        local_tz=_UTC,
        tod_start=None,
        tod_end=None,
    )

    assert sorted(slots, key=lambda s: s[2]) == [
        (rec_b, 0.0, 300.0),
        (rec_a, 0.0, 1800.0),
    ]
    # One segment per recording.
    assert len({s[0] for s in slots}) == len(slots) == 2


def test_whole_recording_applies_time_expansion() -> None:
    """The full-length end honours the recording's time_expansion factor."""
    rec = uuid4()
    rows = [(rec, 600.0, 10.0, datetime(2026, 6, 9, 6, 0, tzinfo=UTC))]

    slots = _enumerate_segments(
        rows,
        segment_mode="whole_recording",
        segment_length=None,
        local_tz=_UTC,
        tod_start=None,
        tod_end=None,
    )

    assert slots == [(rec, 0.0, 6000.0)]


def test_whole_recording_skips_zero_duration_and_tod_filtered() -> None:
    """Zero-duration and out-of-window recordings are excluded."""
    keep = uuid4()
    zero = uuid4()
    out_of_window = uuid4()
    rows = [
        (keep, 100.0, 1.0, datetime(2026, 6, 9, 7, 0, tzinfo=UTC)),
        (zero, 0.0, 1.0, datetime(2026, 6, 9, 7, 0, tzinfo=UTC)),
        (out_of_window, 100.0, 1.0, datetime(2026, 6, 9, 12, 0, tzinfo=UTC)),
    ]

    slots = _enumerate_segments(
        rows,
        segment_mode="whole_recording",
        segment_length=None,
        local_tz=_UTC,
        tod_start=dt_time(6, 0),
        tod_end=dt_time(10, 0),
    )

    assert slots == [(keep, 0.0, 100.0)]


def test_fixed_mode_contiguous_slots_unchanged() -> None:
    """Regression: fixed mode still emits contiguous non-overlapping slots."""
    rec = uuid4()
    # 100 s duration, 30 s slots -> floor(100/30) = 3 slots (0, 30, 60).
    rows = [(rec, 100.0, 1.0, datetime(2026, 6, 9, 6, 0, tzinfo=UTC))]

    slots = _enumerate_segments(
        rows,
        segment_mode="fixed",
        segment_length=30.0,
        local_tz=_UTC,
        tod_start=None,
        tod_end=None,
    )

    assert slots == [
        (rec, 0.0, 30.0),
        (rec, 30.0, 60.0),
        (rec, 60.0, 90.0),
    ]


def test_fixed_mode_skips_recording_shorter_than_slot() -> None:
    """A recording shorter than one slot produces no fixed-mode segments."""
    rec = uuid4()
    rows = [(rec, 20.0, 1.0, datetime(2026, 6, 9, 6, 0, tzinfo=UTC))]

    slots = _enumerate_segments(
        rows,
        segment_mode="fixed",
        segment_length=60.0,
        local_tz=_UTC,
        tod_start=None,
        tod_end=None,
    )

    assert slots == []

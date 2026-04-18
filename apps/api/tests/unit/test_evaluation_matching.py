"""Unit tests for the symmetric-overlap matching algorithm (spec 003-annotation §4).

Tests exercise :func:`_score`, :func:`_overlaps`, and :func:`_safe_div`
directly from :mod:`echoroo.workers.evaluation_tasks` without any database
dependency.  Each test maps to a scenario described in the spec or the task
brief to serve as regression guards for the core evaluation logic.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

import pytest

from echoroo.workers.evaluation_tasks import _overlaps, _safe_div, _score

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MODEL_REF: dict[str, Any] = {"kind": "birdnet"}


def _gt(
    recording_id: UUID,
    start: float,
    end: float,
    taxon_id: UUID,
) -> dict[str, Any]:
    return {
        "recording_id": recording_id,
        "start": start,
        "end": end,
        "taxon_id": taxon_id,
    }


def _det(
    recording_id: UUID,
    start: float,
    end: float,
    taxon_id: UUID,
) -> dict[str, Any]:
    return {
        "recording_id": recording_id,
        "start": start,
        "end": end,
        "taxon_id": taxon_id,
    }


def _extract(rows: list[dict[str, Any]], taxon_id: UUID | None) -> dict[str, Any]:
    """Return the result row matching the given taxon_id (or overall row when None)."""
    for row in rows:
        if row["taxon_id"] == taxon_id:
            return row
    raise KeyError(f"No row for taxon_id={taxon_id!r}")


# ---------------------------------------------------------------------------
# _safe_div
# ---------------------------------------------------------------------------


class TestSafeDiv:
    def test_normal_division(self) -> None:
        assert _safe_div(3.0, 4.0) == pytest.approx(0.75)

    def test_zero_denominator_returns_zero(self) -> None:
        assert _safe_div(1.0, 0.0) == 0.0

    def test_negative_denominator_returns_zero(self) -> None:
        assert _safe_div(1.0, -1.0) == 0.0


# ---------------------------------------------------------------------------
# _overlaps predicate
# ---------------------------------------------------------------------------


class TestOverlaps:
    def test_overlap_same_species(self) -> None:
        rec = uuid4()
        taxon = uuid4()
        d = _det(rec, 9.0, 12.0, taxon)
        g = _gt(rec, 10.0, 11.0, taxon)
        assert _overlaps(d, g) is True

    def test_no_overlap_different_species(self) -> None:
        rec = uuid4()
        taxon_a, taxon_b = uuid4(), uuid4()
        d = _det(rec, 10.2, 10.8, taxon_b)
        g = _gt(rec, 10.0, 11.0, taxon_a)
        assert _overlaps(d, g) is False

    def test_no_overlap_different_recordings(self) -> None:
        taxon = uuid4()
        d = _det(uuid4(), 10.0, 11.0, taxon)
        g = _gt(uuid4(), 10.0, 11.0, taxon)
        assert _overlaps(d, g) is False

    def test_touch_boundary_no_overlap(self) -> None:
        """Exactly touching (not overlapping) should return False."""
        rec = uuid4()
        taxon = uuid4()
        d = _det(rec, 11.0, 12.0, taxon)
        g = _gt(rec, 10.0, 11.0, taxon)
        # max(11.0, 10.0) = 11.0  <  min(12.0, 11.0) = 11.0  -> False
        assert _overlaps(d, g) is False


# ---------------------------------------------------------------------------
# _score — single-species scenarios
# ---------------------------------------------------------------------------


class TestScoreDetectionSpansMultipleGTs:
    """1 detection covers 3 ground-truth intervals (wide-window scenario)."""

    def test_metrics(self) -> None:
        rec = uuid4()
        taxon = uuid4()
        gts = [
            _gt(rec, 10.0, 10.5, taxon),
            _gt(rec, 12.0, 12.5, taxon),
            _gt(rec, 14.0, 14.5, taxon),
        ]
        dets = [_det(rec, 8.0, 15.0, taxon)]
        rows = _score(_MODEL_REF, gts, dets)
        row = _extract(rows, taxon)
        assert row["tp_precision"] == 1, "1 detection overlaps at least one GT"
        assert row["fp"] == 0
        assert row["tp_recall"] == 3, "all 3 GTs overlapped by the detection"
        assert row["fn"] == 0
        assert row["precision"] == pytest.approx(1.0)
        assert row["recall"] == pytest.approx(1.0)
        assert row["f1"] == pytest.approx(1.0)


class TestScoreMultipleDetectionsSameGT:
    """3 detections all overlap the same 1 GT."""

    def test_metrics(self) -> None:
        rec = uuid4()
        taxon = uuid4()
        gts = [_gt(rec, 10.0, 11.0, taxon)]
        dets = [
            _det(rec, 9.5, 10.5, taxon),
            _det(rec, 10.2, 10.8, taxon),
            _det(rec, 10.5, 11.2, taxon),
        ]
        rows = _score(_MODEL_REF, gts, dets)
        row = _extract(rows, taxon)
        assert row["tp_precision"] == 3, "all 3 detections overlap the GT"
        assert row["fp"] == 0
        assert row["tp_recall"] == 1, "the single GT is overlapped"
        assert row["fn"] == 0
        assert row["precision"] == pytest.approx(1.0)
        assert row["recall"] == pytest.approx(1.0)


class TestScoreNoOverlap:
    """Detection and GT are completely non-overlapping in time."""

    def test_metrics(self) -> None:
        rec = uuid4()
        taxon = uuid4()
        gts = [_gt(rec, 10.0, 11.0, taxon)]
        dets = [_det(rec, 20.0, 21.0, taxon)]
        rows = _score(_MODEL_REF, gts, dets)
        row = _extract(rows, taxon)
        assert row["tp_precision"] == 0
        assert row["fp"] == 1
        assert row["tp_recall"] == 0
        assert row["fn"] == 1
        assert row["precision"] == pytest.approx(0.0)
        assert row["recall"] == pytest.approx(0.0)
        assert row["f1"] == pytest.approx(0.0)


class TestScoreSpeciesMismatch:
    """Detection overlaps in time but species identity differs — both sides penalised."""

    def test_metrics(self) -> None:
        rec = uuid4()
        taxon_x, taxon_y = uuid4(), uuid4()
        gts = [_gt(rec, 10.0, 11.0, taxon_x)]
        dets = [_det(rec, 10.2, 10.8, taxon_y)]
        rows = _score(_MODEL_REF, gts, dets)

        row_y = _extract(rows, taxon_y)
        assert row_y["tp_precision"] == 0
        assert row_y["fp"] == 1

        row_x = _extract(rows, taxon_x)
        assert row_x["tp_recall"] == 0
        assert row_x["fn"] == 1


class TestScoreShortPulseInLargeWindow:
    """Window-size invariant: 0.2 s pulse inside a 5 s Perch window counts as TP."""

    def test_metrics(self) -> None:
        rec = uuid4()
        taxon = uuid4()
        gts = [_gt(rec, 10.0, 10.2, taxon)]   # 0.2 s pulse
        dets = [_det(rec, 8.0, 13.0, taxon)]   # 5 s window
        rows = _score(_MODEL_REF, gts, dets)
        row = _extract(rows, taxon)
        assert row["tp_precision"] == 1
        assert row["fp"] == 0
        assert row["tp_recall"] == 1
        assert row["fn"] == 0
        assert row["precision"] == pytest.approx(1.0)
        assert row["recall"] == pytest.approx(1.0)


class TestScoreEdgeOverlap:
    """Detection starts exactly at GT end — no overlap (overlap > 0 only)."""

    def test_metrics(self) -> None:
        rec = uuid4()
        taxon = uuid4()
        gts = [_gt(rec, 10.0, 11.0, taxon)]
        dets = [_det(rec, 11.0, 12.0, taxon)]  # touches, does not overlap
        rows = _score(_MODEL_REF, gts, dets)
        row = _extract(rows, taxon)
        assert row["tp_precision"] == 0
        assert row["fp"] == 1
        assert row["tp_recall"] == 0
        assert row["fn"] == 1


class TestScorePrecisionRecallF1ZeroDivision:
    """Zero detections and zero GTs — all metrics default to 0.0."""

    def test_empty_inputs(self) -> None:
        rows = _score(_MODEL_REF, [], [])
        # Only the overall row should be present (no per-taxon rows).
        overall = _extract(rows, None)
        assert overall["tp_precision"] == 0
        assert overall["fp"] == 0
        assert overall["tp_recall"] == 0
        assert overall["fn"] == 0
        assert overall["precision"] == pytest.approx(0.0)
        assert overall["recall"] == pytest.approx(0.0)
        assert overall["f1"] == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# _score — multi-species scenario
# ---------------------------------------------------------------------------


class TestScoreMultiSpeciesBreakdown:
    """GT: 2x species X + 1x species Y.  Det: 1x species X (covers both GTs), 0x species Y.

    Under symmetric (non-1:1) matching:
    - 1 detection for X overlaps both GT rows of X  =>  TP_P=1, FP=0, TP_R=2, FN=0
    - 0 detections for Y                            =>  TP_P=0, FP=0, TP_R=0, FN=1
    """

    def test_per_species_metrics(self) -> None:
        rec = uuid4()
        taxon_x, taxon_y = uuid4(), uuid4()
        gts = [
            _gt(rec, 10.0, 10.5, taxon_x),
            _gt(rec, 12.0, 12.5, taxon_x),
            _gt(rec, 14.0, 14.5, taxon_y),
        ]
        # Single wide-window detection covers both X GTs.
        dets = [_det(rec, 8.0, 15.0, taxon_x)]
        rows = _score(_MODEL_REF, gts, dets)

        row_x = _extract(rows, taxon_x)
        assert row_x["tp_precision"] == 1
        assert row_x["fp"] == 0
        assert row_x["tp_recall"] == 2
        assert row_x["fn"] == 0
        assert row_x["precision"] == pytest.approx(1.0)
        assert row_x["recall"] == pytest.approx(1.0)

        row_y = _extract(rows, taxon_y)
        assert row_y["tp_precision"] == 0
        assert row_y["fp"] == 0
        assert row_y["tp_recall"] == 0
        assert row_y["fn"] == 1
        assert row_y["precision"] == pytest.approx(0.0)  # 0/0 -> 0.0
        assert row_y["recall"] == pytest.approx(0.0)

    def test_overall_aggregation(self) -> None:
        rec = uuid4()
        taxon_x, taxon_y = uuid4(), uuid4()
        gts = [
            _gt(rec, 10.0, 10.5, taxon_x),
            _gt(rec, 12.0, 12.5, taxon_x),
            _gt(rec, 14.0, 14.5, taxon_y),
        ]
        dets = [_det(rec, 8.0, 15.0, taxon_x)]
        rows = _score(_MODEL_REF, gts, dets)

        overall = _extract(rows, None)
        # X: TP_P=1, FP=0, TP_R=2, FN=0 + Y: TP_P=0, FP=0, TP_R=0, FN=1
        assert overall["tp_precision"] == 1
        assert overall["fp"] == 0
        assert overall["tp_recall"] == 2
        assert overall["fn"] == 1

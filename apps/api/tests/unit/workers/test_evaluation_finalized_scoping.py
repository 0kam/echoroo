"""Unit tests for the FINALIZED-only evaluation universe (TASK A).

The cross-model evaluation must score detections only against *finalized*
ground truth. A segment is finalized when ``status == ANNOTATED`` (the segment
service sets a confirmed-empty segment — ``is_empty=True``, no
TimeRangeAnnotation rows — to ``status == ANNOTATED`` so it stays a valid
NEGATIVE). An ``unannotated`` segment means "not yet looked at"; its detections
have no ground truth to match and must therefore be EXCLUDED from the universe
rather than counted as False Positives.

These tests cover:

1. The SQL predicate applied by :func:`_load_segments` and
   :func:`_load_ground_truths` (both gate on ``status = 'annotated'`` and no
   longer use the old ``status != 'skipped'`` universe).
2. The three scoring outcomes through the real Python overlap + scoring path:
   (a) a detection overlapping an ``unannotated`` segment is NOT counted as FP;
   (b) a detection overlapping a finalized ``is_empty=True`` segment IS counted
   as FP; (c) normal TP / FP / FN on finalized annotated segments still works.
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa  # noqa: F401  (kept for parity with sibling worker tests)
from sqlalchemy.dialects import postgresql

from echoroo.models.enums import DetectionSource
from echoroo.workers.evaluation_tasks import (
    _load_detections_for_ref,
    _load_ground_truths,
    _load_segments,
    _score,
)

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# SQL helpers / doubles
# ---------------------------------------------------------------------------


def _normalize_sql(stmt: Any) -> str:
    """Compile a statement against postgresql with literal binds, lowercased
    and whitespace-collapsed so structural assertions match cleanly."""
    compiled = stmt.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )
    return re.sub(r"\s+", " ", str(compiled)).strip().lower()


class _ScalarResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalars(self) -> _ScalarResult:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)


class _RowResult:
    def __init__(self, rows: list[tuple[Any, Any]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[Any, Any]]:
        return list(self._rows)


class _CaptureDB:
    """Records the SQL statement and returns a canned result."""

    def __init__(self, result: Any) -> None:
        self._result = result
        self.statements: list[Any] = []

    async def execute(self, stmt: Any, params: Any | None = None) -> Any:
        self.statements.append(stmt)
        return self._result


class _Segment:
    """Plain attribute container that quacks like ``AnnotationSegment``."""

    def __init__(
        self,
        *,
        recording_id: UUID,
        start_time_sec: float,
        end_time_sec: float,
        id: UUID | None = None,
    ) -> None:
        self.id = id or uuid4()
        self.recording_id = recording_id
        self.start_time_sec = start_time_sec
        self.end_time_sec = end_time_sec


class _Annotation:
    """Quacks like a detection ``RecordingAnnotation`` row."""

    def __init__(
        self,
        *,
        recording_id: UUID,
        start_time: float,
        end_time: float,
    ) -> None:
        self.recording_id = recording_id
        self.start_time = start_time
        self.end_time = end_time


# ---------------------------------------------------------------------------
# 1. SQL predicate: finalized (status == ANNOTATED), not "!= SKIPPED"
# ---------------------------------------------------------------------------


async def test_load_segments_filters_on_annotated_status() -> None:
    """_load_segments now scopes the universe to status = 'annotated'."""
    db = _CaptureDB(_ScalarResult([]))
    await _load_segments(db, uuid4())

    sql = _normalize_sql(db.statements[0])
    assert "annotation_segments.status = 'annotated'" in sql
    # The old universe ("everything except skipped") must be gone.
    assert "!= 'skipped'" not in sql
    assert "<> 'skipped'" not in sql


async def test_load_ground_truths_gates_join_on_annotated_status() -> None:
    """_load_ground_truths gates the JOIN on the same finalized predicate."""
    db = _CaptureDB(_RowResult([]))
    await _load_ground_truths(db, uuid4())

    sql = _normalize_sql(db.statements[0])
    assert "annotation_segments.status = 'annotated'" in sql


async def test_load_ground_truths_maps_rows_to_recording_absolute() -> None:
    """Returned GT rows are recording-absolute (segment offset + annotation)."""
    rec = uuid4()
    taxon = uuid4()
    seg = _Segment(recording_id=rec, start_time_sec=10.0, end_time_sec=20.0)
    ann = _make_gt_annotation(start=1.0, end=2.0, taxon_id=taxon)

    db = _CaptureDB(_RowResult([(ann, seg)]))
    rows = await _load_ground_truths(db, uuid4())

    assert len(rows) == 1
    assert rows[0]["recording_id"] == rec
    assert rows[0]["start"] == pytest.approx(11.0)
    assert rows[0]["end"] == pytest.approx(12.0)
    assert rows[0]["taxon_id"] == taxon


def _make_gt_annotation(*, start: float, end: float, taxon_id: UUID) -> Any:
    """A TimeRangeAnnotation-like object consumed by _load_ground_truths."""

    class _GT:
        def __init__(self) -> None:
            self.start_time_sec = start
            self.end_time_sec = end
            self.taxon_id = taxon_id

    return _GT()


# ---------------------------------------------------------------------------
# 2. Detection-scoping universe excludes detections outside finalized segments
# ---------------------------------------------------------------------------


async def test_detections_outside_finalized_segments_are_excluded() -> None:
    """A detection that overlaps no FINALIZED segment window is discarded.

    The caller (``_run_annotation_evaluation``) only ever passes the FINALIZED
    segments returned by :func:`_load_segments`. A detection that falls inside
    an ``unannotated`` segment (absent from that list) therefore overlaps no
    window and is dropped before scoring — so it can never become a FP.
    """
    rec = uuid4()
    # Only the finalized segment [0, 5) is in the universe. The unannotated
    # segment [5, 10) is deliberately NOT passed in.
    finalized = _Segment(recording_id=rec, start_time_sec=0.0, end_time_sec=5.0)

    # Detection A overlaps the finalized window -> kept.
    # Detection B sits entirely inside the (excluded) unannotated window -> dropped.
    det_in_finalized = _Annotation(recording_id=rec, start_time=1.0, end_time=2.0)
    det_in_unannotated = _Annotation(recording_id=rec, start_time=6.0, end_time=7.0)

    db = _CaptureDB(
        _RowResult(
            [
                (det_in_finalized, uuid4()),
                (det_in_unannotated, uuid4()),
            ]
        )
    )

    detections = await _load_detections_for_ref(
        db, segments=[finalized], model_ref={"kind": "birdnet"}
    )

    assert len(detections) == 1
    assert detections[0]["start"] == pytest.approx(1.0)
    assert detections[0]["end"] == pytest.approx(2.0)

    # And the SQL filtered by the BirdNET source.
    sql = _normalize_sql(db.statements[0])
    assert DetectionSource.BIRDNET.value in sql


# ---------------------------------------------------------------------------
# 3. End-to-end a / b / c scoring outcomes through the real path
# ---------------------------------------------------------------------------


def _det(rec: UUID, start: float, end: float, taxon: UUID) -> dict[str, Any]:
    return {"recording_id": rec, "start": start, "end": end, "taxon_id": taxon}


def _gt(rec: UUID, start: float, end: float, taxon: UUID) -> dict[str, Any]:
    return {"recording_id": rec, "start": start, "end": end, "taxon_id": taxon}


def _overall(rows: list[dict[str, Any]]) -> dict[str, Any]:
    for row in rows:
        if row["taxon_id"] is None:
            return row
    raise AssertionError("missing overall row")


async def test_case_a_detection_over_unannotated_segment_is_not_fp() -> None:
    """(a) A detection overlapping an UNANNOTATED segment is NOT counted.

    Build the real universe: ``_load_segments`` returns only the finalized
    segment, so the detection that lives in the unannotated window is excluded
    by ``_load_detections_for_ref`` and never reaches ``_score`` -> 0 FP.
    """
    rec = uuid4()
    taxon = uuid4()

    # Universe: one finalized empty segment [0,5). The unannotated [5,10) is
    # NOT returned by _load_segments (status filter), so we don't include it.
    finalized = _Segment(recording_id=rec, start_time_sec=0.0, end_time_sec=5.0)

    # The model detection overlaps ONLY the unannotated window [5,10).
    det_in_unannotated = _Annotation(recording_id=rec, start_time=6.0, end_time=7.0)

    db = _CaptureDB(_RowResult([(det_in_unannotated, taxon)]))
    detections = await _load_detections_for_ref(
        db, segments=[finalized], model_ref={"kind": "birdnet"}
    )

    # The detection is excluded from the universe.
    assert detections == []

    # No GT (the finalized segment is empty); no detections -> no FP, no TP.
    rows = _score({"kind": "birdnet"}, [], detections)
    overall = _overall(rows)
    assert overall["fp"] == 0
    assert overall["tp_precision"] == 0
    assert overall["fn"] == 0


async def test_case_b_detection_over_finalized_empty_segment_is_fp() -> None:
    """(b) A detection overlapping a finalized is_empty=True segment IS a FP.

    The annotator confirmed the segment empty (status=ANNOTATED, is_empty=True),
    so it is a valid NEGATIVE: a model detection inside it is a False Positive.
    """
    rec = uuid4()
    taxon = uuid4()

    # Finalized confirmed-empty segment [0,5): in the universe, zero GT rows.
    finalized_empty = _Segment(
        recording_id=rec, start_time_sec=0.0, end_time_sec=5.0
    )
    det_in_empty = _Annotation(recording_id=rec, start_time=1.0, end_time=2.0)

    db = _CaptureDB(_RowResult([(det_in_empty, taxon)]))
    detections = await _load_detections_for_ref(
        db, segments=[finalized_empty], model_ref={"kind": "birdnet"}
    )

    # The detection overlaps the finalized window -> kept.
    assert len(detections) == 1

    # The finalized-empty segment contributes NO ground truth, so the detection
    # cannot match anything -> exactly one False Positive.
    rows = _score({"kind": "birdnet"}, [], detections)
    overall = _overall(rows)
    assert overall["fp"] == 1
    assert overall["tp_precision"] == 0


async def test_case_c_normal_tp_fp_fn_on_finalized_annotated_segments() -> None:
    """(c) Normal TP / FP / FN on finalized ANNOTATED segments still works."""
    rec = uuid4()
    taxon = uuid4()

    finalized = _Segment(recording_id=rec, start_time_sec=0.0, end_time_sec=10.0)

    # Two detections overlap the finalized window.
    det_match = _Annotation(recording_id=rec, start_time=2.0, end_time=3.0)
    det_miss = _Annotation(recording_id=rec, start_time=8.0, end_time=9.0)

    db = _CaptureDB(_RowResult([(det_match, taxon), (det_miss, taxon)]))
    detections = await _load_detections_for_ref(
        db, segments=[finalized], model_ref={"kind": "birdnet"}
    )
    assert len(detections) == 2

    # Ground truth: one annotation overlapping det_match, plus an un-detected GT.
    gts = [
        _gt(rec, 2.0, 3.0, taxon),   # overlapped by det_match -> TP
        _gt(rec, 5.0, 6.0, taxon),   # not overlapped by any detection -> FN
    ]

    rows = _score({"kind": "birdnet"}, gts, detections)
    overall = _overall(rows)
    assert overall["tp_precision"] == 1   # det_match matched a GT
    assert overall["fp"] == 1             # det_miss matched nothing
    assert overall["tp_recall"] == 1      # the [2,3) GT was detected
    assert overall["fn"] == 1             # the [5,6) GT was missed

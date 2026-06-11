"""Celery task running the cross-model evaluation pipeline (spec A3).

The task iterates over every requested model reference of an
:class:`EvaluationRun`, collects the detection annotations that intersect
the ground-truth segments, applies the symmetric-overlap matching rule
from ``specs/003-annotation/research.md`` §4 and persists aggregated
:class:`EvaluationResult` rows (one per species + one ``taxon_id IS NULL``
overall row per model reference).

Source of the detection annotations per model kind (all read from the live
:class:`RecordingAnnotation` table ``recording_annotations_DEFERRED``):

- **BirdNET**: rows with ``source = 'birdnet'``.
- **Perch**: rows with ``source = 'perch'``.
- **Custom**: rows with ``source = 'custom_svm'`` and
  ``detection_run_id`` pointing at a :class:`DetectionRun` whose
  ``model_version`` equals the custom model UUID (this is how
  :meth:`CustomModelService.create_detection_run` persists the linkage).

Species identity for all three sources is carried by
``RecordingAnnotation.tag_id`` → ``Tag.taxon_id``; rows whose tag has no
taxon link are discarded before scoring (they cannot match any GT row).
"""

from __future__ import annotations

import asyncio
import logging
import traceback
from collections import defaultdict
from typing import Any
from uuid import UUID

from sqlalchemy import and_, select

from echoroo.models.annotation_set import (
    AnnotationSegment,
    TimeRangeAnnotation,
)
from echoroo.models.detection_run import DetectionRun
from echoroo.models.enums import DetectionSource
from echoroo.models.recording_annotation import RecordingAnnotation
from echoroo.models.tag import Tag
from echoroo.repositories.evaluation import (
    EvaluationResultRepository,
    EvaluationRunRepository,
)
from echoroo.workers.celery_app import app
from echoroo.workers.db_utils import get_worker_engine_and_session_factory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Celery task entrypoint
# ---------------------------------------------------------------------------


@app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="echoroo.workers.evaluation_tasks.run_annotation_evaluation",
    time_limit=1800,
    soft_time_limit=1680,
)
def run_annotation_evaluation(_self: Any, evaluation_run_id: str) -> dict[str, Any]:
    """Entry point for the ``worker-cpu`` queue.

    Args:
        evaluation_run_id: UUID string of the target
            :class:`EvaluationRun`.

    Returns:
        Summary dict with ``status`` and counts of inserted result rows.
    """
    return asyncio.run(_run_annotation_evaluation(UUID(evaluation_run_id)))


# ---------------------------------------------------------------------------
# Async implementation
# ---------------------------------------------------------------------------


async def _run_annotation_evaluation(evaluation_run_id: UUID) -> dict[str, Any]:
    """Async impl fetched inside ``asyncio.run()``."""
    engine, session_factory = get_worker_engine_and_session_factory()
    inserted = 0
    try:
        async with session_factory() as db:
            run_repo = EvaluationRunRepository(db)
            result_repo = EvaluationResultRepository(db)

            run = await run_repo.get_by_id(evaluation_run_id)
            if run is None:
                logger.error(
                    "Evaluation run %s not found", evaluation_run_id
                )
                return {"status": "not_found"}

            await run_repo.mark_running(evaluation_run_id)
            await db.commit()

            try:
                segments = await _load_segments(db, run.annotation_set_id)
                gts = await _load_ground_truths(db, run.annotation_set_id)

                all_rows: list[dict[str, Any]] = []
                for ref in run.requested_model_refs:
                    detections = await _load_detections_for_ref(
                        db, segments=segments, model_ref=ref,
                    )
                    per_ref_rows = _score(ref, gts, detections)
                    all_rows.extend(per_ref_rows)

                if all_rows:
                    await result_repo.bulk_insert(evaluation_run_id, all_rows)
                    inserted = len(all_rows)
                await run_repo.mark_completed(evaluation_run_id)
                await db.commit()
            except Exception:
                err = traceback.format_exc()
                logger.exception(
                    "Evaluation run %s failed", evaluation_run_id,
                )
                await db.rollback()
                await run_repo.mark_failed(evaluation_run_id, err)
                await db.commit()
                return {"status": "failed", "error": err}

        return {"status": "completed", "results_inserted": inserted}
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# Data loading helpers
# ---------------------------------------------------------------------------


async def _load_segments(
    db: Any, annotation_set_id: UUID,
) -> list[AnnotationSegment]:
    """Load every FINALIZED segment for the set (the evaluation universe).

    Only segments with ``status == AnnotationSegmentStatus.ANNOTATED`` are
    finalized. A confirmed-empty segment (annotator marked "no target calls",
    ``is_empty=True``) is finalized to ``status == ANNOTATED`` by the segment
    service, so it stays a valid NEGATIVE and any model detection overlapping
    it is correctly counted as a False Positive. ``unannotated`` segments mean
    "not yet finalized" and must be excluded so detections overlapping them are
    NOT scored (they have no ground truth yet, which would unfairly depress
    precision). ``skipped`` segments are likewise excluded.
    """
    from echoroo.models.enums import AnnotationSegmentStatus

    stmt = (
        select(AnnotationSegment)
        .where(AnnotationSegment.annotation_set_id == annotation_set_id)
        .where(AnnotationSegment.status == AnnotationSegmentStatus.ANNOTATED)
    )
    return list((await db.execute(stmt)).scalars().all())


async def _load_ground_truths(
    db: Any, annotation_set_id: UUID,
) -> list[dict[str, Any]]:
    """Load ground-truth intervals as recording-absolute (start, end, taxon).

    Each returned dict has keys ``recording_id`` (UUID),
    ``start`` (float, sec), ``end`` (float, sec), ``taxon_id`` (UUID).

    The JOIN is gated on the SAME finalized-status predicate used by
    :func:`_load_segments` (``status == ANNOTATED``) so the detection-scoping
    universe and the ground-truth universe stay consistent.
    """
    from echoroo.models.enums import AnnotationSegmentStatus

    stmt = (
        select(TimeRangeAnnotation, AnnotationSegment)
        .join(
            AnnotationSegment,
            AnnotationSegment.id == TimeRangeAnnotation.segment_id,
        )
        .where(AnnotationSegment.annotation_set_id == annotation_set_id)
        .where(AnnotationSegment.status == AnnotationSegmentStatus.ANNOTATED)
    )
    rows: list[dict[str, Any]] = []
    for ann, seg in (await db.execute(stmt)).all():
        abs_start = seg.start_time_sec + ann.start_time_sec
        abs_end = seg.start_time_sec + ann.end_time_sec
        rows.append(
            {
                "recording_id": seg.recording_id,
                "start": float(abs_start),
                "end": float(abs_end),
                "taxon_id": ann.taxon_id,
            }
        )
    return rows


async def _load_detections_for_ref(
    db: Any,
    *,
    segments: list[AnnotationSegment],
    model_ref: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return detection annotations intersecting the set's segment windows.

    Detections are filtered per-recording to those overlapping at least one
    finalized segment window (``det.start < seg.end AND det.end > seg.start``).
    This discards detections that fall entirely outside the finalized audio and
    therefore cannot contribute to precision or recall.

    Args:
        db: Active async session.
        segments: Every FINALIZED (``status == ANNOTATED``) segment of the
            evaluated set (the universe produced by :func:`_load_segments`).
        model_ref: Dict with ``kind`` and optional ``model_id``.

    Returns:
        List of dicts with keys ``recording_id``, ``start``, ``end``,
        ``taxon_id``.
    """
    if not segments:
        return []

    # Group segments by recording for per-recording overlap clauses.
    segments_by_rec: dict[UUID, list[tuple[float, float]]] = defaultdict(list)
    for seg in segments:
        segments_by_rec[seg.recording_id].append(
            (float(seg.start_time_sec), float(seg.end_time_sec))
        )

    kind = str(model_ref.get("kind"))
    stmt = (
        select(RecordingAnnotation, Tag.taxon_id)
        .join(Tag, Tag.id == RecordingAnnotation.tag_id)
        .where(RecordingAnnotation.recording_id.in_(segments_by_rec.keys()))
        .where(Tag.taxon_id.is_not(None))
    )

    if kind == "birdnet":
        stmt = stmt.where(RecordingAnnotation.source == DetectionSource.BIRDNET)
    elif kind == "perch":
        stmt = stmt.where(
            RecordingAnnotation.source.in_(
                [DetectionSource.PERCH, DetectionSource.PERCH_SEARCH]
            )
        )
    elif kind == "custom":
        model_id_raw = model_ref.get("model_id")
        if not model_id_raw:
            logger.warning(
                "custom model_ref missing model_id; returning no detections",
            )
            return []
        model_id = UUID(str(model_id_raw))
        run_ids_stmt = select(DetectionRun.id).where(
            and_(
                DetectionRun.model_name == "custom_svm",
                DetectionRun.model_version == str(model_id),
            )
        )
        run_ids = list(
            (await db.execute(run_ids_stmt)).scalars().all()
        )
        if not run_ids:
            return []
        stmt = stmt.where(
            and_(
                RecordingAnnotation.source == DetectionSource.CUSTOM_SVM,
                RecordingAnnotation.detection_run_id.in_(run_ids),
            )
        )
    else:
        logger.warning("Unknown model_ref kind %r; skipping", kind)
        return []

    # Coarse filter: annotation must intersect some recording window.
    # We apply the per-recording segment-window filter in Python below to
    # avoid building a very large OR-tree in SQL.
    raw_rows = (await db.execute(stmt)).all()

    detections: list[dict[str, Any]] = []
    for annotation, taxon_id in raw_rows:
        rec_segments = segments_by_rec.get(annotation.recording_id)
        if not rec_segments:
            continue
        a_start = float(annotation.start_time)
        a_end = float(annotation.end_time)
        if not any(
            a_start < seg_end and a_end > seg_start
            for seg_start, seg_end in rec_segments
        ):
            continue
        detections.append(
            {
                "recording_id": annotation.recording_id,
                "start": a_start,
                "end": a_end,
                "taxon_id": taxon_id,
            }
        )
    return detections


# ---------------------------------------------------------------------------
# Scoring (symmetric-overlap matching)
# ---------------------------------------------------------------------------


def _overlaps(
    det: dict[str, Any], gt: dict[str, Any],
) -> bool:
    """Return True when det and gt satisfy the overlap predicate.

    Matches species identity (``taxon_id``) and requires strictly positive
    time overlap on the same recording.
    """
    if det["recording_id"] != gt["recording_id"]:
        return False
    if det["taxon_id"] != gt["taxon_id"]:
        return False
    return bool(
        max(det["start"], gt["start"]) < min(det["end"], gt["end"])
    )


def _safe_div(num: float, denom: float) -> float:
    """Return ``num/denom`` with 0.0 on zero or negative denominator."""
    if denom <= 0:
        return 0.0
    value = num / denom
    # Guard against NaN sneaking in via upstream floats.
    if value != value:  # noqa: PLR0124  NaN check
        return 0.0
    return value


def _score(
    model_ref: dict[str, Any],
    gts: list[dict[str, Any]],
    detections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply symmetric-overlap matching and return per-species + overall rows.

    Args:
        model_ref: Model reference dict (passed through onto each row).
        gts: Ground-truth rows (same shape as :func:`_load_ground_truths`).
        detections: Detection rows (same shape as
            :func:`_load_detections_for_ref`).

    Returns:
        List of result-row dicts ready for
        :meth:`EvaluationResultRepository.bulk_insert`. Always contains the
        overall row (``taxon_id = None``) plus one row per taxon observed
        in either GT or detections.
    """
    gts_by_taxon: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    for gt in gts:
        gts_by_taxon[gt["taxon_id"]].append(gt)

    dets_by_taxon: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    for det in detections:
        dets_by_taxon[det["taxon_id"]].append(det)

    # ---- overall -----------------------------------------------------------
    overall_tp_p = 0
    overall_fp = 0
    overall_tp_r = 0
    overall_fn = 0

    # Precompute GT overlap flags once per GT by taxon to avoid O(N*M) across
    # all species when one taxon is dense.
    rows: list[dict[str, Any]] = []
    taxa_union: set[UUID] = set(gts_by_taxon.keys()) | set(dets_by_taxon.keys())
    for taxon_id in taxa_union:
        taxon_gts = gts_by_taxon.get(taxon_id, [])
        taxon_dets = dets_by_taxon.get(taxon_id, [])

        tp_p = 0
        fp = 0
        for det in taxon_dets:
            if any(_overlaps(det, gt) for gt in taxon_gts):
                tp_p += 1
            else:
                fp += 1

        tp_r = 0
        fn = 0
        for gt in taxon_gts:
            if any(_overlaps(det, gt) for det in taxon_dets):
                tp_r += 1
            else:
                fn += 1

        precision = _safe_div(tp_p, tp_p + fp)
        recall = _safe_div(tp_r, tp_r + fn)
        f1 = _safe_div(2 * precision * recall, precision + recall)

        rows.append(
            {
                "model_ref": model_ref,
                "taxon_id": taxon_id,
                "tp_precision": tp_p,
                "fp": fp,
                "tp_recall": tp_r,
                "fn": fn,
                "precision": precision,
                "recall": recall,
                "f1": f1,
            }
        )

        overall_tp_p += tp_p
        overall_fp += fp
        overall_tp_r += tp_r
        overall_fn += fn

    overall_precision = _safe_div(overall_tp_p, overall_tp_p + overall_fp)
    overall_recall = _safe_div(overall_tp_r, overall_tp_r + overall_fn)
    overall_f1 = _safe_div(
        2 * overall_precision * overall_recall,
        overall_precision + overall_recall,
    )

    rows.append(
        {
            "model_ref": model_ref,
            "taxon_id": None,
            "tp_precision": overall_tp_p,
            "fp": overall_fp,
            "tp_recall": overall_tp_r,
            "fn": overall_fn,
            "precision": overall_precision,
            "recall": overall_recall,
            "f1": overall_f1,
        }
    )

    return rows


__all__ = ["run_annotation_evaluation"]

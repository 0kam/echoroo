"""Cross-model evaluation service (spec 003-annotation, Phase A3).

Entry point for the Evaluation dashboard:

- :meth:`EvaluationService.evaluate_annotation_set` creates an
  :class:`EvaluationRun` in ``pending`` status and enqueues the
  :func:`run_annotation_evaluation` Celery task on the default queue
  (served by the ``worker-cpu`` container in ``compose.dev.yaml``).
- :meth:`EvaluationService.get_run` returns the persisted run.
- :meth:`EvaluationService.get_summary` returns the grouped-by-model
  dashboard summary (:class:`EvaluationSummary`) for a completed run.

Authorization is enforced at the router level (``check_project_access``);
the service assumes caller has already validated the user's ability to
read/write the parent project.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.models.annotation_set import AnnotationSet
from echoroo.models.evaluation import EvaluationRun
from echoroo.models.taxon import Taxon
from echoroo.repositories.evaluation import (
    EvaluationResultRepository,
    EvaluationRunRepository,
)
from echoroo.schemas.evaluation import (
    EvaluationRunResponse,
    EvaluationSummary,
    ModelEvaluationSummary,
    OverallMetric,
    SpeciesMetric,
)

logger = logging.getLogger(__name__)


def _model_ref_key(ref: dict[str, Any]) -> tuple[str, str]:
    """Stable hashable key for a model reference dict.

    Args:
        ref: Model reference payload.

    Returns:
        Tuple suitable for use as a dict key (``kind``, ``model_id or ""``).
    """
    kind = str(ref.get("kind", ""))
    model_id = str(ref.get("model_id", ""))
    return (kind, model_id)


class EvaluationService:
    """Service layer orchestrating evaluation run lifecycle."""

    def __init__(
        self,
        db: AsyncSession,
        run_repo: EvaluationRunRepository,
        result_repo: EvaluationResultRepository,
    ) -> None:
        """Initialize the service.

        Args:
            db: Active async session (used for side queries like taxon
                lookups).
            run_repo: Evaluation run repository.
            result_repo: Evaluation result repository.
        """
        self.db = db
        self.run_repo = run_repo
        self.result_repo = result_repo

    async def evaluate_annotation_set(
        self,
        *,
        annotation_set_id: UUID,
        model_refs: list[dict[str, Any]],
        user_id: UUID,
    ) -> EvaluationRunResponse:
        """Create a pending evaluation run and dispatch the worker task.

        Args:
            annotation_set_id: Target AnnotationSet ID. Must exist.
            model_refs: Wire-format list of model references
                (dicts with ``kind`` and optional ``model_id``).
            user_id: Authenticated user requesting the evaluation.

        Raises:
            HTTPException: 404 when the AnnotationSet does not exist.

        Returns:
            :class:`EvaluationRunResponse` for the newly created run.
        """
        # Verify AnnotationSet existence.
        set_row = (
            await self.db.execute(
                select(AnnotationSet).where(
                    AnnotationSet.id == annotation_set_id
                )
            )
        ).scalar_one_or_none()
        if set_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Annotation set not found",
            )

        run = await self.run_repo.create(
            annotation_set_id=annotation_set_id,
            created_by_id=user_id,
            requested_model_refs=model_refs,
        )

        # Commit before enqueueing so the worker can fetch the row.
        await self.db.commit()

        # Import here to avoid pulling Celery into request-serving startup.
        from echoroo.workers.evaluation_tasks import run_annotation_evaluation

        # Dispatch on the default queue — the ``worker-cpu`` container in
        # ``compose.dev.yaml`` listens on ``-Q default``. Using an explicit
        # non-existent queue (e.g. ``worker-cpu``) would leave the task
        # pending forever because no worker consumes from it.
        async_result = run_annotation_evaluation.delay(str(run.id))
        logger.info(
            "Dispatched evaluation task: run_id=%s task_id=%s",
            run.id,
            async_result.id,
        )

        return EvaluationRunResponse.model_validate(run)

    async def get_run(self, run_id: UUID) -> EvaluationRun:
        """Fetch an evaluation run or raise 404."""
        run = await self.run_repo.get_by_id(run_id)
        if run is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Evaluation run not found",
            )
        return run

    async def list_by_annotation_set(
        self,
        annotation_set_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[EvaluationRun], int]:
        """List evaluation runs for a set (newest first)."""
        return await self.run_repo.list_by_annotation_set(
            annotation_set_id, limit=limit, offset=offset,
        )

    async def delete_run(self, run_id: UUID) -> None:
        """Delete an evaluation run (cascades to results)."""
        run = await self.run_repo.get_by_id(run_id)
        if run is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Evaluation run not found",
            )
        await self.run_repo.delete(run_id)
        await self.db.commit()

    async def get_summary(self, run_id: UUID) -> EvaluationSummary:
        """Return the grouped-by-model dashboard summary for a run.

        For a run still in ``pending`` or ``running`` status the ``models``
        list may be empty or partial; the caller is expected to poll.

        Args:
            run_id: Evaluation run ID.

        Raises:
            HTTPException: 404 when the run does not exist.

        Returns:
            :class:`EvaluationSummary` containing a summary per model ref.
        """
        run = await self.get_run(run_id)
        results = await self.result_repo.list_by_run(run_id)

        # Preload taxa referenced by per-species rows.
        taxon_ids = {
            r.taxon_id for r in results if r.taxon_id is not None
        }
        taxa_map: dict[UUID, Taxon] = {}
        if taxon_ids:
            taxa_rows = (
                await self.db.execute(
                    select(Taxon).where(Taxon.id.in_(taxon_ids))
                )
            ).scalars().all()
            taxa_map = {t.id: t for t in taxa_rows}

        # Bucket results by model_ref.
        buckets: dict[tuple[str, str], dict[str, Any]] = {}
        for r in results:
            key = _model_ref_key(r.model_ref)
            bucket = buckets.setdefault(
                key,
                {"model_ref": r.model_ref, "overall": None, "species": []},
            )
            if r.taxon_id is None:
                bucket["overall"] = r
            else:
                bucket["species"].append(r)

        summaries: list[ModelEvaluationSummary] = []
        for bucket in buckets.values():
            overall_row = bucket["overall"]
            overall = (
                OverallMetric(
                    tp_precision=overall_row.tp_precision,
                    fp=overall_row.fp,
                    tp_recall=overall_row.tp_recall,
                    fn=overall_row.fn,
                    precision=overall_row.precision,
                    recall=overall_row.recall,
                    f1=overall_row.f1,
                    detections_total=overall_row.tp_precision + overall_row.fp,
                    ground_truths_total=overall_row.tp_recall + overall_row.fn,
                )
                if overall_row is not None
                else OverallMetric(
                    tp_precision=0,
                    fp=0,
                    tp_recall=0,
                    fn=0,
                    precision=0.0,
                    recall=0.0,
                    f1=0.0,
                    detections_total=0,
                    ground_truths_total=0,
                )
            )
            species_rows: list[SpeciesMetric] = []
            for sr in bucket["species"]:
                taxon = taxa_map.get(sr.taxon_id) if sr.taxon_id else None
                species_rows.append(
                    SpeciesMetric(
                        taxon_id=sr.taxon_id,
                        scientific_name=(
                            taxon.scientific_name if taxon else None
                        ),
                        common_name=None,
                        tp_precision=sr.tp_precision,
                        fp=sr.fp,
                        tp_recall=sr.tp_recall,
                        fn=sr.fn,
                        precision=sr.precision,
                        recall=sr.recall,
                        f1=sr.f1,
                        detections_total=sr.tp_precision + sr.fp,
                        ground_truths_total=sr.tp_recall + sr.fn,
                    )
                )
            species_rows.sort(key=lambda m: m.f1, reverse=True)

            summaries.append(
                ModelEvaluationSummary(
                    model_ref=bucket["model_ref"],
                    overall=overall,
                    species=species_rows,
                )
            )

        return EvaluationSummary(
            id=run.id,
            annotation_set_id=run.annotation_set_id,
            status=run.status.value,
            requested_model_refs=run.requested_model_refs,
            started_at=run.started_at,
            completed_at=run.completed_at,
            error_message=run.error_message,
            created_at=run.created_at,
            updated_at=run.updated_at,
            models=summaries,
        )


__all__ = ["EvaluationService"]

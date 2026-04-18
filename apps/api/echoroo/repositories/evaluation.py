"""Repositories for the cross-model evaluation feature (spec 003-annotation, A3).

Two thin persistence wrappers:

- :class:`EvaluationRunRepository` — CRUD + status transitions for
  :class:`EvaluationRun`.
- :class:`EvaluationResultRepository` — bulk insert + grouped retrieval of
  :class:`EvaluationResult` rows.

Both repos deliberately do not enforce cross-entity invariants; the service
and worker layers are responsible for orchestrating the full evaluation
lifecycle.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select

from echoroo.models.evaluation import (
    EvaluationResult,
    EvaluationRun,
    EvaluationRunStatus,
)
from echoroo.repositories.base import BaseRepository


class EvaluationRunRepository(BaseRepository[EvaluationRun]):
    """Repository for :class:`EvaluationRun` rows."""

    model = EvaluationRun

    async def create(
        self,
        *,
        annotation_set_id: UUID,
        created_by_id: UUID,
        requested_model_refs: list[dict[str, Any]],
    ) -> EvaluationRun:
        """Create a new evaluation run in ``pending`` status.

        Args:
            annotation_set_id: Owning AnnotationSet ID.
            created_by_id: Requesting user ID.
            requested_model_refs: Wire-format list of model references.

        Returns:
            The newly created ``EvaluationRun``.
        """
        run = EvaluationRun(
            annotation_set_id=annotation_set_id,
            created_by_id=created_by_id,
            requested_model_refs=requested_model_refs,
            status=EvaluationRunStatus.PENDING,
        )
        self.db.add(run)
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def get_by_id(self, run_id: UUID) -> EvaluationRun | None:
        """Fetch an evaluation run by primary key."""
        result = await self.db.execute(
            select(EvaluationRun).where(EvaluationRun.id == run_id)
        )
        return result.scalar_one_or_none()

    async def list_by_annotation_set(
        self,
        annotation_set_id: UUID,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[EvaluationRun], int]:
        """List evaluation runs for a set, newest first, with total count."""
        total_stmt = (
            select(func.count())
            .select_from(EvaluationRun)
            .where(EvaluationRun.annotation_set_id == annotation_set_id)
        )
        total = (await self.db.execute(total_stmt)).scalar_one()

        stmt = (
            select(EvaluationRun)
            .where(EvaluationRun.annotation_set_id == annotation_set_id)
            .order_by(EvaluationRun.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        items = list((await self.db.execute(stmt)).scalars().all())
        return items, int(total)

    async def mark_running(self, run_id: UUID) -> EvaluationRun | None:
        """Transition a run into ``running`` status; stamps ``started_at``.

        Args:
            run_id: Evaluation run ID.

        Returns:
            The updated run, or None if not found.
        """
        run = await self.get_by_id(run_id)
        if run is None:
            return None
        run.status = EvaluationRunStatus.RUNNING
        run.started_at = datetime.now(UTC)
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def mark_completed(self, run_id: UUID) -> EvaluationRun | None:
        """Transition a run into ``completed``; stamps ``completed_at``."""
        run = await self.get_by_id(run_id)
        if run is None:
            return None
        run.status = EvaluationRunStatus.COMPLETED
        run.completed_at = datetime.now(UTC)
        run.error_message = None
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def mark_failed(
        self, run_id: UUID, error_message: str,
    ) -> EvaluationRun | None:
        """Transition a run into ``failed`` with the given error text."""
        run = await self.get_by_id(run_id)
        if run is None:
            return None
        run.status = EvaluationRunStatus.FAILED
        run.completed_at = datetime.now(UTC)
        run.error_message = error_message
        await self.db.flush()
        await self.db.refresh(run)
        return run


class EvaluationResultRepository(BaseRepository[EvaluationResult]):
    """Repository for :class:`EvaluationResult` rows."""

    model = EvaluationResult

    async def bulk_insert(
        self,
        evaluation_run_id: UUID,
        rows: list[dict[str, Any]],
    ) -> list[EvaluationResult]:
        """Bulk-insert result rows for one evaluation run.

        Each row dict may contain the keys: ``model_ref`` (dict),
        ``taxon_id`` (UUID | None), ``tp_precision``, ``fp``, ``tp_recall``,
        ``fn``, ``precision``, ``recall``, ``f1``.

        Args:
            evaluation_run_id: Parent run.
            rows: List of attribute dicts.

        Returns:
            The created instances in input order.
        """
        instances = [
            EvaluationResult(
                evaluation_run_id=evaluation_run_id,
                model_ref=row["model_ref"],
                taxon_id=row.get("taxon_id"),
                tp_precision=int(row.get("tp_precision", 0)),
                fp=int(row.get("fp", 0)),
                tp_recall=int(row.get("tp_recall", 0)),
                fn=int(row.get("fn", 0)),
                precision=float(row.get("precision", 0.0)),
                recall=float(row.get("recall", 0.0)),
                f1=float(row.get("f1", 0.0)),
            )
            for row in rows
        ]
        self.db.add_all(instances)
        await self.db.flush()
        return instances

    async def list_by_run(
        self, evaluation_run_id: UUID,
    ) -> list[EvaluationResult]:
        """Return all result rows for a run, ordered by primary key.

        Callers typically re-group the rows by ``model_ref`` in Python
        because ordering on a JSONB column is awkward in SQL.
        """
        stmt = (
            select(EvaluationResult)
            .where(EvaluationResult.evaluation_run_id == evaluation_run_id)
            .order_by(EvaluationResult.id.asc())
        )
        return list((await self.db.execute(stmt)).scalars().all())


__all__ = [
    "EvaluationRunRepository",
    "EvaluationResultRepository",
]

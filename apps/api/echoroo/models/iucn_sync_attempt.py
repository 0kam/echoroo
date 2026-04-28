"""IUCN Red List sync attempt log (006-permissions-redesign, FR-036).

Each row captures one execution of the periodic IUCN sync worker
(`echoroo.tasks.iucn_sync.run_iucn_sync`, scheduled in Phase 11 Batch 2).
The worker pulls the current IUCN Red List snapshot, compares it against
existing :class:`echoroo.models.taxon_sensitivity.TaxonSensitivity` rows
whose ``source = 'iucn'``, and upserts the diff.

The ``loosened_species_count`` column is a sanity-check counter required by
the spec (data-model §3.15): if a single sync would loosen masking on more
than the threshold defined in ``system_settings`` (e.g. >50 species at
once), the worker aborts the run and records ``status='failure'`` with the
count, preventing accidental large-scale exposure of sensitive taxa.

The ``(status, started_at DESC)`` index supports the admin dashboard query
"show me the last successful sync" and the Celery beat heartbeat check.

Note: per data-model.md §3.15, this entity inherits :class:`UUIDMixin` only —
``created_at`` / ``updated_at`` are intentionally omitted. The lifecycle is
captured by the explicit ``started_at`` / ``finished_at`` columns instead.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from echoroo.models.base import Base, UUIDMixin


class IucnSyncAttempt(UUIDMixin, Base):
    """One run of the IUCN Red List sync worker (FR-036).

    See module docstring for the full FR mapping. The single
    ``ix_iucn_sync_attempts_status_started`` index defined in the baseline
    Alembic migration supports both the dashboard "latest successful sync"
    query and the heartbeat check that watches for stuck ``running`` rows.
    """

    __tablename__ = "iucn_sync_attempts"

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        doc="Wall-clock timestamp at which the worker entered the running state.",
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc=(
            "Wall-clock timestamp at which the worker entered a terminal "
            "state (success or failure). NULL while ``status = 'running'``."
        ),
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        doc=(
            "One of 'running', 'success', 'failure'. Stored as String "
            "(not enum) to keep the ops dashboard easy to extend without an "
            "ALTER TYPE migration."
        ),
    )
    error_detail: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        doc=(
            "Free-form error description recorded when ``status='failure'``. "
            "May contain stack-trace-like text; not exposed to non-superusers."
        ),
    )
    synced_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        doc=(
            "Total number of TaxonSensitivity rows upserted in this run. "
            "NULL while running."
        ),
    )
    loosened_species_count: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
        doc=(
            "Number of taxa whose sensitivity_h3_res would have *increased* "
            "(less masking) in this sync. The worker aborts and records "
            "status='failure' if this exceeds the configured threshold "
            "(spec §3.15 sanity check)."
        ),
    )

    __table_args__ = (
        Index(
            "ix_iucn_sync_attempts_status_started",
            "status",
            text("started_at DESC"),
        ),
    )

    def __repr__(self) -> str:
        """String representation of IucnSyncAttempt."""
        return (
            "<IucnSyncAttempt("
            f"id={self.id}, status={self.status}, "
            f"started_at={self.started_at}, finished_at={self.finished_at}"
            ")>"
        )


__all__ = ["IucnSyncAttempt"]

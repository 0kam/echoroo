"""History of taxon identity changes (WS-A v2 slice 5).

Append-only by convention — the API only ever reads it and no code path
updates or deletes rows — but not enforced at the database level (no
triggers / RLS).

A taxon's local ``taxa.id`` UUID is immutable, but the *external* identity it
carries is not: a Catalogue of Life XR re-resolution can move a taxon onto a
different usage key, flip its status from ``ACCEPTED`` to ``SYNONYM``, rewrite
the accepted name, or clear the identity entirely when a newer COL release no
longer matches the name. Those rewrites used to be invisible — the previous
value was simply overwritten.

This table records one row per changed identity field, written in the SAME
transaction as the ``taxa`` UPDATE that caused it, so a chunk commit either
banks both the new value and its history row or neither. It is deliberately
NOT routed through :class:`~echoroo.services.audit.AuditLogService`: the
platform audit log requires a fresh SERIALIZABLE session plus a global
advisory lock per row, which would serialize a 6,500-row batch resolution.

Vernacular (display-name) changes are NOT identity changes and are not
recorded here — they are re-derivable from the bundled/authority loaders.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from echoroo.models.base import Base, TimestampMixin, UUIDMixin

#: Identity-bearing ``taxa`` columns whose rewrites are journalled. Kept as a
#: plain tuple (not a DB enum) so adding a field is a code change, never an
#: ``ALTER TYPE`` on a live table — see ``IucnSyncAttempt.status`` for the same
#: precedent.
IDENTITY_HISTORY_FIELDS: tuple[str, ...] = (
    "col_xr_id",
    "col_xr_accepted_id",
    "col_xr_status",
    "accepted_scientific_name",
    "gbif_taxon_key",
    "authorship",
    "accepted_authorship",
    "col_xr_release",
)

#: Where the change came from.
IDENTITY_HISTORY_SOURCES: tuple[str, ...] = ("col_xr", "gbif", "admin", "migration")

#: Who caused it. ``system`` covers unattributed background work (a direct
#: service call with neither a request user nor a Celery task id).
IDENTITY_HISTORY_ACTOR_KINDS: tuple[str, ...] = ("user", "task", "system")


class TaxonIdentityHistory(UUIDMixin, TimestampMixin, Base):
    """One journalled change to one identity field of one taxon.

    Attributes:
        taxon_id: The taxon whose identity changed (RESTRICT: history outlives
            nothing — a taxon carrying history cannot be hard-deleted silently).
        field: Which ``taxa`` column changed (see ``IDENTITY_HISTORY_FIELDS``).
        old_value: Previous value rendered as text, NULL when the field was
            unset before.
        new_value: New value rendered as text, NULL when the field was cleared.
        source: Resolver family that produced the change (``col_xr``/``gbif``/
            ``admin``/``migration``).
        resolver: Concrete producer (e.g. ``resolve_col_xr_batch``).
        release: External release the change was pinned to (COL release alias).
        actor_kind: ``user`` / ``task`` / ``system``.
        actor_user_id: Request user, when a human triggered the change.
        actor_task_id: Celery task id, when a background task did.
        changed_at: When the change was applied.
        detail: Free-form JSON context (match type, confidence, decision, ...).
    """

    __tablename__ = "taxon_identity_history"

    taxon_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        # RESTRICT, not CASCADE: the journal is the reason we can explain a
        # historical identity, so deleting the taxon must be a deliberate act
        # that deals with its history first.
        ForeignKey("taxa.id", ondelete="RESTRICT"),
        nullable=False,
        doc="Taxon whose identity changed",
    )
    field: Mapped[str] = mapped_column(
        String(64), nullable=False, doc="Identity column that changed",
    )
    old_value: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="Previous value as text (NULL when unset)",
    )
    new_value: Mapped[str | None] = mapped_column(
        Text, nullable=True, doc="New value as text (NULL when cleared)",
    )
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, doc="col_xr / gbif / admin / migration",
    )
    resolver: Mapped[str | None] = mapped_column(
        String(128), nullable=True, doc="Concrete producer of the change",
    )
    release: Mapped[str | None] = mapped_column(
        String(32), nullable=True, doc="External release pinned at change time",
    )
    actor_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, doc="user / task / system",
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        # SET NULL: deleting a user must never delete or block the journal.
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        doc="Request user that caused the change, when any",
    )
    actor_task_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, doc="Celery task id that caused the change",
    )
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, doc="When the change was applied",
    )
    detail: Mapped[dict[str, object] | None] = mapped_column(
        JSONB, nullable=True, doc="Free-form context for the change",
    )

    __table_args__ = (
        # "What happened to this taxon, newest first" — the operator query.
        Index(
            "ix_taxon_identity_history_taxon_changed_at",
            "taxon_id",
            text("changed_at DESC"),
        ),
        # "Every taxon whose status flipped in the last release", newest first.
        Index(
            "ix_taxon_identity_history_field_changed_at",
            "field",
            text("changed_at DESC"),
        ),
        # "What did this batch run change?" — sparse by construction, so the
        # index is partial.
        Index(
            "ix_taxon_identity_history_actor_task_id",
            "actor_task_id",
            postgresql_where=text("actor_task_id IS NOT NULL"),
        ),
        # A no-op rewrite is not history: an identical re-resolution must
        # write nothing at all, and this makes that a database invariant
        # rather than a convention the writer is trusted to keep.
        CheckConstraint(
            "old_value IS DISTINCT FROM new_value",
            name="ck_taxon_identity_history_actual_change",
        ),
        # Attribution is mandatory in the shape the actor_kind promises.
        CheckConstraint(
            "(actor_kind = 'user' AND actor_user_id IS NOT NULL"
            " AND actor_task_id IS NULL)"
            " OR (actor_kind = 'task' AND actor_task_id IS NOT NULL"
            " AND actor_user_id IS NULL)"
            " OR (actor_kind = 'system' AND actor_user_id IS NULL"
            " AND actor_task_id IS NULL)",
            name="ck_taxon_identity_history_actor_present",
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<TaxonIdentityHistory(taxon_id={self.taxon_id}, field={self.field}, "
            f"{self.old_value!r}->{self.new_value!r})>"
        )

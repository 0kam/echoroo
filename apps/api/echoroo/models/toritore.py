"""ToriTore (とりトレ) proficiency models (preview-only integration).

ToriTore is NIES's bird-call learning app. Monitors export their test
results as JSON and upload them to Echoroo so the annotation workflow can:

* gate participation on the latest test ``total_score`` (Part A), and
* snapshot the annotator's per-species correct rate onto an annotation
  row at creation time (Part B).

Two tables back the upload:

* :class:`ToriToreTestResult` — one row per test (a JSON's
  ``project.test_history[]`` expands to N rows), owned by the uploading
  Echoroo :class:`~echoroo.models.user.User`. The ToriTore-side user /
  project identifiers are stored for reference only — they are NOT
  Echoroo principals.
* :class:`ToriToreSpeciesScore` — one row per species per test, matched
  to a :class:`~echoroo.models.taxon.Taxon` by GBIF key (best-effort).

This is an internal research-preview feature and is intentionally
isolated from the (separately-removed) annotation-project subsystem.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from echoroo.models.base import Base, UUIDMixin

if TYPE_CHECKING:
    from echoroo.models.taxon import Taxon
    from echoroo.models.user import User


class ToriToreTestResult(UUIDMixin, Base):
    """One ToriTore test result owned by an Echoroo uploader.

    A single uploaded JSON expands ``project.test_history[]`` into one row
    per test. Idempotent re-upload is keyed on
    ``(user_id, source_timestamp, test_number)``.

    Attributes:
        user_id: Echoroo uploader (FK → users.id, CASCADE).
        toritore_user_id / toritore_user_name: ToriTore-side identity
            (reference only; never an Echoroo principal).
        toritore_project_id / toritore_project_name: ToriTore-side project.
        source_timestamp: Parsed from the JSON top-level ``timestamp``
            (``YYYYMMDDHHMMSS±H:MM``). NULL when the timestamp could not be
            parsed; ordering falls back to ``uploaded_at``.
        test_number: ToriTore test ordinal within the upload.
        test_timestamp: ToriTore-side per-test timestamp string (opaque).
        total_score: Overall score for this test in [0, 1].
        uploaded_at: Server-side ingest time (fallback ordering key).
        raw_json: Original test payload for audit / reprocessing.
    """

    __tablename__ = "toritore_test_results"

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        doc="Echoroo uploader user ID",
    )
    toritore_user_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, doc="ToriTore-side user id (reference only)",
    )
    toritore_user_name: Mapped[str | None] = mapped_column(
        String(200), nullable=True, doc="ToriTore-side user name (reference only)",
    )
    toritore_project_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, doc="ToriTore-side project id (reference only)",
    )
    toritore_project_name: Mapped[str | None] = mapped_column(
        String(200), nullable=True, doc="ToriTore-side project name (reference only)",
    )
    source_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        doc="Parsed top-level JSON timestamp; NULL when unparseable",
    )
    test_number: Mapped[int] = mapped_column(
        Integer, nullable=False, doc="ToriTore test ordinal within the upload",
    )
    test_timestamp: Mapped[str | None] = mapped_column(
        String(100), nullable=True, doc="ToriTore per-test timestamp string (opaque)",
    )
    total_score: Mapped[float] = mapped_column(
        Float, nullable=False, doc="Overall test score in [0, 1]",
    )
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        doc="Server-side ingest time (fallback ordering key)",
    )
    raw_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True, doc="Original test payload for audit / reprocessing",
    )

    # Relationships
    user: Mapped[User] = relationship("User", lazy="raise")
    species_scores: Mapped[list[ToriToreSpeciesScore]] = relationship(
        "ToriToreSpeciesScore",
        back_populates="test_result",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "source_timestamp",
            "test_number",
            name="uq_toritore_test_results_user_source_test",
        ),
        Index("ix_toritore_test_results_user_id", "user_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<ToriToreTestResult(id={self.id}, user_id={self.user_id}, "
            f"test_number={self.test_number}, total_score={self.total_score})>"
        )


class ToriToreSpeciesScore(UUIDMixin, Base):
    """One species result inside a ToriTore test.

    Attributes:
        test_result_id: Owning test (FK → toritore_test_results.id, CASCADE).
        gbif_taxon_key: GBIF usageKey parsed from the JSON ``species_id``
            numeric string. NULL when the id was not int-parseable.
        species_name: ToriTore-supplied scientific name (reference / fallback).
        is_correct: 1 when the monitor answered correctly, else 0.
        taxon_id: Best-effort resolution to a local Taxon by GBIF key
            (nullable; snapshot matching is by ``gbif_taxon_key`` regardless).
    """

    __tablename__ = "toritore_species_scores"

    test_result_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("toritore_test_results.id", ondelete="CASCADE"),
        nullable=False,
        doc="Owning ToriToreTestResult ID",
    )
    gbif_taxon_key: Mapped[int | None] = mapped_column(
        Integer, nullable=True, doc="GBIF usageKey (NULL when unparseable)",
    )
    species_name: Mapped[str | None] = mapped_column(
        String(300), nullable=True, doc="ToriTore-supplied scientific name",
    )
    is_correct: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, doc="1 = correct, 0 = incorrect",
    )
    taxon_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("taxa.id", ondelete="SET NULL"),
        nullable=True,
        doc="Best-effort resolved local Taxon ID",
    )

    # Relationships
    test_result: Mapped[ToriToreTestResult] = relationship(
        "ToriToreTestResult",
        back_populates="species_scores",
        lazy="raise",
    )
    taxon: Mapped[Taxon | None] = relationship("Taxon", lazy="raise")

    __table_args__ = (
        Index("ix_toritore_species_scores_test_result_id", "test_result_id"),
        Index("ix_toritore_species_scores_gbif_taxon_key", "gbif_taxon_key"),
    )

    def __repr__(self) -> str:
        return (
            f"<ToriToreSpeciesScore(id={self.id}, "
            f"test_result_id={self.test_result_id}, "
            f"gbif_taxon_key={self.gbif_taxon_key}, is_correct={self.is_correct})>"
        )

"""Datetime parsing configuration per dataset."""

from __future__ import annotations

from enum import Enum
import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
import sqlalchemy.orm as orm

from echoroo.models.base import Base

if TYPE_CHECKING:
    from echoroo.models.dataset import Dataset

__all__ = ["DatetimePatternType", "DatasetDatetimePattern"]


class DatetimePatternType(str, Enum):
    """Supported datetime parsing strategies."""

    STRPTIME = "strptime"
    REGEX = "regex"


class DatasetDatetimePattern(Base):
    """Persisted datetime parsing configuration for a dataset."""

    __tablename__ = "datetime_pattern"
    __table_args__ = (
        sa.UniqueConstraint(
            "dataset_id",
            name="uq_datetime_pattern_dataset_id",
        ),
    )

    id: orm.Mapped[int] = orm.mapped_column(primary_key=True, init=False)
    """Surrogate identifier."""

    dataset_id: orm.Mapped[int] = orm.mapped_column(
        sa.ForeignKey("dataset.id", ondelete="CASCADE"),
        nullable=False,
    )
    """Dataset the pattern applies to."""

    pattern: orm.Mapped[str] = orm.mapped_column(
        sa.String(length=255),
        nullable=False,
    )
    """Pattern text, semantics depend on `pattern_type`."""

    pattern_type: orm.Mapped[DatetimePatternType] = orm.mapped_column(
        sa.Enum(DatetimePatternType, name="datetime_pattern_type"),
        nullable=False,
        default=DatetimePatternType.STRPTIME,
        server_default=DatetimePatternType.STRPTIME.value,
    )
    """Parsing strategy type."""

    sample_filename: orm.Mapped[str | None] = orm.mapped_column(
        sa.String(length=255),
        nullable=True,
        default=None,
    )
    """Representative filename used for validation feedback."""

    sample_result: orm.Mapped[datetime.datetime | None] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    """Result obtained when parsing `sample_filename`."""

    dataset: orm.Mapped["Dataset"] = orm.relationship(
        "Dataset",
        back_populates="datetime_pattern",
        repr=False,
        init=False,
    )
    """Parent dataset relationship."""

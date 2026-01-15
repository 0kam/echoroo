"""Recorder model.

Represents hardware devices used to capture audio for datasets.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy import func, select, inspect

from echoroo.models.base import Base

if TYPE_CHECKING:
    from echoroo.models.dataset import Dataset

__all__ = ["Recorder"]


class Recorder(Base):
    """Recorder model for the recorder lookup table."""

    __tablename__ = "recorder"

    recorder_id: orm.Mapped[str] = orm.mapped_column(
        sa.String(length=255),
        primary_key=True,
    )
    """Natural identifier for the recorder model (e.g. SM4)."""

    recorder_name: orm.Mapped[str] = orm.mapped_column(
        sa.String(length=255),
        nullable=False,
    )
    """Marketing/product name of the recorder."""

    manufacturer: orm.Mapped[str | None] = orm.mapped_column(
        sa.String(length=255),
        nullable=True,
        default=None,
    )
    """Manufacturer of the recorder."""

    version: orm.Mapped[str | None] = orm.mapped_column(
        sa.String(length=255),
        nullable=True,
        default=None,
    )
    """Optional firmware or hardware version."""

    # Relationships -----------------------------------------------------------------
    datasets: orm.Mapped[list["Dataset"]] = orm.relationship(
        "Dataset",
        back_populates="primary_recorder",
        default_factory=list,
        init=False,
        repr=False,
    )
    """Datasets whose primary recorder references this entry."""


from echoroo.models.dataset import Dataset

inspect(Recorder).add_property(
    "usage_count",
    orm.column_property(
        select(func.count(Dataset.id))
        .where(Dataset.primary_recorder_id == Recorder.recorder_id)
        .correlate_except(Dataset)
        .scalar_subquery(),
        deferred=False,
    ),
)

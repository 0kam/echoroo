"""License model.

Defines usage licenses that datasets can reference.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import sqlalchemy as sa
import sqlalchemy.orm as orm
from sqlalchemy import func, select, inspect

from echoroo.models.base import Base

if TYPE_CHECKING:
    from echoroo.models.dataset import Dataset

__all__ = ["License"]


class License(Base):
    """License lookup table."""

    __tablename__ = "license"

    license_id: orm.Mapped[str] = orm.mapped_column(
        sa.String(length=255),
        primary_key=True,
    )
    """Identifier for the license (e.g. CCBY4)."""

    license_name: orm.Mapped[str] = orm.mapped_column(
        sa.String(length=255),
        nullable=False,
    )
    """Human readable license name."""

    license_link: orm.Mapped[str] = orm.mapped_column(
        sa.String(length=255),
        nullable=False,
    )
    """Link to the full license text."""

    datasets: orm.Mapped[list["Dataset"]] = orm.relationship(
        "Dataset",
        back_populates="license",
        default_factory=list,
        repr=False,
        init=False,
    )
    """Datasets referencing this license."""


from echoroo.models.dataset import Dataset

inspect(License).add_property(
    "usage_count",
    orm.column_property(
        select(func.count(Dataset.id))
        .where(Dataset.license_id == License.license_id)
        .correlate_except(Dataset)
        .scalar_subquery(),
        deferred=False,
    ),
)

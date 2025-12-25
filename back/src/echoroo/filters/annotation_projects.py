"""Filters for Annotation Projects."""

from uuid import UUID

from sqlalchemy import Select

from echoroo import models
from echoroo.filters import base

__all__ = [
    "SearchFilter",
    "AnnotationProjectFilter",
]


SearchFilter = base.search_filter(
    [
        models.AnnotationProject.name,
        models.AnnotationProject.description,
    ]
)

CreatedOnFilter = base.date_filter(models.AnnotationProject.created_on)

DatasetIdFilter = base.integer_filter(models.AnnotationProject.dataset_id)


class DatasetFilter(base.Filter):
    """Filter annotation projects by the dataset they belong to."""

    eq: UUID | None = None

    def filter(self, query: Select) -> Select:
        """Filter the query."""
        if not self.eq:
            return query

        return query.join(
            models.Dataset,
            models.AnnotationProject.dataset_id == models.Dataset.id,
        ).where(models.Dataset.uuid == self.eq)


AnnotationProjectFilter = base.combine(
    SearchFilter,
    created_on=CreatedOnFilter,
    dataset_id=DatasetIdFilter,
    dataset=DatasetFilter,
)

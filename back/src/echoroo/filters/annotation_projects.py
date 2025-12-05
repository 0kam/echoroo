"""Filters for Annotation Projects."""

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

DatasetUuidFilter = base.uuid_filter(
    models.AnnotationProject.dataset_id,
)

AnnotationProjectFilter = base.combine(
    SearchFilter,
    created_on=CreatedOnFilter,
    dataset_id=DatasetIdFilter,
    dataset=DatasetUuidFilter,
)

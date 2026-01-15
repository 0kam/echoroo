"""Schema validation tests for project-centric metadata."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from echoroo import schemas
from echoroo.models import VisibilityLevel


def test_dataset_create_requires_project(tmp_path):
    with pytest.raises(ValidationError) as exc:
        schemas.DatasetCreate(
            name="sample",
            audio_dir=str(tmp_path),
        )
    assert "project_id" in str(exc.value.errors())


def test_dataset_create_accepts_project(tmp_path):
    payload = schemas.DatasetCreate(
        name="sample",
        audio_dir=str(tmp_path),
        project_id="proj-123",
        visibility=VisibilityLevel.PUBLIC,
    )
    assert payload.project_id == "proj-123"
    assert payload.visibility == VisibilityLevel.PUBLIC


def test_annotation_project_create_requires_dataset():
    with pytest.raises(ValidationError) as exc:
        schemas.AnnotationProjectCreate(
            name="proj",
            description="desc",
        )
    assert "dataset_id" in str(exc.value.errors())


def test_annotation_project_create_defaults_visibility_to_restricted():
    payload = schemas.AnnotationProjectCreate(
        name="proj",
        description="desc",
        dataset_id=1,
    )
    assert payload.visibility == VisibilityLevel.RESTRICTED

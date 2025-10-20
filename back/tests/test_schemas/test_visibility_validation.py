"""Validation tests for visibility/owner_group combinations."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from whombat import schemas
from whombat.models import VisibilityLevel


def test_dataset_create_restricted_requires_group(tmp_path):
    with pytest.raises(ValidationError) as exc:
        schemas.DatasetCreate(
            name="sample",
            audio_dir=str(tmp_path),
            visibility=VisibilityLevel.RESTRICTED,
        )
    assert "Restricted visibility requires owner_group_id" in str(exc.value)


def test_dataset_create_disallows_group_for_non_restricted(tmp_path):
    with pytest.raises(ValidationError) as exc:
        schemas.DatasetCreate(
            name="sample",
            audio_dir=str(tmp_path),
            visibility=VisibilityLevel.PRIVATE,
            owner_group_id=1,
        )
    assert "only be set when visibility is 'restricted'" in str(exc.value)


def test_dataset_update_restricted_requires_group():
    with pytest.raises(ValidationError) as exc:
        schemas.DatasetUpdate(
            visibility=VisibilityLevel.RESTRICTED,
        )
    assert "requires owner_group_id" in str(exc.value)


def test_dataset_update_disallows_group_for_non_restricted():
    with pytest.raises(ValidationError) as exc:
        schemas.DatasetUpdate(
            visibility=VisibilityLevel.PUBLIC,
            owner_group_id=1,
        )
    assert "only be set when visibility is 'restricted'" in str(exc.value)


def test_annotation_project_create_restricted_requires_group():
    with pytest.raises(ValidationError) as exc:
        schemas.AnnotationProjectCreate(
            name="proj",
            description="desc",
            visibility=VisibilityLevel.RESTRICTED,
        )
    assert "Restricted visibility requires owner_group_id" in str(exc.value)


def test_annotation_project_create_disallows_group_for_non_restricted():
    with pytest.raises(ValidationError) as exc:
        schemas.AnnotationProjectCreate(
            name="proj",
            description="desc",
            visibility=VisibilityLevel.PUBLIC,
            owner_group_id=1,
        )
    assert "only be set when visibility is 'restricted'" in str(exc.value)


def test_annotation_project_update_restricted_requires_group():
    with pytest.raises(ValidationError) as exc:
        schemas.AnnotationProjectUpdate(
            visibility=VisibilityLevel.RESTRICTED,
        )
    assert "requires owner_group_id" in str(exc.value)


def test_annotation_project_update_disallows_group_for_non_restricted():
    with pytest.raises(ValidationError) as exc:
        schemas.AnnotationProjectUpdate(
            visibility=VisibilityLevel.PRIVATE,
            owner_group_id=42,
        )
    assert "only be set when visibility is 'restricted'" in str(exc.value)

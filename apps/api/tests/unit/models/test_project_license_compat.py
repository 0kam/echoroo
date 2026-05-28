"""Project license read compatibility facade tests."""

from __future__ import annotations

from uuid import uuid4

from echoroo.models.enums import ProjectVisibility
from echoroo.models.license import License
from echoroo.models.project import Project


def test_project_license_returns_attached_license_short_name() -> None:
    license_record = License(
        id="custom-arbitrary",
        name="Custom Arbitrary",
        short_name="CUSTOM-ARBITRARY",
    )
    project = Project(
        name="Compat",
        visibility=ProjectVisibility.PUBLIC,
        license_id=license_record.id,
        license_record=license_record,
        owner_id=uuid4(),
    )

    assert project.license == "CUSTOM-ARBITRARY"


def test_project_license_returns_none_when_license_id_is_none() -> None:
    project = Project(
        name="Compat",
        visibility=ProjectVisibility.PUBLIC,
        license_id=None,
        owner_id=uuid4(),
    )

    assert project.license is None


def test_project_license_returns_none_when_license_record_is_not_attached() -> None:
    project = Project(
        name="Compat",
        visibility=ProjectVisibility.PUBLIC,
        license_id="cc-by",
        owner_id=uuid4(),
    )

    assert project.license is None

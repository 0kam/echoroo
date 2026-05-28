"""Project license compatibility facade tests."""

from __future__ import annotations

from uuid import uuid4

import pytest

from echoroo.models.enums import ProjectLicense, ProjectVisibility
from echoroo.models.project import Project


def test_project_license_setter_accepts_legacy_enum_and_string() -> None:
    project = Project(
        name="Compat",
        visibility=ProjectVisibility.PUBLIC,
        license=ProjectLicense.CC_BY,
        owner_id=uuid4(),
    )

    assert project.license_id == "cc-by"
    assert project.license == "CC-BY"

    project.license = "CC-BY-NC"

    assert project.license_id == "cc-by-nc"
    assert project.license == "CC-BY-NC"


def test_project_license_setter_accepts_none_and_rejects_unknown_string() -> None:
    project = Project(
        name="Compat",
        visibility=ProjectVisibility.PUBLIC,
        license="CC0",
        owner_id=uuid4(),
    )

    project.license = None

    assert project.license_id is None
    assert project.license is None

    with pytest.raises(ValueError):
        project.license = "MIT"

"""Contract tests for ``DELETE /web-api/v1/admin/licenses/{license_id}`` (spec/012).

Locks the 409 envelope shape from
``specs/012-license-master-unification/contracts/admin-licenses-delete.yaml``
on the BFF (``/web-api/v1/admin/licenses/{id}``) surface. Cases mirror the
rev.2 tasks.md T037..T041 spec sheet:

* 204 — no dependents.
* 409 — project-only dependency (project_count>0, dataset_count=0).
* 409 — dataset-only dependency (project_count=0, dataset_count>0).
* 409 — both dependencies.
* 404 — unknown license id.

W2-3 PR-11 unmounted the Bearer (``/api/v1/admin/licenses/{id}``) surface;
the four Bearer-variant cases were dropped and only the cookie + CSRF BFF
variants remain (the BFF delegates to the same legacy handler, so the wire
shape is identical). The race-recovery branch is covered at the service
layer in ``tests/unit/services/test_license_service.py`` to keep the contract
suite focused on the wire shape.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.auth import issue_access_token
from echoroo.core.settings import get_settings
from echoroo.middleware.csrf import issue_csrf_token
from echoroo.models.dataset import Dataset
from echoroo.models.enums import (
    ProjectStatus,
    ProjectVisibility,
)
from echoroo.models.license import License
from echoroo.models.project import Project
from echoroo.models.recorder import Recorder
from echoroo.models.site import Site
from echoroo.models.user import User

BFF_PATH = "/web-api/v1/admin/licenses"

# The contract YAML at ``contracts/admin-licenses-delete.yaml`` is the single
# source of truth for the 409 / 404 wire body; the assertions below reference
# its fields verbatim.
EXPECTED_409_FIELDS = {"error_code", "message", "short_name", "project_count", "dataset_count"}


_DEFAULT_RESTRICTED_CONFIG: dict[str, object] = {
    "allow_media_playback": False,
    "allow_detection_view": False,
    "mask_species_in_detection": False,
    "allow_download": False,
    "allow_export": False,
    "allow_voting_and_comments": False,
    "public_location_precision_h3_res": 3,
    "allow_precise_location_to_viewer": False,
}


# ---------------------------------------------------------------------------
# Fixtures — superuser actor + license under test
# ---------------------------------------------------------------------------


@pytest.fixture
async def t044_superuser(db_session: AsyncSession) -> User:
    """User row + active ``superusers`` allow-list entry.

    spec/006 (Permissions redesign) stripped ``users.is_superuser``; the
    new SOT is the ``superusers`` table. The auth middleware stamps
    ``user.is_superuser = True`` when an active row is found, so we
    seed BOTH the user and the allow-list row here.
    """
    user = User(
        email="t044-superuser@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T044 Superuser",
        security_stamp="t044" + "s" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    await db_session.execute(
        sa.text(
            """
            INSERT INTO superusers (id, user_id, added_by_id, added_at)
            VALUES (:id, :uid, :uid, NOW())
            """
        ),
        {"id": uuid4(), "uid": user.id},
    )
    await db_session.commit()
    return user


@pytest.fixture
async def t044_superuser_session_auth(
    db_session: AsyncSession,
    t044_superuser: User,
) -> dict[str, dict[str, str]]:
    """Cookie session + CSRF header for BFF DELETE requests."""
    settings = get_settings()
    session_id = uuid4()
    await db_session.execute(
        sa.text(
            "INSERT INTO token_families (family_id, user_id, created_at) "
            "VALUES (:family_id, :user_id, NOW())"
        ),
        {"family_id": session_id, "user_id": t044_superuser.id},
    )
    await db_session.commit()

    access_token = issue_access_token(
        user_id=t044_superuser.id,
        security_stamp=t044_superuser.security_stamp,
    )
    csrf_token = issue_csrf_token(
        str(session_id),
        session_secret=settings.web_session_secret,
    )
    return {
        "headers": {
            "Authorization": f"Bearer {access_token}",
            "X-CSRF-Token": csrf_token,
        },
        "cookies": {settings.web_session_cookie_name: str(session_id)},
    }


async def _make_project(
    db_session: AsyncSession,
    *,
    owner: User,
    license_id: str,
    name: str = "T044 Project",
) -> Project:
    """Insert a project that references the given license.

    Owner identity lives on :class:`Project.owner_id` — there is NO
    ``ProjectMemberRole.OWNER`` (the enum is VIEWER / MEMBER / ADMIN).
    For dependency-count purposes we only need the row to exist with the
    right ``license_id``; downstream gates that care about membership
    are out of scope for this contract suite.
    """
    project = Project(
        name=name,
        description="License-dependent project",
        visibility=ProjectVisibility.RESTRICTED,
        license_id=license_id,
        owner_id=owner.id,
        status=ProjectStatus.ACTIVE,
        restricted_config=dict(_DEFAULT_RESTRICTED_CONFIG),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


async def _make_dataset(
    db_session: AsyncSession,
    *,
    project: Project,
    owner: User,
    license_id: str,
    name: str = "T044 Dataset",
) -> Dataset:
    """Insert a dataset with the minimal FK scaffolding spec/012 needs.

    The dataset row only needs to *exist* with the right ``license_id``
    so :meth:`LicenseRepository.count_dependents` sees it. Recorder is
    nullable so we skip it; site + project are FK-required.
    """
    # Recorder.id is a non-autogen string PK; use a deterministic suffix
    # per call to avoid collisions across cases.
    recorder_id = f"t044-rec-{uuid4().hex[:8]}"
    recorder = Recorder(
        id=recorder_id,
        manufacturer="ACME",
        recorder_name="TestRec-1",
    )
    db_session.add(recorder)
    await db_session.commit()

    site = Site(
        project_id=project.id,
        name=f"{name}-{uuid4().hex[:8]}",
        h3_index_member="852a1072fffffff",
        h3_index_member_resolution=5,
    )
    db_session.add(site)
    await db_session.commit()
    await db_session.refresh(site)

    dataset = Dataset(
        project_id=project.id,
        site_id=site.id,
        recorder_id=recorder_id,
        license_id=license_id,
        name=name,
        description="License-dependent dataset",
        created_by_id=owner.id,
    )
    db_session.add(dataset)
    await db_session.commit()
    await db_session.refresh(dataset)
    return dataset


# ---------------------------------------------------------------------------
# 204 — no dependents (BFF surface)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDeleteLicenseSucceedsWhenNoDependents:
    """T037 — 204 No Content when no projects/datasets reference the license."""

    async def test_bff_surface_returns_204(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t044_superuser_session_auth: dict[str, dict[str, str]],
    ) -> None:
        # Seed a fresh standalone row for the BFF delete. Tests run in their
        # own db_session transaction so the row needs an explicit insert here.
        await db_session.execute(
            sa.text(
                "INSERT INTO licenses (id, name, short_name, url, description, "
                "created_at, updated_at) VALUES (:id, :n, :sn, NULL, NULL, "
                "NOW(), NOW()) ON CONFLICT DO NOTHING"
            ),
            {"id": "t044-bff-204", "n": "T044 BFF 204", "sn": "T044-BFF-204"},
        )
        await db_session.commit()

        response = await client.delete(
            f"{BFF_PATH}/t044-bff-204",
            **t044_superuser_session_auth,
        )
        assert response.status_code == 204, response.text


# ---------------------------------------------------------------------------
# 409 — license_in_use envelope (BFF surface, three dependency permutations)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDeleteLicenseRefuses409:
    """T038 + T039 + T040 — 409 envelope on the BFF surface."""

    async def test_project_only_dependency_bff(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t044_superuser: User,
        t044_superuser_session_auth: dict[str, dict[str, str]],
    ) -> None:
        # Only a project references the license-under-test, so only the
        # project count is non-zero.
        lic = License(
            id="t044-project-only",
            name="T044 Project-Only",
            short_name="T044-PROJECT-ONLY",
        )
        db_session.add(lic)
        await db_session.commit()
        await _make_project(
            db_session,
            owner=t044_superuser,
            license_id=lic.id,
            name="T044 Project-Only Project",
        )

        response = await client.delete(
            f"{BFF_PATH}/{lic.id}", **t044_superuser_session_auth
        )
        assert response.status_code == 409, response.text
        body = response.json()
        assert set(body.keys()) == EXPECTED_409_FIELDS, body
        assert body["error_code"] == "license_in_use"
        assert body["short_name"] == "T044-PROJECT-ONLY"
        assert body["project_count"] == 1
        assert body["dataset_count"] == 0

    async def test_dataset_only_dependency_bff(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t044_superuser: User,
        t044_superuser_session_auth: dict[str, dict[str, str]],
    ) -> None:
        # Project uses a different license; dataset references the
        # license-under-test so only the dataset count is non-zero.
        scaffold_license = License(
            id="t044-ds-scaffold",
            name="T044 DS Scaffold",
            short_name="T044-DS-SCAFFOLD",
        )
        target_license = License(
            id="t044-dataset-only",
            name="T044 Dataset-Only",
            short_name="T044-DATASET-ONLY",
        )
        db_session.add_all([scaffold_license, target_license])
        await db_session.commit()

        project = await _make_project(
            db_session,
            owner=t044_superuser,
            license_id=scaffold_license.id,
            name="T044 Scaffold Project",
        )
        await _make_dataset(
            db_session,
            project=project,
            owner=t044_superuser,
            license_id=target_license.id,
            name="T044 Dataset-Only Dataset",
        )

        response = await client.delete(
            f"{BFF_PATH}/{target_license.id}", **t044_superuser_session_auth
        )
        assert response.status_code == 409, response.text
        body = response.json()
        assert set(body.keys()) == EXPECTED_409_FIELDS, body
        assert body["error_code"] == "license_in_use"
        assert body["short_name"] == "T044-DATASET-ONLY"
        assert body["project_count"] == 0
        assert body["dataset_count"] == 1

    async def test_both_dependencies_bff(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t044_superuser: User,
        t044_superuser_session_auth: dict[str, dict[str, str]],
    ) -> None:
        """Both project + dataset dependencies on the BFF surface."""
        lic = License(
            id="t044-both-bff",
            name="T044 Both BFF",
            short_name="T044-BOTH-BFF",
        )
        db_session.add(lic)
        await db_session.commit()

        project = await _make_project(
            db_session,
            owner=t044_superuser,
            license_id=lic.id,
            name="T044 Both BFF Project",
        )
        await _make_dataset(
            db_session,
            project=project,
            owner=t044_superuser,
            license_id=lic.id,
            name="T044 Both BFF Dataset",
        )

        response = await client.delete(
            f"{BFF_PATH}/{lic.id}", **t044_superuser_session_auth
        )
        assert response.status_code == 409, response.text
        body = response.json()
        assert body["error_code"] == "license_in_use"
        assert body["short_name"] == "T044-BOTH-BFF"
        assert body["project_count"] == 1
        assert body["dataset_count"] == 1


# ---------------------------------------------------------------------------
# 404 — unknown license id (BFF surface)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDeleteLicense404:
    """T041 — 404 on the BFF surface when the license id does not exist."""

    async def test_unknown_id_bff_returns_404(
        self,
        client: AsyncClient,
        t044_superuser_session_auth: dict[str, dict[str, str]],
    ) -> None:
        response = await client.delete(
            f"{BFF_PATH}/does-not-exist", **t044_superuser_session_auth
        )
        assert response.status_code == 404, response.text

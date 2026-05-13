"""Smoke coverage for spec/009 PR A project read BFF paths."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.settings import get_settings
from echoroo.models.dataset import Dataset
from echoroo.models.enums import (
    DatasetStatus,
    DatasetVisibility,
    DatetimeParseStatus,
    ProjectLicense,
    ProjectStatus,
    ProjectVisibility,
)
from echoroo.models.project import Project
from echoroo.models.recording import Recording
from echoroo.models.site import Site
from tests.integration.api.web_v1._helpers import assert_api_key_cross_rejected

_RESTRICTED_CONFIG: dict[str, Any] = {
    "allow_media_playback": True,
    "allow_detection_view": True,
    "mask_species_in_detection": False,
    "allow_download": False,
    "allow_export": False,
    "allow_voting_and_comments": False,
    "public_location_precision_h3_res": 5,
    "allow_precise_location_to_viewer": False,
}


async def _create_user(
    db: AsyncSession,
    *,
    email: str = "test@echoroo.app",
    password: str = "correct horse battery staple",
) -> Any:
    from echoroo.core.security import hash_password
    from echoroo.models.user import User

    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password(password),
        display_name="Test User",
        security_stamp="s" * 64,
        two_factor_enabled=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _seed_refresh_token(db: AsyncSession, user: Any) -> str:
    from echoroo.api.web_v1.auth import _issue_web_refresh_token

    token, record = _issue_web_refresh_token(
        user_id=user.id,
        security_stamp=user.security_stamp,
    )
    await db.execute(
        sa.text(
            "INSERT INTO token_families (family_id, user_id, created_at) "
            "VALUES (:family_id, :user_id, :created_at)"
        ),
        {
            "family_id": UUID(record.family_id),
            "user_id": record.user_id,
            "created_at": record.issued_at,
        },
    )
    await db.execute(
        sa.text(
            "INSERT INTO refresh_tokens "
            "(jti, user_id, family_id, issued_at, expires_at) "
            "VALUES (:jti, :user_id, :family_id, :issued_at, :expires_at)"
        ),
        {
            "jti": UUID(record.jti),
            "user_id": record.user_id,
            "family_id": UUID(record.family_id),
            "issued_at": record.issued_at,
            "expires_at": record.expires_at,
        },
    )
    await db.commit()
    return token


async def _create_project(
    db: AsyncSession,
    user: Any,
    *,
    name: str,
    visibility: ProjectVisibility = ProjectVisibility.PUBLIC,
) -> Project:
    project = Project(
        id=uuid.uuid4(),
        name=name,
        description="spec/009 PR A smoke project",
        visibility=visibility,
        license=ProjectLicense.CC_BY,
        owner_id=user.id,
        status=ProjectStatus.ACTIVE,
        restricted_config=(
            _RESTRICTED_CONFIG if visibility == ProjectVisibility.RESTRICTED else {}
        ),
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


async def _create_recording_fixture(
    db: AsyncSession,
    *,
    user: Any,
    project: Project,
) -> tuple[Dataset, Recording]:
    site = Site(
        id=uuid.uuid4(),
        project_id=project.id,
        name="T021 Site",
        h3_index_member="8928308280fffff",
        h3_index_member_resolution=9,
    )
    db.add(site)
    await db.flush()

    dataset = Dataset(
        id=uuid.uuid4(),
        project_id=project.id,
        site_id=site.id,
        created_by_id=user.id,
        name="T021 Dataset",
        visibility=DatasetVisibility.PUBLIC,
        status=DatasetStatus.COMPLETED,
    )
    db.add(dataset)
    await db.flush()

    recording_id = uuid.uuid4()
    recording = Recording(
        id=recording_id,
        dataset_id=dataset.id,
        filename="t021-recording.wav",
        path=f"recordings/{project.id}/{dataset.id}/{recording_id}.wav",
        hash="t021hash",
        duration=12.5,
        samplerate=48_000,
        channels=2,
        datetime=datetime(2026, 5, 13, 9, 30, tzinfo=UTC),
        datetime_parse_status=DatetimeParseStatus.SUCCESS,
    )
    db.add(recording)
    await db.commit()
    await db.refresh(dataset)
    await db.refresh(recording)
    return dataset, recording


@pytest.mark.asyncio
async def test_projects_read_smoke_accepts_session_and_rejects_api_key(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session)
    public_project = await _create_project(
        db_session,
        user,
        name="T021 Public Project",
    )
    restricted_project = await _create_project(
        db_session,
        user,
        name="T021 Restricted Project",
        visibility=ProjectVisibility.RESTRICTED,
    )
    dataset, recording = await _create_recording_fixture(
        db_session,
        user=user,
        project=public_project,
    )
    refresh_token = await _seed_refresh_token(db_session, user)

    refresh = await client.post(
        "/web-api/v1/auth/refresh",
        cookies={get_settings().web_refresh_cookie_name: refresh_token},
    )
    assert refresh.status_code == 200, refresh.text
    access_token = refresh.json()["access_token"]

    response = await client.get(
        "/web-api/v1/projects",
        headers={"Authorization": f"Bearer {access_token}"},
        follow_redirects=True,
    )
    assert response.status_code == 200, response.text
    assert set(response.json()) >= {"items", "total", "page"}

    detail = await client.get(
        f"/web-api/v1/projects/{restricted_project.id}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["id"] == str(restricted_project.id)

    recordings = await client.get(
        f"/web-api/v1/projects/{public_project.id}/recordings",
        params={
            "dataset_id": str(dataset.id),
            "search": "t021",
            "sort_by": "filename",
            "sort_order": "asc",
            "limit": "10",
        },
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert recordings.status_code == 200, recordings.text
    recordings_body = recordings.json()
    assert recordings_body["total"] == 1
    assert recordings_body["items"][0] == {
        "id": str(recording.id),
        "project_id": str(public_project.id),
        "dataset_id": str(dataset.id),
        "name": "t021-recording.wav",
        "duration_seconds": 12.5,
        "samplerate": 48000,
        "channels": 2,
        "datetime": "2026-05-13T09:30:00Z",
        "datetime_parse_status": "success",
        "site_h3_index": "8928308280fffff",
    }

    client.cookies.clear()
    bearer_only_restricted_detail = await client.get(
        f"/web-api/v1/projects/{restricted_project.id}",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert bearer_only_restricted_detail.status_code == 404

    guest_recordings = await client.get(
        f"/web-api/v1/projects/{public_project.id}/recordings",
    )
    assert guest_recordings.status_code == 200, guest_recordings.text
    assert guest_recordings.json()["total"] == 1

    await assert_api_key_cross_rejected(client, "GET", "/web-api/v1/projects")
    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"/web-api/v1/projects/{public_project.id}",
    )
    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"/web-api/v1/projects/{public_project.id}/recordings",
    )

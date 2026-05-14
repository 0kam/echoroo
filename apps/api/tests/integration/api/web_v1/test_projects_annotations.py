"""Spec/009 PR D coverage for project annotation BFF adapters."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from uuid import uuid4

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.api.v1 import annotations as legacy_annotations
from echoroo.api.web_v1.projects import _annotations
from echoroo.core.database import get_db
from echoroo.core.settings import get_settings
from echoroo.middleware.auth import get_current_user
from tests.integration.api.web_v1._helpers import (
    assert_api_key_cross_rejected,
    assert_csrf_required,
    assert_permission_denial_returns_403,
)
from tests.integration.api.web_v1.test_projects_read_smoke import (
    _RESTRICTED_CONFIG,
    _create_project,
    _create_user,
    _seed_refresh_token,
)


async def _fake_db() -> AsyncIterator[object]:
    yield object()


async def _noop_gate_action(**kwargs: object) -> object:
    return object()


def _build_app(user: object, service: object) -> FastAPI:
    app = FastAPI()
    app.include_router(_annotations.router, prefix="/web-api/v1/projects")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[legacy_annotations.get_annotation_service] = (
        lambda: service
    )
    return app


async def _bff_session_headers(
    client: AsyncClient,
    db: AsyncSession,
    user: object,
) -> dict[str, str]:
    client.cookies.clear()
    refresh_token = await _seed_refresh_token(db, user)
    response = await client.post(
        "/web-api/v1/auth/refresh",
        cookies={get_settings().web_refresh_cookie_name: refresh_token},
    )
    assert response.status_code == 200, response.text
    return {
        "Authorization": f"Bearer {response.json()['access_token']}",
        "X-CSRF-Token": response.headers["X-CSRF-Token"],
    }


async def _seed_restricted_project_raw(db: AsyncSession, owner_id: object) -> object:
    project_id = uuid4()
    await db.execute(
        sa.text(
            """
            INSERT INTO projects (
                id,
                name,
                description,
                visibility,
                license,
                owner_id,
                status,
                restricted_config,
                created_at,
                updated_at
            )
            VALUES (
                :id,
                :name,
                :description,
                'restricted',
                'CC-BY',
                :owner_id,
                'active',
                CAST(:restricted_config AS jsonb),
                now(),
                now()
            )
            """
        ),
        {
            "id": project_id,
            "name": "PR D Restricted Batch Tag",
            "description": "spec/009 PR D restricted project",
            "owner_id": owner_id,
            "restricted_config": json.dumps(_RESTRICTED_CONFIG),
        },
    )
    await db.commit()
    return project_id


@pytest.mark.asyncio
async def test_batch_tag_bff_delegates_to_legacy_and_preserves_response_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    task_id = uuid4()
    tag_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}

    async def fake_batch_tag_clips(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"updated_count": 1, "clip_annotations": []}

    monkeypatch.setattr(
        legacy_annotations,
        "batch_tag_clips",
        fake_batch_tag_clips,
    )
    monkeypatch.setattr(_annotations, "gate_action", _noop_gate_action)

    async with AsyncClient(
        transport=ASGITransport(app=_build_app(user, service)),
        base_url="http://testserver",
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/clip-annotations/batch-tag",
            json={"task_ids": [str(task_id)], "tag_id": str(tag_id)},
        )

    assert response.status_code == 200
    assert response.json() == {"updated_count": 1, "clip_annotations": []}
    assert captured["project_id"] == project_id
    assert captured["current_user"] is user
    assert captured["service"] is service
    request = captured["request"]
    assert isinstance(request, legacy_annotations.BatchTagRequest)
    assert request.task_ids == [task_id]
    assert request.tag_id == tag_id


def test_batch_tag_bff_path_is_declared() -> None:
    paths = _build_app(SimpleNamespace(id=uuid4()), object()).openapi()["paths"]
    assert (
        "/web-api/v1/projects/{project_id}/clip-annotations/batch-tag"
        in paths
    )


@pytest.mark.asyncio
async def test_batch_tag_bff_requires_csrf(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(
        db_session,
        email=f"prd-batch-tag-owner-{uuid4()}@example.com",
    )
    project = await _create_project(
        db_session,
        owner,
        name="PR D Batch Tag CSRF",
    )
    headers = await _bff_session_headers(client, db_session, owner)

    await assert_csrf_required(
        client,
        "POST",
        f"/web-api/v1/projects/{project.id}/clip-annotations/batch-tag",
        headers=headers,
        body={"task_ids": [str(uuid4())], "tag_id": str(uuid4())},
    )


@pytest.mark.asyncio
async def test_batch_tag_bff_rejects_api_key_bearer(
    client: AsyncClient,
) -> None:
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"/web-api/v1/projects/{uuid4()}/clip-annotations/batch-tag",
        body={"task_ids": [str(uuid4())], "tag_id": str(uuid4())},
    )


@pytest.mark.asyncio
async def test_batch_tag_restricted_non_member_returns_403_not_401(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    owner = await _create_user(
        db_session,
        email=f"prd-batch-tag-owner-{uuid4()}@example.com",
    )
    outsider = await _create_user(
        db_session,
        email=f"prd-batch-tag-outsider-{uuid4()}@example.com",
    )
    project_id = await _seed_restricted_project_raw(db_session, owner.id)
    headers = await _bff_session_headers(client, db_session, outsider)

    await assert_permission_denial_returns_403(
        client,
        "POST",
        f"/web-api/v1/projects/{project_id}/clip-annotations/batch-tag",
        headers=headers,
        body={"task_ids": [str(uuid4())], "tag_id": str(uuid4())},
    )

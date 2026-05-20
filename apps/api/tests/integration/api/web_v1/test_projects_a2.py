"""Spec/009 PR A2 coverage for project BFF reads and mutations."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.settings import get_settings
from echoroo.models.enums import ProjectLicense, ProjectVisibility
from echoroo.models.project import Project
from echoroo.models.user import User
from echoroo.services.project import DEFAULT_RESTRICTED_CONFIG
from tests.integration.api.web_v1._helpers import (
    assert_api_key_cross_rejected,
    assert_audit_actor_kind_session,
    assert_csrf_required,
    assert_legacy_v1_rejects_bff_token,
    assert_permission_denial_returns_403,
    assert_rate_limit_bucket_web,
)
from tests.integration.api.web_v1.test_projects_read_smoke import (
    _create_user,
    _seed_refresh_token,
)


async def _bff_session_headers(
    client: AsyncClient,
    db: AsyncSession,
    user: User,
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


def _without_csrf(headers: dict[str, str]) -> dict[str, str]:
    return {key: value for key, value in headers.items() if key.lower() != "x-csrf-token"}


@pytest.mark.asyncio
async def test_members_get_bff_contract(
    client: AsyncClient,
    db_session: AsyncSession,
    test_project: Project,
    test_user: User,
    member_user: User,
) -> None:
    owner_headers = await _bff_session_headers(client, db_session, test_user)
    response = await client.get(
        f"/web-api/v1/projects/{test_project.id}/members",
        headers=_without_csrf(owner_headers),
    )
    assert response.status_code == 200, response.text
    assert len(response.json()) >= 2
    assert_rate_limit_bucket_web(response)

    member_headers = await _bff_session_headers(client, db_session, member_user)
    await assert_permission_denial_returns_403(
        client,
        "GET",
        f"/web-api/v1/projects/{test_project.id}/members",
        headers=_without_csrf(member_headers),
    )
    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"/web-api/v1/projects/{test_project.id}/members",
    )


@pytest.mark.asyncio
async def test_legacy_v1_project_members_rejects_bff_jwt(
    unshimmed_client: AsyncClient,
    bff_jwt_factory: Any,
    test_project: Project,
    test_user: User,
) -> None:
    await assert_legacy_v1_rejects_bff_token(
        unshimmed_client,
        "GET",
        f"/api/v1/projects/{test_project.id}/members",
        bff_token=bff_jwt_factory(user_id=test_user.id),
    )


@pytest.mark.asyncio
async def test_overview_bff_contract(
    client: AsyncClient,
    db_session: AsyncSession,
    test_project: Project,
    test_user: User,
    other_user: User,
) -> None:
    owner_headers = await _bff_session_headers(client, db_session, test_user)
    response = await client.get(
        f"/web-api/v1/projects/{test_project.id}/overview",
        headers=_without_csrf(owner_headers),
    )
    assert response.status_code == 200, response.text
    assert set(response.json()) == {
        "sites",
        "recording_calendar",
        "total_recordings",
        "total_sites",
        "total_duration",
    }
    assert_rate_limit_bucket_web(response)

    outsider_headers = await _bff_session_headers(client, db_session, other_user)
    await assert_permission_denial_returns_403(
        client,
        "GET",
        f"/web-api/v1/projects/{test_project.id}/overview",
        headers=_without_csrf(outsider_headers),
    )
    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"/web-api/v1/projects/{test_project.id}/overview",
    )


@pytest.mark.asyncio
async def test_project_create_update_delete_bff_contract(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
    member_user: User,
) -> None:
    owner_headers = await _bff_session_headers(client, db_session, test_user)
    create_body = {
        "name": f"A2 Project {uuid.uuid4()}",
        "description": "created by PR A2 test",
        "visibility": ProjectVisibility.PUBLIC.value,
        "license": ProjectLicense.CC_BY.value,
    }
    await assert_csrf_required(
        client,
        "POST",
        "/web-api/v1/projects",
        body=create_body,
        headers=owner_headers,
    )
    create = await client.post(
        "/web-api/v1/projects",
        json=create_body,
        headers=owner_headers,
        follow_redirects=True,
    )
    assert create.status_code == 201, create.text
    created_project_id = create.json()["id"]
    created_project_uuid = uuid.UUID(created_project_id)
    assert_rate_limit_bucket_web(create)
    create_audit = await assert_audit_actor_kind_session(
        db_session,
        {"action": "project.create", "project_id": created_project_uuid},
    )
    assert create_audit["after"]["name"] == create_body["name"]

    member_headers = await _bff_session_headers(client, db_session, member_user)
    await assert_permission_denial_returns_403(
        client,
        "PATCH",
        f"/web-api/v1/projects/{created_project_id}",
        headers=member_headers,
        body={"name": "Denied rename"},
    )

    owner_headers = await _bff_session_headers(client, db_session, test_user)
    update = await client.patch(
        f"/web-api/v1/projects/{created_project_id}",
        json={"name": "A2 Renamed Project"},
        headers=owner_headers,
    )
    assert update.status_code == 200, update.text
    assert update.json()["name"] == "A2 Renamed Project"
    update_audit = await assert_audit_actor_kind_session(
        db_session,
        {"action": "project.update", "project_id": created_project_uuid},
    )
    assert update_audit["detail"]["updated_fields"] == ["name"]
    assert update_audit["before"]["name"] == create_body["name"]
    assert update_audit["after"]["name"] == "A2 Renamed Project"

    await assert_csrf_required(
        client,
        "DELETE",
        f"/web-api/v1/projects/{created_project_id}",
        headers=owner_headers,
    )
    delete = await client.delete(
        f"/web-api/v1/projects/{created_project_id}",
        headers=owner_headers,
    )
    assert delete.status_code == 204, delete.text
    db_session.expire_all()
    deleted_project = await db_session.get(Project, created_project_uuid)
    assert deleted_project is None
    delete_audit = await assert_audit_actor_kind_session(
        db_session,
        {"action": "project.delete"},
        table="platform_audit_log",
    )
    assert delete_audit["detail"]["project_id"] == created_project_id
    assert delete_audit["detail"]["delete_mode"] == "hard_delete"
    assert delete_audit["before"]["name"] == "A2 Renamed Project"
    assert delete_audit["after"] is None

    await assert_api_key_cross_rejected(
        client,
        "POST",
        "/web-api/v1/projects/",
        body=create_body,
    )


@pytest.mark.asyncio
async def test_create_restricted_project_with_empty_config_uses_defaults(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
) -> None:
    owner_headers = await _bff_session_headers(client, db_session, test_user)
    response = await client.post(
        "/web-api/v1/projects",
        json={
            "name": f"A2 Restricted Defaults {uuid.uuid4()}",
            "description": "restricted project with empty config",
            "visibility": ProjectVisibility.RESTRICTED.value,
            "license": ProjectLicense.CC_BY.value,
            "restricted_config": {},
        },
        headers=owner_headers,
        follow_redirects=True,
    )

    assert response.status_code == 201, response.text
    restricted_config = response.json()["restricted_config"]
    assert set(restricted_config) == set(DEFAULT_RESTRICTED_CONFIG)
    assert restricted_config == DEFAULT_RESTRICTED_CONFIG


@pytest.mark.asyncio
async def test_create_restricted_project_user_override_wins(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
) -> None:
    owner_headers = await _bff_session_headers(client, db_session, test_user)
    response = await client.post(
        "/web-api/v1/projects",
        json={
            "name": f"A2 Restricted Override {uuid.uuid4()}",
            "description": "restricted project with config overrides",
            "visibility": ProjectVisibility.RESTRICTED.value,
            "license": ProjectLicense.CC_BY.value,
            "restricted_config": {
                "allow_media_playback": True,
                "public_location_precision_h3_res": 5,
            },
        },
        headers=owner_headers,
        follow_redirects=True,
    )

    assert response.status_code == 201, response.text
    expected_config = {
        **DEFAULT_RESTRICTED_CONFIG,
        "allow_media_playback": True,
        "public_location_precision_h3_res": 5,
    }
    restricted_config = response.json()["restricted_config"]
    assert set(restricted_config) == set(DEFAULT_RESTRICTED_CONFIG)
    assert restricted_config == expected_config


@pytest.mark.asyncio
async def test_create_public_project_with_empty_config_succeeds(
    client: AsyncClient,
    db_session: AsyncSession,
    test_user: User,
) -> None:
    owner_headers = await _bff_session_headers(client, db_session, test_user)
    response = await client.post(
        "/web-api/v1/projects",
        json={
            "name": f"A2 Public Empty Config {uuid.uuid4()}",
            "description": "public project with empty config",
            "visibility": ProjectVisibility.PUBLIC.value,
            "license": ProjectLicense.CC_BY.value,
            "restricted_config": {},
        },
        headers=owner_headers,
        follow_redirects=True,
    )

    assert response.status_code == 201, response.text


@pytest.mark.asyncio
async def test_project_member_mutations_bff_contract(
    client: AsyncClient,
    db_session: AsyncSession,
    test_project: Project,
    test_user: User,
    member_user: User,
) -> None:
    target_user = await _create_user(
        db_session,
        email=f"a2-member-{uuid.uuid4()}@example.com",
    )
    owner_headers = await _bff_session_headers(client, db_session, test_user)

    add_body = {"email": target_user.email, "role": "viewer"}
    await assert_csrf_required(
        client,
        "POST",
        f"/web-api/v1/projects/{test_project.id}/members",
        body=add_body,
        headers=owner_headers,
    )
    add = await client.post(
        f"/web-api/v1/projects/{test_project.id}/members",
        json=add_body,
        headers=owner_headers,
    )
    assert add.status_code == 201, add.text
    assert add.json()["user"]["id"] == str(target_user.id)
    add_audit = await assert_audit_actor_kind_session(
        db_session,
        {"action": "project.member.invite", "project_id": test_project.id},
    )
    assert add_audit["detail"]["user_id"] == str(target_user.id)
    assert add_audit["after"]["role"] == "viewer"

    member_headers = await _bff_session_headers(client, db_session, member_user)
    await assert_permission_denial_returns_403(
        client,
        "PATCH",
        f"/web-api/v1/projects/{test_project.id}/members/{target_user.id}",
        headers=member_headers,
        body={"role": "member"},
    )

    owner_headers = await _bff_session_headers(client, db_session, test_user)
    update = await client.patch(
        f"/web-api/v1/projects/{test_project.id}/members/{target_user.id}",
        json={"role": "member"},
        headers=owner_headers,
    )
    assert update.status_code == 200, update.text
    assert update.json()["role"] == "member"
    role_audit = await assert_audit_actor_kind_session(
        db_session,
        {
            "action": "project.member.update_role",
            "project_id": test_project.id,
        },
    )
    assert role_audit["detail"]["user_id"] == str(target_user.id)
    assert role_audit["detail"]["old_role"] == "viewer"
    assert role_audit["detail"]["new_role"] == "member"

    delete = await client.delete(
        f"/web-api/v1/projects/{test_project.id}/members/{target_user.id}",
        headers=owner_headers,
    )
    assert delete.status_code == 204, delete.text
    remove_audit = await assert_audit_actor_kind_session(
        db_session,
        {"action": "project.member.remove", "project_id": test_project.id},
    )
    assert remove_audit["detail"]["user_id"] == str(target_user.id)
    assert remove_audit["before"]["role"] == "member"
    assert remove_audit["after"] is None

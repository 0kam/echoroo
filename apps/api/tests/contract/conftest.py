"""Fixtures for contract tests."""

from uuid import UUID

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.jwt import create_access_token
from echoroo.core.settings import get_settings
from echoroo.models.enums import ProjectMemberRole, ProjectVisibility
from echoroo.models.project import Project, ProjectMember
from echoroo.models.user import User
from tests.conftest import ensure_test_database_schema_sync


@pytest.fixture(scope="session", autouse=True)
def _ensure_test_database_schema_for_contract() -> None:
    """Session-scoped autouse fixture that ensures the test DB schema is current.

    Phase 17 §D-0 follow-up (2026-05-08): moved out of root ``tests/conftest.py``
    so ``tests/runbook/`` smoke tests (which have no Postgres available) no
    longer crash at session start with ``OSError: Connect call failed``.
    """
    ensure_test_database_schema_sync()


@pytest.fixture
async def test_user(db_session: AsyncSession) -> User:
    """Create a test user (project owner).

    Args:
        db_session: Database session

    Returns:
        Test user instance
    """
    user = User(
        email="testuser@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="Test User",
        security_stamp="contract-stamp-test",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def other_user(db_session: AsyncSession) -> User:
    """Create another test user (no access to project).

    Args:
        db_session: Database session

    Returns:
        Test user instance
    """
    user = User(
        email="otheruser@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="Other User",
        security_stamp="contract-stamp-other",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def member_user(db_session: AsyncSession) -> User:
    """Create a test user that will be a project member.

    Args:
        db_session: Database session

    Returns:
        Test user instance
    """
    user = User(
        email="member@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="Member User",
        security_stamp="contract-stamp-member",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def admin_user(db_session: AsyncSession) -> User:
    """Create a test user that will be a project admin.

    Args:
        db_session: Database session

    Returns:
        Test user instance
    """
    user = User(
        email="admin@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="Admin User",
        security_stamp="contract-stamp-admin",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def auth_headers(db_session: AsyncSession, test_user: User) -> dict[str, str]:
    """Create authentication headers for test user.

    Args:
        db_session: Database session
        test_user: Test user

    Returns:
        Headers with Bearer token
    """
    access_token = create_access_token({"sub": str(test_user.id)})
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
async def auth_headers_other(db_session: AsyncSession, other_user: User) -> dict[str, str]:
    """Create authentication headers for other user.

    Args:
        db_session: Database session
        other_user: Other test user

    Returns:
        Headers with Bearer token
    """
    access_token = create_access_token({"sub": str(other_user.id)})
    return {"Authorization": f"Bearer {access_token}"}


async def bff_session_headers(
    client: AsyncClient, db: AsyncSession, user: User
) -> dict[str, str]:
    """Build a CSRF-capable ``/web-api/v1`` session for ``user``.

    W2-3 unmounts the legacy ``/api/v1`` browser routes; their behaviour now
    lives on the ``/web-api/v1`` BFF, which sits behind the CSRF middleware
    (``apps/api/echoroo/middleware/csrf.py``). A mutation that omits either the
    session cookie or the ``X-CSRF-Token`` header is rejected with 403 before the
    permission gate runs, so contract tests that exercise BFF mutations seed a
    refresh token, exchange it at ``/web-api/v1/auth/refresh`` for an access token
    + ``X-CSRF-Token``, and send both.
    """
    from echoroo.api.web_v1.auth import _issue_web_refresh_token

    token, record = _issue_web_refresh_token(
        user_id=user.id, security_stamp=user.security_stamp
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
    client.cookies.clear()
    response = await client.post(
        "/web-api/v1/auth/refresh",
        cookies={get_settings().web_refresh_cookie_name: token},
    )
    assert response.status_code == 200, response.text
    return {
        "Authorization": f"Bearer {response.json()['access_token']}",
        "X-CSRF-Token": response.headers["X-CSRF-Token"],
    }


@pytest.fixture
async def csrf_headers(
    client: AsyncClient, db_session: AsyncSession, test_user: User
) -> dict[str, str]:
    """CSRF-capable BFF session headers for ``test_user`` (mutations on /web-api/v1)."""
    return await bff_session_headers(client, db_session, test_user)


@pytest.fixture
async def csrf_headers_other(
    client: AsyncClient, db_session: AsyncSession, other_user: User
) -> dict[str, str]:
    """CSRF-capable BFF session headers for ``other_user`` (non-member 403 cases)."""
    return await bff_session_headers(client, db_session, other_user)


@pytest.fixture
async def auth_headers_member(db_session: AsyncSession, member_user: User) -> dict[str, str]:
    """Create authentication headers for member user.

    Args:
        db_session: Database session
        member_user: Member test user

    Returns:
        Headers with Bearer token
    """
    access_token = create_access_token({"sub": str(member_user.id)})
    return {"Authorization": f"Bearer {access_token}"}


@pytest.fixture
async def auth_headers_admin(db_session: AsyncSession, admin_user: User) -> dict[str, str]:
    """Create authentication headers for admin user.

    Args:
        db_session: Database session
        admin_user: Admin test user

    Returns:
        Headers with Bearer token
    """
    access_token = create_access_token({"sub": str(admin_user.id)})
    return {"Authorization": f"Bearer {access_token}"}


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


@pytest.fixture
async def test_project(db_session: AsyncSession, test_user: User) -> Project:
    """Create a test project.

    Args:
        db_session: Database session
        test_user: Project owner

    Returns:
        Test project instance
    """
    project = Project(
        name="Test Project",
        description="A test project",
        visibility=ProjectVisibility.RESTRICTED,
        license_id="cc-by",
        owner_id=test_user.id,
        # Phase 11 ck_projects_restricted_config_shape requires the eight
        # canonical toggle keys whenever ``visibility='restricted'``.
        restricted_config=dict(_DEFAULT_RESTRICTED_CONFIG),
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
def test_project_id(test_project: Project) -> str:
    """Get test project ID.

    Args:
        test_project: Test project

    Returns:
        Project UUID as string
    """
    return str(test_project.id)


@pytest.fixture
def test_owner_id(test_user: User) -> str:
    """Get test project owner ID.

    Args:
        test_user: Test user

    Returns:
        User UUID as string
    """
    return str(test_user.id)


@pytest.fixture
def test_user_email(member_user: User) -> str:
    """Get test member user email.

    Args:
        member_user: Member test user

    Returns:
        User email
    """
    return member_user.email


@pytest.fixture
async def test_member(
    db_session: AsyncSession,
    test_project: Project,
    member_user: User,
) -> ProjectMember:
    """Create a test project member.

    Args:
        db_session: Database session
        test_project: Test project
        member_user: Member user

    Returns:
        Project member instance
    """
    member = ProjectMember(
        user_id=member_user.id,
        project_id=test_project.id,
        role=ProjectMemberRole.MEMBER,
        invited_by_id=test_project.owner_id,
    )
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(member)
    return member


@pytest.fixture
def test_member_id(member_user: User) -> str:
    """Get test member user ID.

    Args:
        member_user: Member user

    Returns:
        User UUID as string
    """
    return str(member_user.id)


@pytest.fixture
async def test_admin_member(
    db_session: AsyncSession,
    test_project: Project,
    admin_user: User,
) -> ProjectMember:
    """Create a test project admin member.

    Args:
        db_session: Database session
        test_project: Test project
        admin_user: Admin user

    Returns:
        Project member instance with admin role
    """
    member = ProjectMember(
        user_id=admin_user.id,
        project_id=test_project.id,
        role=ProjectMemberRole.ADMIN,
        invited_by_id=test_project.owner_id,
    )
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(member)
    return member

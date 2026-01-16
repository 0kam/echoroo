"""Fixtures for contract tests."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.jwt import create_access_token
from echoroo.models.enums import ProjectRole, ProjectVisibility
from echoroo.models.project import Project, ProjectMember
from echoroo.models.user import User


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
        hashed_password="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="Test User",
        is_active=True,
        is_verified=True,
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
        hashed_password="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="Other User",
        is_active=True,
        is_verified=True,
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
        hashed_password="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="Member User",
        is_active=True,
        is_verified=True,
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
        hashed_password="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="Admin User",
        is_active=True,
        is_verified=True,
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
        target_taxa="Passeriformes",
        visibility=ProjectVisibility.PRIVATE,
        owner_id=test_user.id,
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
        role=ProjectRole.MEMBER,
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
        role=ProjectRole.ADMIN,
        invited_by_id=test_project.owner_id,
    )
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(member)
    return member

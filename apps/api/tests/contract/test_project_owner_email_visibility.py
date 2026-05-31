"""Contract tests for project owner email visibility (Phase 9 polish round 2 致命 1).

Verifies the privacy contract for ``ProjectResponse.owner.email``:

    1. Guest → Restricted detail              -> ``owner.email`` is None
       (FR-030; even though the project is Restricted, Guest must never
       see the address).
    2. Authenticated non-member → Restricted  -> ``owner.email`` populated
       (US4 AC2 mailto: hook).
    3. Authenticated non-member → Public      -> ``owner.email`` is None
       (Public surfaces never expose the owner email).
    4. Owner → own Restricted project          -> ``owner.email`` populated
       (Authenticated + Restricted = exposed).
    5. Member → Restricted                     -> ``owner.email`` populated
       (Authenticated + Restricted = exposed).

The detail endpoint also returns ``current_user_role`` per Phase 9 polish
round 2 Major 2; the case-3 / case-5 assertions exercise a couple of
those values incidentally so the gate the Web UI uses for the Restricted
"Request access" callout stays end-to-end correct.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.jwt import create_access_token
from echoroo.models.enums import (
    ProjectMemberRole,
    ProjectStatus,
    ProjectVisibility,
)
from echoroo.models.project import Project, ProjectMember
from echoroo.models.user import User


# Local user/auth fixtures — the shared ``tests/contract/conftest.py``
# fixtures for users use the legacy ``password_hash`` keyword argument
# which the User model no longer accepts (the column was renamed to
# ``password_hash``). We define module-local fixtures with the modern
# field name so this suite is self-contained instead of waiting on a
# conftest-wide fix that touches a much larger surface.
def _build_user(email: str, display_name: str) -> User:
    """Construct a minimal :class:`User` row.

    Only the columns that are :data:`nullable=False` and lack a server
    default need to be specified here; everything else picks up its
    column default at flush time.
    """
    return User(
        email=email,
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name=display_name,
        security_stamp="email-visibility-suite",
    )


@pytest.fixture
async def email_owner_user(db_session: AsyncSession) -> User:
    user = _build_user(
        email="email-vis-owner@example.com",
        display_name="Email Visibility Owner",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def email_nonmember_user(db_session: AsyncSession) -> User:
    user = _build_user(
        email="email-vis-nonmember@example.com",
        display_name="Email Visibility Non-Member",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def email_member_user(db_session: AsyncSession) -> User:
    user = _build_user(
        email="email-vis-member@example.com",
        display_name="Email Visibility Member",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def owner_headers(email_owner_user: User) -> dict[str, str]:
    token = create_access_token({"sub": str(email_owner_user.id)})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def nonmember_headers(email_nonmember_user: User) -> dict[str, str]:
    token = create_access_token({"sub": str(email_nonmember_user.id)})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def member_headers(email_member_user: User) -> dict[str, str]:
    token = create_access_token({"sub": str(email_member_user.id)})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def public_project(
    db_session: AsyncSession, email_owner_user: User
) -> Project:
    """Create a Public + Active project owned by ``email_owner_user``."""
    project = Project(
        name="Public Project for Email Visibility",
        description="Public visibility test project",
        visibility=ProjectVisibility.PUBLIC,
        status=ProjectStatus.ACTIVE,
        license_id="cc-by",
        owner_id=email_owner_user.id,
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


_RESTRICTED_DEFAULT_CONFIG: dict[str, object] = {
    "allow_media_playback": True,
    "allow_detection_view": True,
    "mask_species_in_detection": False,
    "allow_download": False,
    "allow_export": False,
    "allow_voting_and_comments": True,
    "public_location_precision_h3_res": 9,
    "allow_precise_location_to_viewer": False,
}


@pytest.fixture
async def restricted_project(
    db_session: AsyncSession, email_owner_user: User
) -> Project:
    """Create a Restricted + Active project owned by ``email_owner_user``.

    The ``ck_projects_restricted_config_shape`` constraint demands every
    Restricted row carry the full eight-key toggle map; we use a
    spec-faithful default so the row passes the check without binding
    this suite to one particular toggle combination.
    """
    project = Project(
        name="Restricted Project for Email Visibility",
        description="Restricted visibility test project",
        visibility=ProjectVisibility.RESTRICTED,
        status=ProjectStatus.ACTIVE,
        license_id="cc-by",
        restricted_config=dict(_RESTRICTED_DEFAULT_CONFIG),
        owner_id=email_owner_user.id,
    )
    db_session.add(project)
    await db_session.commit()
    await db_session.refresh(project)
    return project


@pytest.fixture
async def restricted_project_member(
    db_session: AsyncSession,
    restricted_project: Project,
    email_member_user: User,
) -> ProjectMember:
    """Attach ``email_member_user`` as MEMBER on the Restricted project."""
    member = ProjectMember(
        user_id=email_member_user.id,
        project_id=restricted_project.id,
        role=ProjectMemberRole.MEMBER,
        invited_by_id=restricted_project.owner_id,
    )
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(member)
    return member


@pytest.mark.asyncio
class TestProjectOwnerEmailVisibility:
    """Phase 9 polish round 2 致命 1 — owner.email exposure contract."""

    async def test_guest_public_detail_has_no_owner_email(
        self,
        client: AsyncClient,
        public_project: Project,
    ) -> None:
        """Guest on Public detail must NOT see ``owner.email`` (FR-030).

        The Web UI surface (``/web-api/v1/projects/{id}``) is the
        Guest-aware path; FR-018 enumeration safety blocks Guest detail
        on Restricted projects (the call returns 404), so the Public +
        Active path is the one the privacy contract has to defend here.
        """
        response = await client.get(
            f"/web-api/v1/projects/{public_project.id}"
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert "owner" in data
        # Guest path: email MUST be scrubbed even on Public projects
        # (FR-030). The mailto: AC2 affordance applies only to
        # Authenticated callers on Restricted projects.
        assert data["owner"].get("email") is None
        # Guest is not a member -> current_user_role is None.
        assert data.get("current_user_role") is None

    async def test_guest_restricted_detail_returns_404(
        self,
        client: AsyncClient,
        restricted_project: Project,
    ) -> None:
        """Guest on Restricted detail returns 404 (FR-018 anti-enumeration).

        Belt-and-braces: the privacy contract for ``owner.email`` only
        matters if the surface returns 200. We assert the documented
        Guest-on-Restricted-detail outcome here so a future regression
        that lifted the visibility gate would be caught alongside the
        email-scrub assertion in
        :meth:`test_guest_public_detail_has_no_owner_email`.
        """
        response = await client.get(
            f"/web-api/v1/projects/{restricted_project.id}"
        )
        assert response.status_code == 404, response.text

    async def test_authenticated_nonmember_restricted_detail_exposes_owner_email(
        self,
        client: AsyncClient,
        restricted_project: Project,
        nonmember_headers: dict[str, str],
        email_owner_user: User,
    ) -> None:
        """Authenticated non-member on Restricted detail sees ``owner.email`` (US4 AC2).

        We hit the Web UI surface (``/web-api/v1/projects/{id}``) here
        because that is the route the Web UI actually uses for the US4
        AC2 mailto: callout — it routes through the central
        :func:`is_allowed` gate so Authenticated non-members on a
        Restricted Active project can read the metadata (FR-019).

        Phase 9 polish round 3 Minor 1 (2026-04-27): the assertion now
        compares the exposed value against the seeded owner email
        verbatim instead of a truthy probe, so a future regression that
        emits the wrong address (e.g. swapping in the caller's email by
        mistake) would fail this test.
        """
        response = await client.get(
            f"/web-api/v1/projects/{restricted_project.id}",
            headers=nonmember_headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["owner"]["email"] == email_owner_user.email, (
            "Authenticated non-member on Restricted detail MUST see the "
            "seeded owner.email (US4 AC2 mailto: hook)."
        )
        # Authenticated non-member -> current_user_role is None so the
        # Web UI shows the Request access callout.
        assert data.get("current_user_role") is None

    async def test_authenticated_nonmember_public_detail_has_no_owner_email(
        self,
        client: AsyncClient,
        public_project: Project,
        nonmember_headers: dict[str, str],
    ) -> None:
        """Authenticated non-member on Public detail must NOT see ``owner.email``.

        Public projects never need the mailto: AC2 affordance, so the
        privacy contract keeps the email scrubbed (FR-030). Same Web UI
        surface as the Restricted positive case for symmetry.
        """
        response = await client.get(
            f"/web-api/v1/projects/{public_project.id}",
            headers=nonmember_headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["owner"].get("email") is None, (
            "Public detail must never expose owner.email regardless of caller."
        )

    async def test_owner_restricted_detail_exposes_own_email(
        self,
        client: AsyncClient,
        restricted_project: Project,
        owner_headers: dict[str, str],
        email_owner_user: User,
    ) -> None:
        """Owner on own Restricted detail sees their own email + role='owner'."""
        response = await client.get(
            f"/web-api/v1/projects/{restricted_project.id}",
            headers=owner_headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["owner"]["email"] == email_owner_user.email, (
            "Owner viewing own Restricted project must see the seeded "
            "owner.email (Authenticated + Restricted = exposed)."
        )
        assert data.get("current_user_role") == "owner"

    async def test_member_restricted_detail_exposes_owner_email(
        self,
        client: AsyncClient,
        restricted_project: Project,
        restricted_project_member: ProjectMember,
        member_headers: dict[str, str],
        email_owner_user: User,
    ) -> None:
        """Member on Restricted detail sees ``owner.email`` + role='member'."""
        response = await client.get(
            f"/web-api/v1/projects/{restricted_project.id}",
            headers=member_headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["owner"]["email"] == email_owner_user.email, (
            "Member on Restricted detail must see the seeded owner.email "
            "(Authenticated + Restricted = exposed)."
        )
        # Member role is one of the active membership branches -> not
        # None, so the Web UI hides the Request access callout.
        assert data.get("current_user_role") == "member"

    # =========================================================================
    # Phase 9 polish round 3 Major 1 + Minor 1 (2026-04-27): /api/v1 mirror.
    #
    # Major 1: ``service.get_project`` no longer re-runs ``has_project_access``,
    # so the Bearer surface (``/api/v1/projects/{id}``) finally matches the
    # Web UI surface for Restricted Authenticated non-member detail reads.
    # Minor 1: each Web UI assertion above had no Bearer twin; we add the
    # programmatic-surface mirror here so the contract is exercised on both
    # routers (six positive cases + create + license PATCH = 12 tests total).
    # =========================================================================

    async def test_bearer_authenticated_nonmember_restricted_detail_exposes_owner_email(
        self,
        client: AsyncClient,
        restricted_project: Project,
        nonmember_headers: dict[str, str],
        email_owner_user: User,
    ) -> None:
        """Bearer GET ``/api/v1/projects/{id}`` for Authenticated non-member.

        Phase 9 polish round 3 Major 1 regression guard: prior to the
        fix, ``service.get_project`` re-ran ``has_project_access`` after
        the central ``gate_action`` had already authorised the read,
        causing Authenticated non-members to 403 on Restricted detail.
        With the legacy access check removed, this surface must now mirror
        the Web UI behaviour: 200 + populated ``owner.email`` +
        ``current_user_role == None`` so the US4 AC2 mailto: hook works
        on the programmatic surface too.
        """
        response = await client.get(
            f"/api/v1/projects/{restricted_project.id}",
            headers=nonmember_headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["owner"]["email"] == email_owner_user.email, (
            "Bearer surface: Authenticated non-member on Restricted detail "
            "MUST see the seeded owner.email (US4 AC2 mailto: hook)."
        )
        assert data.get("current_user_role") is None

    async def test_bearer_authenticated_nonmember_public_detail_has_no_owner_email(
        self,
        client: AsyncClient,
        public_project: Project,
        nonmember_headers: dict[str, str],
    ) -> None:
        """Bearer GET ``/api/v1/projects/{id}`` for Public detail scrubs ``owner.email``.

        Public surfaces never expose the owner email regardless of
        authentication state (FR-030). The Bearer twin of
        :meth:`test_authenticated_nonmember_public_detail_has_no_owner_email`.
        """
        response = await client.get(
            f"/api/v1/projects/{public_project.id}",
            headers=nonmember_headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["owner"].get("email") is None, (
            "Bearer surface: Public detail must never expose owner.email "
            "regardless of caller (FR-030)."
        )

    async def test_bearer_owner_restricted_detail_exposes_own_email(
        self,
        client: AsyncClient,
        restricted_project: Project,
        owner_headers: dict[str, str],
        email_owner_user: User,
    ) -> None:
        """Bearer GET ``/api/v1/projects/{id}`` for owner on own Restricted project."""
        response = await client.get(
            f"/api/v1/projects/{restricted_project.id}",
            headers=owner_headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["owner"]["email"] == email_owner_user.email, (
            "Bearer surface: owner viewing own Restricted project must "
            "see the seeded owner.email."
        )
        assert data.get("current_user_role") == "owner"

    async def test_bearer_member_restricted_detail_exposes_owner_email(
        self,
        client: AsyncClient,
        restricted_project: Project,
        restricted_project_member: ProjectMember,
        member_headers: dict[str, str],
        email_owner_user: User,
    ) -> None:
        """Bearer GET ``/api/v1/projects/{id}`` for member on Restricted project."""
        response = await client.get(
            f"/api/v1/projects/{restricted_project.id}",
            headers=member_headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["owner"]["email"] == email_owner_user.email, (
            "Bearer surface: member on Restricted detail must see the "
            "seeded owner.email."
        )
        assert data.get("current_user_role") == "member"

    async def test_bearer_create_public_project_scrubs_owner_email(
        self,
        client: AsyncClient,
        nonmember_headers: dict[str, str],
    ) -> None:
        """Bearer POST ``/api/v1/projects`` Public response scrubs ``owner.email``.

        Even though the POST creator is the project's owner, a Public
        visibility project never exposes ``owner.email`` (FR-030). The
        privacy contract is independent of caller identity.
        """
        body = {
            "name": "Phase 9 Round 3 Public Mirror",
            "description": "Bearer POST mirror for owner-email scrub",
            "visibility": "public",
            "license_id": "cc-by",
        }
        response = await client.post(
            "/api/v1/projects",
            json=body,
            headers=nonmember_headers,
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert data["owner"].get("email") is None, (
            "Bearer create: Public project response must scrub owner.email "
            "regardless of the caller being the creator (FR-030)."
        )
        # The creator is always the owner of a freshly-created project.
        assert data.get("current_user_role") == "owner"

    async def test_bearer_create_restricted_project_exposes_owner_email(
        self,
        client: AsyncClient,
        nonmember_headers: dict[str, str],
        email_nonmember_user: User,
    ) -> None:
        """Bearer POST ``/api/v1/projects`` Restricted response exposes ``owner.email``.

        Authenticated + Restricted is the exposure branch of the privacy
        contract; the create response carries the same shape as the
        detail surface so ``owner.email`` must surface here.
        """
        body = {
            "name": "Phase 9 Round 3 Restricted Mirror",
            "description": "Bearer POST mirror for owner-email exposure",
            "visibility": "restricted",
            "license_id": "cc-by",
            "restricted_config": dict(_RESTRICTED_DEFAULT_CONFIG),
        }
        response = await client.post(
            "/api/v1/projects",
            json=body,
            headers=nonmember_headers,
        )
        assert response.status_code == 201, response.text
        data = response.json()
        # The Bearer caller is the creator -> they are the owner of the
        # newly-created Restricted project, so the seeded caller email is
        # the same as the owner email exposed in the response.
        assert data["owner"]["email"] == email_nonmember_user.email, (
            "Bearer create: Restricted project response must expose the "
            "creator's email under the owner sub-object."
        )
        assert data.get("current_user_role") == "owner"

    async def test_bearer_license_patch_restricted_exposes_owner_email(
        self,
        client: AsyncClient,
        restricted_project: Project,
        owner_headers: dict[str, str],
        email_owner_user: User,
    ) -> None:
        """Bearer PATCH ``/api/v1/projects/{id}/license`` Restricted response exposes ``owner.email``.

        FR-085 / FR-087: license PATCH responses share the
        ``ProjectResponse`` shape with the detail surface; the privacy
        scrub helper is invoked there too. On a Restricted project the
        Authenticated owner sees ``owner.email`` populated.
        """
        response = await client.patch(
            f"/api/v1/projects/{restricted_project.id}/license",
            json={"license_id": "cc-by-nc"},
            headers=owner_headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["owner"]["email"] == email_owner_user.email, (
            "Bearer license PATCH: Restricted response must expose the "
            "seeded owner.email (Authenticated + Restricted = exposed)."
        )
        assert data.get("current_user_role") == "owner"
        # Sanity: the PATCH actually changed the license so we know the
        # response payload comes from the post-commit refresh, not a
        # cached pre-PATCH snapshot.
        assert data.get("license") == "CC-BY-NC"

    async def test_bearer_license_patch_public_scrubs_owner_email(
        self,
        client: AsyncClient,
        public_project: Project,
        owner_headers: dict[str, str],
    ) -> None:
        """Bearer PATCH ``/api/v1/projects/{id}/license`` Public response scrubs ``owner.email``.

        Public-visibility responses never expose the owner email — the
        scrub helper applies regardless of mutation surface (FR-030).
        """
        response = await client.patch(
            f"/api/v1/projects/{public_project.id}/license",
            json={"license_id": "cc-by-nc"},
            headers=owner_headers,
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["owner"].get("email") is None, (
            "Bearer license PATCH: Public response must scrub owner.email "
            "regardless of caller (FR-030)."
        )
        assert data.get("current_user_role") == "owner"
        assert data.get("license") == "CC-BY-NC"

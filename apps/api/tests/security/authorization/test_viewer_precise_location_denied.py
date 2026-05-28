"""Viewer precise-location capability boundary (T405, FR-022 / SC-017).

Spec FR-022: ``allow_precise_location_to_viewer`` is the only Restricted
toggle that can lift :data:`echoroo.core.permissions.Permission.VIEW_PRECISE_LOCATION`
for a project Viewer. SC-017 expresses the inverse safety net — when the
toggle is OFF, a Restricted-project Viewer MUST NOT be able to read precise
location data through any path: the permission gate denies it AND the
response filter clamps the H3 cell to the project's
``public_location_precision_h3_res`` ceiling.

Tests cover:

1. Pure permission engine (``compute_effective_permissions`` /
   ``compute_effective_resolution``):
   * Viewer + ``allow_precise_location_to_viewer=False`` →
     ``VIEW_PRECISE_LOCATION`` NOT in effective permissions, resolution
     clamped to ``public_location_precision_h3_res``.
   * Viewer + ``allow_precise_location_to_viewer=True`` →
     ``VIEW_PRECISE_LOCATION`` IS in effective permissions, resolution
     equals member resolution (full precision).
2. End-to-end via the sites HTTP surface:
   * Toggle OFF → Site detail returns the H3 cell coarsened to the
     toggle ceiling (e.g. res 7) instead of the original res 9.
   * Toggle ON → Site detail returns the original H3 cell (res 9).
3. Defence-in-depth: raw ``latitude`` / ``longitude`` fields are scrubbed
   regardless of the toggle (FR-028 / FR-030).

The pure-engine tests run against the unit-level
:mod:`echoroo.core.permissions` API so the FR-022 contract is locked even
if a future endpoint refactor changes the response shape. The HTTP cases
target the existing sites endpoint because Site is the only resource that
exposes ``h3_index`` directly to authenticated callers (Recording inherits
its cell from the parent Site, Detection only carries it via Recording).
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.jwt import create_access_token
from echoroo.core.permissions import (
    H3_RES_7,
    H3_RES_15,
    Permission,
    ProjectVisibility,
    compute_effective_permissions,
    compute_effective_resolution,
)
from echoroo.models.enums import (
    ProjectMemberRole,
    ProjectStatus,
)
from echoroo.models.enums import ProjectVisibility as DBProjectVisibility
from echoroo.models.project import Project, ProjectMember
from echoroo.models.site import Site
from echoroo.models.user import User

# A known res-9 H3 cell. ``cell_to_parent(.., 7)`` should produce a strictly
# coarser cell, which is the property the HTTP test asserts.
_H3_RES_9_CELL = "89283082803ffff"


# ---------------------------------------------------------------------------
# Helpers — minimal Project + Site + Member projections for unit tests.
# ---------------------------------------------------------------------------


def _project_with_toggle(*, allow_precise: bool, ceiling_res: int) -> SimpleNamespace:
    """Build a stand-in Project for the pure permission engine tests.

    Mirrors the duck type that ``compute_effective_*`` expects (visibility
    + restricted_config). Using SimpleNamespace keeps the test independent
    from SQLAlchemy fixture wiring.
    """
    return SimpleNamespace(
        id=uuid4(),
        visibility=ProjectVisibility.RESTRICTED,
        restricted_config={
            "allow_media_playback": False,
            "allow_detection_view": True,
            "mask_species_in_detection": False,
            "allow_download": False,
            "allow_export": False,
            "allow_voting_and_comments": False,
            "public_location_precision_h3_res": ceiling_res,
            "allow_precise_location_to_viewer": allow_precise,
        },
    )


def _viewer_user_with_role() -> SimpleNamespace:
    """Stand-in for a project Viewer member.

    ``resolve_role`` reads ``user.project_role`` directly — see the helper
    in :mod:`echoroo.core.permissions`. The unit test thus avoids the full
    ``gate_action`` membership lookup.
    """
    return SimpleNamespace(
        id=uuid4(),
        is_superuser=False,
        project_role=ProjectMemberRole.VIEWER,
    )


def _resource_with_h3(member_h3: str, member_res: int) -> SimpleNamespace:
    """Build a Resource view for ``compute_effective_resolution``."""
    return SimpleNamespace(
        h3_index_member=member_h3,
        h3_index_member_resolution=member_res,
        taxon_id=None,
    )


# ---------------------------------------------------------------------------
# Tests — pure permission engine.
# ---------------------------------------------------------------------------


class TestViewerPreciseLocationPermissionEngine:
    """FR-022 / SC-017: Viewer + Restricted toggle decides VIEW_PRECISE_LOCATION."""

    def test_toggle_off_excludes_precise_location_from_effective_permissions(
        self,
    ) -> None:
        """``allow_precise_location_to_viewer=False`` ⇒ no VIEW_PRECISE_LOCATION."""
        project = _project_with_toggle(allow_precise=False, ceiling_res=H3_RES_7)

        effective = compute_effective_permissions(
            normalized_role="Viewer",
            project=project,
        )

        assert Permission.VIEW_PRECISE_LOCATION not in effective, (
            "FR-022: Viewer must NOT receive VIEW_PRECISE_LOCATION when the "
            "Restricted toggle is OFF"
        )

    def test_toggle_on_grants_precise_location_to_viewer(self) -> None:
        """``allow_precise_location_to_viewer=True`` ⇒ VIEW_PRECISE_LOCATION granted."""
        project = _project_with_toggle(allow_precise=True, ceiling_res=H3_RES_7)

        effective = compute_effective_permissions(
            normalized_role="Viewer",
            project=project,
        )

        assert Permission.VIEW_PRECISE_LOCATION in effective, (
            "FR-022: Viewer MUST receive VIEW_PRECISE_LOCATION when the "
            "Restricted toggle is ON"
        )

    def test_toggle_off_clamps_resolution_to_ceiling(self) -> None:
        """Without VIEW_PRECISE_LOCATION the resolution clamps to the toggle ceiling."""
        project = _project_with_toggle(allow_precise=False, ceiling_res=H3_RES_7)
        resource = _resource_with_h3(_H3_RES_9_CELL, H3_RES_15)

        effective = compute_effective_permissions(
            normalized_role="Viewer",
            project=project,
        )
        resolution = compute_effective_resolution(
            resource=resource,
            role="Viewer",
            project=project,
            effective_permissions=effective,
        )

        assert resolution == H3_RES_7, (
            f"SC-017: Viewer with toggle OFF must clamp to res {H3_RES_7}, "
            f"got {resolution}"
        )

    def test_toggle_on_returns_member_resolution(self) -> None:
        """With VIEW_PRECISE_LOCATION the resolution equals member resolution."""
        project = _project_with_toggle(allow_precise=True, ceiling_res=H3_RES_7)
        resource = _resource_with_h3(_H3_RES_9_CELL, H3_RES_15)

        effective = compute_effective_permissions(
            normalized_role="Viewer",
            project=project,
        )
        resolution = compute_effective_resolution(
            resource=resource,
            role="Viewer",
            project=project,
            effective_permissions=effective,
        )

        assert resolution == H3_RES_15, (
            f"FR-022: Viewer with toggle ON must see member resolution "
            f"{H3_RES_15}, got {resolution}"
        )


# ---------------------------------------------------------------------------
# Tests — end-to-end via the Sites HTTP surface.
#
# Restricted project + Viewer member + Site at res 9. With the toggle OFF
# and ``public_location_precision_h3_res=7`` the response's ``h3_index``
# field MUST be coarsened to a res 7 ancestor. With the toggle ON the
# response keeps the original res 9 cell.
# ---------------------------------------------------------------------------


def _viewer_restricted_config(*, allow_precise: bool) -> dict[str, object]:
    return {
        "allow_media_playback": True,
        "allow_detection_view": True,
        "mask_species_in_detection": False,
        "allow_download": False,
        "allow_export": False,
        "allow_voting_and_comments": False,
        "public_location_precision_h3_res": H3_RES_7,
        "allow_precise_location_to_viewer": allow_precise,
    }


@pytest_asyncio.fixture
async def t405_owner(db_session: AsyncSession) -> User:
    user = User(
        email="t405owner@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T405 Owner",
        security_stamp="t405" + "o" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def t405_viewer(db_session: AsyncSession) -> User:
    user = User(
        email="t405viewer@example.com",
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name="T405 Viewer",
        security_stamp="t405" + "v" * 60,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
def t405_viewer_headers(t405_viewer: User) -> dict[str, str]:
    return {
        "Authorization": (
            f"Bearer {create_access_token({'sub': str(t405_viewer.id)})}"
        )
    }


async def _seed_restricted_project_with_viewer(
    db: AsyncSession,
    *,
    owner: User,
    viewer: User,
    allow_precise: bool,
) -> tuple[Project, Site]:
    """Create a Restricted project with the requested toggle + a Site at res 9."""
    project = Project(
        name=(
            "T405 Restricted (allow_precise=ON)"
            if allow_precise
            else "T405 Restricted (allow_precise=OFF)"
        ),
        description="FR-022 viewer precise-location coverage",
        visibility=DBProjectVisibility.RESTRICTED,
        license_id="cc-by",
        owner_id=owner.id,
        status=ProjectStatus.ACTIVE,
        restricted_config=_viewer_restricted_config(allow_precise=allow_precise),
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)

    member = ProjectMember(
        project_id=project.id,
        user_id=viewer.id,
        role=ProjectMemberRole.VIEWER,
        joined_at=datetime.now(UTC),
        invited_by_id=owner.id,
    )
    db.add(member)

    site = Site(
        project_id=project.id,
        name="T405 Site",
        h3_index_member=_H3_RES_9_CELL,
    )
    db.add(site)
    await db.commit()
    await db.refresh(site)
    return project, site


@pytest.mark.asyncio
class TestViewerPreciseLocationHttpSurface:
    """End-to-end FR-022 coverage via the sites endpoint."""

    async def test_viewer_with_toggle_off_sees_coarsened_h3(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t405_owner: User,
        t405_viewer: User,
        t405_viewer_headers: dict[str, str],
    ) -> None:
        """Toggle OFF + Viewer ⇒ ``h3_index`` is coarsened to the ceiling."""
        project, site = await _seed_restricted_project_with_viewer(
            db_session,
            owner=t405_owner,
            viewer=t405_viewer,
            allow_precise=False,
        )

        response = await client.get(
            f"/api/v1/projects/{project.id}/sites/{site.id}",
            headers=t405_viewer_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        # Canonical wire key after Phase 13 P4 rename is ``h3_index_member``;
        # the legacy ``h3_index`` alias is still emitted by response_filter
        # for transitional readers but tests pin to the canonical name.
        returned_h3 = body["h3_index_member"]

        # The original res-9 cell is hidden — the response cell is at the
        # toggle ceiling resolution. We assert the coarsening happened by
        # confirming the value is a strict ancestor of the original cell.
        assert returned_h3 != _H3_RES_9_CELL, (
            "SC-017: Viewer with toggle OFF must NOT see the original "
            f"res-9 cell {_H3_RES_9_CELL!r}, got {returned_h3!r}"
        )
        try:
            import h3 as _h3
            assert int(_h3.get_resolution(returned_h3)) == H3_RES_7, (
                f"SC-017: Viewer with toggle OFF should see res-{H3_RES_7} "
                f"cell, got resolution {_h3.get_resolution(returned_h3)} "
                f"({returned_h3!r})"
            )
        except ImportError:  # pragma: no cover — h3 is a runtime dependency
            pass

        # Defence in depth (FR-028 / FR-030): raw lat/lng MUST be scrubbed
        # regardless of the precise-location toggle.
        assert body.get("latitude") in (None, ""), (
            f"FR-028: latitude must be scrubbed, got {body.get('latitude')!r}"
        )
        assert body.get("longitude") in (None, ""), (
            f"FR-028: longitude must be scrubbed, got {body.get('longitude')!r}"
        )

    async def test_viewer_with_toggle_on_sees_member_resolution(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        t405_owner: User,
        t405_viewer: User,
        t405_viewer_headers: dict[str, str],
    ) -> None:
        """Toggle ON + Viewer ⇒ ``h3_index`` keeps the original member cell."""
        project, site = await _seed_restricted_project_with_viewer(
            db_session,
            owner=t405_owner,
            viewer=t405_viewer,
            allow_precise=True,
        )

        response = await client.get(
            f"/api/v1/projects/{project.id}/sites/{site.id}",
            headers=t405_viewer_headers,
        )
        assert response.status_code == 200, response.text
        body = response.json()
        # Canonical wire key after Phase 13 P4 rename is ``h3_index_member``.
        returned_h3 = body["h3_index_member"]

        # Toggle ON lifts VIEW_PRECISE_LOCATION → response keeps the raw
        # res-9 cell that the Site row stores.
        assert returned_h3 == _H3_RES_9_CELL, (
            f"FR-022: Viewer with toggle ON should see member resolution "
            f"cell {_H3_RES_9_CELL!r}, got {returned_h3!r}"
        )


# ---------------------------------------------------------------------------
# Phase 8 polish round 2 Minor 2 — Detection-scope FR-022 capability matrix.
#
# Site detail proves the HTTP response_filter integration; the unit cases
# below extend the FR-022 capability check to the detection-row scope so
# that the per-detection h3 cell would also be clamped wherever the
# response_filter is wired against a Detection resource. The unit form
# is intentional: ``DetectionResponse`` does not currently carry an
# ``h3_index`` field at the top level (it inherits site / recording cells
# via the embedded resource), so a pure HTTP test would conflate FR-022
# (capability presence) with the orthogonal "which schema fields surface
# the cell" question. The pure permission-engine cases here pin the
# capability contract independently of the response shape — when a future
# endpoint adds a per-detection ``h3_index`` field the wired-in filter
# will inherit the clamp already proven here.
# ---------------------------------------------------------------------------


def _detection_resource_with_h3(
    member_h3: str, member_res: int, taxon_id: object | None = None
) -> SimpleNamespace:
    """Build a Detection-shaped Resource view for ``compute_effective_resolution``.

    Matches the duck type the filter expects when called against a
    detection row (per ``api/v1/detections.py:_apply_detection_response_filter``).
    """
    return SimpleNamespace(
        h3_index_member=member_h3,
        h3_index_member_resolution=member_res,
        taxon_id=taxon_id,
    )


class TestViewerPreciseLocationDetectionScope:
    """Phase 8 polish round 2 Minor 2 — FR-022 on detection-scope resources.

    Mirrors :class:`TestViewerPreciseLocationPermissionEngine` but pins
    the contract for a Detection-shaped Resource — i.e. when a viewer
    issues a detection-list / detection-detail request, the H3 clamp
    on the carried location cell follows the same rule. The unit form
    is independent of any specific endpoint's response shape so the
    contract is locked even before Phase 11 expands the response filter
    onto endpoints that surface per-detection h3 cells directly.
    """

    def test_detection_resource_toggle_off_clamps_to_ceiling(self) -> None:
        """Detection-scope resource + toggle OFF ⇒ resolution clamps."""
        project = _project_with_toggle(allow_precise=False, ceiling_res=H3_RES_7)
        resource = _detection_resource_with_h3(_H3_RES_9_CELL, H3_RES_15)

        effective = compute_effective_permissions(
            normalized_role="Viewer",
            project=project,
        )
        resolution = compute_effective_resolution(
            resource=resource,
            role="Viewer",
            project=project,
            effective_permissions=effective,
        )

        assert Permission.VIEW_PRECISE_LOCATION not in effective, (
            "FR-022: Viewer must NOT receive VIEW_PRECISE_LOCATION on "
            "detection scope when allow_precise_location_to_viewer=false"
        )
        assert resolution == H3_RES_7, (
            f"SC-017: Detection-scope clamp must hit res {H3_RES_7} when "
            f"toggle is OFF, got {resolution}"
        )

    def test_detection_resource_toggle_on_returns_member_resolution(self) -> None:
        """Detection-scope resource + toggle ON ⇒ resolution = member precise."""
        project = _project_with_toggle(allow_precise=True, ceiling_res=H3_RES_7)
        resource = _detection_resource_with_h3(_H3_RES_9_CELL, H3_RES_15)

        effective = compute_effective_permissions(
            normalized_role="Viewer",
            project=project,
        )
        resolution = compute_effective_resolution(
            resource=resource,
            role="Viewer",
            project=project,
            effective_permissions=effective,
        )

        assert Permission.VIEW_PRECISE_LOCATION in effective, (
            "FR-022: Viewer MUST receive VIEW_PRECISE_LOCATION on "
            "detection scope when allow_precise_location_to_viewer=true"
        )
        assert resolution == H3_RES_15, (
            f"FR-022: Detection-scope toggle ON must surface member "
            f"resolution {H3_RES_15}, got {resolution}"
        )


__all__ = [
    "TestViewerPreciseLocationDetectionScope",
    "TestViewerPreciseLocationHttpSurface",
    "TestViewerPreciseLocationPermissionEngine",
]

"""FR-112b (spec/006 Rev.3.3) — non-member superuser project-scope role mapping.

The Stage-1 gate (``is_allowed``) upgrades a non-member superuser's
``normalized_role`` to ``Owner`` for project-scope actions that are
**not** on ``SUPERUSER_PROJECT_SCOPE_ALLOWLIST`` and that are **not**
``is_superuser_only=True``. This makes the platform-admin perspective
"see / operate everything" work uniformly across Public and Restricted
projects, while leaving the other safety guards intact:

- ``is_superuser_only=True`` actions hard-fail in Step 0c unless they
  are on the allowlist (Step 0b bypass).
- API-key superuser principals are vetoed in Step -1 / Step 0a / Step 0b.
- archived projects still block ``is_mutating=True`` actions in Step 1.
- Response filter (FR-112a) still strips raw lat/lng and HIDDEN-clamps
  H3 even when the caller's normalized_role is Owner-equivalent.

This suite exercises the gate at the pure-function level — no DB and
no FastAPI app — so each scenario is a focused statement about the
Step-2 role upgrade. Response-filter behaviour is covered separately
in ``test_superuser_response_filter_raw_forbidden.py``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from echoroo.core.actions import (
    PLATFORM_IUCN_FORCE_RESYNC_ACTION,
    PROJECT_RESTORE_ACTION,
    RECORDING_LIST_ACTION,
    RECORDING_MEDIA_ACTION,
    RECORDING_UPDATE_ACTION,
)
from echoroo.core.permissions import (
    H3_RES_9,
    Permission,
    ProjectVisibility,
    is_allowed,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_project(
    *,
    visibility: ProjectVisibility = ProjectVisibility.PUBLIC,
    status: str = "active",
) -> SimpleNamespace:
    """Project fixture with conservative Restricted toggles (all off)."""
    return SimpleNamespace(
        id="proj-fr112b",
        owner_id="some-other-owner",
        visibility=visibility,
        restricted_config={
            "allow_media_playback": False,
            "allow_detection_view": False,
            "mask_species_in_detection": False,
            "allow_download": False,
            "allow_export": False,
            "allow_voting_and_comments": False,
            "public_location_precision_h3_res": H3_RES_9,
            "allow_precise_location_to_viewer": False,
        },
        status=status,
    )


def _make_session_superuser() -> SimpleNamespace:
    """Cookie/JWT superuser — no _api_key_scopes attribute, non-member."""
    return SimpleNamespace(
        id="user-superuser-fr112b",
        is_superuser=True,
        project_role=None,
    )


def _make_session_authenticated() -> SimpleNamespace:
    """Cookie/JWT non-superuser, non-member of the target project."""
    return SimpleNamespace(
        id="user-auth-fr112b",
        is_superuser=False,
        project_role=None,
    )


def _make_api_key_superuser() -> SimpleNamespace:
    """API-key principal owned by a superuser. Step -1 / 0b should veto."""
    return SimpleNamespace(
        id="user-superuser-apikey-fr112b",
        is_superuser=True,
        project_role=None,
        _api_key_scopes=("view_detection",),
        _api_key_id="apikey-fr112b",
        _api_key_project_id=None,
    )


# ---------------------------------------------------------------------------
# Core invariant: Owner upgrade for non-allowlist, non-superuser-only actions
# ---------------------------------------------------------------------------


class TestNonMemberSuperuserOwnerUpgrade:
    """FR-112b: non-member superuser becomes Owner for normal project actions."""

    @pytest.mark.parametrize(
        "visibility",
        [ProjectVisibility.PUBLIC, ProjectVisibility.RESTRICTED],
    )
    def test_read_recording_list_allowed_on_any_visibility(
        self, visibility: ProjectVisibility
    ) -> None:
        """recording.list (VIEW_DETECTION, read) succeeds for non-member superuser
        on Public AND Restricted, regardless of Restricted toggles being off.

        Counterpart: a normal Authenticated non-member on the same Restricted
        project (toggles off) gets denied — see test below.
        """
        project = _make_project(visibility=visibility)
        user = _make_session_superuser()

        allowed, effective = is_allowed(
            action=RECORDING_LIST_ACTION,
            user=user,
            project=project,
        )

        assert allowed is True, (
            f"non-member superuser must read recording.list on {visibility.value} "
            "via FR-112b Owner upgrade"
        )
        assert Permission.VIEW_DETECTION in effective
        # Owner-equivalent permissions reach the response: VIEW_MEDIA too.
        assert Permission.VIEW_MEDIA in effective

    def test_read_recording_media_allowed_restricted_toggles_off(self) -> None:
        """Restricted + allow_media_playback=False would deny Authenticated,
        but superuser should still pass via Owner upgrade."""
        project = _make_project(visibility=ProjectVisibility.RESTRICTED)
        # sanity: toggles really are off
        assert project.restricted_config["allow_media_playback"] is False

        user = _make_session_superuser()

        allowed, _ = is_allowed(
            action=RECORDING_MEDIA_ACTION,
            user=user,
            project=project,
        )
        assert allowed is True

    def test_mutating_non_allowlist_non_superuser_only_allowed(self) -> None:
        """recording.update (MANAGE_DATASET, mutating, not superuser-only,
        not on allowlist) succeeds for non-member superuser via Owner upgrade.

        This is the load-bearing assertion of FR-112b: superusers can mutate
        non-member projects via the normal Matrix path. The audit-log
        enrichment for this code path is tracked in PHASE17_BACKLOG §G.
        """
        project = _make_project(visibility=ProjectVisibility.PUBLIC)
        user = _make_session_superuser()

        allowed, effective = is_allowed(
            action=RECORDING_UPDATE_ACTION,
            user=user,
            project=project,
        )
        assert allowed is True
        assert Permission.MANAGE_DATASET in effective


# ---------------------------------------------------------------------------
# Negative control: non-superuser Authenticated is NOT upgraded
# ---------------------------------------------------------------------------


class TestNonMemberAuthenticatedNotUpgraded:
    """Sanity: only superusers get the Owner upgrade. Regular Authenticated
    non-members continue to be governed by Matrix + Restricted toggles."""

    def test_authenticated_denied_on_restricted_toggles_off(self) -> None:
        """Plain Authenticated user on Restricted with playback toggle off
        must be denied for recording.media — proves FR-112b is gated on
        ``_is_superuser`` and not blanket-grant by `Authenticated` rows."""
        project = _make_project(visibility=ProjectVisibility.RESTRICTED)
        user = _make_session_authenticated()

        allowed, _ = is_allowed(
            action=RECORDING_MEDIA_ACTION,
            user=user,
            project=project,
        )
        assert allowed is False

    def test_authenticated_denied_mutating(self) -> None:
        """Plain Authenticated must NOT be able to update someone else's
        recording, even on a Public project."""
        project = _make_project(visibility=ProjectVisibility.PUBLIC)
        user = _make_session_authenticated()

        allowed, effective = is_allowed(
            action=RECORDING_UPDATE_ACTION,
            user=user,
            project=project,
        )
        assert allowed is False
        assert Permission.MANAGE_DATASET not in effective


# ---------------------------------------------------------------------------
# Allowlist branch: project.restore goes through Step 0b
# ---------------------------------------------------------------------------


class TestAllowlistBypassStillUsesStep0b:
    """When the action is on SUPERUSER_PROJECT_SCOPE_ALLOWLIST, Stage-1 must
    return at Step 0b without falling through to the Step-2 upgrade."""

    def test_project_restore_allowed_on_archived_project(self) -> None:
        """project.restore (allowlist + is_superuser_only + is_mutating)
        succeeds for a session superuser even on an archived project,
        which is exactly the operational scenario the allowlist was added
        for. Step 0b bypasses Step 1's archived/mutating block by returning
        before reaching it."""
        project = _make_project(
            visibility=ProjectVisibility.RESTRICTED,
            status="archived",
        )
        user = _make_session_superuser()

        allowed, _ = is_allowed(
            action=PROJECT_RESTORE_ACTION,
            user=user,
            project=project,
        )
        assert allowed is True

    def test_project_restore_denied_for_api_key_superuser(self) -> None:
        """FR-084 defence-in-depth: API key principals are vetoed even when
        the underlying user is a superuser AND the action is on the
        allowlist. Step -1 (universal API-key veto for is_superuser_only)
        fires first."""
        project = _make_project(
            visibility=ProjectVisibility.RESTRICTED,
            status="archived",
        )
        user = _make_api_key_superuser()

        allowed, _ = is_allowed(
            action=PROJECT_RESTORE_ACTION,
            user=user,
            project=project,
        )
        assert allowed is False


# ---------------------------------------------------------------------------
# Platform-scope branch: no Step-2 upgrade for non-project actions
# ---------------------------------------------------------------------------


class TestPlatformScopeBranchUntouched:
    """Step 0a still routes platform-scope superuser-only actions through
    its own branch. The FR-112b upgrade lives in Step 2 (project-scope only)
    and must not interfere here."""

    def test_platform_iucn_force_resync_session_superuser_allowed(self) -> None:
        user = _make_session_superuser()

        allowed, _ = is_allowed(
            action=PLATFORM_IUCN_FORCE_RESYNC_ACTION,
            user=user,
            project=None,  # platform-scope ignores project
        )
        assert allowed is True

    def test_platform_iucn_force_resync_api_key_superuser_denied(self) -> None:
        """API-key superuser principals are denied platform-scope actions
        regardless of the underlying user's superuser status."""
        user = _make_api_key_superuser()

        allowed, _ = is_allowed(
            action=PLATFORM_IUCN_FORCE_RESYNC_ACTION,
            user=user,
            project=None,
        )
        assert allowed is False

    def test_platform_iucn_force_resync_authenticated_denied(self) -> None:
        user = _make_session_authenticated()

        allowed, _ = is_allowed(
            action=PLATFORM_IUCN_FORCE_RESYNC_ACTION,
            user=user,
            project=None,
        )
        assert allowed is False


# ---------------------------------------------------------------------------
# Step 1: archived block applies even after the Owner upgrade
# ---------------------------------------------------------------------------


class TestArchivedBlockAppliesToSuperuser:
    """Step 1's archived/mutating block runs BEFORE the Step-2 Owner upgrade
    and therefore still bites non-member superusers on non-allowlist mutating
    actions. The only escape is the allowlist (e.g. project.restore)."""

    def test_recording_update_denied_on_archived_project(self) -> None:
        """recording.update is mutating but not on the allowlist — the
        archived guard fires first."""
        project = _make_project(
            visibility=ProjectVisibility.PUBLIC,
            status="archived",
        )
        user = _make_session_superuser()

        allowed, _ = is_allowed(
            action=RECORDING_UPDATE_ACTION,
            user=user,
            project=project,
        )
        assert allowed is False

    def test_recording_list_allowed_on_archived_project(self) -> None:
        """Read actions (non-mutating) are unaffected by the archived guard,
        so the Owner upgrade still grants them on an archived project."""
        project = _make_project(
            visibility=ProjectVisibility.PUBLIC,
            status="archived",
        )
        user = _make_session_superuser()

        allowed, _ = is_allowed(
            action=RECORDING_LIST_ACTION,
            user=user,
            project=project,
        )
        assert allowed is True

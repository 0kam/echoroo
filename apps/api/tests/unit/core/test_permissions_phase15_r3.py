"""Phase 15 R3 NO-GO regression tests for ``echoroo.core.permissions``.

These tests pin the Codex re-review fixes against commit ``f4b2c85c``:

* Major 1 — ``USER_SCOPE_PERMISSIONS`` MUST intersect with the API key's
  ``granted_permissions``. An API key issued with
  ``scopes=("view_detection",)`` cannot exercise ``MANAGE_API_KEY`` /
  ``MANAGE_2FA`` just because its owning user trivially holds those
  user-scope rights.
* Pure-function unit tests only — no DB, no FastAPI app. The
  cross-project gate (``api_key_project_scope_mismatch``) is exercised
  separately by the integration suite where ``gate_action`` actually
  runs.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from echoroo.core.permissions import (
    ACTIONS,
    Action,
    Permission,
    ProjectVisibility,
    is_allowed,
)


def _make_project(
    visibility: ProjectVisibility = ProjectVisibility.PUBLIC,
    *,
    status: str = "active",
) -> SimpleNamespace:
    return SimpleNamespace(
        id="proj-r3",
        owner_id=None,
        visibility=visibility,
        restricted_config={
            "allow_media_playback": False,
            "allow_detection_view": False,
            "mask_species_in_detection": False,
            "allow_download": False,
            "allow_export": False,
            "allow_voting_and_comments": False,
            "public_location_precision_h3_res": 3,
            "allow_precise_location_to_viewer": False,
        },
        status=status,
    )


def _make_user(**kwargs: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": "user-r3",
        "is_superuser": False,
        "project_role": None,
    }
    base.update(kwargs)
    return SimpleNamespace(**base)


# Reuse the existing manage-api-key Action if registered, else build one.
def _user_scope_action(perm: Permission) -> Action:
    for action in ACTIONS.values():
        if action.required_permission == perm:
            return action
    # ACTIONS catalog is filled by the FastAPI router import — under a
    # bare unit-test process some user-scope actions may not be wired
    # yet. Fall back to a synthetic Action with the same shape so the
    # gate machinery has something to run against.
    return Action(name=f"_test.{perm.value}", required_permission=perm, is_mutating=False)


# ---------------------------------------------------------------------------
# Major 1 — USER_SCOPE_PERMISSIONS MUST intersect with API key scopes
# ---------------------------------------------------------------------------


class TestUserScopeApiKeyIntersection:
    def test_session_user_keeps_manage_api_key(self) -> None:
        """Plain logged-in user (no API key) holds MANAGE_API_KEY trivially."""
        action = _user_scope_action(Permission.MANAGE_API_KEY)
        user = _make_user()
        project = _make_project()
        allowed, _ = is_allowed(action=action, user=user, project=project)
        assert allowed is True

    def test_api_key_without_manage_api_key_scope_is_denied(self) -> None:
        """Major 1 fix: an API key NOT holding MANAGE_API_KEY MUST 403.

        Pre-fix the gate let any logged-in user pass user-scope checks
        unconditionally — so an API key with ``scopes=("view_detection",)``
        could mint a second key on behalf of its owning user.
        """
        action = _user_scope_action(Permission.MANAGE_API_KEY)
        user = _make_user()
        project = _make_project()
        allowed, _ = is_allowed(
            action=action,
            user=user,
            project=project,
            api_key_granted_permissions=frozenset({Permission.VIEW_DETECTION}),
        )
        assert allowed is False

    def test_api_key_with_manage_api_key_scope_is_allowed(self) -> None:
        """Sanity: a key that DOES hold MANAGE_API_KEY still passes."""
        action = _user_scope_action(Permission.MANAGE_API_KEY)
        user = _make_user()
        project = _make_project()
        allowed, _ = is_allowed(
            action=action,
            user=user,
            project=project,
            api_key_granted_permissions=frozenset({Permission.MANAGE_API_KEY}),
        )
        assert allowed is True

    def test_api_key_without_manage_2fa_scope_is_denied(self) -> None:
        """Same intersection rule applies to MANAGE_2FA."""
        action = _user_scope_action(Permission.MANAGE_2FA)
        user = _make_user()
        project = _make_project()
        allowed, _ = is_allowed(
            action=action,
            user=user,
            project=project,
            api_key_granted_permissions=frozenset({Permission.VIEW_DETECTION}),
        )
        assert allowed is False

    def test_api_key_search_cross_project_requires_scope(self) -> None:
        """SEARCH_CROSS_PROJECT also flows through the user-scope gate."""
        action = _user_scope_action(Permission.SEARCH_CROSS_PROJECT)
        user = _make_user()
        project = _make_project()
        # Without scope: 403.
        allowed_without, _ = is_allowed(
            action=action,
            user=user,
            project=project,
            api_key_granted_permissions=frozenset({Permission.VIEW_DETECTION}),
        )
        assert allowed_without is False
        # With scope: 200.
        allowed_with, _ = is_allowed(
            action=action,
            user=user,
            project=project,
            api_key_granted_permissions=frozenset(
                {Permission.SEARCH_CROSS_PROJECT}
            ),
        )
        assert allowed_with is True

    def test_session_path_unchanged_when_api_key_granted_is_none(self) -> None:
        """When ``api_key_granted_permissions=None`` the legacy path runs.

        Regression guard: the Major 1 fix must NOT 403 cookie / JWT
        callers (which never pass scopes through).
        """
        for perm in (
            Permission.MANAGE_API_KEY,
            Permission.MANAGE_2FA,
            Permission.SEARCH_CROSS_PROJECT,
        ):
            action = _user_scope_action(perm)
            user = _make_user()
            project = _make_project()
            allowed, _ = is_allowed(
                action=action,
                user=user,
                project=project,
                api_key_granted_permissions=None,
            )
            assert allowed is True, f"session path regressed for {perm}"


# ---------------------------------------------------------------------------
# Major 1 — Guest still 403s on user-scope perms regardless of API scopes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "perm",
    [
        Permission.MANAGE_API_KEY,
        Permission.MANAGE_2FA,
        Permission.SEARCH_CROSS_PROJECT,
    ],
)
def test_guest_is_denied_regardless_of_api_scopes(perm: Permission) -> None:
    """Anonymous callers cannot reach user-scope perms even with scopes set."""
    action = _user_scope_action(perm)
    project = _make_project()
    allowed, _ = is_allowed(
        action=action,
        user=None,
        project=project,
        api_key_granted_permissions=frozenset({perm}),
    )
    assert allowed is False

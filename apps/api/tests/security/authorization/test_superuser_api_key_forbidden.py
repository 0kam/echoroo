"""T956 — Superuser-only operations are forbidden via API key authentication.

Target: FR-084 (API key cannot escalate to superuser operations) /
        PR-007 (Superuser scope cannot be delegated to API keys).

The superuser engine actions (add, revoke, approve, break-glass) are
flagged ``is_platform_scope=True`` AND ``is_superuser_only=True`` on the
Action objects registered in the permission catalog. The ``is_allowed``
gate (``is_platform_scope`` branch) only permits authenticated Superusers
and always denies API key callers, because:

1.  Platform-scope actions require ``_is_superuser(user) == True``.
2.  ``is_superuser`` is stamped from the live ``superusers`` table only
    when the user authenticates via a first-party session (cookie / JWT).
    API key auth sets ``_api_key_scopes`` but does NOT stamp ``is_superuser``
    — the middleware intentionally omits the superuser DB probe for API
    key paths (FR-084 defence in depth).
3.  Even if an API key were somehow issued with a ``superuser`` scope, the
    gate would still reject it because ``is_platform_scope`` is decided
    solely on ``_is_superuser(user)``, not on scope strings.

Admin HTTP endpoint status
--------------------------
The admin superuser CRUD endpoints
(``POST /admin/superusers``, etc.) are **not yet implemented** in Phase 15.
This suite therefore exercises the gate at the ``is_allowed`` / unit level
rather than via a live FastAPI test client.  Each test constructs a
minimal ``user``-like ``SimpleNamespace`` that mirrors the stamped
attributes produced by ``echoroo.middleware.auth``, then calls
``is_allowed`` directly (or through ``gate_action`` where possible via
a mocked DB dependency).

endpoint-level test deferred to Batch 5; gating verified at gate_action level
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from echoroo.core.permissions import (
    ACTIONS,
    Action,
    Permission,
    ProjectVisibility,
    is_allowed,
    register_action,
)

# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------


def _make_project(
    *,
    visibility: ProjectVisibility = ProjectVisibility.PUBLIC,
    status: str = "active",
) -> SimpleNamespace:
    return SimpleNamespace(
        id="proj-t956",
        owner_id=None,
        visibility=visibility,
        restricted_config={
            "allow_media_playback": True,
            "allow_detection_view": True,
            "mask_species_in_detection": False,
            "allow_download": True,
            "allow_export": True,
            "allow_voting_and_comments": True,
            "public_location_precision_h3_res": 9,
            "allow_precise_location_to_viewer": False,
        },
        status=status,
    )


def _make_api_key_user(
    *,
    is_superuser: bool = False,
    scopes: tuple[str, ...] = ("view_detection",),
) -> SimpleNamespace:
    """Construct a User-like object stamped by API key auth middleware."""
    user = SimpleNamespace(
        id="user-t956",
        is_superuser=is_superuser,
        project_role=None,
        # Stamped by _stamp_api_key_scopes (middleware/auth.py)
        _api_key_scopes=scopes,
        _api_key_id="apikey-t956",
        _api_key_project_id=None,
    )
    return user


def _make_session_user(*, is_superuser: bool = False) -> SimpleNamespace:
    """Construct a User-like object from a first-party session (no API key)."""
    return SimpleNamespace(
        id="user-t956-session",
        is_superuser=is_superuser,
        project_role=None,
        # No _api_key_scopes → gate treats as session caller
    )


def _get_or_register_platform_action(name: str) -> Action:
    """Return the named Action from the catalog, creating a platform-scope stub if absent."""
    if name in ACTIONS:
        return ACTIONS[name]
    # Superuser operations are platform-scope: no project, superuser_only=True.
    action = Action(
        name=name,
        required_permission=None,
        is_mutating=True,
        is_superuser_only=True,
        is_platform_scope=True,
    )
    try:
        return register_action(action)
    except ValueError:
        # Already registered with same shape — fetch.
        return ACTIONS[name]


# Superuser platform actions (names align with superuser_service audit labels).
_SUPERUSER_ADD_ACTION = _get_or_register_platform_action("superuser.add")
_SUPERUSER_REVOKE_ACTION = _get_or_register_platform_action("superuser.revoke")
_SUPERUSER_APPROVE_ACTION = _get_or_register_platform_action("superuser.approve")
_SUPERUSER_BREAK_GLASS_ACTION = _get_or_register_platform_action("superuser.break_glass.enter")

_SUPERUSER_ACTIONS = [
    _SUPERUSER_ADD_ACTION,
    _SUPERUSER_REVOKE_ACTION,
    _SUPERUSER_APPROVE_ACTION,
    _SUPERUSER_BREAK_GLASS_ACTION,
]

_ACTION_NAMES = [a.name for a in _SUPERUSER_ACTIONS]


# ---------------------------------------------------------------------------
# Scenario 1-4: API key user → 403 on all superuser platform actions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("action", _SUPERUSER_ACTIONS, ids=_ACTION_NAMES)
def test_api_key_user_denied_superuser_platform_actions(action: Action) -> None:
    """API key callers MUST NOT be allowed on any superuser platform action.

    An API key principal never has ``is_superuser=True`` (the middleware
    skips the superuser DB probe for API key paths). Even if the owning
    user were a superuser, the middleware only stamps ``is_superuser`` for
    session callers.
    """
    api_key_user = _make_api_key_user(is_superuser=False)
    # Platform-scope actions: ``project`` param is ignored / irrelevant.
    # Pass a minimal project object for completeness.
    project = _make_project()
    allowed, _ = is_allowed(
        action=action,
        user=api_key_user,
        project=project,
        request=None,
    )
    assert allowed is False, (
        f"API key user must be denied platform-scope action {action.name!r} "
        "(FR-084 / PR-007)"
    )


@pytest.mark.parametrize("action", _SUPERUSER_ACTIONS, ids=_ACTION_NAMES)
def test_api_key_user_with_broad_scopes_still_denied(action: Action) -> None:
    """Even an API key with many scopes cannot reach superuser platform actions.

    The platform-scope branch checks ``_is_superuser(user)`` ONLY — scope
    strings are irrelevant for this gate branch.
    """
    # Give the API key every project-scope permission string possible.
    all_scopes = tuple(p.value for p in Permission)
    api_key_user = _make_api_key_user(is_superuser=False, scopes=all_scopes)
    project = _make_project()
    allowed, _ = is_allowed(
        action=action,
        user=api_key_user,
        project=project,
        request=None,
        api_key_granted_permissions=frozenset(Permission),
    )
    assert allowed is False, (
        f"Broad-scope API key must still be denied platform action {action.name!r}"
    )


# ---------------------------------------------------------------------------
# Scenario 5: non-superuser session user → denied (control)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("action", _SUPERUSER_ACTIONS, ids=_ACTION_NAMES)
def test_non_superuser_session_user_denied_superuser_actions(action: Action) -> None:
    """A non-superuser session caller is also denied (control scenario)."""
    session_user = _make_session_user(is_superuser=False)
    project = _make_project()
    allowed, _ = is_allowed(
        action=action,
        user=session_user,
        project=project,
        request=None,
    )
    assert allowed is False, (
        f"Non-superuser session user must be denied {action.name!r}"
    )


# ---------------------------------------------------------------------------
# Scenario 6: superuser session user → allowed (positive control)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("action", _SUPERUSER_ACTIONS, ids=_ACTION_NAMES)
def test_superuser_session_user_allowed_on_platform_actions(action: Action) -> None:
    """An authenticated superuser session IS allowed on platform actions.

    This is the positive control: ``is_superuser=True`` is stamped only
    for first-party session callers (cookie / JWT), never for API key
    paths.
    """
    session_su = _make_session_user(is_superuser=True)
    project = _make_project()
    allowed, _ = is_allowed(
        action=action,
        user=session_su,
        project=project,
        request=None,
    )
    assert allowed is True, (
        f"Authenticated superuser session must be allowed on {action.name!r}"
    )


# ---------------------------------------------------------------------------
# Edge: anonymous (None) caller is always denied
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("action", _SUPERUSER_ACTIONS, ids=_ACTION_NAMES)
def test_anonymous_caller_denied_superuser_actions(action: Action) -> None:
    """Unauthenticated (None) callers MUST be denied platform-scope actions."""
    project = _make_project()
    allowed, _ = is_allowed(
        action=action,
        user=None,
        project=project,
        request=None,
    )
    assert allowed is False, (
        f"Anonymous caller must be denied platform-scope action {action.name!r}"
    )


# ---------------------------------------------------------------------------
# Structural: all superuser platform actions are flagged correctly
# ---------------------------------------------------------------------------


def test_all_superuser_actions_flagged_platform_scope() -> None:
    """Superuser engine actions must carry is_platform_scope=True + is_superuser_only=True."""
    for action in _SUPERUSER_ACTIONS:
        assert action.is_platform_scope is True, (
            f"{action.name!r} must have is_platform_scope=True (FR-084)"
        )
        assert action.is_superuser_only is True, (
            f"{action.name!r} must have is_superuser_only=True (FR-084)"
        )
        assert action.required_permission is None, (
            f"{action.name!r} platform-scope action must have required_permission=None"
        )

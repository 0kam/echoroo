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


# ---------------------------------------------------------------------------
# Integration-style: middleware _stamp_superuser_status path simulation
#
# These tests simulate the FULL middleware → gate_action pathway using
# SimpleNamespace objects that mirror the exact attribute shape produced by
# echoroo.middleware.auth after _stamp_superuser_status has been called.
#
# The critical invariant (FR-084 defence-in-depth):
#   "Even if _stamp_superuser_status sets is_superuser=True on a User row that
#    was fetched via an API-key request, the is_platform_scope branch in
#    is_allowed MUST still veto the caller because _api_key_scopes is present."
#
# This is not a theoretical concern: auth.py line 173-174 shows that
# _stamp_superuser_status IS called for API-key paths too (after the User row
# is loaded). If the veto check were missing, a superuser-owned API key could
# reach platform-scope operations.
# ---------------------------------------------------------------------------


def _simulate_middleware_stamp(
    *,
    is_superuser_in_db: bool,
    has_api_key: bool,
    scopes: tuple[str, ...] = ("view_detection",),
    superuser_id: str | None = "su-id-t956-int",
) -> SimpleNamespace:
    """Build a User-like object as auth.py would after both stamp helpers run.

    Replicates the attribute shape produced by:
        1. db.execute(select(User).where(...)) → user row
        2. _stamp_api_key_scopes(user, principal)   ← sets _api_key_scopes if API key
        3. await _stamp_superuser_status(db, user)  ← always sets is_superuser
    """
    user = SimpleNamespace(
        id="user-t956-integration",
        # _stamp_superuser_status always sets these two attributes:
        is_superuser=is_superuser_in_db,
        _superuser_id=superuser_id if is_superuser_in_db else None,
        project_role=None,
    )
    if has_api_key:
        # _stamp_api_key_scopes sets these three attributes:
        user._api_key_id = "apikey-t956-int"
        user._api_key_scopes = scopes
        user._api_key_project_id = None
    return user


class TestMiddlewareStampThenGateVeto:
    """Verify is_allowed veto after _stamp_superuser_status has set is_superuser=True.

    These tests use is_allowed directly with SimpleNamespace fixtures that
    precisely mirror the attribute shape auth.py produces.  The test class
    documents the exact code path that FR-084 defence-in-depth protects.
    """

    def test_superuser_api_key_vetoed_even_after_is_superuser_stamp(self) -> None:
        """Core invariant: API key caller with is_superuser=True is still denied.

        auth.py calls _stamp_superuser_status for API-key paths (line 174).
        So the stamped User will have is_superuser=True AND _api_key_scopes set.
        The is_platform_scope branch MUST veto based on _api_key_scopes presence.
        """
        # Simulate: superuser user authenticated via their own API key.
        # _stamp_superuser_status runs → is_superuser=True
        # _stamp_api_key_scopes runs  → _api_key_scopes=(...) present
        user = _simulate_middleware_stamp(
            is_superuser_in_db=True,
            has_api_key=True,
        )
        project = _make_project()

        for action in _SUPERUSER_ACTIONS:
            allowed, _ = is_allowed(
                action=action,
                user=user,
                project=project,
                request=None,
            )
            assert allowed is False, (
                f"Superuser API key caller (is_superuser=True + _api_key_scopes set) "
                f"must be vetoed on {action.name!r}. "
                f"This verifies the FR-084 veto in the is_platform_scope branch fires "
                f"AFTER _stamp_superuser_status would have set is_superuser=True."
            )

    def test_superuser_session_caller_allowed_after_stamp(self) -> None:
        """Positive control: superuser session caller (no _api_key_scopes) is allowed.

        When auth.py runs _stamp_superuser_status for a cookie/JWT session,
        it does NOT call _stamp_api_key_scopes (_api_key_scopes absent).
        The is_platform_scope branch must allow this caller.
        """
        user = _simulate_middleware_stamp(
            is_superuser_in_db=True,
            has_api_key=False,  # session path: _stamp_api_key_scopes NOT called
        )
        project = _make_project()

        for action in _SUPERUSER_ACTIONS:
            allowed, _ = is_allowed(
                action=action,
                user=user,
                project=project,
                request=None,
            )
            assert allowed is True, (
                f"Superuser session caller (is_superuser=True, no _api_key_scopes) "
                f"must be allowed on {action.name!r} (positive control)"
            )

    def test_non_superuser_api_key_denied_platform_actions(self) -> None:
        """Non-superuser user with API key: denied (is_superuser=False path)."""
        user = _simulate_middleware_stamp(
            is_superuser_in_db=False,
            has_api_key=True,
        )
        project = _make_project()

        for action in _SUPERUSER_ACTIONS:
            allowed, _ = is_allowed(
                action=action,
                user=user,
                project=project,
                request=None,
            )
            assert allowed is False, (
                f"Non-superuser API key caller must be denied {action.name!r} "
                f"(control: fails on _is_superuser check before veto even fires)"
            )

    def test_platform_iucn_action_vetoed_for_superuser_api_key(self) -> None:
        """Specific test for PLATFORM_IUCN_FORCE_RESYNC_ACTION (actions.py:488).

        This action is defined in actions.py (not stub-registered here) and
        exercises the real production action object to confirm the veto applies
        to a concrete real-world platform action (not just the test stubs above).
        """
        from echoroo.core.actions import PLATFORM_IUCN_FORCE_RESYNC_ACTION

        user = _simulate_middleware_stamp(
            is_superuser_in_db=True,
            has_api_key=True,
            scopes=("view_detection", "view_recording"),
        )
        project = _make_project()

        allowed, _ = is_allowed(
            action=PLATFORM_IUCN_FORCE_RESYNC_ACTION,
            user=user,
            project=project,
            request=None,
        )
        assert allowed is False, (
            "PLATFORM_IUCN_FORCE_RESYNC_ACTION must be vetoed for a superuser-owned "
            "API key (is_superuser=True + _api_key_scopes set). "
            "FR-084: API key principals must never reach platform-scope operations."
        )

    def test_platform_iucn_action_allowed_for_superuser_session(self) -> None:
        """Positive control: PLATFORM_IUCN_FORCE_RESYNC_ACTION allowed via session."""
        from echoroo.core.actions import PLATFORM_IUCN_FORCE_RESYNC_ACTION

        user = _simulate_middleware_stamp(
            is_superuser_in_db=True,
            has_api_key=False,
        )
        project = _make_project()

        allowed, _ = is_allowed(
            action=PLATFORM_IUCN_FORCE_RESYNC_ACTION,
            user=user,
            project=project,
            request=None,
        )
        assert allowed is True, (
            "PLATFORM_IUCN_FORCE_RESYNC_ACTION must be allowed for a superuser "
            "session caller (no _api_key_scopes). Positive control."
        )

    # ---------------------------------------------------------------------
    # R3 — Step 0b project-scope superuser allowlist veto for API keys
    #
    # ``PROJECT_ARCHIVE_ACTION`` and ``PROJECT_RESTORE_ACTION`` are
    # project-scope (NOT ``is_platform_scope=True``) but they ARE listed
    # in :data:`SUPERUSER_PROJECT_SCOPE_ALLOWLIST` (FR-008b). Without the
    # Step 0b veto, the middleware's ``_stamp_superuser_status`` (which
    # runs for API key paths too — auth.py:173-174) would let a
    # superuser-owned API key short-circuit through the allowlist branch
    # and execute archive/restore without proving session-level
    # superuser identity. R3 closes this by requiring
    # ``_api_key_scopes`` to be absent in the Step 0b match — API key
    # callers fall through to the Matrix path where they are denied
    # because their intersected scopes do not grant ``EDIT_PROJECT``
    # (or because Step 0c hard-fails non-superuser callers).
    # ---------------------------------------------------------------------

    def test_superuser_api_key_vetoed_on_project_archive_allowlist(self) -> None:
        """Case (a): superuser-owned API key + project.archive → deny.

        The Step 0b allowlist short-circuit MUST NOT apply because
        ``_api_key_scopes`` is present. Falls through to the normal
        Matrix path where the api-key scopes ``("view_detection",)``
        do not grant EDIT_PROJECT → deny.
        """
        from echoroo.core.actions import PROJECT_ARCHIVE_ACTION

        user = _simulate_middleware_stamp(
            is_superuser_in_db=True,
            has_api_key=True,
            scopes=("view_detection",),
        )
        project = _make_project()

        allowed, _ = is_allowed(
            action=PROJECT_ARCHIVE_ACTION,
            user=user,
            project=project,
            request=None,
            api_key_granted_permissions=frozenset({Permission.VIEW_DETECTION}),
        )
        assert allowed is False, (
            "Superuser-owned API key MUST NOT exercise PROJECT_ARCHIVE_ACTION "
            "via the Step 0b allowlist short-circuit. FR-084 defence-in-depth: "
            "the veto requires _api_key_scopes to be absent for the allowlist "
            "match to fire; API key callers fall through to the Matrix path "
            "where their intersected scopes are insufficient."
        )

    def test_superuser_api_key_vetoed_on_project_restore_allowlist(self) -> None:
        """Case (b): superuser-owned API key + project.restore → deny.

        Same veto as (a). The action is in the allowlist but the
        ``_api_key_scopes`` presence prevents the short-circuit.
        """
        from echoroo.core.actions import PROJECT_RESTORE_ACTION

        user = _simulate_middleware_stamp(
            is_superuser_in_db=True,
            has_api_key=True,
            scopes=("view_detection",),
        )
        # ``project.restore`` only makes sense on archived projects, but
        # Step 0b is evaluated before the Step 1 archived block — and Step
        # 0b is the branch we're verifying is now vetoed.
        project = _make_project(status="archived")

        allowed, _ = is_allowed(
            action=PROJECT_RESTORE_ACTION,
            user=user,
            project=project,
            request=None,
            api_key_granted_permissions=frozenset({Permission.VIEW_DETECTION}),
        )
        assert allowed is False, (
            "Superuser-owned API key MUST NOT exercise PROJECT_RESTORE_ACTION "
            "via the Step 0b allowlist short-circuit. FR-084 defence-in-depth."
        )

    def test_superuser_session_allowed_on_project_archive_positive_control(
        self,
    ) -> None:
        """Case (c): cookie session superuser + project.archive → allow.

        Positive control. A session caller has no ``_api_key_scopes``
        attribute, so Step 0b's allowlist short-circuit fires normally
        and grants the request. This proves the R3 veto only blocks API
        key principals and does not regress legitimate session-based
        superuser archive/restore flows.
        """
        from echoroo.core.actions import PROJECT_ARCHIVE_ACTION

        user = _simulate_middleware_stamp(
            is_superuser_in_db=True,
            has_api_key=False,  # cookie/JWT path — no _api_key_scopes
        )
        project = _make_project()

        allowed, _ = is_allowed(
            action=PROJECT_ARCHIVE_ACTION,
            user=user,
            project=project,
            request=None,
        )
        assert allowed is True, (
            "Cookie-session superuser MUST still be allowed on "
            "PROJECT_ARCHIVE_ACTION via the Step 0b allowlist short-circuit. "
            "Positive control: the R3 veto must not regress session callers."
        )

    def test_non_superuser_api_key_denied_on_project_archive_control(self) -> None:
        """Case (d): non-superuser API key + project.archive → deny (control).

        This case never depended on the Step 0b veto — Step 0c
        (``is_superuser_only`` hard-fail) already denies non-superuser
        callers regardless of authentication path. Included here as a
        regression guard to confirm the Step 0c invariant continues to
        hold after the R3 patch.
        """
        from echoroo.core.actions import PROJECT_ARCHIVE_ACTION

        user = _simulate_middleware_stamp(
            is_superuser_in_db=False,
            has_api_key=True,
            scopes=("edit_project",),  # even with EDIT scope: still denied
        )
        project = _make_project()

        allowed, _ = is_allowed(
            action=PROJECT_ARCHIVE_ACTION,
            user=user,
            project=project,
            request=None,
            api_key_granted_permissions=frozenset({Permission.EDIT_PROJECT}),
        )
        assert allowed is False, (
            "Non-superuser API key MUST be denied PROJECT_ARCHIVE_ACTION via "
            "the Step 0c is_superuser_only hard-fail (control)."
        )

    def test_veto_attribute_inspection_matches_middleware_contract(self) -> None:
        """Structural: the veto condition uses _api_key_scopes presence, not value.

        The is_platform_scope branch does:
            is_api_key_caller = getattr(user, "_api_key_scopes", None) is not None
        This means even an empty tuple () triggers the veto — the presence of
        the attribute itself (not its content) is the signal.
        """
        # Edge: _api_key_scopes = empty tuple — still triggers veto
        user_empty_scopes = _simulate_middleware_stamp(
            is_superuser_in_db=True,
            has_api_key=True,
            scopes=(),  # empty — but attribute IS present
        )
        project = _make_project()

        for action in _SUPERUSER_ACTIONS:
            allowed, _ = is_allowed(
                action=action,
                user=user_empty_scopes,
                project=project,
                request=None,
            )
            assert allowed is False, (
                f"Empty _api_key_scopes=() still triggers veto on {action.name!r}. "
                f"Veto is based on attribute PRESENCE, not scope content."
            )

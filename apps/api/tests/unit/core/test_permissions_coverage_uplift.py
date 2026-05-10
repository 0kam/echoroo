"""Coverage uplift unit tests for ``echoroo.core.permissions``.

Phase 17 §C easy-win batch 1: targets the small reject / fallback
branches at lines 393, 452, 458, 461, 466-468, 538-539, 637, 816-826,
868, 922, 979-982, 1030, 1137, 1215-1216, 1292, 1321-1322 so the module
clears the 95% permission-critical threshold without touching production
code.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from echoroo.core import permissions as mod
from echoroo.core.permissions import (
    Action,
    Permission,
    ProjectVisibility,
    _ScopedPrincipal,
    _stash_state,
    active_trusted_capabilities,
    check_project_access,
    compute_effective_permissions,
    compute_effective_resolution,
    is_allowed,
    resolve_role,
)
from echoroo.models.enums import ProjectMemberRole


def _project(**kwargs: Any) -> SimpleNamespace:
    """Build a minimal project stand-in."""
    defaults = {
        "id": uuid4(),
        "owner_id": uuid4(),
        "visibility": ProjectVisibility.PUBLIC,
        "status": "active",
        "restricted_config": {},
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _user(**kwargs: Any) -> SimpleNamespace:
    defaults = {
        "id": uuid4(),
        "is_superuser": False,
        "project_role": None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# resolve_role / normalize_role
# ---------------------------------------------------------------------------


def test_resolve_role_returns_guest_when_user_none() -> None:
    """resolve_role(None, project) → 'Guest' (line 393)."""
    assert resolve_role(None, _project()) == "Guest"


# ---------------------------------------------------------------------------
# active_trusted_capabilities
# ---------------------------------------------------------------------------


def test_active_trusted_capabilities_returns_empty_for_no_rows() -> None:
    """active_trusted_capabilities(None) → empty frozenset (line 452)."""
    assert active_trusted_capabilities(None) == frozenset()
    assert active_trusted_capabilities([]) == frozenset()


def test_active_trusted_capabilities_skips_inactive_status() -> None:
    """Rows whose status != 'active' are skipped (line 458)."""
    row = SimpleNamespace(
        status="revoked",
        expires_at=None,
        granted_permissions=[Permission.VOTE],
    )
    assert active_trusted_capabilities([row]) == frozenset()


def test_active_trusted_capabilities_skips_expired_rows() -> None:
    """Expired rows (expires_at <= now) are skipped (line 461)."""
    past = datetime.now(UTC) - timedelta(days=1)
    row = SimpleNamespace(
        status="active",
        expires_at=past,
        granted_permissions=[Permission.VOTE],
    )
    assert (
        active_trusted_capabilities([row], now_utc=datetime.now(UTC))
        == frozenset()
    )


def test_active_trusted_capabilities_drops_unknown_permission_strings() -> None:
    """Unknown permission strings in granted_permissions are dropped silently
    (lines 466-468).
    """
    row = SimpleNamespace(
        status="active",
        expires_at=None,
        granted_permissions=["totally_not_a_real_permission"],
    )
    assert active_trusted_capabilities([row]) == frozenset()


def test_active_trusted_capabilities_returns_intersection_with_allowlist() -> None:
    """Granted permissions are intersected with TRUSTED_ALLOWED_PERMISSIONS."""
    row = SimpleNamespace(
        status="active",
        expires_at=None,
        granted_permissions=[Permission.VOTE],
    )
    out = active_trusted_capabilities([row])
    assert Permission.VOTE in out


# ---------------------------------------------------------------------------
# compute_effective_permissions — Superuser branch
# ---------------------------------------------------------------------------


def test_compute_effective_permissions_includes_superuser_perms() -> None:
    """Superuser role unions in _SUPERUSER_PERMS (lines 538-539)."""
    project = _project()
    out = compute_effective_permissions(
        normalized_role="Superuser",
        project=project,
    )
    # _SUPERUSER_PERMS == _OWNER_PERMS — assert via Owner-tier permissions.
    assert Permission.DELETE_PROJECT in out
    assert Permission.MANAGE_MEMBERS in out


# ---------------------------------------------------------------------------
# compute_effective_resolution — override.direction unknown branch (line 637)
# ---------------------------------------------------------------------------


def test_compute_effective_resolution_unknown_direction_falls_back() -> None:
    """When override.direction is neither LOOSER nor STRICTER, effective_global
    falls back to the global value (line 637).
    """
    taxon_id = uuid4()
    project = _project(visibility=ProjectVisibility.PUBLIC)
    resource = SimpleNamespace(taxon_id=taxon_id, h3_index_member_resolution=15)
    override = SimpleNamespace(
        direction="UNKNOWN_DIRECTION",
        approval_status=None,
        sensitivity_h3_res=7,
    )
    out = compute_effective_resolution(
        resource=resource,
        role="Guest",
        project=project,
        taxon_sensitivity_map={taxon_id: 9},
        override_map={(project.id, taxon_id): override},
    )
    # Guest sees Public ceiling (H3_RES_9) intersected with global (9) → 9.
    assert out == 9


# ---------------------------------------------------------------------------
# is_allowed — superuser_only + project None branches
# ---------------------------------------------------------------------------


def _action(
    *,
    name: str = "test.action",
    required_permission: Permission | None = Permission.EDIT_PROJECT,
    is_mutating: bool = True,
    is_superuser_only: bool = False,
) -> Action:
    return Action(
        name=name,
        required_permission=required_permission,
        is_mutating=is_mutating,
        is_superuser_only=is_superuser_only,
    )


def test_is_allowed_rejects_superuser_only_action_for_non_superuser() -> None:
    """Non-superusers always lose on is_superuser_only actions
    (lines 815-817).
    """
    user = _user(is_superuser=False)
    project = _project()
    action = _action(is_superuser_only=True)
    request = MagicMock()
    request.state = SimpleNamespace()
    allowed, effective = is_allowed(
        action=action, user=user, project=project, request=request
    )
    assert allowed is False
    assert effective == frozenset()


def test_is_allowed_rejects_when_project_required_but_none() -> None:
    """Project-scope actions with project=None return (False, frozenset())
    (lines 820-821).
    """
    user = _user()
    action = _action(is_superuser_only=False)
    request = MagicMock()
    request.state = SimpleNamespace()
    allowed, effective = is_allowed(
        action=action, user=user, project=None, request=request
    )
    assert allowed is False
    assert effective == frozenset()


def test_is_allowed_blocks_archived_project_mutations() -> None:
    """Archived projects reject any mutating action (lines 824-826)."""
    user = _user()
    project = _project(status="archived", owner_id=user.id)
    action = _action(is_mutating=True)
    request = MagicMock()
    request.state = SimpleNamespace()
    allowed, _ = is_allowed(
        action=action, user=user, project=project, request=request
    )
    assert allowed is False


def test_is_allowed_search_cross_project_denied_for_guest() -> None:
    """Guest is denied SEARCH_CROSS_PROJECT (line 868)."""
    project = _project()
    action = _action(
        required_permission=Permission.SEARCH_CROSS_PROJECT,
        is_mutating=False,
    )
    request = MagicMock()
    request.state = SimpleNamespace()
    allowed, _ = is_allowed(
        action=action, user=None, project=project, request=request
    )
    assert allowed is False


# ---------------------------------------------------------------------------
# _stash_state — request.state is None / missing branch
# ---------------------------------------------------------------------------


def test_stash_state_no_op_when_state_missing() -> None:
    """_stash_state returns silently when request.state is None (line 922)."""
    request = SimpleNamespace(state=None)
    _stash_state(request, effective=frozenset(), normalized_role="Guest")  # no-op
    assert request.state is None


def test_stash_state_no_op_when_request_none() -> None:
    """_stash_state returns silently when request is None (line 919)."""
    _stash_state(None, effective=frozenset(), normalized_role="Guest")


# ---------------------------------------------------------------------------
# _resolve_project_member_role — string coerce + ValueError fallback
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_project_member_role_coerces_string_value() -> None:
    """A driver returning the role as a string is coerced to ProjectMemberRole
    (line 980).
    """
    db = MagicMock()
    fake_result = MagicMock()
    fake_result.scalar_one_or_none.return_value = "ADMIN"
    db.execute = AsyncMock(return_value=fake_result)

    role = await mod._resolve_project_member_role(
        db, project_id=uuid4(), user_id=uuid4()
    )
    assert role == ProjectMemberRole.ADMIN


@pytest.mark.asyncio
async def test_resolve_project_member_role_returns_none_for_invalid_string() -> None:
    """An invalid role string returns None instead of raising (lines 981-982)."""
    db = MagicMock()
    fake_result = MagicMock()
    fake_result.scalar_one_or_none.return_value = "not-a-real-role"
    db.execute = AsyncMock(return_value=fake_result)

    role = await mod._resolve_project_member_role(
        db, project_id=uuid4(), user_id=uuid4()
    )
    assert role is None


# ---------------------------------------------------------------------------
# _ScopedPrincipal immutability (line 1030)
# ---------------------------------------------------------------------------


def test_scoped_principal_is_immutable() -> None:
    """Setting an arbitrary attribute on _ScopedPrincipal raises AttributeError
    (line 1030).
    """
    inner = SimpleNamespace(id=uuid4())
    sp = _ScopedPrincipal(inner, ProjectMemberRole.ADMIN)
    assert sp.project_role == ProjectMemberRole.ADMIN
    assert sp.id == inner.id
    with pytest.raises(AttributeError):
        sp.something_new = "leak"


# ---------------------------------------------------------------------------
# decide_action_permission — refresh_api_key_scopes + project_missing branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_decide_action_permission_returns_project_missing_for_refresh_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When refresh_api_key_scopes=True and the project is missing, the
    function returns a project_missing decision (lines 1136-1141).
    """
    db = MagicMock()
    fake_result = MagicMock()
    fake_result.scalar_one_or_none.return_value = None
    db.execute = AsyncMock(return_value=fake_result)

    user = _user()
    action = _action()
    request = MagicMock()
    request.state = SimpleNamespace()

    decision = await mod.decide_action_permission(
        db=db,
        action=action,
        project_id=uuid4(),
        current_user=user,
        request=request,
        refresh_api_key_scopes=True,
    )
    assert decision.allowed is False
    assert decision.reason == "project_missing"


# ---------------------------------------------------------------------------
# decide_action_permission — _api_key_scopes ValueError branch (line 1215-1216)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_key_scope_translation_drops_unknown_permission_names(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown scope names are silently dropped during translation (lines 1215-1216).

    Exercises the production ``decide_action_permission`` HTTP-time path
    (``refresh_api_key_scopes=False``) with an API-key principal whose
    ``_api_key_scopes`` mixes a known and an unknown scope. The unknown
    scope MUST be silently dropped (the ``ValueError`` branch at lines
    1215-1216 of ``permissions.py``) and only the known one MUST survive
    into the ``is_allowed`` call as ``api_key_granted_permissions``.
    """
    project_owner_id = uuid4()
    project = _project(owner_id=project_owner_id)

    # Patch the project loader so we never hit the database.
    async def _fake_load_project_or_404(_db: Any, _pid: UUID) -> Any:
        return project

    monkeypatch.setattr(mod, "load_project_or_404", _fake_load_project_or_404)

    # Patch the membership lookup so the principal is treated as a
    # non-member, non-owner Authenticated caller (the only path that
    # reaches the API-key scope translation block).
    async def _fake_resolve_role(*_a: Any, **_kw: Any) -> Any:
        return None

    monkeypatch.setattr(mod, "_resolve_project_member_role", _fake_resolve_role)

    # Patch the trusted overlay so we don't hit a DB-backed import.
    async def _fake_get_trusted(*_a: Any, **_kw: Any) -> frozenset[Permission]:
        return frozenset()

    import echoroo.services.trusted_service as trusted_service

    monkeypatch.setattr(
        trusted_service,
        "get_active_trusted_capabilities",
        _fake_get_trusted,
    )

    # Capture the kwargs handed to ``is_allowed`` so we can assert that
    # the unknown scope was dropped and only ``VIEW_DETECTION`` survived.
    captured: dict[str, Any] = {}

    def _fake_is_allowed(
        *,
        action: Action,
        user: Any,
        project: Any,
        request: Any,
        trusted_capabilities: frozenset[Permission] = frozenset(),
        api_key_granted_permissions: frozenset[Permission] | None = None,
    ) -> tuple[bool, frozenset[Permission]]:
        captured["api_key_granted_permissions"] = api_key_granted_permissions
        return True, frozenset()

    monkeypatch.setattr(mod, "is_allowed", _fake_is_allowed)

    # Authenticated, non-owner, non-superuser caller carrying API-key
    # scopes (one valid, one unknown) — exactly the shape stamped by
    # the auth router for an ``/api/v1`` Bearer caller.
    user = _user(is_superuser=False)
    user._api_key_scopes = ["view_detection", "totally_unknown_scope"]

    action = _action(
        required_permission=Permission.VIEW_DETECTION,
        is_mutating=False,
    )
    request = MagicMock()
    request.state = SimpleNamespace()

    decision = await mod.decide_action_permission(
        db=MagicMock(),
        action=action,
        project_id=project.id,
        current_user=user,
        request=request,
        refresh_api_key_scopes=False,
    )

    assert decision.allowed is True
    # The unknown scope name MUST have been silently dropped — only
    # ``VIEW_DETECTION`` reached ``is_allowed``.
    assert captured["api_key_granted_permissions"] == frozenset(
        {Permission.VIEW_DETECTION}
    )


# ---------------------------------------------------------------------------
# gate_action — project_missing → 404 (line 1292)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_action_translates_project_missing_to_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """gate_action surfaces project_missing as a 404 (line 1292)."""
    fake_decision = mod.PermissionDecision(
        allowed=False,
        project=None,
        reason="project_missing",
    )
    monkeypatch.setattr(
        mod, "decide_action_permission", AsyncMock(return_value=fake_decision)
    )
    with pytest.raises(HTTPException) as excinfo:
        await mod.gate_action(
            action=_action(),
            project_id=uuid4(),
            current_user=_user(),
            request=MagicMock(),
            db=MagicMock(),
        )
    assert excinfo.value.status_code == 404


# ---------------------------------------------------------------------------
# check_project_access — 403 when not a member (lines 1321-1322)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_check_project_access_raises_403_when_no_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """check_project_access raises HTTP 403 when has_project_access is False
    (lines 1321-1322).
    """
    db = MagicMock()
    fake_repo = MagicMock()
    fake_repo.has_project_access = AsyncMock(return_value=False)
    monkeypatch.setattr(
        "echoroo.repositories.project.ProjectRepository",
        lambda _db: fake_repo,
    )
    with pytest.raises(HTTPException) as excinfo:
        await check_project_access(uuid4(), uuid4(), db)
    assert excinfo.value.status_code == 403


@pytest.mark.asyncio
async def test_check_project_access_returns_when_user_has_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """check_project_access returns silently when the user has access."""
    db = MagicMock()
    fake_repo = MagicMock()
    fake_repo.has_project_access = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "echoroo.repositories.project.ProjectRepository",
        lambda _db: fake_repo,
    )
    await check_project_access(uuid4(), uuid4(), db)  # should not raise

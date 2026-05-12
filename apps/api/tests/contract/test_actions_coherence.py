"""Coherence contract tests for the ACTIONS catalog (spec/007 Phase 3 AD-4).

Validates structural invariants between:
- The ACTIONS catalog (echoroo.core.actions)
- The ROLE_PERMISSIONS canonical matrix
- Permission category classification (AD-8)
- Route HTTP methods (via FastAPI app reflection + AST scan)

10 test classes covering all AD-4 checks plus the AD-8 SEARCH_CROSS_PROJECT
tightening verification.

Note: The AST guard scan reuses _handler_invokes_guard from
tests.security.authorization.test_endpoint_coverage. Route-to-action mapping
(classes 3, 6, 7, 9) walks handler source for gate_action(<ACTION>, ...)
calls to associate the action's name with the HTTP method.
"""
from __future__ import annotations

import ast
import inspect
import re
import textwrap
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

import echoroo.core.actions  # noqa: F401 — side-effect: fills ACTIONS catalog
from echoroo.core.permissions import (
    ACTIONS,
    ENDPOINT_BACKED_PERMISSIONS,
    ROLE_PERMISSIONS,
    SUPERUSER_ONLY_PERMISSIONS,
    USER_SCOPE_PERMISSIONS,
    Action,
    Permission,
    ProjectVisibility,
    compute_effective_permissions,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_GUARD_CALLABLE_NAMES: frozenset[str] = frozenset({
    "gate_action",
    "check_action",
    "require_permission",
    "is_allowed",
    "check_project_access",
    "_require_authenticated_superuser",
    "_require_authenticated",
    "accept_invitation",
    "decline_invitation_by_recipient",
})

_SUPERUSER_GUARD_NAMES: frozenset[str] = frozenset({
    "CurrentSuperuser",
    "get_current_active_superuser",
    "_require_authenticated_superuser",
})

# Permissions in the Canonical Matrix across all roles (union of all role perms).
_ALL_MATRIX_PERMISSIONS: frozenset[Permission] = frozenset().union(
    *ROLE_PERMISSIONS.values()
)


def _handler_source(handler: object) -> str | None:
    """Return dedented handler source or None if unavailable."""
    try:
        source = inspect.getsource(handler)
    except (OSError, TypeError):
        return None
    return textwrap.dedent(source)


def _handler_invokes_guard(handler: object) -> bool:
    """Return True if handler body calls any permission guard helper."""
    source = _handler_source(handler)
    if source is None:
        return False
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name: str | None = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name in _GUARD_CALLABLE_NAMES:
                return True
    return False


def _handler_invokes_superuser_guard(handler: object) -> bool:
    """Return True if handler type-annotation or body references CurrentSuperuser."""
    source = _handler_source(handler)
    if source is None:
        return False
    return any(guard_name in source for guard_name in _SUPERUSER_GUARD_NAMES)


@pytest.fixture(scope="module")
def app() -> FastAPI:
    """Build the real FastAPI app for route reflection."""
    from echoroo.main import create_app
    return create_app()


@pytest.fixture(scope="module")
def action_to_http_methods(app: FastAPI) -> dict[str, set[str]]:
    """Map action name -> set of HTTP methods from routes that call gate_action(ACTION).

    Uses AST scan: walks each route handler's source for gate_action(...)
    call-sites. Extracts the first argument (which should be an Action
    constant imported from echoroo.core.actions) and associates the action
    name with the route's HTTP method(s).

    This is Option B per spec/007 Codex consultation — we do NOT add
    path/method fields to Action.
    """
    mapping: dict[str, set[str]] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        source = _handler_source(route.endpoint)
        if source is None:
            continue
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name: str | None = None
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            if name not in ("gate_action", "check_action"):
                continue
            # First positional argument should be the ACTION variable.
            if not node.args:
                continue
            arg = node.args[0]
            # Could be a Name (e.g. DETECTION_LIST_ACTION) or Attribute.
            action_var: str | None = None
            if isinstance(arg, ast.Name):
                action_var = arg.id
            elif isinstance(arg, ast.Attribute):
                action_var = arg.attr
            if action_var is None:
                continue
            # Resolve variable to an Action via the actions module namespace.
            action_obj = getattr(echoroo.core.actions, action_var, None)
            if not isinstance(action_obj, Action):
                continue
            action_name = action_obj.name
            methods = route.methods or set()
            mapping.setdefault(action_name, set()).update(methods)

    return mapping


# ---------------------------------------------------------------------------
# Test class 1: Every Action's required_permission is in the matrix or a
# known exempt category.
# ---------------------------------------------------------------------------


class TestEveryActionPermissionInMatrix:
    """AD-4 class 1: every project-scope Action's required_permission appears
    in ROLE_PERMISSIONS for at least one role, or in USER_SCOPE_PERMISSIONS
    or SUPERUSER_ONLY_PERMISSIONS.

    Catches typos and permissions removed from the matrix without updating
    the ACTIONS catalog.
    """

    def test_all_project_scope_actions_permission_in_matrix_or_exempt(self) -> None:
        violations: list[str] = []
        for name, action in ACTIONS.items():
            if action.is_platform_scope:
                continue  # platform-scope has required_permission=None by design
            perm = action.required_permission
            if perm is None:
                # project-scope should always have a permission (model validator
                # enforces this, but test makes it explicit)
                violations.append(f"{name}: required_permission is None")
                continue
            in_matrix = any(perm in role_perms for role_perms in ROLE_PERMISSIONS.values())
            in_user_scope = perm in USER_SCOPE_PERMISSIONS
            in_superuser_only = perm in SUPERUSER_ONLY_PERMISSIONS
            if not (in_matrix or in_user_scope or in_superuser_only):
                violations.append(
                    f"{name}: required_permission={perm!r} not found in any role's "
                    f"ROLE_PERMISSIONS row, USER_SCOPE_PERMISSIONS, or "
                    f"SUPERUSER_ONLY_PERMISSIONS"
                )
        assert not violations, (
            "Actions with unrecognised required_permission (AD-4 coherence):\n  - "
            + "\n  - ".join(violations)
        )


# ---------------------------------------------------------------------------
# Test class 2: Every ENDPOINT_BACKED_PERMISSIONS member is covered by >=1 Action.
# ---------------------------------------------------------------------------


class TestAllEndpointBackedPermissionsCoveredByActions:
    """AD-4 class 2: every Permission in ENDPOINT_BACKED_PERMISSIONS must appear
    as required_permission on at least one registered Action.

    Forces full coverage: if a permission exists in the enum and is classified
    as endpoint-backed, a route MUST back it.

    Known gap (xfail): SEARCH_CROSS_PROJECT is in ENDPOINT_BACKED_PERMISSIONS
    per AD-8 reclassification, but the ACTIONS catalog currently has no Action
    with required_permission=SEARCH_CROSS_PROJECT. The search gate uses
    compute_effective_permissions() directly (not gate_action) so the cross-
    project search endpoint does not need an Action entry. This gap is tracked
    as a follow-on task for spec/008-permissions-vocabulary-refinement.
    """

    # Permissions that are endpoint-backed by category but do not currently
    # have a dedicated Action entry (known gaps, tracked for follow-up).
    _KNOWN_GAPS: frozenset[Permission] = frozenset({
        Permission.SEARCH_CROSS_PROJECT,  # search gate uses compute_effective_permissions directly
    })

    def test_all_endpoint_backed_permissions_have_an_action(self) -> None:
        action_permissions: set[Permission] = {
            action.required_permission
            for action in ACTIONS.values()
            if action.required_permission is not None
        }
        missing: list[str] = []
        for perm in sorted(ENDPOINT_BACKED_PERMISSIONS, key=lambda p: p.value):
            if perm in self._KNOWN_GAPS:
                continue
            if perm not in action_permissions:
                missing.append(perm.value)
        assert not missing, (
            "ENDPOINT_BACKED_PERMISSIONS with no Action (AD-4 coverage gap):\n  - "
            + "\n  - ".join(missing)
        )

    @pytest.mark.xfail(
        reason=(
            "SEARCH_CROSS_PROJECT is ENDPOINT_BACKED per AD-8 but has no Action "
            "entry — search gate uses compute_effective_permissions() directly. "
            "Tracked for spec/008 follow-up."
        ),
        strict=True,
    )
    def test_search_cross_project_known_gap(self) -> None:
        """Document the known SEARCH_CROSS_PROJECT Action gap (xfail strict)."""
        action_permissions: set[Permission] = {
            action.required_permission
            for action in ACTIONS.values()
            if action.required_permission is not None
        }
        assert Permission.SEARCH_CROSS_PROJECT in action_permissions, (
            "Expected to fail: SEARCH_CROSS_PROJECT has no Action entry (known gap)"
        )


# ---------------------------------------------------------------------------
# Test class 3: Superuser-only Actions are consistent with AST scan.
# ---------------------------------------------------------------------------


class TestSuperuserOnlyActionsConsistent:
    """AD-4 class 3: every Action with is_superuser_only=True must:
    - have required_permission in SUPERUSER_ONLY_PERMISSIONS (or None if platform-scope)
    - be backed by a route whose handler references a CurrentSuperuser-style dependency.

    Note: SUPERUSER_ONLY_PERMISSIONS currently contains only MANAGE_SITE.
    Project-scope superuser actions (archive/restore/taxon_override) use
    EDIT_PROJECT as a sentinel — the matrix-level restriction comes from
    is_superuser_only=True gate enforcement, not from the permission category.
    Those actions are exempt from the required_permission category check but
    still subject to the AST dependency check.
    """

    def test_platform_scope_superuser_actions_have_no_required_permission(
        self,
    ) -> None:
        violations: list[str] = []
        for name, action in ACTIONS.items():
            if action.is_platform_scope and action.is_superuser_only and action.required_permission is not None:
                violations.append(
                    f"{name}: is_platform_scope=True but required_permission={action.required_permission!r}"
                )
        assert not violations, (
            "Platform-scope superuser actions must have required_permission=None:\n  - "
            + "\n  - ".join(violations)
        )

    def test_superuser_only_actions_backed_by_superuser_route(self, app: FastAPI) -> None:
        """Routes backing is_superuser_only actions reference CurrentSuperuser."""
        # Build action-name -> handler mapping via gate_action AST scan.
        action_to_handler: dict[str, object] = {}
        for route in app.routes:
            if not isinstance(route, APIRoute):
                continue
            source = _handler_source(route.endpoint)
            if source is None:
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                fname: str | None = None
                if isinstance(func, ast.Name):
                    fname = func.id
                elif isinstance(func, ast.Attribute):
                    fname = func.attr
                if fname not in ("gate_action", "check_action"):
                    continue
                if not node.args:
                    continue
                arg = node.args[0]
                action_var: str | None = None
                if isinstance(arg, ast.Name):
                    action_var = arg.id
                elif isinstance(arg, ast.Attribute):
                    action_var = arg.attr
                if action_var is None:
                    continue
                action_obj = getattr(echoroo.core.actions, action_var, None)
                if isinstance(action_obj, Action):
                    action_to_handler[action_obj.name] = route.endpoint

        violations: list[str] = []
        for name, action in ACTIONS.items():
            if not action.is_superuser_only:
                continue
            handler = action_to_handler.get(name)
            if handler is None:
                # Action registered but no route found via gate_action scan —
                # could be a platform-scope action on the admin router using
                # CurrentSuperuser directly. We skip missing mappings to avoid
                # false positives; test_superuser_platform_scope covers these.
                continue
            if not _handler_invokes_superuser_guard(handler):
                violations.append(
                    f"{name}: is_superuser_only=True but handler does not "
                    f"reference CurrentSuperuser / _require_authenticated_superuser"
                )
        assert not violations, (
            "is_superuser_only Actions without superuser dependency (AD-4 class 3):\n  - "
            + "\n  - ".join(violations)
        )


# ---------------------------------------------------------------------------
# Test class 4: Every permission key in ROLE_PERMISSIONS is a Permission enum member.
# ---------------------------------------------------------------------------


class TestRolePermissionsSubsetOfEnum:
    """AD-4 class 4: every permission in ROLE_PERMISSIONS must be a valid
    Permission enum member. Guards against drift after enum renames.
    """

    def test_all_role_permission_entries_are_valid_enum_members(self) -> None:
        valid_values = set(Permission)
        violations: list[str] = []
        for role, perms in ROLE_PERMISSIONS.items():
            for perm in perms:
                if perm not in valid_values:
                    violations.append(f"{role.value}: {perm!r} not in Permission enum")
        assert not violations, (
            "Invalid Permission entries in ROLE_PERMISSIONS:\n  - "
            + "\n  - ".join(violations)
        )


# ---------------------------------------------------------------------------
# Test class 5: No duplicate action names.
# ---------------------------------------------------------------------------


class TestNoDuplicateActionNames:
    """AD-4 class 5: Action name field is unique across the catalog.

    ACTIONS dict already enforces this via dict key, but this test makes the
    contract explicit and verifiable without relying on dict collision behaviour.
    """

    def test_action_names_are_unique(self) -> None:
        names = list(ACTIONS.keys())
        assert len(names) == len(set(names)), (
            f"Duplicate action names detected: "
            f"{[n for n in names if names.count(n) > 1]}"
        )

    def test_action_name_matches_dict_key(self) -> None:
        """Each Action's .name field must equal its dict key."""
        mismatches: list[str] = []
        for key, action in ACTIONS.items():
            if key != action.name:
                mismatches.append(f"key={key!r} != action.name={action.name!r}")
        assert not mismatches, (
            "ACTIONS key / action.name mismatches:\n  - "
            + "\n  - ".join(mismatches)
        )


# ---------------------------------------------------------------------------
# Test class 6: Mutating actions have POST/PUT/PATCH/DELETE HTTP method.
# ---------------------------------------------------------------------------


class TestMutatingActionsHaveMutatingHttpMethod:
    """AD-4 class 6: every Action with is_mutating=True must be bound to a
    route whose HTTP method is one of POST, PUT, PATCH, DELETE.

    Uses the action_to_http_methods fixture (gate_action AST scan).
    """

    _MUTATING_METHODS: frozenset[str] = frozenset({"POST", "PUT", "PATCH", "DELETE"})

    def test_mutating_actions_have_mutating_http_methods(
        self, action_to_http_methods: dict[str, set[str]]
    ) -> None:
        violations: list[str] = []
        for name, action in ACTIONS.items():
            if not action.is_mutating:
                continue
            methods = action_to_http_methods.get(name)
            if methods is None:
                # Action not found in any gate_action call — cannot verify.
                continue
            non_mutating = methods - self._MUTATING_METHODS
            if non_mutating and not (methods & self._MUTATING_METHODS):
                # Bound ONLY to non-mutating methods.
                violations.append(
                    f"{name}: is_mutating=True but HTTP methods are {sorted(methods)}"
                )
        assert not violations, (
            "Mutating Actions on non-mutating HTTP methods (AD-4 class 6):\n  - "
            + "\n  - ".join(violations)
        )


# ---------------------------------------------------------------------------
# Test class 7: Read-only actions have GET (or HEAD) HTTP method.
# ---------------------------------------------------------------------------


class TestReadActionsHaveReadHttpMethod:
    """AD-4 class 7: Action with is_mutating=False and required_permission in
    a read-only category MUST be bound to GET (or HEAD).

    Exempt: search session creation (POST that semantically reads).
    """

    _READ_ONLY_PERMISSIONS: frozenset[Permission] = frozenset({
        Permission.VIEW_PROJECT_METADATA,
        Permission.VIEW_DATASET_LIST,
        Permission.VIEW_MEDIA,
        Permission.VIEW_DETECTION,
        Permission.VIEW_PRECISE_LOCATION,
        Permission.VIEW_AUDIT_LOG,
        Permission.SEARCH_WITHIN_PROJECT,
        Permission.SEARCH_CROSS_PROJECT,
    })

    # Search session/batch creation are POST but semantically read operations.
    _EXEMPT_ACTION_NAME_PREFIXES: tuple[str, ...] = (
        "search.session",
        "search.batch",
        "search.similarity",
        "search.cross",
    )

    def _is_exempt(self, action_name: str) -> bool:
        return any(
            action_name.startswith(prefix)
            for prefix in self._EXEMPT_ACTION_NAME_PREFIXES
        )

    def test_read_actions_have_get_or_head_method(
        self, action_to_http_methods: dict[str, set[str]]
    ) -> None:
        violations: list[str] = []
        for name, action in ACTIONS.items():
            if action.is_mutating:
                continue
            perm = action.required_permission
            if perm not in self._READ_ONLY_PERMISSIONS:
                continue
            if self._is_exempt(name):
                continue
            methods = action_to_http_methods.get(name)
            if methods is None:
                continue
            if not (methods & {"GET", "HEAD"}):
                violations.append(
                    f"{name}: read-only action but HTTP methods are {sorted(methods)}"
                )
        assert not violations, (
            "Read-only Actions not bound to GET/HEAD (AD-4 class 7):\n  - "
            + "\n  - ".join(violations)
        )


# ---------------------------------------------------------------------------
# Test class 8: Superuser-only and platform-scope mutual exclusivity rules.
# ---------------------------------------------------------------------------


class TestSuperuserAndPlatformScopeMutuallyExclusive:
    """AD-4 class 8: invariants about is_superuser_only + is_platform_scope
    + required_permission combinations.

    - is_platform_scope=True => required_permission must be None
    - is_platform_scope=True => is_superuser_only must be True
    - is_platform_scope=False + is_superuser_only=False => required_permission
      must be set (enforced by model validator, but explicit here)
    """

    def test_platform_scope_implies_superuser_only(self) -> None:
        violations: list[str] = []
        for name, action in ACTIONS.items():
            if action.is_platform_scope and not action.is_superuser_only:
                violations.append(name)
        assert not violations, (
            "is_platform_scope=True but is_superuser_only=False:\n  - "
            + "\n  - ".join(violations)
        )

    def test_platform_scope_implies_no_required_permission(self) -> None:
        violations: list[str] = []
        for name, action in ACTIONS.items():
            if action.is_platform_scope and action.required_permission is not None:
                violations.append(
                    f"{name}: required_permission={action.required_permission!r}"
                )
        assert not violations, (
            "is_platform_scope=True but required_permission is not None:\n  - "
            + "\n  - ".join(violations)
        )

    def test_project_scope_not_superuser_only_requires_permission(self) -> None:
        """Non-superuser project-scope actions must declare required_permission."""
        violations: list[str] = []
        for name, action in ACTIONS.items():
            if not action.is_platform_scope and not action.is_superuser_only and action.required_permission is None:
                violations.append(name)
        assert not violations, (
            "Project-scope non-superuser Actions without required_permission:\n  - "
            + "\n  - ".join(violations)
        )

    def test_superuser_only_project_scope_uses_sentinel_or_superuser_perm(
        self,
    ) -> None:
        """Superuser-only project-scope actions use a sentinel permission.

        They MUST NOT use USER_SCOPE_PERMISSIONS (which are matrix-exempt and
        any logged-in user holds). The only acceptable values are permissions
        that appear in the canonical matrix (so non-superuser users fail closed
        via the matrix check if the is_superuser_only gate is somehow bypassed).
        """
        violations: list[str] = []
        for name, action in ACTIONS.items():
            if action.is_platform_scope or not action.is_superuser_only:
                continue
            perm = action.required_permission
            if perm is not None and perm in USER_SCOPE_PERMISSIONS:
                violations.append(
                    f"{name}: is_superuser_only=True but required_permission="
                    f"{perm!r} is in USER_SCOPE_PERMISSIONS (any user would "
                    f"pass the matrix check)"
                )
        assert not violations, (
            "Superuser-only project-scope Actions with user-scope sentinel:\n  - "
            + "\n  - ".join(violations)
        )


# ---------------------------------------------------------------------------
# Test class 9: Path pattern matches permission category (interim, regex-based).
# ---------------------------------------------------------------------------


class TestPathPatternMatchesPermissionCategory:
    """AD-4 class 9 (interim): for well-known path patterns, the Action's
    required_permission must be in the expected category set.

    Marked interim — a TODO migration to per-Action structured
    resource/operation/scope/category metadata is planned post-launch.
    The regex table is inline below.

    TODO(post-launch): replace this regex check with per-Action metadata once
    spec/009-action-metadata-migration is implemented.
    """

    # (path_regex_pattern, allowed_methods, expected_permissions_set, description)
    _PATH_RULES: list[tuple[str, set[str], set[Permission], str]] = [
        (
            r".*/members(/.*)?$",
            {"POST", "PUT", "PATCH", "DELETE"},
            {Permission.MANAGE_MEMBERS},
            "/members/* (mutate) => MANAGE_MEMBERS",
        ),
        (
            r".*/trusted-users(/.*)?$",
            {"POST", "PUT", "PATCH", "DELETE"},
            {Permission.MANAGE_TRUSTED},
            "/trusted-users/* (mutate) => MANAGE_TRUSTED",
        ),
        (
            r".*/visibility$",
            {"POST", "PUT", "PATCH"},
            {Permission.EDIT_PROJECT},
            "/visibility (mutate) => EDIT_PROJECT",
        ),
        (
            r".*/restricted-toggles(/.*)?$",
            {"POST", "PUT", "PATCH", "DELETE"},
            {Permission.EDIT_PROJECT},
            "/restricted-toggles/* (mutate) => EDIT_PROJECT",
        ),
        (
            r".*/transfer-ownership$",
            {"POST", "PUT", "PATCH", "DELETE"},
            {Permission.TRANSFER_OWNERSHIP},
            "/transfer-ownership => TRANSFER_OWNERSHIP",
        ),
        (
            r".*/license$",
            {"POST", "PUT", "PATCH", "DELETE"},
            {Permission.MANAGE_LICENSE},
            "/license (mutate) => MANAGE_LICENSE",
        ),
        (
            r".*/audit-log$",
            {"GET", "HEAD"},
            {Permission.VIEW_AUDIT_LOG},
            "/audit-log (read) => VIEW_AUDIT_LOG",
        ),
    ]

    def test_path_pattern_permission_category(self, app: FastAPI) -> None:
        # Build action-name -> (path, method, permission) from route reflection.
        action_route_info: dict[str, list[tuple[str, str]]] = {}
        for route in app.routes:
            if not isinstance(route, APIRoute):
                continue
            source = _handler_source(route.endpoint)
            if source is None:
                continue
            try:
                tree = ast.parse(source)
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                func = node.func
                fname: str | None = None
                if isinstance(func, ast.Name):
                    fname = func.id
                elif isinstance(func, ast.Attribute):
                    fname = func.attr
                if fname not in ("gate_action", "check_action"):
                    continue
                if not node.args:
                    continue
                arg = node.args[0]
                action_var: str | None = None
                if isinstance(arg, ast.Name):
                    action_var = arg.id
                elif isinstance(arg, ast.Attribute):
                    action_var = arg.attr
                if action_var is None:
                    continue
                action_obj = getattr(echoroo.core.actions, action_var, None)
                if not isinstance(action_obj, Action):
                    continue
                for method in sorted(route.methods or set()):
                    action_route_info.setdefault(action_obj.name, []).append(
                        (route.path, method)
                    )

        violations: list[str] = []
        for rule_pattern, rule_methods, expected_perms, description in self._PATH_RULES:
            regex = re.compile(rule_pattern, re.IGNORECASE)
            for action_name, route_infos in action_route_info.items():
                action = ACTIONS.get(action_name)
                if action is None:
                    continue
                for path, method in route_infos:
                    if not regex.match(path):
                        continue
                    if method.upper() not in rule_methods:
                        continue
                    perm = action.required_permission
                    if perm not in expected_perms:
                        violations.append(
                            f"{action_name} [{method} {path}]: "
                            f"expected {expected_perms} for rule '{description}', "
                            f"got {perm!r}"
                        )

        assert not violations, (
            "Path-pattern / permission category mismatches (AD-4 class 9 interim):\n  - "
            + "\n  - ".join(violations)
        )


# ---------------------------------------------------------------------------
# Test class 10: SEARCH_CROSS_PROJECT is matrix-gated (AD-8 tightening).
# ---------------------------------------------------------------------------


class TestSearchCrossProjectIsMatrixGated:
    """AD-4 class 10: verify compute_effective_permissions grants
    SEARCH_CROSS_PROJECT to Authenticated on Public visibility but NOT on
    Restricted visibility.

    This captures the AD-8 tightening where SEARCH_CROSS_PROJECT moved from
    USER_SCOPE_PERMISSIONS (granted to any authenticated user unconditionally)
    to ENDPOINT_BACKED_PERMISSIONS (project-context-dependent).
    """

    def _make_project(self, visibility: ProjectVisibility) -> Any:
        project = MagicMock()
        project.visibility = visibility
        project.restricted_config = {}
        return project

    def test_authenticated_public_project_gets_search_cross_project(self) -> None:
        project = self._make_project(ProjectVisibility.PUBLIC)
        effective = compute_effective_permissions(
            normalized_role="Authenticated",
            project=project,
        )
        assert Permission.SEARCH_CROSS_PROJECT in effective, (
            "Authenticated on Public must have SEARCH_CROSS_PROJECT "
            "(AD-8 tightening check)"
        )

    def test_authenticated_restricted_project_no_search_cross_project(self) -> None:
        """Authenticated on Restricted does NOT get SEARCH_CROSS_PROJECT via toggles."""
        project = self._make_project(ProjectVisibility.RESTRICTED)
        effective = compute_effective_permissions(
            normalized_role="Authenticated",
            project=project,
        )
        assert Permission.SEARCH_CROSS_PROJECT not in effective, (
            "Authenticated on Restricted MUST NOT have SEARCH_CROSS_PROJECT "
            "(AD-8 tightening: moved from USER_SCOPE to ENDPOINT_BACKED)"
        )

    def test_guest_public_project_no_search_cross_project(self) -> None:
        """Guest never gets SEARCH_CROSS_PROJECT even on Public."""
        project = self._make_project(ProjectVisibility.PUBLIC)
        effective = compute_effective_permissions(
            normalized_role="Guest",
            project=project,
        )
        assert Permission.SEARCH_CROSS_PROJECT not in effective

    def test_member_gets_search_cross_project_from_matrix(self) -> None:
        """Member holds SEARCH_CROSS_PROJECT via the Canonical Matrix."""
        project = self._make_project(ProjectVisibility.RESTRICTED)
        effective = compute_effective_permissions(
            normalized_role="Member",
            project=project,
        )
        assert Permission.SEARCH_CROSS_PROJECT in effective, (
            "Member should have SEARCH_CROSS_PROJECT from ROLE_PERMISSIONS matrix"
        )

    def test_viewer_restricted_no_search_cross_project(self) -> None:
        """Viewer on Restricted does not hold SEARCH_CROSS_PROJECT."""
        project = self._make_project(ProjectVisibility.RESTRICTED)
        effective = compute_effective_permissions(
            normalized_role="Viewer",
            project=project,
        )
        assert Permission.SEARCH_CROSS_PROJECT not in effective

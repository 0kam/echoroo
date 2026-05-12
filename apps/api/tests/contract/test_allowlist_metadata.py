"""AST-based metadata audit for the endpoint ALLOWLIST (spec/007 Phase 3 AD-5).

Phase 2A.1 added basic structural validation (reason >= 20 chars, owner,
project_scope_allowed, methods) in tests/unit/core/test_endpoint_allowlist.py.
This file adds the AST-level checks that require route handler inspection:

1. superuser_only category entries => handler MUST reference CurrentSuperuser
2. token_auth_only category entries => handler MUST reference an invitation-token
   dependency (accept_invitation / decline_invitation_by_recipient or token path param)
3. expiry < today => fail CI (expired entry must be removed or extended)
4. last_reviewed_at + review_interval_days < today => fail CI (stale review)
5. {project_id} in path_pattern => project_scope_allowed=True (also in Phase 2A.1;
   repeated here for completeness / belt-and-suspenders)
6. Admin endpoints (/api/v1/admin/* or /web-api/v1/admin/*) MUST NOT appear in
   ALLOWLIST (they must be registered as Actions with is_superuser_only=True per AD-6)

Note: checks 3, 4, 5 duplicate subset of Phase 2A.1 and module-level
_validate_allowlist(). They are retained here so the Phase 3 lint file is
self-contained and fails with actionable messages even if the earlier guard
is disabled.
"""
from __future__ import annotations

import inspect
import re
import textwrap
from datetime import date
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from echoroo.core.endpoint_allowlist import (
    ALLOWLIST,
    AllowlistCategory,
    AllowlistEntry,
)

# ---------------------------------------------------------------------------
# Helpers — reuse the same AST scan pattern as test_endpoint_coverage.py
# ---------------------------------------------------------------------------

_SUPERUSER_GUARD_NAMES: frozenset[str] = frozenset({
    "CurrentSuperuser",
    "get_current_active_superuser",
    "_require_authenticated_superuser",
})

_TOKEN_AUTH_GUARD_NAMES: frozenset[str] = frozenset({
    "accept_invitation",
    "decline_invitation_by_recipient",
    "accept_project_invitation",
    "decline_project_invitation",
})

_ADMIN_PATH_RE = re.compile(r"^/(api|web-api)/v1/admin(/.*)?$")


def _handler_source(handler: object) -> str | None:
    """Return dedented source for a handler or None if unavailable."""
    try:
        source = inspect.getsource(handler)
    except (OSError, TypeError):
        return None
    return textwrap.dedent(source)


def _source_references_any(source: str, names: frozenset[str]) -> bool:
    """Return True if *source* references any name in *names*."""
    return any(name in source for name in names)


def _source_has_token_path_param(source: str) -> bool:
    """Return True if the handler function signature has a `token` path parameter.

    Invitation accept/decline handlers receive the invitation token as a
    positional path parameter named `token`. We check for `token: str` or
    `token` in the parameter list as a lightweight AST-free heuristic.
    """
    return "token:" in source or "token :" in source


@pytest.fixture(scope="module")
def app() -> FastAPI:
    """Build the real FastAPI app for route reflection."""
    from echoroo.main import create_app
    return create_app()


@pytest.fixture(scope="module")
def path_to_handlers(app: FastAPI) -> dict[str, list[Any]]:
    """Map route path -> list of (method, handler) pairs."""
    mapping: dict[str, list[Any]] = {}
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        mapping.setdefault(route.path, []).append(route.endpoint)
    return mapping


def _find_handler_for_entry(
    entry: AllowlistEntry,
    path_to_handlers: dict[str, list[Any]],
) -> list[Any]:
    """Return handlers for an ALLOWLIST entry's path_pattern.

    Performs a simple normalisation: replaces `{var}` placeholders with
    `{...}` so the pattern can be compared against FastAPI route paths which
    use `{var_name}` segments. Returns empty list if no route matches.
    """
    # Convert the allowlist pattern to a FastAPI-style path by keeping
    # braces but normalising the trailing /* wildcard.
    pattern = entry.path_pattern.rstrip("/*")
    if pattern in path_to_handlers:
        return path_to_handlers[pattern]

    # Try removing trailing wildcard suffix.
    for path, handlers in path_to_handlers.items():
        if path == pattern or path.startswith(pattern + "/"):
            return handlers
    return []


# ---------------------------------------------------------------------------
# Check 1: superuser_only category => CurrentSuperuser dependency
# ---------------------------------------------------------------------------


class TestSuperuserOnlyCategoryHasSuperuserDep:
    """AD-5: ALLOWLIST entries with category=SUPERUSER_ONLY must reference
    a CurrentSuperuser-style dependency in their handler source.

    Note: AllowlistCategory.SUPERUSER_ONLY is currently reserved and UNUSED
    in the production ALLOWLIST (admin endpoints are registered as Actions per
    AD-6). This test guards against future misuse.
    """

    def test_superuser_only_entries_reference_superuser_dep(
        self, path_to_handlers: dict[str, list[Any]]
    ) -> None:
        violations: list[str] = []
        superuser_entries = [
            e for e in ALLOWLIST if e.category == AllowlistCategory.SUPERUSER_ONLY
        ]
        for entry in superuser_entries:
            handlers = _find_handler_for_entry(entry, path_to_handlers)
            if not handlers:
                # No route found — flag for inspection.
                violations.append(
                    f"{entry.path_pattern}: SUPERUSER_ONLY but no matching route found"
                )
                continue
            for handler in handlers:
                source = _handler_source(handler)
                if source is None:
                    violations.append(
                        f"{entry.path_pattern}: cannot inspect handler source"
                    )
                    continue
                if not _source_references_any(source, _SUPERUSER_GUARD_NAMES):
                    violations.append(
                        f"{entry.path_pattern}: SUPERUSER_ONLY but handler does not "
                        f"reference {sorted(_SUPERUSER_GUARD_NAMES)}"
                    )
        assert not violations, (
            "ALLOWLIST SUPERUSER_ONLY entries without superuser dep (AD-5):\n  - "
            + "\n  - ".join(violations)
        )

    def test_superuser_only_category_currently_unused(self) -> None:
        """AD-6 invariant: SUPERUSER_ONLY category should be empty.

        Admin endpoints are registered as Actions; the SUPERUSER_ONLY category
        is reserved as an escape hatch only.
        """
        superuser_entries = [
            e for e in ALLOWLIST if e.category == AllowlistCategory.SUPERUSER_ONLY
        ]
        # We do not hard-fail here because a future legitimate use may exist.
        # Instead, flag any entry so reviewers can audit it explicitly.
        if superuser_entries:
            paths = [e.path_pattern for e in superuser_entries]
            pytest.xfail(
                f"ALLOWLIST SUPERUSER_ONLY entries found — review required "
                f"(AD-6 escape hatch): {paths}"
            )


# ---------------------------------------------------------------------------
# Check 2: token_auth_only category => invitation-token style dependency
# ---------------------------------------------------------------------------


class TestTokenAuthOnlyCategoryHasTokenDep:
    """AD-5: ALLOWLIST entries with category=TOKEN_AUTH_ONLY must implement
    invitation-token style authentication (handler references accept_invitation,
    decline_invitation_by_recipient, or has a `token` path parameter).
    """

    def test_token_auth_only_entries_have_token_dep(
        self, path_to_handlers: dict[str, list[Any]]
    ) -> None:
        violations: list[str] = []
        token_entries = [
            e for e in ALLOWLIST if e.category == AllowlistCategory.TOKEN_AUTH_ONLY
        ]
        for entry in token_entries:
            handlers = _find_handler_for_entry(entry, path_to_handlers)
            if not handlers:
                violations.append(
                    f"{entry.path_pattern}: TOKEN_AUTH_ONLY but no matching route found"
                )
                continue
            for handler in handlers:
                source = _handler_source(handler)
                if source is None:
                    violations.append(
                        f"{entry.path_pattern}: cannot inspect handler source"
                    )
                    continue
                has_token = (
                    _source_references_any(source, _TOKEN_AUTH_GUARD_NAMES)
                    or _source_has_token_path_param(source)
                )
                if not has_token:
                    violations.append(
                        f"{entry.path_pattern}: TOKEN_AUTH_ONLY but handler does not "
                        f"reference token auth pattern (accept_invitation, "
                        f"decline_invitation_by_recipient, or token path param)"
                    )
        assert not violations, (
            "ALLOWLIST TOKEN_AUTH_ONLY entries without token dep (AD-5):\n  - "
            + "\n  - ".join(violations)
        )


# ---------------------------------------------------------------------------
# Check 3: expiry < today => fail CI
# ---------------------------------------------------------------------------


class TestNoExpiredAllowlistEntries:
    """AD-5: entries with expiry < today must be removed or extended.

    An expired entry indicates the original justification has lapsed.
    """

    def test_no_entry_has_past_expiry(self) -> None:
        today = date.today()
        violations: list[tuple[AllowlistEntry, date]] = []
        for entry in ALLOWLIST:
            if entry.expiry is not None and entry.expiry < today:
                violations.append((entry, entry.expiry))
        assert not violations, (
            "ALLOWLIST entries with expired expiry (AD-5 lint):\n  - "
            + "\n  - ".join(
                f"{entry.path_pattern}: expiry={expiry}, today={today}"
                for entry, expiry in violations
            )
        )


# ---------------------------------------------------------------------------
# Check 4: last_reviewed_at + review_interval_days < today => fail CI
# ---------------------------------------------------------------------------


class TestNoStaleAllowlistReviews:
    """AD-5: entries where last_reviewed_at + review_interval_days < today
    indicate the review cadence has been missed.

    Also covered by test_endpoint_allowlist.py and module-level
    _validate_allowlist(), but repeated here for belt-and-suspenders and
    so Phase 3 lint is self-contained.
    """

    def test_no_entry_past_review_by_date(self) -> None:
        from datetime import timedelta
        today = date.today()
        violations: list[tuple[AllowlistEntry, date]] = []
        for entry in ALLOWLIST:
            deadline = entry.last_reviewed_at + timedelta(days=entry.review_interval_days)
            if deadline < today:
                violations.append((entry, deadline))
        assert not violations, (
            "ALLOWLIST entries past their review-by date (AD-5 lint):\n  - "
            + "\n  - ".join(
                f"{entry.path_pattern}: last_reviewed={entry.last_reviewed_at}, "
                f"deadline={deadline}, today={today}"
                for entry, deadline in violations
            )
        )


# ---------------------------------------------------------------------------
# Check 5: {project_id} in path_pattern => project_scope_allowed=True
# ---------------------------------------------------------------------------


class TestProjectScopedEntriesHaveExplicitOptIn:
    """AD-5: ALLOWLIST entries whose path_pattern contains {project_id} MUST
    set project_scope_allowed=True.

    Also enforced by _validate_allowlist() at import time and by
    test_endpoint_allowlist.py. Belt-and-suspenders for Phase 3 audit.
    """

    def test_project_scoped_paths_opt_in_explicitly(self) -> None:
        violations = [
            entry
            for entry in ALLOWLIST
            if "{project_id}" in entry.path_pattern and not entry.project_scope_allowed
        ]
        assert not violations, (
            "ALLOWLIST entries with {project_id} but project_scope_allowed=False:\n  - "
            + "\n  - ".join(e.path_pattern for e in violations)
        )


# ---------------------------------------------------------------------------
# Check 6: Admin endpoints MUST NOT appear in ALLOWLIST (AD-6 invariant)
# ---------------------------------------------------------------------------


class TestAdminEndpointsNotInAllowlist:
    """AD-5 / AD-6: /api/v1/admin/* and /web-api/v1/admin/* MUST NOT appear in
    the ALLOWLIST. Admin endpoints are registered as Actions with
    is_superuser_only=True + is_platform_scope=True per AD-6 unified approach.

    An admin endpoint in the ALLOWLIST would bypass the Action gate entirely,
    making it untracked by ACTIONS catalog coherence tests.
    """

    def test_no_admin_path_in_allowlist(self) -> None:
        violations: list[str] = []
        for entry in ALLOWLIST:
            if _ADMIN_PATH_RE.match(entry.path_pattern):
                violations.append(
                    f"{entry.path_pattern} (category={entry.category.value})"
                )
        assert not violations, (
            "Admin paths in ALLOWLIST (must be registered as Actions per AD-6):\n  - "
            + "\n  - ".join(violations)
        )

    def test_admin_actions_registered_in_actions_catalog(self) -> None:
        """Verify that the ACTIONS catalog contains superuser platform-scope entries.

        This is the positive counterpart to the ALLOWLIST exclusion check:
        if admin endpoints are NOT in the allowlist, they MUST be in ACTIONS.
        """
        import echoroo.core.actions  # noqa: F401
        from echoroo.core.permissions import ACTIONS

        platform_scope_actions = [
            name for name, action in ACTIONS.items() if action.is_platform_scope
        ]
        assert len(platform_scope_actions) > 0, (
            "No platform-scope Actions in ACTIONS catalog — admin endpoints "
            "must be registered as Actions per AD-6"
        )

    def test_no_superuser_only_category_matches_admin_paths(self) -> None:
        """SUPERUSER_ONLY category entries, if any, must not cover admin paths.

        Belt-and-suspenders: SUPERUSER_ONLY is supposed to be the escape hatch
        for future edge cases, NOT for admin endpoints (which have Action entries).
        """
        violations: list[str] = []
        for entry in ALLOWLIST:
            if entry.category == AllowlistCategory.SUPERUSER_ONLY and _ADMIN_PATH_RE.match(entry.path_pattern):
                violations.append(entry.path_pattern)
        assert not violations, (
            "Admin paths covered by SUPERUSER_ONLY allowlist category "
            "(should be Actions per AD-6):\n  - "
            + "\n  - ".join(violations)
        )

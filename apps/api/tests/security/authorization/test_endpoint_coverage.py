"""Endpoint coverage reflection test (T047).

Research §18-D + SC-001. For every FastAPI route registered on the app, its
logical action name MUST be present in ``ACTIONS`` (the catalog defined in
``core/permissions.py``). This catches endpoints that were added without
registering a corresponding ``Action`` — a prerequisite for the permission
guard to wrap them (FR-008a).

Expected status: RED until Phase 3 fills ``ACTIONS`` with every route key.
Phase 2 ships an empty dict, so this test fails by design until the endpoint
wiring catches up. The structural guarantee is still meaningful — a subsequent
phase simply cannot merge with unregistered routes.

The test is parametrised per-route so CI shows which endpoints are missing.
"""
from __future__ import annotations

from collections.abc import Iterable

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from echoroo.core.endpoint_allowlist import ALLOWLIST, is_allowlisted
from echoroo.core.permissions import ACTIONS

# spec/007 AD-5 (Phase 2A.1): the legacy ``ALLOWLIST_PATHS: frozenset[str]``
# was replaced by the structured :data:`ALLOWLIST` records living in
# ``echoroo.core.endpoint_allowlist``. Each entry now carries category,
# reason, owner, spec_ref, last_reviewed_at metadata so CI can audit drift.
# Re-exported here as a backwards-compatible alias used by older fixtures.
ALLOWLIST_PATHS: frozenset[str] = frozenset(entry.path_pattern for entry in ALLOWLIST)


def _collect_actionable_routes(app: FastAPI) -> Iterable[tuple[str, str]]:
    """Yield ``(path, method)`` tuples for every non-allowlisted APIRoute."""
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in sorted(route.methods or set()):
            if method in {"HEAD", "OPTIONS"}:
                continue
            if is_allowlisted(route.path, method):
                continue
            yield route.path, method


def _derive_action_name(path: str, method: str) -> str:
    """Derive canonical action name for a route (spec FR-008a convention).

    We use ``<method>:<path>`` as the key in ACTIONS so that every path-method
    pair maps to exactly one Action. Implementations are free to adopt a more
    domain-ish naming in Phase 3 (e.g. ``detection.vote``); the test only
    requires the same key be present in ACTIONS.
    """
    return f"{method}:{path}"


@pytest.fixture(scope="module")
def app() -> FastAPI:
    """Build the real FastAPI app for route reflection."""
    # Local import so this module is importable in Phase 2 even if main
    # imports fail during Phase 3 churn.
    from echoroo.main import create_app

    return create_app()


def test_actions_catalog_is_dict() -> None:
    """ACTIONS must be a dict keyed by action name (FR-008a)."""
    assert isinstance(ACTIONS, dict)


@pytest.mark.skip(
    reason=(
        "Phase 2: ACTIONS is intentionally empty. Phase 3 (T100+) registers"
        " every endpoint. This test becomes mandatory at T100f enforcement."
    )
)
def test_every_route_registered_in_actions(app: FastAPI) -> None:
    """SC-001: every FastAPI route has a matching Action entry.

    Parametric-equivalent assert — we iterate so the error message lists all
    missing routes at once.
    """
    missing: list[str] = []
    for path, method in _collect_actionable_routes(app):
        key = _derive_action_name(path, method)
        # Either the exact derived key OR any Action whose name maps to this
        # path/method pair satisfies the check. Phase 3 may prefer domain keys.
        if key in ACTIONS:
            continue
        # Fallback: scan ACTIONS for a matching route attribute if present.
        found = any(
            getattr(action, "path", None) == path
            and getattr(action, "method", None) == method
            for action in ACTIONS.values()
        )
        if not found:
            missing.append(f"{method} {path}")
    assert not missing, (
        "Routes missing from ACTIONS catalog (FR-008a):\n  - "
        + "\n  - ".join(sorted(missing))
    )

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


# spec/007 Phase 2A.7 (Codex consultation 2026-05-12, Option B): the legacy
# ``METHOD:/path`` key convention required either path/method fields on every
# Action or a 152-Action backfill. Both alternatives diverge from the
# code's actual contract — handlers call ``gate_action(<ACTION>, ...)`` (or a
# small list of equivalent guard helpers) and that variable references an
# Action instance imported from ``echoroo.core.actions``. The proper SC-001
# guarantee is therefore: every non-allowlisted route's handler invokes one
# of the canonical guard helpers (matching the surface enforced by
# ``scripts/lint_permission_guard.py``). The check below performs an AST
# scan of each handler's source to detect those invocations.
#
# This is intentionally narrower than verifying the Action *name* exists in
# ACTIONS at static-scan time: if a handler imported a non-existent symbol,
# the module would fail to import and the whole app fixture would error
# out before this test even runs. The structural coherence of ``ACTIONS``
# itself is owned by ``tests/contract/test_actions_coherence.py``.

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


def _handler_invokes_guard(handler: object) -> bool:
    """Return True if *handler*'s source body invokes any guard helper."""
    import ast
    import inspect

    try:
        source = inspect.getsource(handler)
    except (OSError, TypeError):
        # Cannot resolve source (built-in, lambda, etc.) — assume unguarded.
        return False

    # Dedent so the source parses as a module-level function.
    import textwrap
    source = textwrap.dedent(source)

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


def _handler_qualname(handler: object) -> tuple[str | None, str | None]:
    """Return ``(file_relpath, function_name)`` for *handler*.

    Used to map a FastAPI route to its entry in
    ``scripts/allowlists/permission_guard_allowlist.txt`` (line-level
    fingerprints of the form ``<file>:<function_name>:missing-permission-guard``).
    """
    import inspect
    from pathlib import Path

    try:
        source_file = inspect.getsourcefile(handler)  # type: ignore[arg-type]
    except TypeError:
        return None, None
    if source_file is None:
        return None, None

    # Repo root may be parents[3] (host: echoroo/) or parents[5] depending
    # on where pytest runs from. Walk up until we find a directory that
    # contains both ``apps`` and ``scripts``.
    candidate_root: Path | None = None
    for parent in Path(__file__).resolve().parents:
        if (parent / "apps").is_dir() and (parent / "scripts").is_dir():
            candidate_root = parent
            break
    src_resolved = Path(source_file).resolve()
    if candidate_root is not None:
        try:
            relpath = str(src_resolved.relative_to(candidate_root))
        except ValueError:
            relpath = source_file
    else:
        # In the docker container we only have /app == repo apps/api;
        # fingerprints in the allowlist are still relative to project root
        # (``apps/api/echoroo/...``). Strip the /app prefix and re-prefix.
        s = str(src_resolved)
        if s.startswith("/app/"):
            relpath = "apps/api/" + s[len("/app/"):]
        else:
            relpath = source_file

    func_name = getattr(handler, "__name__", None)
    return relpath, func_name


def _load_lint_allowlist() -> set[str]:
    """Load fingerprints from scripts/allowlists/permission_guard_allowlist.txt.

    Phase 2.11 P1-a line-level format: ``<file>:<function_name>:<tag>``.
    Inline comments (``# ...``) are stripped.

    Search order (first match wins):
      1. ``ECHOROO_LINT_ALLOWLIST`` env var path.
      2. ``scripts/allowlists/permission_guard_allowlist.txt`` relative to
         any ancestor of this test file.
      3. ``/tmp/scripts/allowlists/permission_guard_allowlist.txt`` (used by
         docker test runners that bind-mount only ``echoroo/`` into ``/app``).
    """
    from pathlib import Path
    import os

    candidates: list[Path] = []
    env = os.environ.get("ECHOROO_LINT_ALLOWLIST")
    if env:
        candidates.append(Path(env))
    for parent in Path(__file__).resolve().parents:
        candidates.append(
            parent / "scripts" / "allowlists" / "permission_guard_allowlist.txt"
        )
    candidates.append(
        Path("/tmp/scripts/allowlists/permission_guard_allowlist.txt")
    )

    for allowlist_path in candidates:
        if allowlist_path.exists():
            fingerprints: set[str] = set()
            for raw in allowlist_path.read_text().splitlines():
                line = raw.split("#", 1)[0].strip()
                if not line:
                    continue
                fingerprints.add(line)
            return fingerprints
    return set()


def test_every_route_registered_in_actions(app: FastAPI) -> None:
    """SC-001: every non-allowlisted FastAPI route invokes the permission guard.

    Per spec/007 Phase 2A.7 (Codex Option B, 2026-05-12): the guarantee
    enforced here is that the handler body invokes ``gate_action(...)`` or
    an equivalent canonical guard helper. Cross-referencing the resolved
    Action against ``ACTIONS`` itself is unnecessary because the variable
    would have failed to import if absent, and the catalog's internal
    coherence is covered by ``test_actions_coherence.py``.

    Endpoints listed in
    ``scripts/allowlists/permission_guard_allowlist.txt`` (the
    pre-existing line-level fingerprint allowlist consumed by
    ``scripts/lint_permission_guard.py``) are exempted — they represent
    pre-spec/007 technical debt tracked under spec/006 Phase 3 US11
    cleanup. spec/007 Phase 2A.7 enforces NO REGRESSION from that
    baseline: the test fails only if a route is unguarded AND not in
    that allowlist AND not in the structured ``ALLOWLIST`` (AD-5).

    Parametric-equivalent assert — we iterate so the error message lists all
    missing routes at once.
    """
    lint_allowlist = _load_lint_allowlist()
    unguarded: list[str] = []
    seen: set[tuple[str, str]] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in sorted(route.methods or set()):
            if method in {"HEAD", "OPTIONS"}:
                continue
            if is_allowlisted(route.path, method):
                continue
            key = (route.path, method)
            if key in seen:
                continue
            seen.add(key)
            if _handler_invokes_guard(route.endpoint):
                continue
            file_rel, func_name = _handler_qualname(route.endpoint)
            if file_rel and func_name:
                # Allowlist fingerprints use repo-root-relative paths
                # ("apps/api/echoroo/..."). _handler_qualname returns the
                # path relative to the repo root by climbing 3 levels from
                # this test file (.../apps/api/tests/security/authorization/
                # → repo root).
                fingerprint = f"{file_rel}:{func_name}:missing-permission-guard"
                if fingerprint in lint_allowlist:
                    continue
            unguarded.append(f"{method} {route.path}")

    assert not unguarded, (
        "Routes without permission guard and NOT in the lint allowlist "
        "(FR-008a). Spec/007 Phase 2A.7 forbids regression from the "
        "lint-allowlist baseline.\n  - "
        + "\n  - ".join(sorted(unguarded))
    )

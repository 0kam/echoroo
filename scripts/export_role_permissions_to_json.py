#!/usr/bin/env python3
"""Export the backend permission matrix to a JSON fixture for the frontend.

The fixture lives at::

    apps/web/src/lib/utils/__fixtures__/role_permissions.json

and is consumed by the SvelteKit client's permission binding tests to
keep frontend gating in lock-step with the backend Canonical Matrix
(spec/007 Phase 2B.0 + spec/007 §AD-8).

Usage:

    # Regenerate the fixture (default; writes the JSON file).
    uv run python scripts/export_role_permissions_to_json.py

    # CI drift gate: compare against the committed fixture and exit 1 if
    # they differ. Prints a one-line diff hint on mismatch.
    uv run python scripts/export_role_permissions_to_json.py --check

Exit codes:

    0  fixture is up to date (or was regenerated successfully)
    1  drift detected (only emitted in --check mode), or an internal error

Determinism guarantees:

    * Permission values are emitted sorted, so a re-run produces byte-
      identical output.
    * ``generated_at_utc`` is included for observability but is NOT used
      for the drift comparison — see ``_strip_volatile`` in the
      ``--check`` branch. The ``generated_from_commit`` field is reserved
      for future CI integration and is currently always ``null``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from echoroo.core.permissions import (
    COMPUTED_ONLY_PERMISSIONS,
    ENDPOINT_BACKED_PERMISSIONS,
    FRONTEND_PROJECT_PERMISSIONS,
    ROLE_PERMISSIONS,
    SUPERUSER_ONLY_PERMISSIONS,
    USER_SCOPE_PERMISSIONS,
    ComputedRole,
    Permission,
)

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------
#
# This script lives at ``<repo-root>/scripts/export_role_permissions_to_json.py``.
# The fixture is written to ``<repo-root>/apps/web/src/lib/utils/__fixtures__/``.
#
# When invoked from the CI runner with ``working-directory: apps/api`` (the
# convention shared with ``dump_openapi.py``), the relative path
# ``../../scripts/...`` is resolved before the script body runs, so the
# default ``Path(__file__).resolve().parents[1]`` is the repo root.
#
# Local Docker development: the dev backend container only bind-mounts
# ``apps/api/echoroo`` (not the repo root), so the script is typically
# ``docker cp``'d to ``/tmp/`` for execution; ``parents[1]`` then resolves
# to ``/`` and the default output path is unreachable. Override the repo
# root via ``ECHOROO_REPO_ROOT`` for this case (see the project README's
# Phase 2B.0 section for the canonical local invocation).
_DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[1]
_REPO_ROOT = Path(os.environ.get("ECHOROO_REPO_ROOT", _DEFAULT_REPO_ROOT))
OUTPUT_PATH = (
    _REPO_ROOT
    / "apps"
    / "web"
    / "src"
    / "lib"
    / "utils"
    / "__fixtures__"
    / "role_permissions.json"
)


# ---------------------------------------------------------------------------
# Fixture construction
# ---------------------------------------------------------------------------

def _sorted_perm_values(perms: frozenset[Permission] | set[Permission]) -> list[str]:
    """Return ``perms`` as a sorted list of string values (stable output)."""
    return sorted(p.value for p in perms)


def _public_guest_authenticated_overlay() -> dict[str, list[str]]:
    """Compute the Public-visibility "overlay" granted to non-member principals.

    Mirrors the branches in
    :func:`echoroo.core.permissions.compute_effective_permissions` for the
    ``normalized_role == "Guest"`` and ``"Authenticated"`` cases when the
    project visibility is ``PUBLIC``. We re-derive the lists here (rather
    than calling the function with a fake project) so the JSON output is a
    declarative restatement of the backend contract and any change to the
    overlay logic forces both this script AND the matching frontend tests
    to be updated together (CI drift gate).
    """
    guest_public_extra = [
        Permission.VIEW_MEDIA.value,
        Permission.VIEW_DETECTION.value,
    ]
    authenticated_public_extra = [
        Permission.VIEW_MEDIA.value,
        Permission.VIEW_DETECTION.value,
        Permission.SEARCH_WITHIN_PROJECT.value,
        Permission.SEARCH_CROSS_PROJECT.value,
        Permission.DOWNLOAD.value,
        Permission.EXPORT.value,
        Permission.VOTE.value,
        Permission.COMMENT.value,
    ]
    return {
        "guest": sorted(guest_public_extra),
        "authenticated_non_member": sorted(authenticated_public_extra),
    }


def _restricted_toggle_map() -> dict[str, list[str]]:
    """Return the Restricted-visibility toggle-name → permission list map.

    Mirrors ``_RESTRICTED_TOGGLE_PERMS_AUTHENTICATED`` and the
    ``allow_precise_location_to_viewer`` branch inside
    :func:`compute_effective_permissions`. The toggle names are the
    field names on ``ProjectRestrictedConfig``.
    """
    return {
        "allow_media_playback": [Permission.VIEW_MEDIA.value],
        "allow_detection_view": [Permission.VIEW_DETECTION.value],
        "allow_download": [Permission.DOWNLOAD.value],
        "allow_export": [Permission.EXPORT.value],
        "allow_voting_and_comments": sorted(
            [Permission.VOTE.value, Permission.COMMENT.value]
        ),
        "allow_precise_location_to_viewer": [
            Permission.VIEW_PRECISE_LOCATION.value
        ],
    }


def build_fixture() -> dict[str, Any]:
    """Build the JSON-serialisable fixture dict.

    The structure is intentionally stable across re-runs (sorted permission
    lists, fixed key order) so the ``--check`` drift gate yields a clean
    byte-level diff when something changes.
    """
    return {
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "generated_from_commit": None,
        "permissions": sorted(p.value for p in Permission),
        "categories": {
            "endpoint_backed": _sorted_perm_values(ENDPOINT_BACKED_PERMISSIONS),
            "computed_only": _sorted_perm_values(COMPUTED_ONLY_PERMISSIONS),
            "user_scope": _sorted_perm_values(USER_SCOPE_PERMISSIONS),
            "superuser_only": _sorted_perm_values(SUPERUSER_ONLY_PERMISSIONS),
            "frontend_project": _sorted_perm_values(FRONTEND_PROJECT_PERMISSIONS),
        },
        "role_permissions": {
            "viewer": _sorted_perm_values(ROLE_PERMISSIONS[ComputedRole.VIEWER]),
            "member": _sorted_perm_values(ROLE_PERMISSIONS[ComputedRole.MEMBER]),
            "admin": _sorted_perm_values(ROLE_PERMISSIONS[ComputedRole.ADMIN]),
            "owner": _sorted_perm_values(ROLE_PERMISSIONS[ComputedRole.OWNER]),
        },
        "frontend_project_permissions": _sorted_perm_values(
            FRONTEND_PROJECT_PERMISSIONS
        ),
        "visibility_overlays": {
            "public": _public_guest_authenticated_overlay(),
            "restricted_toggles": _restricted_toggle_map(),
        },
    }


# ---------------------------------------------------------------------------
# Serialisation + drift-detection helpers
# ---------------------------------------------------------------------------

def _serialise(fixture: dict[str, Any]) -> str:
    """Return canonical JSON text (trailing newline included)."""
    return json.dumps(fixture, indent=2, sort_keys=False) + "\n"


def _strip_volatile(text: str) -> str:
    """Strip the ``generated_at_utc`` line so drift comparisons ignore it.

    ``generated_at_utc`` is informational only — comparing it would
    guarantee a drift hit on every CI run. We strip it from BOTH the
    freshly-built fixture and the committed file before diffing so a
    re-generation that only updates the timestamp is treated as "no
    drift".
    """
    return "\n".join(
        line
        for line in text.splitlines()
        if '"generated_at_utc"' not in line
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Diff against the committed fixture and exit 1 on drift. "
            "Used by the CI permissions-fixture-drift workflow."
        ),
    )
    args = parser.parse_args()

    fixture = build_fixture()
    new_text = _serialise(fixture)

    if args.check:
        if not OUTPUT_PATH.exists():
            print(
                f"ERROR: fixture file does not exist: {OUTPUT_PATH}\n"
                f"Run: uv run python scripts/{Path(__file__).name}",
                file=sys.stderr,
            )
            return 1
        current_text = OUTPUT_PATH.read_text()
        if _strip_volatile(current_text) != _strip_volatile(new_text):
            print(
                "ERROR: role_permissions.json fixture is out of date.\n"
                "       Run: uv run python "
                f"scripts/{Path(__file__).name}\n"
                "       then commit the regenerated fixture.",
                file=sys.stderr,
            )
            return 1
        print(f"OK: fixture is up to date ({OUTPUT_PATH.relative_to(_REPO_ROOT)})")
        return 0

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(new_text)
    print(f"Wrote {OUTPUT_PATH.relative_to(_REPO_ROOT)} ({len(new_text)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

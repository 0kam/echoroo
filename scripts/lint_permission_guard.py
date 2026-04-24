#!/usr/bin/env python3
"""Lint: every FastAPI path operation must pass through the permission guard.

Enforces FR-008 (all state-changing / data-read endpoints traverse
`is_allowed` / `Depends(check_action(...))`).

Target pattern:
    * Walk every `apps/api/echoroo/api/**/*.py` module.
    * Parse each file with the standard-library `ast` module.
    * Detect function definitions decorated with `@router.get/post/put/patch/delete/...`
      (including `@api_router.*`, `@web_router.*`, etc.).
    * For each path-operation function, verify that either
        - the body references `is_allowed(...)`, or
        - one of its FastAPI dependencies uses `Depends(check_action(...))`.
    * Report functions that do neither.

Allowlist (Phase 2 will move this to a dedicated file):
    * Unauthenticated endpoints in `api/auth.py` (register / login /
      password reset / 2FA challenge) are exempted because they run before
      the authenticated identity is established.

See specs/006-permissions-redesign/research.md §18-A.

Full implementation: T044 (Phase 2).
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path


def find_violations(root: Path) -> list[str]:
    """Return a list of human-readable violation descriptions.

    TODO(T044): implement in Phase 2. For the skeleton we walk the AST so
    we validate that the target tree is reachable, but we do not yet emit
    any findings.
    """
    if not root.exists():
        return []
    for py_file in root.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except (OSError, SyntaxError):
            # Phase 2 will surface parse failures; skeleton stays silent.
            continue
        # Walk to prove the traversal is wired up.
        for _ in ast.walk(tree):
            pass
    # TODO(T044): accumulate and return violations.
    print(
        "[lint_permission_guard] skeleton scan complete "
        "(TODO: implement in T044)",
        file=sys.stderr,
    )
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        type=Path,
        default=Path("apps/api/echoroo/api"),
        help="Root directory to scan (default: apps/api/echoroo/api).",
    )
    parser.add_argument(
        "--fail-on-violation",
        action="store_true",
        help="Exit with status 1 if any violations are found.",
    )
    args = parser.parse_args()

    try:
        violations = find_violations(args.path)
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[lint_permission_guard] unexpected error: {exc}", file=sys.stderr)
        return 2

    for v in violations:
        print(v, file=sys.stderr)
    if violations and args.fail_on_violation:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

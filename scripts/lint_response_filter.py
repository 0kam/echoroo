#!/usr/bin/env python3
"""Lint: every Recording/Detection/Site response must pass apply_response_filter.

Enforces FR-011 (ResponseFilter mandatory on all Recording/Detection/Site
response paths so that privileged fields such as raw coordinates and
uploader PII are stripped before serialization).

Target pattern:
    * Walk every `apps/api/echoroo/api/**/*.py` module.
    * Parse each file with the standard-library `ast` module.
    * Identify path-operation functions where either
        - a decorator has `response_model=Recording|Detection|Site`
          (including `list[Recording]`, `Page[Detection]`, etc.), or
        - the return annotation names `Recording`, `Detection`, or `Site`
          (directly or inside a generic).
    * Verify that the function body references `apply_response_filter(...)`
      or the `@with_response_filter` decorator is present.
    * Report functions that are missing the filter.

See specs/006-permissions-redesign/research.md §18-B.

Full implementation: T045 (Phase 2).
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path


def find_violations(root: Path) -> list[str]:
    """Return a list of human-readable violation descriptions.

    TODO(T045): implement in Phase 2. The skeleton walks the AST so the
    scan plumbing is validated, but no findings are emitted yet.
    """
    if not root.exists():
        return []
    for py_file in root.rglob("*.py"):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except (OSError, SyntaxError):
            continue
        for _ in ast.walk(tree):
            pass
    # TODO(T045): accumulate and return violations.
    print(
        "[lint_response_filter] skeleton scan complete "
        "(TODO: implement in T045)",
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
        print(f"[lint_response_filter] unexpected error: {exc}", file=sys.stderr)
        return 2

    for v in violations:
        print(v, file=sys.stderr)
    if violations and args.fail_on_violation:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

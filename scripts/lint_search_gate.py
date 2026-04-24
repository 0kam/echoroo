#!/usr/bin/env python3
"""Lint: direct SQLAlchemy select() on Detection models is confined to SearchGate.

Enforces FR-025 (all detection/annotation search traffic is forced through
`services/search_gate.py`, which applies the permission + visibility
filter). Direct `select(Detection)` calls outside the allowlist risk
leaking records from projects the caller cannot view.

Target pattern:
    * Walk every `apps/api/echoroo/**/*.py` module.
    * Parse each file with the standard-library `ast` module.
    * Detect `select(Detection)` / `select(Annotation)` / equivalent
      SQLAlchemy `select(...)` calls referencing forbidden models.
    * Fail when such a call appears outside the allowlisted files.

Allowlisted files (only these may call `select(Detection)` directly):
    * apps/api/echoroo/services/search_gate.py
    * apps/api/echoroo/repositories/detection.py

See specs/006-permissions-redesign/research.md §18-C.

Full implementation: T092 (Phase 2).
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

ALLOWLISTED_PATHS: tuple[str, ...] = (
    "apps/api/echoroo/services/search_gate.py",
    "apps/api/echoroo/repositories/detection.py",
)

FORBIDDEN_MODELS: frozenset[str] = frozenset({"Detection", "Annotation"})


def find_violations(root: Path) -> list[str]:
    """Return a list of human-readable violation descriptions.

    TODO(T092): implement in Phase 2. The skeleton walks the AST but does
    not yet emit findings.
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
    # TODO(T092): accumulate and return violations, honouring ALLOWLISTED_PATHS
    # and FORBIDDEN_MODELS.
    print(
        "[lint_search_gate] skeleton scan complete (TODO: implement in T092)",
        file=sys.stderr,
    )
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        type=Path,
        default=Path("apps/api/echoroo"),
        help="Root directory to scan (default: apps/api/echoroo).",
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
        print(f"[lint_search_gate] unexpected error: {exc}", file=sys.stderr)
        return 2

    for v in violations:
        print(v, file=sys.stderr)
    if violations and args.fail_on_violation:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

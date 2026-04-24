#!/usr/bin/env python3
"""Lint: KMS client construction is confined to apps/api/echoroo/core/kms.py.

Enforces FR-091b: only the central KMS wrapper module may instantiate
`boto3.client('kms')` or `boto3.resource('kms')`. Every other caller
must go through the wrapper so that key rotation, envelope encryption,
and audit logging are centralized.

Target pattern:
    * Walk every `apps/api/echoroo/**/*.py` module.
    * Use a regex (sufficient for this rule; Phase 2 may upgrade to AST)
      that matches both single- and double-quoted `'kms'` string literals
      passed to `boto3.client(...)` / `boto3.resource(...)`.
    * Skip the one allowlisted file: `apps/api/echoroo/core/kms.py`.

Allowlist:
    * apps/api/echoroo/core/kms.py  (the canonical wrapper).

See specs/006-permissions-redesign/research.md §18 (related to FR-091*
KMS handling, cross-linked from the §13 encryption plan).

Full implementation: T044 (Phase 2).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ALLOWLISTED_PATHS: tuple[str, ...] = ("apps/api/echoroo/core/kms.py",)

# Matches boto3.client('kms', ...) or boto3.resource("kms", ...).
KMS_CLIENT_PATTERN = re.compile(
    r"boto3\s*\.\s*(?:client|resource)\s*\(\s*['\"]kms['\"]",
)


def find_violations(root: Path) -> list[str]:
    """Return a list of human-readable violation descriptions.

    TODO(T044): implement in Phase 2. The skeleton walks the target tree
    but does not yet emit findings.
    """
    if not root.exists():
        return []
    for py_file in root.rglob("*.py"):
        rel = str(py_file)
        if any(rel.endswith(allowed) for allowed in ALLOWLISTED_PATHS):
            continue
        try:
            py_file.read_text(encoding="utf-8")
        except OSError:
            continue
    # TODO(T044): accumulate and return violations using KMS_CLIENT_PATTERN.
    print(
        "[lint_kms_isolation] skeleton scan complete (TODO: implement in T044)",
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
        print(f"[lint_kms_isolation] unexpected error: {exc}", file=sys.stderr)
        return 2

    for v in violations:
        print(v, file=sys.stderr)
    if violations and args.fail_on_violation:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

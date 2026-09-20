#!/usr/bin/env python3
"""Lint that S3 client access is isolated in ``core/s3.py``.

The two detection rules are:

1. Flag calls to ``client`` or ``resource`` on any receiver when the literal
   service name ``"s3"`` is first positional argument or the
   ``service_name=`` keyword argument.
2. Flag imports, attributes, or bare-name references to
   ``get_s3_client`` or ``get_public_s3_client``.

Both rules apply outside ``apps/api/echoroo/core/s3.py``. They support slice 1
of the storage migration described in
``docs/architecture/storage-lustre-migration.md``.

Exit codes:
    0 -- no violations, or findings were printed with ``--no-fail``
    1 -- one or more violations were found
    2 -- an unexpected error occurred
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

ALLOWLISTED_PATHS: tuple[str, ...] = ("apps/api/echoroo/core/s3.py",)
TARGET_SERVICE = "s3"
CLIENT_FACTORY_METHODS = frozenset({"client", "resource"})
RAW_CLIENT_ACCESSORS = frozenset({"get_s3_client", "get_public_s3_client"})


class _S3IsolationVisitor(ast.NodeVisitor):
    """Collect ``(lineno, detail)`` for S3 isolation violations."""

    def __init__(self) -> None:
        self.violations: list[tuple[int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802 — ast API
        if isinstance(node.func, ast.Attribute):
            method = node.func.attr
            if (
                method in CLIENT_FACTORY_METHODS
                and _call_has_s3_service_name(node)
            ):
                self.violations.append(
                    (
                        node.lineno,
                        f"{method}('s3', ...) outside core/s3.py",
                    )
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802
        for alias in node.names:
            if alias.name in RAW_CLIENT_ACCESSORS:
                self.violations.append(
                    (
                        node.lineno,
                        f"raw S3 client accessor '{alias.name}' outside core/s3.py",
                    )
                )
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        if node.attr in RAW_CLIENT_ACCESSORS:
            self.violations.append(
                (
                    node.lineno,
                    f"raw S3 client accessor '{node.attr}' outside core/s3.py",
                )
            )
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802 — ast API
        if node.id in RAW_CLIENT_ACCESSORS:
            self.violations.append(
                (
                    node.lineno,
                    f"raw S3 client accessor '{node.id}' outside core/s3.py",
                )
            )
        self.generic_visit(node)


def _call_has_s3_service_name(node: ast.Call) -> bool:
    """Return True when an S3 service name is passed to a factory call."""
    if node.args and _is_string_literal(node.args[0], TARGET_SERVICE):
        return True
    return any(
        keyword.arg == "service_name"
        and _is_string_literal(keyword.value, TARGET_SERVICE)
        for keyword in node.keywords
    )


def _is_string_literal(node: ast.AST, expected: str) -> bool:
    return isinstance(node, ast.Constant) and node.value == expected


def _is_allowlisted(py_file: Path) -> bool:
    """Return True when ``py_file`` has an allowlisted POSIX suffix."""
    posix = py_file.as_posix()
    return any(posix.endswith(allowed) for allowed in ALLOWLISTED_PATHS)


def find_violations(root: Path) -> list[str]:
    """Return S3 isolation violations found below ``root``."""
    if not root.exists():
        return []

    findings: list[str] = []
    for py_file in sorted(root.rglob("*.py")):
        if _is_allowlisted(py_file):
            continue
        try:
            source = py_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"cannot read {py_file}: {exc}") from exc
        try:
            tree = ast.parse(source, filename=str(py_file))
        except SyntaxError as exc:
            raise RuntimeError(f"syntax error in {py_file}: {exc}") from exc

        visitor = _S3IsolationVisitor()
        visitor.visit(tree)
        for lineno, detail in sorted(visitor.violations, key=lambda item: item[0]):
            findings.append(f"{py_file}:{lineno}: {detail}")
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        type=Path,
        default=Path("apps/api/echoroo"),
        help="Root directory to scan (default: apps/api/echoroo).",
    )
    parser.add_argument(
        "--no-fail",
        action="store_true",
        help="Print findings but exit 0 even when violations are found.",
    )
    args = parser.parse_args()

    try:
        violations = find_violations(args.path)
    except Exception as exc:  # noqa: BLE001 — defensive top-level catch
        print(f"[lint_s3_isolation] unexpected error: {exc}", file=sys.stderr)
        return 2

    for violation in violations:
        print(violation, file=sys.stderr)

    if violations and not args.no_fail:
        print(
            f"[lint_s3_isolation] {len(violations)} violation(s); "
            "route S3 access through apps/api/echoroo/core/s3.py",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Lint: KMS client construction is confined to apps/api/echoroo/core/kms.py.

Enforces FR-091b: only the central KMS wrapper module may instantiate
``boto3.client('kms', ...)`` or ``boto3.resource('kms', ...)``. Every
other caller must route through the wrapper so that key rotation,
envelope encryption, and audit logging stay centralised and KMS
interactions remain auditable.

Detection strategy:
    * AST-walk every ``apps/api/echoroo/**/*.py`` module.
    * Flag any call whose callable resolves to ``boto3.client`` or
      ``boto3.resource`` and whose first positional argument — or the
      ``service_name`` keyword argument — is the literal string
      ``"kms"`` (case-sensitive — AWS SDK service names are lowercase).
    * The single allowlisted file (``apps/api/echoroo/core/kms.py``)
      is skipped so the wrapper itself can legitimately construct the
      client.

Exit codes:
    0   — no violations
    1   — one or more violations printed as ``<path>:<line>: <detail>``
    2   — internal error (unreadable file, AST parse failure)

See specs/006-permissions-redesign/research.md §1 and §18, plus
spec.md FR-091b for the rationale.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ALLOWLISTED_PATHS: tuple[str, ...] = ("apps/api/echoroo/core/kms.py",)
"""Paths (as POSIX suffixes) allowed to call boto3.client('kms', ...).

Stored as substring suffixes rather than absolute paths so the check
works regardless of where the repository is checked out (CI runners,
git worktrees, developer laptops).
"""

TARGET_SERVICE = "kms"
TARGET_METHODS = frozenset({"client", "resource"})


# ---------------------------------------------------------------------------
# AST detection
# ---------------------------------------------------------------------------


class _Boto3KmsVisitor(ast.NodeVisitor):
    """Collect ``(lineno, description)`` for boto3.client('kms', ...) calls."""

    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self.violations: list[tuple[int, str]] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802 — ast API
        if self._is_boto3_kms_call(node):
            method = _call_method_name(node)
            self.violations.append(
                (
                    node.lineno,
                    f"boto3.{method}('kms', ...) outside core/kms.py",
                )
            )
        self.generic_visit(node)

    def _is_boto3_kms_call(self, node: ast.Call) -> bool:
        method = _call_method_name(node)
        if method not in TARGET_METHODS:
            return False
        if not _call_is_on_boto3(node):
            return False
        return _call_first_arg_is_kms(node)


def _call_method_name(node: ast.Call) -> str | None:
    """Return the attribute name if ``node.func`` is ``X.Y``, else None."""
    func = node.func
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _call_is_on_boto3(node: ast.Call) -> bool:
    """Return True when ``node.func`` is ``boto3.<something>(...)``.

    Handles the common patterns:
        boto3.client("kms")
        import boto3 as b3; b3.client("kms")   — NOT handled (rare; would
                                                 require import tracking).

    The second form is intentionally out of scope; all existing code in
    this repo imports boto3 as ``boto3`` and the permission redesign
    enforces that convention via a code-review rule.
    """
    func = node.func
    if not isinstance(func, ast.Attribute):
        return False
    value = func.value
    return isinstance(value, ast.Name) and value.id == "boto3"


def _call_first_arg_is_kms(node: ast.Call) -> bool:
    """Return True when the call's service_name argument is ``"kms"``.

    ``boto3.client`` accepts ``service_name`` as the first positional
    argument or as a keyword argument; we check both.
    """
    # Positional: boto3.client("kms", ...)
    if node.args:
        first = node.args[0]
        if _is_str_literal(first, TARGET_SERVICE):
            return True
    # Keyword: boto3.client(service_name="kms", ...)
    for kw in node.keywords:
        if kw.arg == "service_name" and _is_str_literal(kw.value, TARGET_SERVICE):
            return True
    return False


def _is_str_literal(node: ast.AST, expected: str) -> bool:
    return isinstance(node, ast.Constant) and node.value == expected


# ---------------------------------------------------------------------------
# File traversal
# ---------------------------------------------------------------------------


def _is_allowlisted(py_file: Path) -> bool:
    """Return True if ``py_file`` matches any allowlisted suffix.

    Comparison is done against the POSIX form of the path so Windows
    separators do not confuse the match (belt-and-braces — CI runs on
    Linux).
    """
    posix = py_file.as_posix()
    return any(posix.endswith(allowed) for allowed in ALLOWLISTED_PATHS)


def find_violations(root: Path) -> list[str]:
    """Scan ``root`` for boto3.client('kms', ...) violations.

    Returns a list of ``"<file>:<line>: <message>"`` strings — one per
    violation — suitable for printing directly to stderr.
    """
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

        visitor = _Boto3KmsVisitor(py_file)
        visitor.visit(tree)
        for lineno, detail in visitor.violations:
            findings.append(f"{py_file}:{lineno}: {detail}")
    return findings


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


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
        help=(
            "Print findings but exit 0 even on violations. Intended for "
            "local inspection; CI must NOT use this flag."
        ),
    )
    args = parser.parse_args()

    try:
        violations = find_violations(args.path)
    except Exception as exc:  # noqa: BLE001 — defensive top-level catch
        print(f"[lint_kms_isolation] unexpected error: {exc}", file=sys.stderr)
        return 2

    for v in violations:
        print(v, file=sys.stderr)

    if violations and not args.no_fail:
        print(
            f"[lint_kms_isolation] {len(violations)} violation(s); "
            "route KMS calls through apps/api/echoroo/core/kms.py",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

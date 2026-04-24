#!/usr/bin/env python3
"""Lint: every FastAPI path operation must pass through the permission guard.

Enforces FR-008 (all state-changing / data-read endpoints traverse
``is_allowed`` / ``Depends(check_action(...))``).

Detection strategy (research §18-A):

    * Walk every ``apps/api/echoroo/api/**/*.py`` module.
    * Parse each file with the standard-library ``ast`` module.
    * For any function whose decorator list contains
      ``@<router>.{get,post,put,patch,delete,head,options}(...)`` treat it as
      a path operation that must be guarded.
    * Accept a guard if EITHER:
        - the function's Depends() keyword defaults include
          ``Depends(check_action(...))`` OR ``Depends(require_permission(...))``
        - OR its body references ``is_allowed(...)`` or ``check_project_access(...)``
          at any depth.
    * Allowlist unauthenticated endpoints (auth.py register / login / etc.).

Exit codes:

    0  — no violations (or not --fail-on-violation)
    1  — at least one unguarded path operation found, with --fail-on-violation
    2  — unexpected internal error

Phase 2 status: the lint IS implemented but is wired into CI in warn-only
mode (T100a-d). T100f flips it to hard-fail once Phase 3 has rewritten every
endpoint to use the new guard.
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

HTTP_METHODS: frozenset[str] = frozenset(
    {"get", "post", "put", "patch", "delete", "head", "options"}
)

GUARD_CALLABLE_NAMES: frozenset[str] = frozenset(
    {
        "check_action",
        "require_permission",
        "is_allowed",
        "check_project_access",
    }
)

# File-level allowlist: routers whose endpoints are authentication-setup
# operations (no authenticated identity yet) and therefore legitimately have
# no permission guard.
ALLOWLIST_FILES: frozenset[str] = frozenset(
    {
        # Phase 3 will split out the session-creation endpoints; until then,
        # the whole auth.py module is exempt (research §18-A).
        "auth.py",
        "setup.py",
    }
)

# Path operations that are registered but should be exempt even within a
# non-allowlisted file (e.g. health checks, OpenAPI helpers).
ALLOWLIST_DECORATOR_PATHS: frozenset[str] = frozenset({"/health", "/", "/ready"})


def _iter_decorator_calls(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Call]:
    return [d for d in node.decorator_list if isinstance(d, ast.Call)]


def _is_http_decorator(call: ast.Call) -> bool:
    """True if ``call`` looks like ``<something>.get/post/...(...)`` ."""
    if not isinstance(call.func, ast.Attribute):
        return False
    return call.func.attr.lower() in HTTP_METHODS


def _decorator_path_arg(call: ast.Call) -> str | None:
    """Extract the string path argument of an HTTP decorator, if literal."""
    if not call.args:
        return None
    arg = call.args[0]
    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
        return arg.value
    return None


def _uses_guard_in_defaults(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    """Walk the function's argument defaults for a Depends(guard(...)) call."""
    defaults: list[ast.expr] = [
        *(d for d in node.args.defaults if d is not None),
        *(d for d in node.args.kw_defaults if d is not None),
    ]
    for default in defaults:
        for sub in ast.walk(default):
            if _is_guard_call(sub):
                return True
    return False


def _is_guard_call(sub: ast.AST) -> bool:
    if not isinstance(sub, ast.Call):
        return False
    name = _callable_name(sub.func)
    return name in GUARD_CALLABLE_NAMES


def _callable_name(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _uses_guard_in_body(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    for stmt in ast.walk(node):
        if stmt is node:
            continue
        if _is_guard_call(stmt):
            return True
    return False


def _function_has_guard(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    return _uses_guard_in_defaults(node) or _uses_guard_in_body(node)


def find_violations(root: Path) -> list[str]:
    """Return human-readable violation lines."""
    violations: list[str] = []
    if not root.exists():
        return violations

    for py_file in sorted(root.rglob("*.py")):
        if py_file.name in ALLOWLIST_FILES:
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except (OSError, SyntaxError) as exc:
            violations.append(f"{py_file}: failed to parse ({exc})")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            http_decorators = [
                d for d in _iter_decorator_calls(node) if _is_http_decorator(d)
            ]
            if not http_decorators:
                continue
            decorator_paths = [
                _decorator_path_arg(d) for d in http_decorators
            ]
            if any(p in ALLOWLIST_DECORATOR_PATHS for p in decorator_paths if p):
                continue
            if _function_has_guard(node):
                continue
            rel = py_file.relative_to(root.parent) if py_file.is_absolute() else py_file
            violations.append(
                f"{rel}:{node.lineno} {node.name} lacks Permission guard "
                f"(expected Depends(check_action(...)) or is_allowed(...))"
            )
    return violations


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

    for line in violations:
        print(line, file=sys.stderr)
    print(
        f"[lint_permission_guard] scanned {args.path}: "
        f"{len(violations)} violation(s) found",
        file=sys.stderr,
    )
    if violations and args.fail_on_violation:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

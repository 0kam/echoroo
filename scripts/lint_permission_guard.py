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

DEFAULT_ALLOWLIST = Path("scripts/allowlists/permission_guard_allowlist.txt")

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


def _load_allowlist(path: Path) -> frozenset[str]:
    """Load a fingerprint allowlist (``# comments`` permitted).

    Phase 2.11 P1-a — allowlist entries are now fingerprints in the form
    ``<file>:<fingerprint>:<short-signature>`` (or, for backwards
    compatibility during migration, a bare repo-relative path). The
    fingerprint locks the allowlist to a SPECIFIC violation rather than
    silently ignoring every future violation that lands in the same
    file.

    Lines starting with ``#`` are comments. Trailing whitespace is
    ignored. Trailing inline ``# comment`` text is stripped.

    Returns the set of full ``<file>:<fingerprint>...`` strings up to
    the first ``  #`` inline comment (two spaces + hash, the canonical
    separator) — the lint's matcher then does prefix comparison so an
    entry like
    ``apps/api/foo.py:my_handler:missing-guard  # legacy``
    matches the fingerprint
    ``apps/api/foo.py:my_handler:missing-guard``.
    """
    if not path.exists():
        return frozenset()
    entries: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        # First strip the inline "  # comment" form (two spaces + hash);
        # then if the WHOLE line is a hash-comment, drop it.
        stripped = raw_line.split("  #", 1)[0].strip()
        if not stripped or stripped.startswith("#"):
            continue
        entries.add(stripped)
    return frozenset(entries)


def _violation_fingerprint(rel_str: str, function_name: str) -> str:
    """Return the stable fingerprint for one permission-guard violation.

    Format: ``<file>:<function_name>:missing-permission-guard``. The
    function name is the AST node's identifier so it is robust against
    line-number drift across edits and refactors. The trailing
    ``missing-permission-guard`` token is the violation kind, kept short
    so allowlist diffs read cleanly.
    """
    return f"{rel_str}:{function_name}:missing-permission-guard"


def _detect_repo_root(start: Path) -> Path:
    candidate = start.resolve()
    for _ in range(8):
        if (candidate / ".git").exists():
            return candidate
        if candidate.parent == candidate:
            return candidate
        candidate = candidate.parent
    return candidate


def _relative_posix(path: Path, repo_root: Path) -> str:
    abs_path = path.resolve()
    try:
        rel = abs_path.relative_to(repo_root.resolve())
    except ValueError:
        rel = path
    return str(rel).replace("\\", "/")


def find_violations(
    root: Path,
    file_allowlist: frozenset[str] | None = None,
    repo_root: Path | None = None,
) -> list[str]:
    """Return human-readable violation lines, skipping fingerprinted allowlist entries.

    Phase 2.11 P1-a: the allowlist is now keyed by a stable PER-VIOLATION
    fingerprint (file + function name + violation kind), not by file
    path. Adding a new unguarded endpoint to a file that has other
    allowlisted endpoints will now correctly fail the lint.
    """
    violations: list[str] = []
    if not root.exists():
        return violations
    if file_allowlist is None:
        file_allowlist = frozenset()
    if repo_root is None:
        repo_root = _detect_repo_root(root)

    for py_file in sorted(root.rglob("*.py")):
        if py_file.name in ALLOWLIST_FILES:
            continue
        rel_str = _relative_posix(py_file, repo_root)
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
            fingerprint = _violation_fingerprint(rel_str, node.name)
            if fingerprint in file_allowlist:
                continue
            rel = py_file.relative_to(root.parent) if py_file.is_absolute() else py_file
            violations.append(
                f"{rel}:{node.lineno} {node.name} lacks Permission guard "
                f"(expected Depends(check_action(...)) or is_allowed(...))  "
                f"[fingerprint: {fingerprint}]"
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
        "--allowlist-file",
        type=Path,
        default=DEFAULT_ALLOWLIST,
        help=(
            f"Allowlist file (default: {DEFAULT_ALLOWLIST}). Each non-empty / "
            "non-comment line is a repo-relative path to skip."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root (default: auto-detect via .git marker).",
    )
    parser.add_argument(
        "--fail-on-violation",
        action="store_true",
        help="Exit with status 1 if any violations are found.",
    )
    args = parser.parse_args()

    try:
        allowlist = _load_allowlist(args.allowlist_file)
        violations = find_violations(args.path, allowlist, args.repo_root)
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

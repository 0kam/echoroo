#!/usr/bin/env python3
"""Lint: every Recording/Detection/Site response must pass apply_response_filter.

Enforces FR-011 (ResponseFilter mandatory on all Recording/Detection/Site
response paths so that privileged fields such as raw coordinates and
uploader PII are stripped before serialization).

Detection strategy (research §18-B):

    * Walk every ``apps/api/echoroo/api/**/*.py`` module.
    * Parse each file with the standard-library ``ast`` module.
    * Identify path-operation functions where either
        - a decorator keyword arg ``response_model=`` names ``Recording``,
          ``Detection``, or ``Site`` (directly or inside a generic such as
          ``list[...]`` / ``Page[...]`` / ``PaginatedResponse[...]``), or
        - the return annotation contains the same names.
    * Verify that the function body references ``apply_response_filter(...)``
      or is decorated with ``@with_response_filter``.
    * Report functions that are missing the filter.

Exit codes:

    0  — no violations (or not --fail-on-violation)
    1  — at least one unfiltered response found, with --fail-on-violation
    2  — unexpected internal error

Phase 2 status: implementation complete; CI runs in warn-only mode
(T100a-d) until Phase 3 wires ``apply_response_filter`` into every
Recording/Detection/Site endpoint. T100f flips it to hard-fail.
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

DEFAULT_ALLOWLIST = Path("scripts/allowlists/response_filter_allowlist.txt")

TARGET_RESPONSE_MODELS: frozenset[str] = frozenset(
    {
        "Recording",
        "RecordingResponse",
        "Detection",
        "DetectionResponse",
        "Site",
        "SiteResponse",
    }
)

FILTER_CALLABLE_NAMES: frozenset[str] = frozenset(
    {
        "apply_response_filter",
        "with_response_filter",
    }
)

HTTP_METHODS: frozenset[str] = frozenset(
    {"get", "post", "put", "patch", "delete"}
)


def _iter_decorator_calls(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[ast.Call]:
    return [d for d in node.decorator_list if isinstance(d, ast.Call)]


def _is_http_decorator(call: ast.Call) -> bool:
    return (
        isinstance(call.func, ast.Attribute)
        and call.func.attr.lower() in HTTP_METHODS
    )


def _collect_response_model_names(call: ast.Call) -> list[str]:
    names: list[str] = []
    for kw in call.keywords:
        if kw.arg == "response_model":
            names.extend(_extract_type_names(kw.value))
    return names


def _extract_type_names(node: ast.AST) -> list[str]:
    """Pull out every ``Name`` token from a type expression.

    Handles ``Recording``, ``list[Recording]``, ``Page[Recording]``,
    ``PaginatedResponse[list[Recording]]``, ``Recording | None`` etc.
    """
    found: list[str] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name):
            found.append(sub.id)
        elif isinstance(sub, ast.Attribute):
            found.append(sub.attr)
    return found


def _uses_filter_in_body(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for sub in ast.walk(node):
        if sub is node:
            continue
        if not isinstance(sub, ast.Call):
            continue
        name = _callable_name(sub.func)
        if name in FILTER_CALLABLE_NAMES:
            return True
    return False


def _callable_name(func: ast.expr) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _has_filter_decorator(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    for dec in node.decorator_list:
        name = _callable_name(dec.func) if isinstance(dec, ast.Call) else _callable_name(dec)
        if name in FILTER_CALLABLE_NAMES:
            return True
    return False


def _return_annotation_names(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[str]:
    if node.returns is None:
        return []
    return _extract_type_names(node.returns)


def _load_allowlist(path: Path) -> frozenset[str]:
    """Load a fingerprint allowlist (``# comments`` permitted).

    Phase 2.11 P1-a — entries are fingerprints of the form
    ``<file>:<function_name>:missing-response-filter``. Inline comments
    use ``  #`` (two spaces + hash) so they are stripped before
    matching. Bare ``#`` lines are full-line comments.
    """
    if not path.exists():
        return frozenset()
    entries: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.split("  #", 1)[0].strip()
        if not stripped or stripped.startswith("#"):
            continue
        entries.add(stripped)
    return frozenset(entries)


def _violation_fingerprint(rel_str: str, function_name: str) -> str:
    """Stable fingerprint for one missing-response-filter violation."""
    return f"{rel_str}:{function_name}:missing-response-filter"


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
    allowlist: frozenset[str] | None = None,
    repo_root: Path | None = None,
) -> list[str]:
    violations: list[str] = []
    if not root.exists():
        return violations
    if allowlist is None:
        allowlist = frozenset()
    if repo_root is None:
        repo_root = _detect_repo_root(root)

    for py_file in sorted(root.rglob("*.py")):
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
            response_names: list[str] = []
            for dec in http_decorators:
                response_names.extend(_collect_response_model_names(dec))
            response_names.extend(_return_annotation_names(node))
            if not any(name in TARGET_RESPONSE_MODELS for name in response_names):
                continue
            if _uses_filter_in_body(node) or _has_filter_decorator(node):
                continue
            fingerprint = _violation_fingerprint(rel_str, node.name)
            if fingerprint in allowlist:
                continue
            rel = py_file.relative_to(root.parent) if py_file.is_absolute() else py_file
            violations.append(
                f"{rel}:{node.lineno} {node.name} returns Recording/Detection/Site "
                f"without apply_response_filter(...)  [fingerprint: {fingerprint}]"
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
        print(f"[lint_response_filter] unexpected error: {exc}", file=sys.stderr)
        return 2

    for line in violations:
        print(line, file=sys.stderr)
    print(
        f"[lint_response_filter] scanned {args.path}: "
        f"{len(violations)} violation(s) found",
        file=sys.stderr,
    )
    if violations and args.fail_on_violation:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

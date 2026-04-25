#!/usr/bin/env python3
"""Lint: raw latitude / longitude / gps_* names must not leak from the API.

Enforces FR-028f / FR-091b / SC-019 (coordinate privacy): raw ``lat``,
``lng``, ``latitude``, ``longitude``, ``coordinates``, ``geo_point`` and
``gps_*`` identifiers must never appear as:

    * Pydantic model field names (class-level annotated attributes, or
      ``Field(...)`` assignments).
    * SQLAlchemy ``Column(...)`` / ``mapped_column(...)`` declarations.
    * Dict-literal STRING keys (``{"lat": ...}``) — only string-literal
      keys are checked so docstrings, URLs, and comments cannot trigger
      false positives.

Detection strategy (research §18-E/F, mirrors ``lint_search_gate.py``):

    * Walk every ``apps/api/echoroo/**/*.py`` module plus the contracts
      directory ``specs/006-permissions-redesign/contracts/`` (as YAML
      text, not parsed AST).
    * Parse Python files with the standard-library ``ast`` module and
      flag the three categories above.
    * Skip whole files listed in
      ``scripts/allowlists/raw_coordinates_allowlist.txt``. The
      allowlist hosts intentional uses (e.g. the Celery payload
      validator, which enumerates the denylist as data).

Exit codes:

    0 — no violations (or not --fail-on-violation)
    1 — at least one forbidden identifier found, with --fail-on-violation
    2 — unexpected internal error

Phase 2 status: lint IS implemented. CI wires it in warn-only mode in
T100d; T100f flips it to hard-fail once Phase 3 has migrated all
recording / site / detection schemas to ``h3_index`` only.
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

# Forbidden identifiers, matched as exact tokens.
FORBIDDEN_NAMES: frozenset[str] = frozenset(
    {
        "lat",
        "lng",
        "latitude",
        "longitude",
        "coordinates",
        "geo_point",
    }
)

# Forbidden prefixes (matched as ``name.startswith(prefix)``).
FORBIDDEN_PREFIXES: tuple[str, ...] = ("gps_",)

# Default scan roots.
DEFAULT_PY_ROOT = Path("apps/api/echoroo")
DEFAULT_CONTRACTS_ROOT = Path("specs/006-permissions-redesign/contracts")
DEFAULT_ALLOWLIST = Path("scripts/allowlists/raw_coordinates_allowlist.txt")

# YAML key regex used for the contracts directory (text-based check only;
# we are not pulling in a YAML parser to keep this script dep-free).
_YAML_KEY_RE = re.compile(
    r"^\s*[-]?\s*(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*:",
    re.MULTILINE,
)


# ---------------------------------------------------------------------------
# Allowlist loading
# ---------------------------------------------------------------------------


def _load_allowlist(path: Path) -> frozenset[str]:
    if not path.exists():
        return frozenset()
    entries: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if line:
            entries.add(line)
    return frozenset(entries)


def _is_allowlisted(rel_path: str, allowlist: frozenset[str]) -> bool:
    return rel_path in allowlist


# ---------------------------------------------------------------------------
# Token classification
# ---------------------------------------------------------------------------


def _is_forbidden(name: str) -> bool:
    if not name:
        return False
    if name in FORBIDDEN_NAMES:
        return True
    return any(name.startswith(prefix) for prefix in FORBIDDEN_PREFIXES)


# ---------------------------------------------------------------------------
# Python AST scanner
# ---------------------------------------------------------------------------


def _scan_python_file(rel_str: str, source: str) -> list[str]:
    """Return violation strings for a single Python source string."""
    violations: list[str] = []
    try:
        tree = ast.parse(source, filename=rel_str)
    except SyntaxError as exc:
        return [f"{rel_str}: failed to parse ({exc})"]

    for node in ast.walk(tree):
        # 1) Class-level Pydantic / dataclass / SQLAlchemy fields:
        #    ``lat: float`` (AnnAssign with Name target).
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            if _is_forbidden(name):
                violations.append(
                    f"{rel_str}:{node.lineno}  forbidden field name "
                    f"'{name}' (use h3_index instead)"
                )
            continue

        # 2) Plain assignments:
        #    ``lat = Column(...)`` / ``lat = mapped_column(...)`` /
        #    ``lat = Field(...)``.
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and _is_forbidden(target.id):
                    violations.append(
                        f"{rel_str}:{node.lineno}  forbidden field name "
                        f"'{target.id}' (use h3_index instead)"
                    )
            continue

        # 3) Dict literals — only flag string-literal keys; non-literal
        #    keys (variables / expressions) are ignored to avoid
        #    false positives.
        if isinstance(node, ast.Dict):
            for key in node.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    if _is_forbidden(key.value):
                        violations.append(
                            f"{rel_str}:{node.lineno}  forbidden dict key "
                            f"'{key.value}' (use h3_index instead)"
                        )
            continue

    return violations


# ---------------------------------------------------------------------------
# YAML (contracts) text scanner
# ---------------------------------------------------------------------------


def _scan_yaml_file(rel_str: str, source: str) -> list[str]:
    """Flag YAML mapping keys (``key:``) that match the denylist.

    Strings inside descriptions / values / comments are ignored — only
    the line-leading mapping key is matched.
    """
    violations: list[str] = []
    for match in _YAML_KEY_RE.finditer(source):
        key = match.group("key")
        if _is_forbidden(key):
            line_no = source[: match.start()].count("\n") + 1
            violations.append(
                f"{rel_str}:{line_no}  forbidden YAML key "
                f"'{key}' (use h3_index instead)"
            )
    return violations


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _relative_posix(path: Path, repo_root: Path) -> str:
    abs_path = path.resolve()
    try:
        rel = abs_path.relative_to(repo_root.resolve())
    except ValueError:
        rel = path
    return str(rel).replace("\\", "/")


def _detect_repo_root(start: Path) -> Path:
    candidate = start.resolve()
    for _ in range(8):
        if (candidate / ".git").exists():
            return candidate
        if candidate.parent == candidate:
            return candidate
        candidate = candidate.parent
    return candidate


def find_violations(
    py_root: Path,
    contracts_root: Path | None,
    allowlist: frozenset[str],
    repo_root: Path | None = None,
) -> list[str]:
    violations: list[str] = []
    if repo_root is None:
        repo_root = _detect_repo_root(py_root)

    if py_root.exists():
        for py_file in sorted(py_root.rglob("*.py")):
            rel_str = _relative_posix(py_file, repo_root)
            if _is_allowlisted(rel_str, allowlist):
                continue
            try:
                source = py_file.read_text(encoding="utf-8")
            except OSError as exc:
                violations.append(f"{rel_str}: failed to read ({exc})")
                continue
            violations.extend(_scan_python_file(rel_str, source))

    if contracts_root is not None and contracts_root.exists():
        for yaml_file in sorted(contracts_root.rglob("*")):
            if not yaml_file.is_file() or yaml_file.suffix not in (".yaml", ".yml"):
                continue
            rel_str = _relative_posix(yaml_file, repo_root)
            if _is_allowlisted(rel_str, allowlist):
                continue
            try:
                source = yaml_file.read_text(encoding="utf-8")
            except OSError as exc:
                violations.append(f"{rel_str}: failed to read ({exc})")
                continue
            violations.extend(_scan_yaml_file(rel_str, source))

    return violations


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_PY_ROOT,
        help=f"Python root to scan (default: {DEFAULT_PY_ROOT}).",
    )
    parser.add_argument(
        "--contracts",
        type=Path,
        default=DEFAULT_CONTRACTS_ROOT,
        help=(
            f"Contracts directory to scan (default: {DEFAULT_CONTRACTS_ROOT}). "
            "Pass an empty string to skip."
        ),
    )
    parser.add_argument(
        "--allowlist-file",
        type=Path,
        default=DEFAULT_ALLOWLIST,
        help=(
            f"Allowlist file (default: {DEFAULT_ALLOWLIST}). "
            "Each non-empty / non-comment line is a repo-relative path."
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

    contracts_root: Path | None = args.contracts
    if contracts_root is not None and str(contracts_root) == "":
        contracts_root = None

    try:
        allowlist = _load_allowlist(args.allowlist_file)
        violations = find_violations(
            args.path,
            contracts_root,
            allowlist,
            repo_root=args.repo_root,
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[lint_no_raw_coordinates] unexpected error: {exc}", file=sys.stderr)
        return 2

    for line in violations:
        print(line, file=sys.stderr)
    print(
        f"[lint_no_raw_coordinates] scanned {args.path}: "
        f"{len(violations)} violation(s) found",
        file=sys.stderr,
    )
    if violations and args.fail_on_violation:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

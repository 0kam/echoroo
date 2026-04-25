#!/usr/bin/env python3
"""Lint: direct SQLAlchemy select() on Detection / Annotation models is
confined to SearchGate.

Enforces FR-025 (all detection / annotation search traffic is forced
through ``services/search_gate.py``, which applies the permission +
visibility filter). Direct ``select(Detection)`` / ``select(Annotation)``
calls outside the allowlisted files risk leaking records from projects
the caller cannot view.

Detection strategy (research §18-C):

    * Walk every ``apps/api/echoroo/**/*.py`` module.
    * Parse each file with the standard-library ``ast`` module.
    * For every call expression of the form ``select(<X>)``, ``select(<X>,
      ...)``, ``select(<X>.col)``, or ``select(...).select_from(<X>)`` —
      where ``<X>`` resolves to a name in :data:`FORBIDDEN_MODELS`
      (directly or via attribute access such as ``models.Detection``) —
      emit a violation unless the file is on the allowlist.

Allowlisted files (only these may call ``select(Detection)`` directly):

    * apps/api/echoroo/services/search_gate.py
    * apps/api/echoroo/repositories/detection.py

Optional ``--allowlist <path>`` adds further temporary exemptions. The
shipped allowlist file lives at
``scripts/allowlists/search_gate_allowlist.txt`` and is empty by default.

Exit codes:

    0 — no violations (or not --fail-on-violation)
    1 — at least one direct select(...) call found, with --fail-on-violation
    2 — unexpected internal error

Phase 2 status: lint IS implemented. CI wires it in warn-only mode in
T100c; T100f flips it to hard-fail once Phase 3 has migrated every
detection / annotation read path through ``SearchGate``.
"""
from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

# Models that may NOT be selected directly outside the allowlist.
FORBIDDEN_MODELS: frozenset[str] = frozenset({"Detection", "Annotation"})

# Hard-coded allowlist (always honoured, regardless of --allowlist file).
_ALWAYS_ALLOWED: tuple[str, ...] = (
    "apps/api/echoroo/services/search_gate.py",
    "apps/api/echoroo/repositories/detection.py",
)

# Default search root.
DEFAULT_ROOT = Path("apps/api/echoroo")
DEFAULT_ALLOWLIST = Path("scripts/allowlists/search_gate_allowlist.txt")


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _is_select_call(call: ast.Call) -> bool:
    """True iff ``call`` looks like ``select(...)`` / ``sa.select(...)`` /
    ``_select(...)`` etc. We match on the trailing identifier so aliased
    imports (``from sqlalchemy import select as sa_select``) are caught.
    """
    func = call.func
    if isinstance(func, ast.Name):
        return func.id == "select" or func.id.endswith("_select")
    if isinstance(func, ast.Attribute):
        return func.attr == "select" or func.attr.endswith("_select")
    return False


def _name_of(node: ast.AST) -> str | None:
    """Return the trailing identifier of a Name / Attribute / Call.

    ``Detection``  -> "Detection"
    ``models.Detection`` -> "Detection"
    ``models.Detection.column`` -> "Detection"  (we walk one level up)
    ``func.count()`` -> None (function call, not a model reference)
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _references_forbidden_model(node: ast.AST) -> str | None:
    """Walk ``node`` and return the first forbidden model name found.

    Handles bare names, ``Detection.column`` attribute chains, and nested
    expressions (``func.count(Detection.id)`` would also flag).
    """
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and sub.id in FORBIDDEN_MODELS:
            return sub.id
        if isinstance(sub, ast.Attribute) and sub.attr in FORBIDDEN_MODELS:
            return sub.attr
    return None


# ---------------------------------------------------------------------------
# Allowlist loading
# ---------------------------------------------------------------------------


def _load_extra_allowlist(path: Path | None) -> frozenset[str]:
    """Load a fingerprint allowlist (Phase 2.11 P1-a).

    Format: ``<file>:select-<MODEL>:direct-select-outside-search-gate``
    or ``<file>:select_from-<MODEL>:direct-select_from-outside-search-gate``.
    Inline comments use ``  #`` (two spaces + hash).
    """
    if path is None:
        return frozenset()
    if not path.exists():
        return frozenset()
    entries: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.split("  #", 1)[0].strip()
        if not stripped or stripped.startswith("#"):
            continue
        entries.add(stripped)
    return frozenset(entries)


def _is_always_allowed(rel_path: str) -> bool:
    """File-level always-allow (the SearchGate implementation itself)."""
    return rel_path in _ALWAYS_ALLOWED


def _violation_fingerprint(rel_str: str, kind: str, model: str) -> str:
    """Stable fingerprint for one direct-select violation.

    Args:
        rel_str: Repo-relative POSIX path.
        kind: ``"select"`` or ``"select_from"``.
        model: Forbidden model name (``"Detection"`` / ``"Annotation"``).
    """
    return f"{rel_str}:{kind}-{model}:direct-{kind}-outside-search-gate"


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------


def find_violations(
    root: Path,
    *,
    extra_allowlist: frozenset[str] = frozenset(),
    repo_root: Path | None = None,
) -> list[str]:
    """Return human-readable violation lines.

    Args:
        root: Directory to walk.
        extra_allowlist: User-supplied additional allowlist entries
            (relative to ``repo_root``).
        repo_root: Repository root used for path normalisation. Defaults
            to ``root.parent.parent.parent`` for the standard
            ``apps/api/echoroo/`` layout, falling back to the file's own
            absolute path otherwise.
    """
    violations: list[str] = []
    if not root.exists():
        return violations

    if repo_root is None:
        # Auto-detect: walk upward until a `.git` directory appears.
        # Stops at the filesystem root if no marker is ever found.
        candidate = root.resolve()
        for _ in range(8):
            if (candidate / ".git").exists():
                break
            if candidate.parent == candidate:
                break
            candidate = candidate.parent
        repo_root = candidate

    for py_file in sorted(root.rglob("*.py")):
        rel_str = _relative_posix(py_file, repo_root)
        if _is_always_allowed(rel_str):
            continue
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except (OSError, SyntaxError) as exc:
            violations.append(f"{rel_str}: failed to parse ({exc})")
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _is_select_call(node):
                model = _select_call_targets_forbidden(node)
                if model is not None:
                    fingerprint = _violation_fingerprint(rel_str, "select", model)
                    if fingerprint in extra_allowlist:
                        continue
                    violations.append(
                        f"{rel_str}:{node.lineno}  direct select({model}) outside SearchGate "
                        f"(use services/search_gate.py)  [fingerprint: {fingerprint}]"
                    )
                continue
            # Detect ``.select_from(Detection)`` chained off any earlier
            # select() — e.g. ``select(func.count()).select_from(Detection)``.
            if isinstance(node.func, ast.Attribute) and node.func.attr == "select_from":
                model = _first_arg_targets_forbidden(node)
                if model is not None:
                    fingerprint = _violation_fingerprint(
                        rel_str, "select_from", model
                    )
                    if fingerprint in extra_allowlist:
                        continue
                    violations.append(
                        f"{rel_str}:{node.lineno}  .select_from({model}) outside SearchGate "
                        f"(use services/search_gate.py)  [fingerprint: {fingerprint}]"
                    )
    return violations


def _select_call_targets_forbidden(call: ast.Call) -> str | None:
    """Return the forbidden model name referenced as a positional arg, if any."""
    for arg in call.args:
        model = _references_forbidden_model(arg)
        if model is not None:
            return model
    return None


def _first_arg_targets_forbidden(call: ast.Call) -> str | None:
    if not call.args:
        return None
    return _references_forbidden_model(call.args[0])


def _relative_posix(path: Path, repo_root: Path) -> str:
    abs_path = path.resolve()
    try:
        rel = abs_path.relative_to(repo_root.resolve())
    except ValueError:
        rel = path
    return str(rel).replace("\\", "/")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_ROOT,
        help=f"Root directory to scan (default: {DEFAULT_ROOT}).",
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=DEFAULT_ALLOWLIST,
        help=(
            f"Optional extra allowlist file (default: {DEFAULT_ALLOWLIST}). "
            "Each line is a repo-relative path; lines starting with `#` are comments."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Repository root for path normalisation (default: auto-detect).",
    )
    parser.add_argument(
        "--fail-on-violation",
        action="store_true",
        help="Exit with status 1 if any violations are found.",
    )
    args = parser.parse_args()

    try:
        extra = _load_extra_allowlist(args.allowlist)
        violations = find_violations(
            args.path,
            extra_allowlist=extra,
            repo_root=args.repo_root,
        )
    except Exception as exc:  # pragma: no cover - defensive
        print(f"[lint_search_gate] unexpected error: {exc}", file=sys.stderr)
        return 2

    for line in violations:
        print(line, file=sys.stderr)
    print(
        f"[lint_search_gate] scanned {args.path}: "
        f"{len(violations)} violation(s) found",
        file=sys.stderr,
    )
    if violations and args.fail_on_violation:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

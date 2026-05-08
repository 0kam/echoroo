#!/usr/bin/env python3
"""Lint: no plain ``@pytest.fixture`` decorator on ``async def`` fixtures.

Background
----------
Phase 17 §D-0 (PR #47) flipped mutmut's in-process pytest.main() from
``asyncio_mode=auto`` to ``asyncio_mode=strict`` to avoid pytest-asyncio
1.3.0 corrupting the global EventLoopPolicy on the second in-process
call. Strict mode requires async fixtures to use
``@pytest_asyncio.fixture``; a plain ``@pytest.fixture`` on an
``async def`` produces an async generator object that pytest-asyncio
strict mode refuses to await, breaking mutmut's baseline (exit 4 /
USAGE_ERROR) and any downstream test that consumes the fixture.

PR #47 converted all 68 pre-existing offending fixtures (across 16
files under ``tests/security/``). This script is the static guard that
prevents future regressions.

Detection strategy
------------------
For each scanned ``.py`` file:

1. AST-parse the source.
2. Walk every ``AsyncFunctionDef`` node.
3. For each decorator, resolve whether it refers to ``pytest.fixture``
   (either ``@pytest.fixture`` or ``@pytest.fixture(...)``). The
   compatible alternative ``@pytest_asyncio.fixture`` (or
   ``@pytest_asyncio.fixture(...)``) is intentionally allowed.
4. Report each violation as ``<path>:<lineno>: <function_name>``.

Scanned roots
-------------
* ``apps/api/tests/unit/``  (recursive, ``*.py``)
* ``apps/api/tests/security/`` (recursive, ``*.py``)
* ``apps/api/conftest.py`` (root, if present)
* Any nested ``conftest.py`` within the two test trees (covered by the
  recursive walk above).

Exit codes
----------
0   — no violations
1   — one or more violations printed
2   — internal error (unreadable file, AST parse failure)

The script is stdlib-only (``ast``, ``argparse``, ``pathlib``, ``sys``)
so it does not require the backend virtualenv to run — `python3` is
sufficient. This keeps the CI step fast and isolated.
"""

from __future__ import annotations

import argparse
import ast
import sys
from collections.abc import Iterable
from pathlib import Path

# ---------------------------------------------------------------------------
# Repository-relative scan roots.
#
# Stored as POSIX suffixes so the script works regardless of where the
# repository is checked out (CI, git worktrees, developer laptops). Resolved
# against the directory passed via ``--repo-root`` (defaults to the parent of
# this script's ``scripts/`` directory).
# ---------------------------------------------------------------------------
SCAN_DIRS: tuple[str, ...] = (
    "apps/api/tests/unit",
    "apps/api/tests/security",
)
SCAN_FILES: tuple[str, ...] = (
    "apps/api/conftest.py",
)


def _iter_python_files(repo_root: Path) -> Iterable[Path]:
    """Yield every ``*.py`` file inside the configured scan roots."""

    for rel_dir in SCAN_DIRS:
        root = repo_root / rel_dir
        if not root.is_dir():
            continue
        # rglob is deterministic in alphabetical order on a single platform,
        # but sort to keep CI output stable across runners.
        for path in sorted(root.rglob("*.py")):
            yield path

    for rel_file in SCAN_FILES:
        path = repo_root / rel_file
        if path.is_file():
            yield path


def _decorator_names(decorator: ast.expr) -> tuple[str | None, str | None]:
    """Return ``(module, attr)`` for an ``Attribute``-style decorator.

    Examples::

        @pytest.fixture           -> ("pytest", "fixture")
        @pytest.fixture(scope=..) -> ("pytest", "fixture")
        @pytest_asyncio.fixture   -> ("pytest_asyncio", "fixture")
        @fixture                  -> (None, "fixture")
        @some.deeply.nested.x     -> (None, None)  # not interesting

    The function deliberately keeps the resolution simple — we only care
    about the two-segment ``<module>.<attr>`` shape because that is how
    ``pytest.fixture`` and ``pytest_asyncio.fixture`` are conventionally
    written. Bare ``from pytest import fixture`` style usage is uncommon
    in this codebase but would slip past this lint; the convention check
    in ruff (E402-style import order) plus code review covers it.
    """

    # Strip the call wrapper if present: @pytest.fixture(scope="module")
    node = decorator.func if isinstance(decorator, ast.Call) else decorator

    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
        return node.value.id, node.attr
    if isinstance(node, ast.Name):
        return None, node.id
    return None, None


def _is_pytest_fixture_decorator(decorator: ast.expr) -> bool:
    """True iff the decorator is the forbidden ``pytest.fixture`` form."""

    module, attr = _decorator_names(decorator)
    return module == "pytest" and attr == "fixture"


def _scan_file(path: Path) -> list[tuple[int, str]]:
    """Return ``[(lineno, func_name), ...]`` violations for one file.

    Raises ``SyntaxError`` (re-raised by the caller as a hard error) when
    AST parsing fails so that broken test files are surfaced loudly
    instead of silently skipped.
    """

    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    violations: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef):
            continue
        for decorator in node.decorator_list:
            if _is_pytest_fixture_decorator(decorator):
                violations.append((node.lineno, node.name))
                # One report per fixture is sufficient even if (somehow)
                # the function carries multiple ``@pytest.fixture``
                # decorators.
                break
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail if any async def fixture under apps/api/tests/{unit,security} "
            "or apps/api/conftest.py uses @pytest.fixture instead of "
            "@pytest_asyncio.fixture."
        ),
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help=(
            "Repository root (defaults to the parent of this script's "
            "scripts/ directory)."
        ),
    )
    args = parser.parse_args(argv)

    repo_root: Path = args.repo_root.resolve()

    total_violations = 0
    files_scanned = 0
    files_with_violations: list[Path] = []

    try:
        for path in _iter_python_files(repo_root):
            files_scanned += 1
            try:
                violations = _scan_file(path)
            except SyntaxError as exc:
                print(
                    f"ERROR: AST parse failed for {path}: {exc}",
                    file=sys.stderr,
                )
                return 2
            except OSError as exc:
                print(
                    f"ERROR: could not read {path}: {exc}",
                    file=sys.stderr,
                )
                return 2

            if violations:
                files_with_violations.append(path)
                rel = path.relative_to(repo_root)
                for lineno, func_name in violations:
                    print(
                        f"{rel}:{lineno}: async fixture '{func_name}' uses "
                        "@pytest.fixture; use @pytest_asyncio.fixture instead "
                        "(asyncio_mode=strict)."
                    )
                    total_violations += 1
    except Exception as exc:  # pragma: no cover - defensive
        print(f"ERROR: unexpected scan failure: {exc}", file=sys.stderr)
        return 2

    print(
        f"\nScanned {files_scanned} file(s) under "
        f"{', '.join(SCAN_DIRS)} + {', '.join(SCAN_FILES)}.",
        file=sys.stderr,
    )

    if total_violations:
        print(
            f"FAIL: {total_violations} violation(s) across "
            f"{len(files_with_violations)} file(s). "
            "Convert each to @pytest_asyncio.fixture and add "
            "`import pytest_asyncio` if missing.",
            file=sys.stderr,
        )
        return 1

    print("OK: no plain @pytest.fixture on async def fixtures.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

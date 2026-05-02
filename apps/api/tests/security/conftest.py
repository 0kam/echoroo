"""Security-suite collection hook (Phase 17 follow-up — Codex 推奨).

The CI ``security-tests`` job runs ``pytest -m "security and not performance"``
to gate the security-suite as a separate pipeline. Until this hook landed,
no test under ``tests/security/**`` carried the ``@pytest.mark.security``
marker — collection produced 0 items and the job exited with status 5
(``no tests ran``).

Manually adding ``pytestmark = pytest.mark.security`` to every file would
collide with existing module-level pytestmarks (``pytest.mark.asyncio``,
xfail / skip toggles, and several files that already chain markers). The
safer fix is collection-time auto-tagging: every item physically located
under ``tests/security/`` gets the ``security`` marker added via
``add_marker`` so existing markers are preserved.

The companion ``markers`` entry in ``pyproject.toml`` registers the
marker so ``--strict-markers`` (already enabled project-wide) does not
reject it.

Hard-gate promotion (currently warn-ratchet in CI) is **out of scope**
for this hook — it is enabled only after the suite has been observed
running cleanly for a few cycles, per Codex guidance.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_SECURITY_ROOT = Path(__file__).resolve().parent


def pytest_collection_modifyitems(
    config: pytest.Config,  # noqa: ARG001 — pytest hookspec requires this name
    items: list[pytest.Item],
) -> None:
    """Auto-tag every test under ``tests/security/**`` with ``@pytest.mark.security``.

    The CI ``security-tests`` job (``pytest -m security``) collects the
    suite via this marker. Auto-tagging keeps existing per-file
    pytestmark declarations (``asyncio``, ``xfail``, etc.) intact while
    guaranteeing 100% coverage of the security tree without manual
    boilerplate.
    """
    security_marker = pytest.mark.security
    for item in items:
        # ``item.path`` (pytest>=7) is the canonical location; fall back
        # to ``fspath`` for compatibility with older plugins. The string
        # comparison is platform-aware via ``Path``.
        try:
            raw_path = Path(str(item.path))
        except (AttributeError, TypeError):
            raw_path = Path(str(item.fspath))
        # Codex Round 4 Minor: resolve() the item path before relative_to
        # so symlink-based test runners (worktree, monorepo bind-mounts)
        # do not silently miss items whose physical location matches
        # _SECURITY_ROOT under a different alias.
        try:
            item_path = raw_path.resolve()
        except (OSError, RuntimeError):
            item_path = raw_path
        try:
            item_path.relative_to(_SECURITY_ROOT)
        except ValueError:
            # Item lives outside tests/security/ — leave it alone.
            continue
        item.add_marker(security_marker)

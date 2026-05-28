"""Focused tests for Alembic revision 0023 (spec/012 Phase 2)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_MIGRATION_RELATIVE_PATH = (
    Path("alembic") / "versions" / "0023_license_master_unification.py"
)
MIGRATION_REVISION = "0023"
PREVIOUS_REVISION = "0022"


def _resolve_migration_path() -> Path:
    this_file = Path(__file__).resolve()
    candidates = [parent / _MIGRATION_RELATIVE_PATH for parent in this_file.parents]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


MIGRATION_PATH = _resolve_migration_path()


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        f"migration_{MIGRATION_REVISION}", MIGRATION_PATH
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_revision_identifiers() -> None:
    module = _load_migration()

    assert module.revision == MIGRATION_REVISION
    assert module.down_revision == PREVIOUS_REVISION


def test_downgrade_raises_not_implemented() -> None:
    module = _load_migration()

    with pytest.raises(NotImplementedError, match="spec/012 A-005"):
        module.downgrade()


def test_downgrade_message_directs_restore_from_backup() -> None:
    module = _load_migration()

    with pytest.raises(NotImplementedError, match="restore from backup"):
        module.downgrade()

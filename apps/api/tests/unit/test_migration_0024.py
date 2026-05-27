"""Focused tests for Alembic revision 0024 (spec/012 Phase 2)."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

_MIGRATION_RELATIVE_PATH = (
    Path("alembic") / "versions" / "0024_license_master_unification.py"
)


def _resolve_migration_path() -> Path:
    this_file = Path(__file__).resolve()
    candidates = [parent / _MIGRATION_RELATIVE_PATH for parent in this_file.parents]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


MIGRATION_PATH = _resolve_migration_path()


def _load_migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0024", MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_downgrade_raises_not_implemented() -> None:
    module = _load_migration()

    with pytest.raises(NotImplementedError, match="forward-only"):
        module.downgrade()

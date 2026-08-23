"""Focused tests for Alembic revision 0035 (taxonomy WS-A v2 slice 3).

Migration 0035 adds the Catalogue of Life XR identity columns to ``taxa``. The
test database schema is built from ``Base.metadata.create_all`` rather than by
replaying Alembic, so these tests do not execute the migration end-to-end. They
lock the revision wiring, assert the up/down operations against a recording
stub, and verify the ORM model carries the same columns and index semantics.

Mirrors the structure of ``tests/unit/test_migration_0034.py``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import sqlalchemy as sa

_MIGRATION_RELATIVE_PATH = (
    Path("alembic") / "versions" / "0035_taxa_col_xr_identity.py"
)
MIGRATION_REVISION = "0035"
PREVIOUS_REVISION = "0034"

TABLE = "taxa"

#: ``column name -> (SQLAlchemy type, expected length or None)``. Every one of
#: these must be added NULLABLE — the migration is additive on a live table.
EXPECTED_COLUMNS: dict[str, tuple[type[Any], int | None]] = {
    "col_xr_id": (sa.String, 16),
    "col_xr_accepted_id": (sa.String, 16),
    "col_xr_accepted_rank": (sa.String, 20),
    "col_xr_status": (sa.String, 32),
    "col_xr_match_type": (sa.String, 20),
    "col_xr_match_confidence": (sa.SmallInteger, None),
    "col_xr_release": (sa.String, 32),
    "col_xr_clb_dataset_key": (sa.Integer, None),
    "col_xr_resolved_at": (sa.DateTime, None),
    "authorship": (sa.String, 200),
    "accepted_authorship": (sa.String, 200),
    "col_xr_classification": (sa.types.JSON, None),
}

EXPECTED_INDEXES: dict[str, str] = {
    "ix_taxa_col_xr_id": "col_xr_id",
    "ix_taxa_col_xr_accepted_id": "col_xr_accepted_id",
}


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


class _RecordingOp:
    """Minimal stand-in for ``alembic.op`` that records invocations."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def __getattr__(self, name: str) -> Any:
        def _record(*args: Any, **kwargs: Any) -> None:
            self.calls.append((name, args, kwargs))

        return _record


def _record(direction: str, monkeypatch: pytest.MonkeyPatch) -> _RecordingOp:
    module = _load_migration()
    recorder = _RecordingOp()
    monkeypatch.setattr(module, "op", recorder)
    getattr(module, direction)()
    return recorder


def test_revision_identifiers() -> None:
    module = _load_migration()

    assert module.revision == MIGRATION_REVISION
    assert module.down_revision == PREVIOUS_REVISION


def test_upgrade_only_touches_taxa(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _record("upgrade", monkeypatch)

    for name, args, kwargs in recorder.calls:
        if name == "add_column":
            assert args[0] == TABLE, args
        elif name == "create_index":
            assert args[1] == TABLE, args
        else:  # pragma: no cover - defensive
            raise AssertionError(f"unexpected op: {name} {args} {kwargs}")


def test_upgrade_adds_every_nullable_column_with_the_right_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _record("upgrade", monkeypatch)

    added = {
        args[1].name: args[1]
        for name, args, _ in recorder.calls
        if name == "add_column"
    }
    assert set(added) == set(EXPECTED_COLUMNS)

    for column_name, (expected_type, expected_length) in EXPECTED_COLUMNS.items():
        column = added[column_name]
        # Additive migration on a populated table: NULLABLE is mandatory.
        assert column.nullable is True, column_name
        assert isinstance(column.type, expected_type), (column_name, column.type)
        if expected_length is not None:
            assert column.type.length == expected_length, column_name


def test_upgrade_creates_non_unique_lookup_indexes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _record("upgrade", monkeypatch)

    indexes = {
        str(args[0]): (args[2], kwargs)
        for name, args, kwargs in recorder.calls
        if name == "create_index"
    }
    assert set(indexes) == set(EXPECTED_INDEXES)

    for index_name, column_name in EXPECTED_INDEXES.items():
        columns, kwargs = indexes[index_name]
        assert columns == [column_name], index_name
        # NON-unique on purpose: taxonomic lumps map several taxa onto one COL
        # XR usage key, so a unique index would reject legitimate data.
        assert kwargs.get("unique") is False, index_name


def test_downgrade_drops_everything_the_upgrade_added(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _record("downgrade", monkeypatch)

    dropped_columns = {
        args[1] for name, args, _ in recorder.calls if name == "drop_column"
    }
    dropped_indexes = {
        str(args[0]) for name, args, _ in recorder.calls if name == "drop_index"
    }
    assert dropped_columns == set(EXPECTED_COLUMNS)
    assert dropped_indexes == set(EXPECTED_INDEXES)

    # Indexes must go before their columns.
    first_column_drop = next(
        i for i, (name, _, _) in enumerate(recorder.calls) if name == "drop_column"
    )
    last_index_drop = max(
        i for i, (name, _, _) in enumerate(recorder.calls) if name == "drop_index"
    )
    assert last_index_drop < first_column_drop


def test_orm_model_matches_the_migrated_schema() -> None:
    from echoroo.models.taxon import Taxon

    table = Taxon.__table__
    for column_name, (expected_type, expected_length) in EXPECTED_COLUMNS.items():
        column = table.c[column_name]
        assert column.nullable is True, column_name
        assert isinstance(column.type, expected_type), (column_name, column.type)
        if expected_length is not None:
            assert column.type.length == expected_length, column_name

    orm_indexes = {index.name: index for index in table.indexes}
    for index_name, column_name in EXPECTED_INDEXES.items():
        index = orm_indexes[index_name]
        assert index.unique is False, index_name
        assert [c.name for c in index.columns] == [column_name], index_name


def test_accepted_scientific_name_is_reused_not_duplicated() -> None:
    """The accepted canonical name reuses the 0027 column — no new twin."""
    from echoroo.models.taxon import Taxon

    assert "accepted_scientific_name" in Taxon.__table__.c
    assert "col_xr_accepted_scientific_name" not in Taxon.__table__.c

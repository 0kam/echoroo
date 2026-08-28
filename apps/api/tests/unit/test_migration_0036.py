"""Focused tests for Alembic revision 0036 (taxonomy WS-A v2 slice 5).

Migration 0036 creates ``taxon_identity_history`` (the append-only journal of
identity-field rewrites) and ``taxon_concept_relations`` (directed "where did
this concept go" edges), then backfills the ``synonym_of`` edges implied by the
identities revision 0035 already resolved.

The test database schema is built from ``Base.metadata.create_all`` rather than
by replaying Alembic, so these tests do not execute the migration end-to-end.
They lock the revision wiring, assert the up/down operations against a
recording stub, and verify the ORM models carry the same columns, indexes and
CHECK constraints.

Mirrors the structure of ``tests/unit/test_migration_0035.py``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import sqlalchemy as sa

_MIGRATION_RELATIVE_PATH = (
    Path("alembic") / "versions" / "0036_taxon_identity_history.py"
)
MIGRATION_REVISION = "0036"
PREVIOUS_REVISION = "0035"

HISTORY_TABLE = "taxon_identity_history"
RELATIONS_TABLE = "taxon_concept_relations"

#: ``column name -> (SQLAlchemy type, expected length or None, nullable)``.
EXPECTED_HISTORY_COLUMNS: dict[str, tuple[type[Any], int | None, bool]] = {
    "id": (sa.Uuid, None, False),
    "created_at": (sa.DateTime, None, False),
    "updated_at": (sa.DateTime, None, False),
    "taxon_id": (sa.Uuid, None, False),
    "field": (sa.String, 64, False),
    "old_value": (sa.Text, None, True),
    "new_value": (sa.Text, None, True),
    "source": (sa.String, 32, False),
    "resolver": (sa.String, 128, True),
    "release": (sa.String, 32, True),
    "actor_kind": (sa.String, 16, False),
    "actor_user_id": (sa.Uuid, None, True),
    "actor_task_id": (sa.String, 64, True),
    "changed_at": (sa.DateTime, None, False),
    "detail": (sa.types.JSON, None, True),
}

EXPECTED_RELATIONS_COLUMNS: dict[str, tuple[type[Any], int | None, bool]] = {
    "id": (sa.Uuid, None, False),
    "created_at": (sa.DateTime, None, False),
    "updated_at": (sa.DateTime, None, False),
    "from_taxon_id": (sa.Uuid, None, False),
    # Nullable on purpose: on the real catalogue every COL accepted usage a
    # synonym points at is NOT a local taxon.
    "to_taxon_id": (sa.Uuid, None, True),
    "to_col_xr_id": (sa.String, 16, True),
    "to_scientific_name": (sa.String, 300, True),
    "relation": (sa.String, 32, False),
    "release": (sa.String, 32, True),
    "authority": (sa.String, 64, True),
    "evidence": (sa.Text, None, True),
    "notes": (sa.Text, None, True),
    "source": (sa.String, 32, False),
    "created_by_id": (sa.Uuid, None, True),
}

#: index name -> (table, unique)
EXPECTED_INDEXES: dict[str, tuple[str, bool]] = {
    f"ix_{HISTORY_TABLE}_created_at": (HISTORY_TABLE, False),
    f"ix_{RELATIONS_TABLE}_created_at": (RELATIONS_TABLE, False),
    "ix_taxon_identity_history_taxon_changed_at": (HISTORY_TABLE, False),
    "ix_taxon_identity_history_field_changed_at": (HISTORY_TABLE, False),
    "ix_taxon_identity_history_actor_task_id": (HISTORY_TABLE, False),
    "ux_taxon_concept_relations_edge": (RELATIONS_TABLE, True),
    "ux_taxon_concept_relations_local_edge": (RELATIONS_TABLE, True),
    "ix_taxon_concept_relations_from_taxon_id": (RELATIONS_TABLE, False),
    "ix_taxon_concept_relations_to_taxon_id": (RELATIONS_TABLE, False),
    "ix_taxon_concept_relations_to_col_xr_id": (RELATIONS_TABLE, False),
}

EXPECTED_CHECKS: dict[str, str] = {
    "ck_taxon_identity_history_actual_change": HISTORY_TABLE,
    "ck_taxon_identity_history_actor_present": HISTORY_TABLE,
    "ck_taxon_concept_relations_target_present": RELATIONS_TABLE,
    "ck_taxon_concept_relations_no_self_edge": RELATIONS_TABLE,
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


def test_upgrade_only_touches_the_two_new_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _record("upgrade", monkeypatch)

    for name, args, kwargs in recorder.calls:
        if name == "create_table":
            assert args[0] in {HISTORY_TABLE, RELATIONS_TABLE}, args
        elif name in {"create_index", "create_check_constraint"}:
            assert args[1] in {HISTORY_TABLE, RELATIONS_TABLE}, args
        elif name == "execute":
            # The one-time synonym-edge backfill.
            assert RELATIONS_TABLE in args[0], args
        else:  # pragma: no cover - defensive
            raise AssertionError(f"unexpected op: {name} {args} {kwargs}")


@pytest.mark.parametrize(
    ("table", "expected"),
    [
        (HISTORY_TABLE, EXPECTED_HISTORY_COLUMNS),
        (RELATIONS_TABLE, EXPECTED_RELATIONS_COLUMNS),
    ],
)
def test_upgrade_creates_every_column_with_the_right_type(
    table: str,
    expected: dict[str, tuple[type[Any], int | None, bool]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _record("upgrade", monkeypatch)

    created = {
        args[0]: args[1:] for name, args, _ in recorder.calls if name == "create_table"
    }
    columns = {column.name: column for column in created[table]}
    assert set(columns) == set(expected)

    for column_name, (expected_type, expected_length, nullable) in expected.items():
        column = columns[column_name]
        assert isinstance(column.type, expected_type), (column_name, column.type)
        if expected_length is not None:
            assert column.type.length == expected_length, column_name
        if column_name != "id":
            assert column.nullable is nullable, column_name


def test_upgrade_creates_every_index_and_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _record("upgrade", monkeypatch)

    indexes = {
        str(args[0]): (args[1], kwargs)
        for name, args, kwargs in recorder.calls
        if name == "create_index"
    }
    assert set(indexes) == set(EXPECTED_INDEXES)
    for index_name, (table, unique) in EXPECTED_INDEXES.items():
        recorded_table, kwargs = indexes[index_name]
        assert recorded_table == table, index_name
        assert kwargs.get("unique") is unique, index_name

    # The two partial indexes must stay partial: without the predicate the
    # local-edge uniqueness rule would reject every COL-keyed edge.
    assert (
        indexes["ux_taxon_concept_relations_local_edge"][1]["postgresql_where"]
        is not None
    )
    assert (
        indexes["ix_taxon_identity_history_actor_task_id"][1]["postgresql_where"]
        is not None
    )

    checks = {
        str(args[0]): args[1]
        for name, args, _ in recorder.calls
        if name == "create_check_constraint"
    }
    assert checks == EXPECTED_CHECKS


def test_upgrade_backfills_synonym_edges_idempotently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _record("upgrade", monkeypatch)

    executed = [args[0] for name, args, _ in recorder.calls if name == "execute"]
    assert len(executed) == 1
    sql = executed[0]

    assert f"INSERT INTO {RELATIONS_TABLE}" in sql
    assert "'synonym_of'" in sql
    assert "'col_xr_auto'" in sql
    # Only synonyms with a target are edges.
    assert "t.col_xr_status = 'SYNONYM'" in sql
    assert "t.col_xr_accepted_id IS NOT NULL" in sql
    # Re-runnable: the runtime seeder writes the very same rows.
    assert "ON CONFLICT (from_taxon_id, relation, to_col_xr_id) DO NOTHING" in sql


def test_backfill_runs_after_the_unique_index_it_relies_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ON CONFLICT`` needs ``ux_taxon_concept_relations_edge`` to exist."""
    recorder = _record("upgrade", monkeypatch)

    edge_index_position = next(
        i
        for i, (name, args, _) in enumerate(recorder.calls)
        if name == "create_index" and str(args[0]) == "ux_taxon_concept_relations_edge"
    )
    backfill_position = next(
        i for i, (name, _, _) in enumerate(recorder.calls) if name == "execute"
    )
    assert edge_index_position < backfill_position


def test_downgrade_drops_both_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _record("downgrade", monkeypatch)

    dropped = [args[0] for name, args, _ in recorder.calls if name == "drop_table"]
    # Relations first: it is the table the backfill wrote into, and dropping a
    # table takes its indexes and CHECKs with it.
    assert dropped == [RELATIONS_TABLE, HISTORY_TABLE]


@pytest.mark.parametrize(
    ("model_path", "expected"),
    [
        ("echoroo.models.taxon_identity_history:TaxonIdentityHistory", "history"),
        ("echoroo.models.taxon_concept_relation:TaxonConceptRelation", "relations"),
    ],
)
def test_orm_models_match_the_migrated_schema(
    model_path: str, expected: str
) -> None:
    import importlib

    module_name, class_name = model_path.split(":")
    model = getattr(importlib.import_module(module_name), class_name)
    table = model.__table__

    columns = (
        EXPECTED_HISTORY_COLUMNS if expected == "history" else EXPECTED_RELATIONS_COLUMNS
    )
    assert set(table.c.keys()) == set(columns)
    for column_name, (expected_type, expected_length, nullable) in columns.items():
        column = table.c[column_name]
        assert isinstance(column.type, expected_type), (column_name, column.type)
        if expected_length is not None:
            assert column.type.length == expected_length, column_name
        if column_name != "id":
            assert column.nullable is nullable, column_name

    orm_indexes = {index.name for index in table.indexes}
    expected_indexes = {
        name for name, (t, _) in EXPECTED_INDEXES.items() if t == table.name
    }
    assert expected_indexes <= orm_indexes

    orm_checks = {
        constraint.name
        for constraint in table.constraints
        if isinstance(constraint, sa.CheckConstraint)
    }
    expected_checks = {
        name for name, t in EXPECTED_CHECKS.items() if t == table.name
    }
    assert expected_checks <= orm_checks


def test_identity_fk_is_restrict_not_cascade() -> None:
    """Provenance must not disappear with a silent cascade delete."""
    from echoroo.models.taxon_concept_relation import TaxonConceptRelation
    from echoroo.models.taxon_identity_history import TaxonIdentityHistory

    taxa_fks = [
        fk
        for table in (
            TaxonIdentityHistory.__table__,
            TaxonConceptRelation.__table__,
        )
        for fk in table.foreign_keys
        if fk.column.table.name == "taxa"
    ]
    assert taxa_fks
    for fk in taxa_fks:
        assert fk.ondelete == "RESTRICT", fk.parent.name

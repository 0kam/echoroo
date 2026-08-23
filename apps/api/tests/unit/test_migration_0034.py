"""Focused tests for Alembic revision 0034 (taxonomy WS-A v2 slice 4).

Migration 0034 re-keys ``taxon_sensitivities.taxon_id`` and
``project_taxon_sensitivity_overrides.taxon_id`` from a ``VARCHAR(64)``
"GBIF species key" onto a ``UUID`` FK to ``taxa.id``. The test database schema
is built from ``Base.metadata.create_all`` rather than by replaying Alembic, so
these tests do not execute the migration end-to-end. They lock the revision
wiring, assert the up/down operations against a recording stub, and verify the
ORM models carry the new column type + FK semantics.

Mirrors the structure of ``tests/unit/test_migration_0033.py``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import sqlalchemy as sa

_MIGRATION_RELATIVE_PATH = Path("alembic") / "versions" / "0034_masking_taxon_uuid_fk.py"
MIGRATION_REVISION = "0034"
PREVIOUS_REVISION = "0033"

SENSITIVITIES_TABLE = "taxon_sensitivities"
OVERRIDES_TABLE = "project_taxon_sensitivity_overrides"

#: The four index / unique-constraint names the migration must drop *and*
#: recreate under the exact same names (nothing downstream may have to learn
#: a new name).
RECREATED_CONSTRAINTS: frozenset[str] = frozenset(
    {
        "ix_taxon_sensitivities_taxon",
        "ux_taxon_sensitivities_taxon_source",
        "ux_taxon_overrides_applied_unique",
        "ix_taxon_overrides_taxon_approval",
    }
)

#: CHECK constraints that must NOT be referenced — none of them mention
#: ``taxon_id``, so touching them would be pure churn (and risk).
UNTOUCHED_CHECKS: frozenset[str] = frozenset(
    {
        "ck_taxon_sensitivities_h3_discrete",
        "ck_taxon_overrides_h3_discrete",
        "ck_taxon_overrides_direction_vs_approval",
    }
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


def _flatten(recorder: _RecordingOp) -> str:
    """Render every recorded call to a searchable string."""
    return " ".join(
        f"{name} {args!r} {kwargs!r}" for name, args, kwargs in recorder.calls
    )


def test_revision_identifiers() -> None:
    module = _load_migration()

    assert module.revision == MIGRATION_REVISION
    assert module.down_revision == PREVIOUS_REVISION


def test_upgrade_only_touches_the_two_masking_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No other table may be modified by the re-key."""
    recorder = _record("upgrade", monkeypatch)

    allowed = {SENSITIVITIES_TABLE, OVERRIDES_TABLE}
    seen_tables: set[str] = set()
    for name, args, kwargs in recorder.calls:
        if name == "drop_index":
            seen_tables.add(kwargs["table_name"])
        elif name in {"drop_column", "add_column", "drop_constraint"}:
            seen_tables.add(args[0] if name != "drop_constraint" else args[1])
        elif name in {"create_index", "create_unique_constraint"}:
            seen_tables.add(args[1])
        elif name == "create_foreign_key":
            # create_foreign_key(name, source_table, referent_table, ...)
            seen_tables.add(args[1])
            assert args[2] == "taxa", args
        elif name == "execute":
            continue  # TRUNCATE statements, asserted separately
        else:  # pragma: no cover - defensive
            raise AssertionError(f"unexpected op: {name}")

    assert seen_tables == allowed


def test_upgrade_truncates_both_tables(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pre-launch: the un-mappable reference rows are discarded, not migrated."""
    recorder = _record("upgrade", monkeypatch)

    truncates = [
        str(args[0])
        for name, args, _ in recorder.calls
        if name == "execute"
    ]
    assert any(
        "TRUNCATE" in stmt and SENSITIVITIES_TABLE in stmt for stmt in truncates
    ), truncates
    assert any(
        "TRUNCATE" in stmt and OVERRIDES_TABLE in stmt for stmt in truncates
    ), truncates


def test_upgrade_adds_uuid_columns_and_taxa_fks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both ``taxon_id`` columns become NOT NULL UUID with a ``taxa.id`` FK."""
    recorder = _record("upgrade", monkeypatch)

    added = {
        args[0]: args[1] for name, args, _ in recorder.calls if name == "add_column"
    }
    assert set(added) == {SENSITIVITIES_TABLE, OVERRIDES_TABLE}
    for table, column in added.items():
        assert column.name == "taxon_id", table
        assert column.nullable is False, table
        assert isinstance(column.type, sa.types.Uuid), (table, column.type)

    fks = {
        args[1]: kwargs
        for name, args, kwargs in recorder.calls
        if name == "create_foreign_key"
    }
    # BOTH tables must be RESTRICT. ``taxon_sensitivities`` is a masking guard
    # table: under CASCADE a ``taxa`` delete (or a delete+reinsert re-seed)
    # would silently empty it and unmask every protected species. Override
    # rows are additionally referenced by the FR-111 approval / audit trail,
    # so a taxon delete must not erase an audited decision either.
    assert fks[SENSITIVITIES_TABLE]["ondelete"] == "RESTRICT"
    assert fks[OVERRIDES_TABLE]["ondelete"] == "RESTRICT"


def test_upgrade_recreates_every_dropped_index_by_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _record("upgrade", monkeypatch)

    dropped: set[str] = set()
    created: set[str] = set()
    for name, args, _ in recorder.calls:
        if name in {"drop_index", "drop_constraint"}:
            dropped.add(str(args[0]))
        elif name in {"create_index", "create_unique_constraint"}:
            created.add(str(args[0]))

    assert dropped >= RECREATED_CONSTRAINTS
    assert created >= RECREATED_CONSTRAINTS


def test_upgrade_leaves_check_constraints_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _record("upgrade", monkeypatch)
    rendered = _flatten(recorder)

    for check_name in UNTOUCHED_CHECKS:
        assert check_name not in rendered, check_name


def test_downgrade_restores_string_columns(monkeypatch: pytest.MonkeyPatch) -> None:
    recorder = _record("downgrade", monkeypatch)

    added = {
        args[0]: args[1] for name, args, _ in recorder.calls if name == "add_column"
    }
    assert set(added) == {SENSITIVITIES_TABLE, OVERRIDES_TABLE}
    for table, column in added.items():
        assert column.name == "taxon_id", table
        assert isinstance(column.type, sa.String), (table, column.type)
        assert column.type.length == 64, table

    dropped_fks = {
        args[0]
        for name, args, kwargs in recorder.calls
        if name == "drop_constraint" and kwargs.get("type_") == "foreignkey"
    }
    assert dropped_fks == {
        "fk_taxon_sensitivities_taxon_id_taxa",
        "fk_taxon_overrides_taxon_id_taxa",
    }

    created = {
        str(args[0])
        for name, args, _ in recorder.calls
        if name in {"create_index", "create_unique_constraint"}
    }
    assert created >= RECREATED_CONSTRAINTS


def test_orm_models_expose_uuid_taxon_id_with_taxa_fk() -> None:
    """The ORM mapping must agree with the migrated schema."""
    from echoroo.models.project_taxon_override import ProjectTaxonSensitivityOverride
    from echoroo.models.taxon_sensitivity import TaxonSensitivity

    for model, expected_ondelete in (
        (TaxonSensitivity, "RESTRICT"),
        (ProjectTaxonSensitivityOverride, "RESTRICT"),
    ):
        column = model.__table__.c.taxon_id
        assert isinstance(column.type, sa.types.Uuid), model.__tablename__
        assert column.nullable is False, model.__tablename__
        fks = list(column.foreign_keys)
        assert len(fks) == 1, model.__tablename__
        assert fks[0].target_fullname == "taxa.id", model.__tablename__
        assert fks[0].ondelete == expected_ondelete, model.__tablename__

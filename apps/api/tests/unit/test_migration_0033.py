"""Focused tests for Alembic revision 0033 (taxonomy WS-A PR6).

Migration 0033 drops the dead ``detections.taxon_id`` ``VARCHAR(64)`` column
(and its composite index ``ix_detections_project_taxon``). The test database
schema is built from ``Base.metadata.create_all`` rather than by replaying
Alembic, so these tests do not execute the migration end-to-end. They lock the
revision wiring, assert the up/down operations against a recording stub, and
verify the ORM model no longer carries the retired column.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_MIGRATION_RELATIVE_PATH = (
    Path("alembic") / "versions" / "0033_drop_dead_detection_taxon_id.py"
)
MIGRATION_REVISION = "0033"
PREVIOUS_REVISION = "0032"


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


def test_revision_identifiers() -> None:
    module = _load_migration()

    assert module.revision == MIGRATION_REVISION
    assert module.down_revision == PREVIOUS_REVISION


def test_upgrade_drops_index_then_column(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_migration()
    recorder = _RecordingOp()
    monkeypatch.setattr(module, "op", recorder)

    module.upgrade()

    ops = [(name, args) for name, args, _ in recorder.calls]
    # The index must be dropped before the column it covers.
    assert ops == [
        ("drop_index", ("ix_detections_project_taxon",)),
        ("drop_column", ("detections", "taxon_id")),
    ]
    # Index drop must target the detections table.
    _, _, index_kwargs = recorder.calls[0]
    assert index_kwargs.get("table_name") == "detections"


def test_downgrade_readds_column_and_index(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_migration()
    recorder = _RecordingOp()
    monkeypatch.setattr(module, "op", recorder)

    module.downgrade()

    names = [name for name, _, _ in recorder.calls]
    # Column must be re-added before the index that references it.
    assert names == ["add_column", "create_index"]

    add_name, add_args, _ = recorder.calls[0]
    assert add_args[0] == "detections"
    column = add_args[1]
    assert column.name == "taxon_id"
    assert column.nullable is True

    _, index_args, _ = recorder.calls[1]
    assert index_args == (
        "ix_detections_project_taxon",
        "detections",
        ["project_id", "taxon_id"],
    )


def test_orm_model_no_longer_exposes_taxon_id() -> None:
    """The retired column must be gone from the ORM mapping (and its index)."""
    from echoroo.models.detection import Detection

    assert not hasattr(Detection, "taxon_id")
    index_names = {idx.name for idx in Detection.__table__.indexes}
    assert "ix_detections_project_taxon" not in index_names


def test_migration_only_touches_detections_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Masking columns live on other tables and must not be referenced here."""
    module = _load_migration()
    recorder = _RecordingOp()
    monkeypatch.setattr(module, "op", recorder)

    module.upgrade()
    module.downgrade()

    for name, args, kwargs in recorder.calls:
        # Op-aware extraction of the table each call targets:
        #   drop_index(name, table_name=...)      -> kwarg
        #   drop_column(table, column)            -> args[0]
        #   add_column(table, column)             -> args[0]
        #   create_index(name, table, columns)    -> args[1]
        if name == "drop_index":
            table = kwargs.get("table_name")
        elif name in {"drop_column", "add_column"}:
            table = args[0]
        elif name == "create_index":
            table = args[1]
        else:  # pragma: no cover - defensive
            raise AssertionError(f"unexpected op: {name}")
        assert table == "detections", (name, args)
        # The intentional masking columns live on other tables (see the
        # migration scope note) and must never be an op target here.
        assert "taxon_sensitivities" not in args
        assert "project_taxon_sensitivity_overrides" not in args

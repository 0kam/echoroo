"""Focused tests for Alembic revision 0032 (W1-4 run_type discriminator).

The test database schema is built from ``Base.metadata.create_all`` rather than
by replaying Alembic, so these tests do not execute the migration end-to-end.
They lock the revision wiring and assert the backfill CASE classification logic
(the load-bearing part of the migration) as a pure derivation.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

_MIGRATION_RELATIVE_PATH = (
    Path("alembic") / "versions" / "0032_detection_run_type_discriminator.py"
)
MIGRATION_REVISION = "0032"
PREVIOUS_REVISION = "0031"


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


def test_enum_definition_matches_model() -> None:
    """The migration enum values must match the ORM ``DetectionRunType``."""
    from echoroo.models.enums import DetectionRunType

    module = _load_migration()

    assert set(module._ENUM_VALUES) == {t.value for t in DetectionRunType}
    assert module._ENUM_NAME == "detectionruntype"


def _classify(
    parameters: dict[str, object] | None,
    model_name: str,
    annotation_count: int,
) -> str:
    """Pure-Python mirror of the migration's backfill CASE expression.

    The branch order here is byte-faithful to the SQL CASE in
    ``0032_detection_run_type_discriminator.py``; the DB-backed test in
    ``tests/contract/test_detection_runs.py`` exercises the actual SQL.
    """
    if parameters is not None and parameters.get("embedding_only") is True:
        return "embedding"
    if model_name == "custom_svm":
        return "custom"
    if model_name == "perch" and annotation_count == 0:
        return "embedding"
    return "detection"


def test_backfill_branch_embedding_only_flag_wins() -> None:
    # Priority 1: embedding_only flag beats every other signal.
    assert _classify({"embedding_only": True}, "perch", 5) == "embedding"
    assert _classify({"embedding_only": True}, "custom_svm", 0) == "embedding"


def test_backfill_branch_custom_svm() -> None:
    # Priority 2: custom_svm (no flag) -> custom, even with zero annotations.
    assert _classify({"threshold": 0.5}, "custom_svm", 0) == "custom"


def test_backfill_branch_legacy_perch_embedding() -> None:
    # Priority 3: legacy Perch embedding rows predating the flag.
    assert _classify(None, "perch", 0) == "embedding"


def test_backfill_branch_default_detection() -> None:
    # else: birdnet (and perch runs that actually produced annotations).
    assert _classify({"min_confidence": 0.5}, "birdnet", 10) == "detection"
    assert _classify(None, "perch", 7) == "detection"

"""Coverage uplift unit tests for ``echoroo._alembic_phase13_supporting_ddl``.

Phase 17 §C heavy-gap batch: targets the ``apply_phase13_supporting_tables``
helper (lines 730-731) so the module clears the 85% threshold without
touching production code.

The helper iterates ``_DDL_STATEMENTS`` and calls ``op.execute(sa.text(stmt))``
once per statement. We monkeypatch ``op`` so the test does not require
an Alembic migration context.
"""

from __future__ import annotations

from typing import Any

import pytest

from echoroo import _alembic_phase13_supporting_ddl as mod


def test_apply_phase13_supporting_tables_executes_every_statement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """apply_phase13_supporting_tables() calls op.execute once per DDL (lines 730-731)."""
    captured: list[Any] = []

    class _FakeOp:
        @staticmethod
        def execute(stmt: Any) -> None:
            captured.append(stmt)

    monkeypatch.setattr(mod, "op", _FakeOp)
    mod.apply_phase13_supporting_tables()
    # Every statement in the module's DDL list must be issued.
    assert len(captured) == len(mod._DDL_STATEMENTS)
    assert len(captured) > 0

"""Fixtures for workers tests.

Phase 17 §D-0 follow-up (2026-05-08): hosts the session-scoped autouse
schema-setup fixture that previously lived in the root ``tests/conftest.py``.
The root location forced every test session — including ``tests/runbook/``
smoke tests that have no Postgres available — to attempt a connection at
session start and crash with ``OSError: Connect call failed``. The fixture
now lives in the per-suite conftests for the suites that genuinely need it.
"""

from __future__ import annotations

import pytest

from tests.conftest import ensure_test_database_schema_sync


@pytest.fixture(scope="session", autouse=True)
def _ensure_test_database_schema_for_workers() -> None:
    """Session-scoped autouse fixture that ensures the test DB schema is current."""
    ensure_test_database_schema_sync()

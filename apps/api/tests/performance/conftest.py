"""Fixtures for performance tests.

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
def _ensure_test_database_schema_for_performance() -> None:
    """Session-scoped autouse fixture that ensures the test DB schema is current.

    Performance tests (T993 / T993a audit-log p95, ``test_api_key_verify_p95``,
    etc.) connect directly to ``TEST_DATABASE_URL`` and need raw-SQL tables
    (``token_families``, ``project_audit_log``, ``platform_audit_log``) that
    ``Base.metadata.create_all`` does not know about.
    """
    ensure_test_database_schema_sync()

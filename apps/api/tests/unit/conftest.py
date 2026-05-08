"""Fixtures for unit tests.

Phase 17 §D-0 follow-up (2026-05-08): hosts the session-scoped autouse
schema-setup fixture that previously lived in the root ``tests/conftest.py``.
The root location forced every test session — including ``tests/runbook/``
smoke tests that have no Postgres available — to attempt a connection at
session start and crash with ``OSError: Connect call failed``. The fixture
now lives in the per-suite conftests for the suites that genuinely need it
(``security/``, ``contract/``, ``integration/``, ``unit/``, ``performance/``,
``workers/``).
"""

from __future__ import annotations

import pytest

from tests.conftest import ensure_test_database_schema_sync


@pytest.fixture(scope="session", autouse=True)
def _ensure_test_database_schema_for_unit() -> None:
    """Session-scoped autouse fixture that ensures the test DB schema is current.

    Several unit-suite tests (e.g.
    ``tests/unit/services/test_superuser_service_phase15_nogo.py``) connect
    directly to ``TEST_DATABASE_URL`` and need raw-SQL tables (``token_families``,
    ``superusers``, ``project_audit_log``) that ``Base.metadata.create_all``
    does not know about.
    """
    ensure_test_database_schema_sync()

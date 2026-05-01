"""Phase 2.11 P0-c — meta-audit fail-closed (FR-096).

The audit-read endpoints in :mod:`echoroo.api.web_v1.audit` are required
to leave a meta-audit trail every time they return rows. The previous
helper swallowed every exception in the meta-write path so the endpoint
returned the page WITHOUT recording the read — fail-OPEN, which is the
exact attack FR-096 defends against.

This module pins the new contract:

1. :class:`MetaAuditWriteError` is raised when the meta-write fails.
2. The helper itself does not return rows when the write fails.
3. The wired endpoints catch the exception and convert it to **503**
   with error code ``META_AUDIT_WRITE_FAILED`` — the page rows are
   NEVER returned to the client in that case.

The tests are unit-level: they patch
``echoroo.api.web_v1.audit.AsyncSessionLocal`` to raise so the helper's
fresh-session path errors out, then assert the wrapper exception type
and (in the endpoint test) the resulting status code + body.
"""

from __future__ import annotations

import contextlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from echoroo.api.web_v1 import audit as audit_api
from echoroo.api.web_v1.audit import MetaAuditWriteError

# ---------------------------------------------------------------------------
# Helpers — fake AsyncSessionLocal that raises on commit
# ---------------------------------------------------------------------------


class _RaisingSession:
    """Minimal AsyncSession look-alike that explodes when the TX is committed.

    The helper opens its own ``async with AsyncSessionLocal() as
    audit_session, audit_session.begin():`` block. We provide just enough
    surface to satisfy that pattern, raise on the inner ``audit_session``
    operations, and let the propagated exception flow through the
    helper's ``except Exception as exc:`` clause.
    """

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def __aenter__(self) -> _RaisingSession:
        return self

    async def __aexit__(self, *_args: Any) -> bool:
        return False

    def begin(self) -> _RaisingSession:
        return self

    async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
        raise self._exc

    async def commit(self) -> None:
        raise self._exc

    async def rollback(self) -> None:
        return None


def _raising_session_factory(exc: Exception) -> Any:
    """Return a callable suitable to replace ``AsyncSessionLocal``."""

    def factory() -> _RaisingSession:
        return _RaisingSession(exc)

    return factory


# ---------------------------------------------------------------------------
# 1) Helper-level: raises MetaAuditWriteError, does NOT swallow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_helper_raises_meta_audit_write_error_on_commit_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fresh-session helper must raise — not swallow — write failures."""
    boom = RuntimeError("simulated postgres outage")
    monkeypatch.setattr(
        audit_api, "AsyncSessionLocal", _raising_session_factory(boom)
    )

    with pytest.raises(MetaAuditWriteError) as excinfo:
        await audit_api._write_meta_audit_in_fresh_session(
            table="platform_audit_log",
            actor_user_id=uuid4(),
            action="platform.audit_log.read",
            request_id="req-1",
            ip="0.0.0.0",
            user_agent="ua",
            detail={},
        )

    err = excinfo.value
    assert err.action == "platform.audit_log.read"
    assert err.request_id == "req-1"
    assert err.__cause__ is boom


@pytest.mark.asyncio
async def test_helper_raises_for_project_table_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The project-table branch fails-closed identically."""
    boom = RuntimeError("kms timeout writing chain hash")
    monkeypatch.setattr(
        audit_api, "AsyncSessionLocal", _raising_session_factory(boom)
    )

    with pytest.raises(MetaAuditWriteError):
        await audit_api._write_meta_audit_in_fresh_session(
            table="project_audit_log",
            actor_user_id=uuid4(),
            project_id=uuid4(),
            action="project.audit_log.read",
            request_id="req-2",
            ip="0.0.0.0",
            user_agent="ua",
            detail={},
        )


# ---------------------------------------------------------------------------
# 2) Endpoint-level: 503 + audit rows are NOT returned
# ---------------------------------------------------------------------------


def _build_audit_app(meta_write: AsyncMock) -> TestClient:
    """Construct a FastAPI app that wires only the audit router with mocks.

    The fixture overrides:

    * ``AsyncSessionLocal`` — irrelevant here; the meta-write itself is
      mocked.
    * ``audit_api._write_meta_audit_in_fresh_session`` — replaced with
      ``meta_write``. Tests configure its side_effect to either succeed
      or raise :class:`MetaAuditWriteError`.
    * The page-fetcher helpers are stubbed to return a known row set.
    * The permission gate is bypassed to focus the test on the
      fail-closed contract.

    Because the audit endpoints depend on FastAPI ``Depends`` for the
    ORM session and the current user, we override those with fakes via
    the ``app.dependency_overrides`` map.
    """
    from echoroo.core.database import get_db
    from echoroo.middleware.auth import (
        CurrentUser,  # noqa: F401 - imported for override key
        get_current_user,
    )

    # --- Stub: page fetchers always return one fake row ---
    fake_rows: list[dict[str, Any]] = []  # empty; we don't care about content
    fake_total = 0

    async def _stub_project_page(*_args: Any, **_kwargs: Any):
        return fake_rows, fake_total

    async def _stub_platform_page(*_args: Any, **_kwargs: Any):
        return fake_rows, fake_total

    audit_api._project_audit_page = _stub_project_page  # type: ignore[assignment]
    audit_api._platform_audit_page = _stub_platform_page  # type: ignore[assignment]

    # --- Stub: bypass permission gate ---
    audit_api.is_allowed = lambda **_kwargs: (True, "stubbed")  # type: ignore[assignment]

    # --- Stub: meta-write helper ---
    audit_api._write_meta_audit_in_fresh_session = meta_write  # type: ignore[assignment]

    # --- Stub: project loader (only used by the project endpoint) ---
    async def _stub_load_project(_db: Any, project_id: Any) -> Any:
        from echoroo.api.web_v1.audit import _ProjectShape

        return _ProjectShape(
            id=project_id,
            visibility="restricted",
            restricted_config={},
            status="active",
            owner_id=uuid4(),
        )

    audit_api._load_project = _stub_load_project  # type: ignore[assignment]

    # --- App ---
    app = FastAPI()
    app.include_router(audit_api.router)

    # Override dependencies.
    fake_user = MagicMock()
    fake_user.id = uuid4()
    fake_user.is_superuser = True

    async def _fake_user_dep() -> Any:
        return fake_user

    async def _fake_db_dep() -> Any:
        # The audit endpoint's DB session is only used by the (now
        # stubbed) page fetchers and the project loader, so any sentinel
        # is fine.
        yield MagicMock()

    app.dependency_overrides[get_current_user] = _fake_user_dep
    app.dependency_overrides[get_db] = _fake_db_dep

    return TestClient(app, raise_server_exceptions=False)


def test_platform_endpoint_returns_503_when_meta_write_fails() -> None:
    """Endpoint: /admin/audit-log returns 503 + does NOT return rows."""
    boom = MetaAuditWriteError(
        action="platform.audit_log.read",
        request_id="req-x",
        reason="simulated",
    )
    meta_write = AsyncMock(side_effect=boom)

    # Save originals so we can restore them.
    saved = {
        "page": audit_api._platform_audit_page,
        "perm": audit_api.is_allowed,
        "meta": audit_api._write_meta_audit_in_fresh_session,
    }
    try:
        client = _build_audit_app(meta_write)
        resp = client.get("/admin/audit-log")
        assert resp.status_code == 503
        body = resp.json()
        # Body should advertise the fail-closed error code.
        detail = body.get("detail", body)
        assert detail.get("error_code") == "META_AUDIT_WRITE_FAILED"
        # And critically: the page rows must NOT be present in the body.
        assert "items" not in detail
        # The meta-write was attempted exactly once.
        assert meta_write.await_count == 1
    finally:
        audit_api._platform_audit_page = saved["page"]  # type: ignore[assignment]
        audit_api.is_allowed = saved["perm"]  # type: ignore[assignment]
        audit_api._write_meta_audit_in_fresh_session = saved["meta"]  # type: ignore[assignment]


def test_platform_endpoint_returns_200_when_meta_write_succeeds() -> None:
    """Sanity: when the meta-write succeeds the endpoint returns the page."""
    meta_write = AsyncMock(return_value=None)
    saved = {
        "page": audit_api._platform_audit_page,
        "perm": audit_api.is_allowed,
        "meta": audit_api._write_meta_audit_in_fresh_session,
    }
    try:
        client = _build_audit_app(meta_write)
        resp = client.get("/admin/audit-log")
        assert resp.status_code == 200
        body = resp.json()
        assert body.get("items") == []
        assert body.get("total") == 0
        assert meta_write.await_count == 1
    finally:
        audit_api._platform_audit_page = saved["page"]  # type: ignore[assignment]
        audit_api.is_allowed = saved["perm"]  # type: ignore[assignment]
        audit_api._write_meta_audit_in_fresh_session = saved["meta"]  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# 3) Exception class smoke
# ---------------------------------------------------------------------------


def test_meta_audit_write_error_carries_action_and_request_id() -> None:
    err = MetaAuditWriteError(
        action="project.audit_log.read", request_id="req-7", reason="boom"
    )
    assert err.action == "project.audit_log.read"
    assert err.request_id == "req-7"
    assert "boom" in str(err)


# Tag silence for unused imports retained intentionally for clarity
_ = contextlib  # noqa: F841

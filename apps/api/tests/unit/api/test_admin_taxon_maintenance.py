"""Unit tests for the taxon-catalog maintenance admin endpoints.

Covers ``POST /web-api/v1/admin/taxon/seed-birdnet`` and
``POST /web-api/v1/admin/taxon/sync-vernacular`` (admin maintenance surface).

These mirror the IUCN force-resync endpoint's testing strategy: the handlers
are invoked directly with mocked dependencies so neither the database, the
Celery broker, nor the real audit chain is required. We assert that:

* a session superuser is accepted, the worker task is dispatched, the task id
  flows into the response, and the platform audit row is emitted;
* a non-superuser caller (``is_allowed`` returns ``False``) receives 403;
* invalid request bodies fail Pydantic validation (sync-vernacular only);
* an audit-write failure is swallowed (FR-089 soft alert) and never blocks the
  dispatch.

The platform-scope superuser-only Action gating (Step -1 api_key veto / Step 0a
superuser branch) is exercised separately under
``tests/security/authorization/test_taxon_maintenance_platform_scope.py``.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from echoroo.api.web_v1 import admin as mod
from echoroo.schemas.admin import TaxonSyncVernacularRequest


class _AsyncSessionContext:
    """Minimal async-context-manager stand-in for ``AsyncSessionLocal()``."""

    def __init__(self, session: object) -> None:
        self.session = session

    async def __aenter__(self) -> object:
        return self.session

    async def __aexit__(self, *exc_info: object) -> None:
        return None


def _request(headers: dict[str, str] | None = None) -> MagicMock:
    request = MagicMock()
    request.headers = headers or {}
    request.client = SimpleNamespace(host="203.0.113.9")
    return request


def _superuser() -> SimpleNamespace:
    return SimpleNamespace(id=uuid4())


def _patch_superuser_gate(
    monkeypatch: pytest.MonkeyPatch, *, allowed: bool
) -> None:
    """Bypass the DB superuser probe and stub the platform-scope gate."""
    monkeypatch.setattr(
        mod, "_require_authenticated_superuser", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(mod, "is_allowed", lambda **_: (allowed, MagicMock()))


def _patch_audit(
    monkeypatch: pytest.MonkeyPatch, *, fail: bool = False
) -> MagicMock:
    """Patch ``AsyncSessionLocal`` + ``AuditLogService``; return the service."""
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    service = MagicMock()
    service.write_platform_event = AsyncMock(
        side_effect=RuntimeError("down") if fail else None
    )
    monkeypatch.setattr(
        mod, "AsyncSessionLocal", lambda: _AsyncSessionContext(session)
    )
    monkeypatch.setattr(mod, "AuditLogService", MagicMock(return_value=service))
    return service


# ---------------------------------------------------------------------------
# seed-birdnet
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_seed_birdnet_superuser_dispatches_and_audits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_superuser_gate(monkeypatch, allowed=True)
    audit_service = _patch_audit(monkeypatch)

    fake_task = MagicMock()
    fake_task.delay = MagicMock(return_value=SimpleNamespace(id="task-seed-1"))
    monkeypatch.setattr(
        "echoroo.workers.taxon_tasks.seed_birdnet_taxa", fake_task, raising=False
    )

    db = MagicMock()
    db.commit = AsyncMock()

    out = await mod.seed_birdnet_taxa(
        request=_request(), current_user=_superuser(), db=db
    )

    assert out.task_id == "task-seed-1"
    fake_task.delay.assert_called_once_with()
    audit_service.write_platform_event.assert_awaited_once()
    assert (
        audit_service.write_platform_event.await_args.kwargs["action"]
        == "platform.taxon.seed_birdnet"
    )


@pytest.mark.asyncio
async def test_seed_birdnet_non_superuser_forbidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_superuser_gate(monkeypatch, allowed=False)
    db = MagicMock()
    db.commit = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await mod.seed_birdnet_taxa(
            request=_request(), current_user=_superuser(), db=db
        )

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_seed_birdnet_audit_failure_is_soft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_superuser_gate(monkeypatch, allowed=True)
    _patch_audit(monkeypatch, fail=True)

    fake_task = MagicMock()
    fake_task.delay = MagicMock(return_value=SimpleNamespace(id="task-seed-2"))
    monkeypatch.setattr(
        "echoroo.workers.taxon_tasks.seed_birdnet_taxa", fake_task, raising=False
    )

    db = MagicMock()
    db.commit = AsyncMock()

    # Must not raise even though the audit write blows up.
    out = await mod.seed_birdnet_taxa(
        request=_request(), current_user=_superuser(), db=db
    )
    assert out.task_id == "task-seed-2"


# ---------------------------------------------------------------------------
# sync-vernacular
# ---------------------------------------------------------------------------


def _patch_vernacular_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[MagicMock, MagicMock, MagicMock]:
    """Patch ``celery.chain`` + the two worker signatures.

    Returns ``(chain, resolve, fetch)`` so callers can assert link ordering.
    """
    resolve = MagicMock()
    resolve.si = MagicMock(return_value="resolve-sig")
    fetch = MagicMock()
    fetch.si = MagicMock(return_value="fetch-sig")
    monkeypatch.setattr(
        "echoroo.workers.taxon_tasks.resolve_gbif_batch", resolve, raising=False
    )
    monkeypatch.setattr(
        "echoroo.workers.taxon_tasks.fetch_vernacular_names_batch",
        fetch,
        raising=False,
    )

    workflow = MagicMock()
    workflow.apply_async = MagicMock(
        return_value=SimpleNamespace(id="chain-task-1")
    )
    chain = MagicMock(return_value=workflow)
    monkeypatch.setattr("celery.chain", chain, raising=False)
    return chain, resolve, fetch


@pytest.mark.asyncio
async def test_sync_vernacular_superuser_dispatches_chain_and_audits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_superuser_gate(monkeypatch, allowed=True)
    audit_service = _patch_audit(monkeypatch)
    chain, resolve, fetch = _patch_vernacular_chain(monkeypatch)

    db = MagicMock()
    db.commit = AsyncMock()

    payload = TaxonSyncVernacularRequest(
        batch_size=42, locales=["en", "ja"], skip_existing=False
    )
    out = await mod.sync_taxon_vernacular(
        request=_request(), payload=payload, current_user=_superuser(), db=db
    )

    assert out.task_id == "chain-task-1"
    # Stage 1 then Stage 2, both as immutable signatures.
    resolve.si.assert_called_once_with(batch_size=42)
    fetch.si.assert_called_once_with(
        batch_size=42, locales=["en", "ja"], skip_existing=False
    )
    chain.assert_called_once_with("resolve-sig", "fetch-sig")
    audit_service.write_platform_event.assert_awaited_once()
    assert (
        audit_service.write_platform_event.await_args.kwargs["action"]
        == "platform.taxon.sync_vernacular"
    )


@pytest.mark.asyncio
async def test_sync_vernacular_non_superuser_forbidden(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_superuser_gate(monkeypatch, allowed=False)
    db = MagicMock()
    db.commit = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await mod.sync_taxon_vernacular(
            request=_request(),
            payload=TaxonSyncVernacularRequest(),
            current_user=_superuser(),
            db=db,
        )

    assert exc_info.value.status_code == 403


def test_sync_vernacular_invalid_batch_size_rejected() -> None:
    with pytest.raises(ValidationError):
        TaxonSyncVernacularRequest(batch_size=0)
    with pytest.raises(ValidationError):
        TaxonSyncVernacularRequest(batch_size=501)


def test_sync_vernacular_defaults() -> None:
    req = TaxonSyncVernacularRequest()
    assert req.batch_size == 100
    assert req.locales is None
    assert req.skip_existing is True

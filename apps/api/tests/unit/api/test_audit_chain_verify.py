"""Tests for the shared audit-chain verifier and its web endpoint."""

from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from echoroo.api.web_v1 import audit as audit_api
from echoroo.core.database import get_db
from echoroo.core.keyring import KeyringAuthError
from echoroo.middleware.auth import get_current_user
from echoroo.services.audit_service import _build_canonical_row
from echoroo.workers import audit_log_export as export

_KEY = b"unit-test-audit-chain-key"
_ZERO_HASH = "0" * 64


def _mac(prev_hash: str, canonical_row: bytes) -> str:
    return hmac.new(
        _KEY,
        prev_hash.encode("ascii") + canonical_row,
        hashlib.sha256,
    ).hexdigest()


def _row(row_id: UUID, created_at: datetime, prev_hash: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": row_id,
        "created_at": created_at,
        "actor_user_id_hash": "a" * 64,
        "project_id": UUID("11111111-1111-1111-1111-111111111111"),
        "action": "project.test",
        "detail": {"kind": "test"},
        "request_id": "request-id",
        "ip_hash": "b" * 64,
        "user_agent_hash": "c" * 64,
        "before": None,
        "after": {"ok": True},
        "prev_hash": prev_hash,
    }
    row["row_hash"] = _mac(
        prev_hash,
        _build_canonical_row(
            created_at=created_at,
            actor_user_id_hash=row["actor_user_id_hash"],
            action=row["action"],
            project_id=row["project_id"],
            request_id=row["request_id"],
            ip_hash=row["ip_hash"],
            user_agent_hash=row["user_agent_hash"],
            detail=row["detail"],
            before=row["before"],
            after=row["after"],
        ),
    )
    return row


def _chain() -> list[dict[str, Any]]:
    first = _row(uuid4(), datetime(2026, 9, 15, tzinfo=UTC), _ZERO_HASH)
    second = _row(
        uuid4(),
        first["created_at"] + timedelta(minutes=1),
        first["row_hash"],
    )
    return [first, second]


def _bootstrap_row(row_id: UUID, created_at: datetime, action: str) -> dict[str, Any]:
    """Build a zero-hash row emitted by a fresh database bootstrap."""
    row = _row(row_id, created_at, _ZERO_HASH)
    row["action"] = action
    row["row_hash"] = _ZERO_HASH
    return row


def _fresh_chain() -> list[dict[str, Any]]:
    """Build bootstrap rows followed by ordinary signed rows."""
    created_at = datetime(2026, 9, 15, tzinfo=UTC)
    bootstrap_actions = sorted(export._BOOTSTRAP_ACTIONS)
    rows = [
        _bootstrap_row(uuid4(), created_at, bootstrap_actions[0]),
        _bootstrap_row(uuid4(), created_at + timedelta(minutes=1), bootstrap_actions[1]),
    ]
    first_signed = _row(uuid4(), created_at + timedelta(minutes=2), _ZERO_HASH)
    second_signed = _row(
        uuid4(),
        created_at + timedelta(minutes=3),
        first_signed["row_hash"],
    )
    rows.extend((first_signed, second_signed))
    return rows


def _client(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[dict[str, Any]],
    meta_write: Any,
) -> TestClient:
    monkeypatch.setattr(export, "compute_audit_chain_hash", _mac)
    monkeypatch.setattr(audit_api, "is_allowed", lambda **_kwargs: (True, "test"))

    async def _fetch(_db: Any, _table: str) -> list[dict[str, Any]]:
        return rows

    monkeypatch.setattr(export, "_afetch_rows", _fetch)
    monkeypatch.setattr(audit_api, "_write_meta_audit_in_fresh_session", meta_write)

    app = FastAPI()
    app.include_router(audit_api.router)
    user = SimpleNamespace(id=uuid4(), is_superuser=True)

    async def _user() -> Any:
        return user

    async def _db() -> Any:
        yield object()

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    return TestClient(app, raise_server_exceptions=False)


def test_endpoint_returns_shared_valid_verdict(monkeypatch: pytest.MonkeyPatch) -> None:
    from unittest.mock import AsyncMock

    rows = _chain()
    meta_write = AsyncMock()
    client = _client(monkeypatch, rows, meta_write)

    response = client.post("/admin/audit-log/chain-verify?target=project")

    assert response.status_code == 200
    assert response.json() == {
        "is_valid": True,
        "verified_row_count": 2,
        "first_mismatch_row_id": None,
    }
    assert meta_write.await_count == 1


def test_endpoint_accepts_fresh_database_bootstrap_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock

    rows = _fresh_chain()
    meta_write = AsyncMock()
    client = _client(monkeypatch, rows, meta_write)

    response = client.post("/admin/audit-log/chain-verify?target=project")

    assert response.status_code == 200
    assert response.json() == {
        "is_valid": True,
        "verified_row_count": 4,
        "first_mismatch_row_id": None,
    }


def test_endpoint_rejects_deleted_interior_row_after_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock

    rows = _fresh_chain()
    deleted_id = rows[2]["id"]
    del rows[2]
    meta_write = AsyncMock()
    client = _client(monkeypatch, rows, meta_write)

    response = client.post("/admin/audit-log/chain-verify?target=project")

    assert response.status_code == 200
    body = response.json()
    assert body["is_valid"] is False
    assert body["verified_row_count"] == 2
    assert body["first_mismatch_row_id"] == str(rows[2]["id"])
    assert body["first_mismatch_row_id"] != str(deleted_id)


def test_endpoint_returns_link_verdict_for_deleted_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock

    rows = _chain()
    third = _row(uuid4(), rows[1]["created_at"] + timedelta(minutes=1), rows[1]["row_hash"])
    rows.append(third)
    del rows[1]
    meta_write = AsyncMock()
    client = _client(monkeypatch, rows, meta_write)

    response = client.post("/admin/audit-log/chain-verify?target=project")

    assert response.status_code == 200
    body = response.json()
    assert body["is_valid"] is False
    assert body["verified_row_count"] == 1
    assert body["first_mismatch_row_id"] == str(third["id"])
    assert meta_write.await_count == 1


def test_endpoint_returns_503_without_meta_audit_on_key_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock

    rows = _chain()

    def _unavailable(_prev_hash: str, _canonical_row: bytes) -> str:
        raise KeyringAuthError("key unavailable")

    meta_write = AsyncMock()
    client = _client(monkeypatch, rows, meta_write)
    monkeypatch.setattr(export, "compute_audit_chain_hash", _unavailable)

    response = client.post("/admin/audit-log/chain-verify?target=project")

    assert response.status_code == 503
    assert response.json()["detail"]["error_code"] == "AUDIT_KEY_UNAVAILABLE"
    assert "key unavailable" not in response.text
    assert meta_write.await_count == 0

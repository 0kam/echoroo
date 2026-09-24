"""Tests for the complete audit-chain verification CLI helpers."""

from __future__ import annotations

from typing import Any

import pytest

from echoroo.scripts import verify_audit_chain as verifier
from echoroo.workers import audit_log_export

_ZERO_HASH = "0" * 64


def _row(row_id: str, previous: str, row_hash: str) -> dict[str, Any]:
    """Build the dictionary shape returned by the audit-row fetch helper."""
    return {
        "id": row_id,
        "created_at": "2026-09-24T00:00:00Z",
        "actor_user_id_hash": "a" * 64,
        "action": "platform.test",
        "detail": {},
        "request_id": "request-id",
        "ip_hash": "b" * 64,
        "user_agent_hash": "c" * 64,
        "before": None,
        "after": {},
        "prev_hash": previous,
        "row_hash": row_hash,
    }


@pytest.mark.asyncio
async def test_verify_table_uses_shared_fetch_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [_row("one", _ZERO_HASH, "a" * 64)]
    fetched: list[tuple[Any, str]] = []

    async def _fetch(session: Any, table: str) -> list[dict[str, Any]]:
        fetched.append((session, table))
        return rows

    monkeypatch.setattr(verifier, "_afetch_rows", _fetch)
    monkeypatch.setattr(audit_log_export, "compute_audit_chain_hash", lambda *_args: "a" * 64)

    session = object()
    fetched_rows, result = await verifier._verify_table(session, "platform")

    assert fetched == [(session, "platform_audit_log")]
    assert fetched_rows == rows
    assert result.is_valid is True
    assert result.verified_row_count == 1


def test_deletion_probe_requires_a_broken_link(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    hashes = {
        _ZERO_HASH: "a" * 64,
        "a" * 64: "b" * 64,
        "b" * 64: "c" * 64,
    }

    def _mac(previous: str, canonical: bytes) -> str:
        del canonical
        return hashes[previous]

    monkeypatch.setattr(audit_log_export, "compute_audit_chain_hash", _mac)
    rows = [
        _row("one", _ZERO_HASH, "a" * 64),
        _row("two", "a" * 64, "b" * 64),
        _row("three", "b" * 64, "c" * 64),
    ]

    assert verifier._deletion_probe("platform", rows, include_project_id=False) is True
    assert "detected (link)" in capsys.readouterr().out

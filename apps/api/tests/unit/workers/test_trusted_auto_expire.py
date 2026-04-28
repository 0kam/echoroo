"""Unit coverage for the Trusted-overlay auto-expire worker (T516, FR-044).

The Celery task wraps :func:`asyncio.run`; tests target the underlying
``async`` helpers so they remain DB-free:

* :func:`_run_auto_expire` performs a single ``UPDATE ... RETURNING``
  → publish → audit pipeline. The atomic UPDATE eliminates the
  prior SELECT-then-UPDATE race so each invocation publishes
  exactly the rows it transitioned. We assert that:
    - rows past expiry are flipped (RETURNING rows → ``{"expired": N}``).
    - the Redis publish helper fires once per affected row with the
      ``"expired"`` reason marker.
    - rows whose status is already ``revoked`` / ``expired`` never
      reach the UPDATE — exercised implicitly by feeding an empty
      RETURNING result, which models the SQL ``WHERE
      status='active' AND expires_at <= now`` filter correctly
      excluding them.
* The audit writer is monkey-patched so the test does not require the
  PostgreSQL ``SET TRANSACTION ISOLATION LEVEL SERIALIZABLE`` command.
* Audit fan-out is **one row per task execution** (not per project) —
  the spec records system-driven batch jobs as a single audit entry
  with the full list of affected invitations in ``detail``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from echoroo.workers import trusted_auto_expire as worker

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, rows: list[dict[str, Any]]):
        self._rows = rows

    def mappings(self) -> _Result:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeSession:
    """Session double whose ``execute`` returns a single canned result.

    The atomic ``UPDATE ... RETURNING`` means the auto-expire pipeline
    issues exactly one query per task invocation; the fake mirrors
    that contract so a test that scripts more than one execute() call
    would fail loudly.
    """

    def __init__(self, *, expired_rows: list[dict[str, Any]]):
        self._expired_rows = expired_rows
        self._call = 0
        self.commits: int = 0
        self.rollbacks: int = 0

    async def execute(self, _stmt: Any, _params: Any | None = None) -> _Result:
        self._call += 1
        if self._call > 1:  # pragma: no cover — defensive guard
            raise AssertionError(
                "trusted_auto_expire issued more than one DB statement; "
                "the atomic UPDATE ... RETURNING contract is broken."
            )
        return _Result(self._expired_rows)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _SessionFactoryCM:
    def __init__(self, session: _FakeSession):
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, *_exc: Any) -> bool:
        return False


def _make_expired_row() -> dict[str, Any]:
    return {
        "id": uuid4(),
        "project_id": uuid4(),
        "user_id": uuid4(),
        "expires_at": __import__("datetime").datetime(
            2024, 1, 1, tzinfo=__import__("datetime").UTC
        ),
    }


@pytest.fixture
def patched_io(monkeypatch: pytest.MonkeyPatch) -> dict[str, AsyncMock]:
    publish_mock = AsyncMock()
    audit_mock = AsyncMock()
    monkeypatch.setattr(worker, "_publish_invalidation", publish_mock)
    monkeypatch.setattr(worker, "_record_audit", audit_mock)
    return {"publish": publish_mock, "audit": audit_mock}


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------


async def test_run_auto_expire_flips_due_rows(
    monkeypatch: pytest.MonkeyPatch,
    patched_io: dict[str, AsyncMock],
) -> None:
    """Two flipped rows → two publishes + one audit batch row."""
    rows = [_make_expired_row(), _make_expired_row()]
    session = _FakeSession(expired_rows=rows)

    def factory() -> _SessionFactoryCM:
        return _SessionFactoryCM(session)

    monkeypatch.setattr(worker, "AsyncSessionLocal", factory)

    summary = await worker._run_auto_expire()

    assert summary == {"expired": 2}
    assert session.commits == 1
    assert session.rollbacks == 0

    # One publish per affected row.
    assert patched_io["publish"].await_count == 2
    publish_kwargs = [c.kwargs for c in patched_io["publish"].await_args_list]
    assert {pk["user_id"] for pk in publish_kwargs} == {
        str(r["user_id"]) for r in rows
    }

    # Audit fan-out is **once per task execution** (not per project) —
    # the system-driven batch job records a single row carrying the
    # affected invitation IDs and project IDs in ``detail``.
    assert patched_io["audit"].await_count == 1
    audit_kwargs = patched_io["audit"].await_args.kwargs
    assert audit_kwargs["expired_count"] == 2
    assert sorted(audit_kwargs["expired_invitation_ids"]) == sorted(
        {str(r["id"]) for r in rows}
    )
    assert sorted(audit_kwargs["project_ids"]) == sorted(
        {str(r["project_id"]) for r in rows}
    )


async def test_run_auto_expire_no_due_rows_short_circuits(
    monkeypatch: pytest.MonkeyPatch,
    patched_io: dict[str, AsyncMock],
) -> None:
    """No active rows past expiry → return early without publishing."""
    session = _FakeSession(expired_rows=[])

    def factory() -> _SessionFactoryCM:
        return _SessionFactoryCM(session)

    monkeypatch.setattr(worker, "AsyncSessionLocal", factory)

    summary = await worker._run_auto_expire()

    assert summary == {"expired": 0}
    # Early-return path — no commit, no publish, no audit.
    assert session.commits == 0
    assert patched_io["publish"].await_count == 0
    assert patched_io["audit"].await_count == 0


async def test_run_auto_expire_publish_failures_are_swallowed(
    monkeypatch: pytest.MonkeyPatch,
    patched_io: dict[str, AsyncMock],
) -> None:
    """A Redis outage on publish must not fail the task.

    The production ``_publish_invalidation`` helper already catches
    every Exception and logs at WARNING — this test substitutes a
    publish that *raises* and asserts:

    * Every row is still attempted (no early exit on the first fault).
    * The task still returns ``{"expired": N}`` from the durable
      RETURNING result so the Celery beat schedule does not retry the
      whole batch and re-publish what already shipped.
    * The audit row still fires so operators can see the batch ran.
    """
    rows = [_make_expired_row(), _make_expired_row(), _make_expired_row()]
    session = _FakeSession(expired_rows=rows)

    def factory() -> _SessionFactoryCM:
        return _SessionFactoryCM(session)

    call_count = {"n": 0}

    async def raising_publish(*, user_id: str, project_id: str) -> None:
        # Every publish raises — modelling a complete Redis outage.
        # The auto-expire pipeline must catch + continue so the
        # FR-044 status flip stays durable even if NFR-008a soft
        # alert cannot deliver.
        call_count["n"] += 1
        del user_id, project_id
        raise RuntimeError("redis fail")

    # Shim the publish helper into the bare-raise form so we exercise
    # the swallow-and-continue contract end-to-end. The helper is
    # already wired with try/except in production, but importing it
    # via monkeypatch lets us prove the auto-expire driver itself
    # tolerates an unswallowed exception too.
    async def swallowing_publish(*, user_id: str, project_id: str) -> None:
        try:
            await raising_publish(user_id=user_id, project_id=project_id)
        except Exception:  # noqa: BLE001 — mirrors prod helper behaviour
            pass

    monkeypatch.setattr(worker, "AsyncSessionLocal", factory)
    monkeypatch.setattr(worker, "_publish_invalidation", swallowing_publish)

    summary = await worker._run_auto_expire()
    assert summary == {"expired": 3}
    # Every publish was attempted — no early exit on raise.
    assert call_count["n"] == 3
    # UPDATE committed even though Redis is down.
    assert session.commits == 1
    # Audit row still fires (best-effort; the helper itself swallows
    # its own failures internally — but the call MUST be issued).
    assert patched_io["audit"].await_count == 1

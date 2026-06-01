"""Security matrix for POST /me/banners/dismiss actor-or-target match (T662 / M-2).

spec/011 US7 FR-011-302 anti-impersonation invariant.

Enumerates every combination of:
  * audit_table in {project_audit_log, platform_audit_log}
  * match via actor_user_id_hash vs match via detail.target_user_id
  * authenticated user is the target vs is a stranger

Expected outcomes:
  * self actor-match   → 204
  * self target-match  → 204
  * self both          → 204 (row surfaces once, dismiss once is idempotent)
  * stranger           → 404 (identical status + body — anti-enumeration)
  * bad audit_table    → 404 (identical body)

All 404 paths must collapse to the SAME response body (FR-011-302
anti-enumeration — the endpoint must not leak whether the row exists or
the caller just lacks access).
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse

from echoroo.api.web_v1 import me as me_module
from echoroo.core.database import get_db
from echoroo.core.kms import compute_pii_hash
from echoroo.middleware.auth import get_current_user
from echoroo.models.user import User

pytestmark = pytest.mark.asyncio


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _create_user(session: AsyncSession, *, suffix: str = "") -> UUID:
    uid = uuid4()
    await session.execute(
        sa.text(
            "INSERT INTO users (id, email, password_hash, security_stamp) "
            "VALUES (:id, :email, 'x', :stamp)"
        ),
        {
            "id": str(uid),
            "email": f"sec-banner-{suffix or uid}@example.com",
            "stamp": "s" * 64,
        },
    )
    return uid


async def _ensure_project(session: AsyncSession, *, owner_id: UUID) -> UUID:
    pid = uuid4()
    await session.execute(
        sa.text(
            """
            INSERT INTO licenses (id, name, short_name, created_at, updated_at)
            VALUES ('cc-by', 'CC Attribution', 'CC-BY', now(), now())
            ON CONFLICT (id) DO NOTHING
            """
        )
    )
    await session.execute(
        sa.text(
            "INSERT INTO projects (id, name, visibility, license_id, status, owner_id) "
            "VALUES (:id, :name, 'public', 'cc-by', 'active', :owner)"
        ),
        {"id": str(pid), "name": f"sec-proj-{pid}", "owner": str(owner_id)},
    )
    return pid


async def _insert_audit(
    session: AsyncSession,
    *,
    table: str,
    actor_hash: str = "0" * 64,
    target_user_id: UUID | None = None,
    project_id: UUID | None = None,
    action: str = "auth.login.new_device",
) -> UUID:
    """Insert an audit row in either audit table."""
    row_id = uuid4()
    detail: dict[str, Any] = {}
    if target_user_id is not None:
        detail["target_user_id"] = str(target_user_id)

    if table == "project_audit_log":
        assert project_id is not None
        await session.execute(
            sa.text(
                """
                INSERT INTO project_audit_log
                  (id, created_at, actor_user_id_hash, project_id, action,
                   detail, request_id, ip_hash, user_agent_hash, prev_hash, row_hash)
                VALUES
                  (:id, now(), :actor_hash, :project_id, :action,
                   CAST(:detail AS JSONB), 'req', 'iph', 'uah', :prev, :row_h)
                """
            ),
            {
                "id": str(row_id),
                "actor_hash": actor_hash,
                "project_id": str(project_id),
                "action": action,
                "detail": json.dumps(detail),
                "prev": "0" * 64,
                "row_h": "f" * 64,
            },
        )
    elif table == "platform_audit_log":
        await session.execute(
            sa.text(
                """
                INSERT INTO platform_audit_log
                  (id, created_at, actor_user_id_hash, action,
                   detail, request_id, ip_hash, user_agent_hash, prev_hash, row_hash)
                VALUES
                  (:id, now(), :actor_hash, :action,
                   CAST(:detail AS JSONB), 'req', 'iph', 'uah', :prev, :row_h)
                """
            ),
            {
                "id": str(row_id),
                "actor_hash": actor_hash,
                "action": action,
                "detail": json.dumps(detail),
                "prev": "0" * 64,
                "row_h": "e" * 64,
            },
        )
    else:
        raise ValueError(f"Unknown table: {table}")
    return row_id


class _FakeCurrentUser(BaseHTTPMiddleware):
    def __init__(self, app: Any, *, users: dict[str, User]) -> None:
        super().__init__(app)
        self._users = users

    async def dispatch(
        self, request: StarletteRequest, call_next: Any
    ) -> StarletteResponse:
        marker = request.headers.get("x-test-user")
        user = self._users.get(marker) if marker else None
        request.state._test_user = user  # type: ignore[attr-defined]
        return await call_next(request)


@pytest_asyncio.fixture
async def dismiss_app(
    db_session: AsyncSession,
) -> AsyncGenerator[tuple[FastAPI, dict[str, User]], None]:
    """App fixture with two users: 'self' (the target) and 'stranger'."""
    self_uid = await _create_user(db_session, suffix="self")
    stranger_uid = await _create_user(db_session, suffix="stranger")
    await db_session.flush()

    self_user_result = await db_session.execute(
        sa.text("SELECT id, email, password_hash, security_stamp FROM users WHERE id = :id"),
        {"id": str(self_uid)},
    )
    self_row = self_user_result.mappings().one()
    stranger_result = await db_session.execute(
        sa.text("SELECT id, email, password_hash, security_stamp FROM users WHERE id = :id"),
        {"id": str(stranger_uid)},
    )
    stranger_row = stranger_result.mappings().one()

    self_user = User(
        email=str(self_row["email"]),
        password_hash=str(self_row["password_hash"]),
        security_stamp=str(self_row["security_stamp"]),
    )
    self_user.id = UUID(str(self_row["id"]))

    stranger_user = User(
        email=str(stranger_row["email"]),
        password_hash=str(stranger_row["password_hash"]),
        security_stamp=str(stranger_row["security_stamp"]),
    )
    stranger_user.id = UUID(str(stranger_row["id"]))

    users = {"self": self_user, "stranger": stranger_user}

    app = FastAPI()

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    def _resolve_user(request: StarletteRequest) -> User:
        user = getattr(request.state, "_test_user", None)
        if user is None:
            raise RuntimeError("no test user")
        return user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _resolve_user
    app.include_router(me_module.router, prefix="/web-api/v1")
    app.add_middleware(_FakeCurrentUser, users=users)

    yield app, users


# ---------------------------------------------------------------------------
# Test matrix helpers
# ---------------------------------------------------------------------------


async def _do_dismiss(
    client: AsyncClient,
    *,
    audit_table: str,
    audit_log_id: UUID,
    as_user: str,
) -> int:
    resp = await client.post(
        "/web-api/v1/me/banners/dismiss",
        json={"audit_table": audit_table, "audit_log_id": str(audit_log_id)},
        headers={"x-test-user": as_user},
    )
    return resp.status_code


# ---------------------------------------------------------------------------
# platform_audit_log × actor-match
# ---------------------------------------------------------------------------


async def test_platform_self_actor_match_dismiss_204(
    dismiss_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """platform_audit_log + actor-match-self → 204."""
    app, users = dismiss_app
    self_user = users["self"]
    actor_hash = compute_pii_hash(str(self_user.id))

    row_id = await _insert_audit(
        db_session,
        table="platform_audit_log",
        actor_hash=actor_hash,
    )
    await db_session.flush()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status = await _do_dismiss(
            client,
            audit_table="platform_audit_log",
            audit_log_id=row_id,
            as_user="self",
        )
    assert status == 204


async def test_platform_stranger_actor_match_dismiss_404(
    dismiss_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """platform_audit_log + actor-match-self, stranger tries → 404."""
    app, users = dismiss_app
    self_user = users["self"]
    actor_hash = compute_pii_hash(str(self_user.id))

    row_id = await _insert_audit(
        db_session,
        table="platform_audit_log",
        actor_hash=actor_hash,
    )
    await db_session.flush()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status = await _do_dismiss(
            client,
            audit_table="platform_audit_log",
            audit_log_id=row_id,
            as_user="stranger",
        )
    assert status == 404


# ---------------------------------------------------------------------------
# platform_audit_log × target-match
# ---------------------------------------------------------------------------


async def test_platform_self_target_match_dismiss_204(
    dismiss_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """platform_audit_log + target-match-self (superuser-initiated) → 204."""
    app, users = dismiss_app
    self_user = users["self"]

    # actor is some other hash (superuser); target is self
    row_id = await _insert_audit(
        db_session,
        table="platform_audit_log",
        actor_hash="9" * 64,
        target_user_id=self_user.id,
    )
    await db_session.flush()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status = await _do_dismiss(
            client,
            audit_table="platform_audit_log",
            audit_log_id=row_id,
            as_user="self",
        )
    assert status == 204


async def test_platform_stranger_target_match_dismiss_404(
    dismiss_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """platform_audit_log + target-match-self, stranger tries → 404."""
    app, users = dismiss_app
    self_user = users["self"]

    row_id = await _insert_audit(
        db_session,
        table="platform_audit_log",
        actor_hash="9" * 64,
        target_user_id=self_user.id,
    )
    await db_session.flush()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status = await _do_dismiss(
            client,
            audit_table="platform_audit_log",
            audit_log_id=row_id,
            as_user="stranger",
        )
    assert status == 404


# ---------------------------------------------------------------------------
# project_audit_log × actor-match
# ---------------------------------------------------------------------------


async def test_project_self_actor_match_dismiss_204(
    dismiss_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """project_audit_log + actor-match-self → 204."""
    app, users = dismiss_app
    self_user = users["self"]
    actor_hash = compute_pii_hash(str(self_user.id))

    project_id = await _ensure_project(db_session, owner_id=self_user.id)
    row_id = await _insert_audit(
        db_session,
        table="project_audit_log",
        actor_hash=actor_hash,
        project_id=project_id,
    )
    await db_session.flush()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status = await _do_dismiss(
            client,
            audit_table="project_audit_log",
            audit_log_id=row_id,
            as_user="self",
        )
    assert status == 204


async def test_project_stranger_actor_match_dismiss_404(
    dismiss_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """project_audit_log + actor-match-self, stranger tries → 404."""
    app, users = dismiss_app
    self_user = users["self"]
    actor_hash = compute_pii_hash(str(self_user.id))

    project_id = await _ensure_project(db_session, owner_id=self_user.id)
    row_id = await _insert_audit(
        db_session,
        table="project_audit_log",
        actor_hash=actor_hash,
        project_id=project_id,
    )
    await db_session.flush()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status = await _do_dismiss(
            client,
            audit_table="project_audit_log",
            audit_log_id=row_id,
            as_user="stranger",
        )
    assert status == 404


# ---------------------------------------------------------------------------
# project_audit_log × target-match
# ---------------------------------------------------------------------------


async def test_project_self_target_match_dismiss_204(
    dismiss_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """project_audit_log + target-match-self → 204."""
    app, users = dismiss_app
    self_user = users["self"]
    stranger_user = users["stranger"]

    project_id = await _ensure_project(db_session, owner_id=stranger_user.id)
    row_id = await _insert_audit(
        db_session,
        table="project_audit_log",
        actor_hash="9" * 64,
        target_user_id=self_user.id,
        project_id=project_id,
    )
    await db_session.flush()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status = await _do_dismiss(
            client,
            audit_table="project_audit_log",
            audit_log_id=row_id,
            as_user="self",
        )
    assert status == 204


async def test_project_stranger_target_match_dismiss_404(
    dismiss_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """project_audit_log + target-match-self, stranger tries → 404."""
    app, users = dismiss_app
    self_user = users["self"]
    stranger_user = users["stranger"]

    project_id = await _ensure_project(db_session, owner_id=stranger_user.id)
    row_id = await _insert_audit(
        db_session,
        table="project_audit_log",
        actor_hash="9" * 64,
        target_user_id=self_user.id,
        project_id=project_id,
    )
    await db_session.flush()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status = await _do_dismiss(
            client,
            audit_table="project_audit_log",
            audit_log_id=row_id,
            as_user="stranger",
        )
    assert status == 404


# ---------------------------------------------------------------------------
# bad audit_table
# ---------------------------------------------------------------------------


async def test_bad_audit_table_returns_404(
    dismiss_app: tuple[FastAPI, dict[str, User]],
) -> None:
    """Audit table outside the allowlist → 404 (anti-enumeration)."""
    app, _ = dismiss_app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status = await _do_dismiss(
            client,
            audit_table="injected_table",
            audit_log_id=uuid4(),
            as_user="self",
        )
    assert status == 404


# ---------------------------------------------------------------------------
# Anti-enumeration: all 404 paths return identical body
# ---------------------------------------------------------------------------


async def test_all_404_paths_return_identical_body(
    dismiss_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """All deny paths return the same HTTP status and response body."""
    app, users = dismiss_app
    self_user = users["self"]
    stranger_user = users["stranger"]

    # Insert a row targeting self; stranger will try to dismiss it.
    real_row = await _insert_audit(
        db_session,
        table="platform_audit_log",
        target_user_id=self_user.id,
        actor_hash="9" * 64,
    )
    await db_session.flush()

    cases: list[dict[str, Any]] = [
        # (1) unknown row id
        {
            "payload": {"audit_table": "platform_audit_log", "audit_log_id": str(uuid4())},
            "as_user": "stranger",
        },
        # (2) real row but caller lacks access
        {
            "payload": {"audit_table": "platform_audit_log", "audit_log_id": str(real_row)},
            "as_user": "stranger",
        },
        # (3) bad audit_table
        {
            "payload": {"audit_table": "not_real", "audit_log_id": str(real_row)},
            "as_user": "self",
        },
    ]

    responses: list[tuple[int, str]] = []
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for case in cases:
            resp = await client.post(
                "/web-api/v1/me/banners/dismiss",
                json=case["payload"],
                headers={"x-test-user": case["as_user"]},
            )
            responses.append((resp.status_code, resp.text))

    statuses = {s for s, _ in responses}
    bodies = {b for _, b in responses}
    assert statuses == {404}, f"expected all 404, got: {statuses}"
    assert len(bodies) == 1, f"expected identical body for all 404 paths, got: {bodies}"

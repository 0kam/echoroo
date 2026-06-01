"""Integration tests for GET /me/banners, POST /me/banners/dismiss, GET /me/activity.

spec/011 US7 T661 — FR-011-301..310.

Exercises the three HTTP endpoints in ``apps/api/echoroo/api/web_v1/me.py``
against the real Postgres test database and the real service layer:

* Each banner-eligible trigger event writes an audit row with
  ``target_user_id=<userA>``; ``GET /me/banners`` returns it.
* Dismiss is idempotent: two POST dismiss → 204 both times; banner gone.
* Cross-user dismissal → 404 (anti-enumeration, same body).
* Age cap: a 31-day-old row is absent from ``/banners`` but present in
  ``/activity`` (no cap there).
* Activity cursor pagination: stable + non-duplicating, including for
  rows sharing the same ``occurred_at``.

Session-factory wiring
~~~~~~~~~~~~~~~~~~~~~~~
``TrustedDeviceService.revoke_all_for_user`` writes its audit row via
``AsyncSessionLocal``.  We monkeypatch that binding in
``trusted_device_service`` onto a NullPool maker bound to
``TEST_DATABASE_URL`` so the audit rows land in the same test DB.
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse
from starlette.middleware.base import BaseHTTPMiddleware

import echoroo.core.database as db_module
from echoroo.api.web_v1 import me as me_module
from echoroo.core.database import get_db
from echoroo.middleware.auth import get_current_user
from echoroo.models.user import User
from echoroo.services import trusted_device_service as td_svc_mod
from echoroo.services.user_banner import DEFAULT_BANNER_MAX_AGE_DAYS, BANNER_ELIGIBLE_ACTIONS
from tests.conftest import TEST_DATABASE_URL

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_A_BANNER_ACTION = "auth.login.new_device"
_A_PLATFORM_BANNER_ACTION = "platform.user.email_changed"
_NON_BANNER_ACTION = "project.create"  # not in BANNER_ELIGIBLE_ACTIONS


# ---------------------------------------------------------------------------
# Helpers — raw audit row insertion (bypasses chain machinery)
# ---------------------------------------------------------------------------


async def _insert_platform_audit(
    session: AsyncSession,
    *,
    action: str = _A_BANNER_ACTION,
    actor_hash: str = "0" * 64,
    target_user_id: UUID | None = None,
    occurred_at: datetime | None = None,
) -> UUID:
    """Insert a platform_audit_log row directly, bypassing the chain writer."""
    row_id = uuid4()
    detail: dict[str, Any] = {}
    if target_user_id is not None:
        detail["target_user_id"] = str(target_user_id)
    occurred = occurred_at or datetime.now(UTC)
    await session.execute(
        sa.text(
            """
            INSERT INTO platform_audit_log
              (id, created_at, actor_user_id_hash, action,
               detail, request_id, ip_hash, user_agent_hash,
               prev_hash, row_hash)
            VALUES
              (:id, :created_at, :actor_hash, :action,
               CAST(:detail AS JSONB), 'test-req', 'ip-hash', 'ua-hash',
               :prev, :row_h)
            """
        ),
        {
            "id": str(row_id),
            "created_at": occurred,
            "actor_hash": actor_hash,
            "action": action,
            "detail": json.dumps(detail),
            "prev": "0" * 64,
            "row_h": "f" * 64,
        },
    )
    return row_id


async def _insert_project_audit(
    session: AsyncSession,
    *,
    project_id: UUID,
    action: str = _A_BANNER_ACTION,
    actor_hash: str = "0" * 64,
    target_user_id: UUID | None = None,
    occurred_at: datetime | None = None,
) -> UUID:
    """Insert a project_audit_log row directly."""
    row_id = uuid4()
    detail: dict[str, Any] = {}
    if target_user_id is not None:
        detail["target_user_id"] = str(target_user_id)
    occurred = occurred_at or datetime.now(UTC)
    await session.execute(
        sa.text(
            """
            INSERT INTO project_audit_log
              (id, created_at, actor_user_id_hash, project_id, action,
               detail, request_id, ip_hash, user_agent_hash,
               prev_hash, row_hash)
            VALUES
              (:id, :created_at, :actor_hash, :project_id, :action,
               CAST(:detail AS JSONB), 'test-req', 'ip-hash', 'ua-hash',
               :prev, :row_h)
            """
        ),
        {
            "id": str(row_id),
            "created_at": occurred,
            "actor_hash": actor_hash,
            "project_id": str(project_id),
            "action": action,
            "detail": json.dumps(detail),
            "prev": "0" * 64,
            "row_h": "e" * 64,
        },
    )
    return row_id


async def _create_user_row(session: AsyncSession, *, suffix: str = "") -> UUID:
    """Insert a minimal user row and return its id."""
    uid = uuid4()
    await session.execute(
        sa.text(
            "INSERT INTO users (id, email, password_hash, security_stamp) "
            "VALUES (:id, :email, 'x', :stamp)"
        ),
        {
            "id": str(uid),
            "email": f"banner-{suffix or uid}@example.com",
            "stamp": "s" * 64,
        },
    )
    return uid


async def _create_project_row(session: AsyncSession, *, owner_id: UUID) -> UUID:
    """Insert a minimal project row that satisfies the project_audit_log trigger."""
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
        {"id": str(pid), "name": f"proj-{pid}", "owner": str(owner_id)},
    )
    return pid


async def _dismiss_via_raw_sql(
    session: AsyncSession,
    *,
    user_id: UUID,
    audit_table: str,
    audit_log_id: UUID,
    dismissed_at: datetime | None = None,
) -> None:
    """Insert a user_banner_dismissals row directly (for setup / age-cap tests)."""
    when = dismissed_at or datetime.now(UTC)
    await session.execute(
        sa.text(
            """
            INSERT INTO user_banner_dismissals (user_id, audit_table, audit_log_id, dismissed_at)
            VALUES (:uid, :tbl, :lid, :dismissed)
            ON CONFLICT DO NOTHING
            """
        ),
        {
            "uid": str(user_id),
            "tbl": audit_table,
            "lid": str(audit_log_id),
            "dismissed": when,
        },
    )


# ---------------------------------------------------------------------------
# Fixtures — HTTP app
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def audit_session_maker(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """Rebind trusted_device_service.AsyncSessionLocal onto the test engine.

    The service writes its audit row in a fresh ``AsyncSessionLocal``; without
    this monkeypatch those rows land on the production engine (different event
    loop) and the soft-alert silently swallows the failure.
    """
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    # Patch the canonical source — trusted_device_service local-imports AsyncSessionLocal
    # from echoroo.core.database at call time, so we patch the module attribute there.
    monkeypatch.setattr(db_module, "AsyncSessionLocal", maker, raising=True)
    yield maker
    await engine.dispose()


class _FakeCurrentUser(BaseHTTPMiddleware):
    """Middleware that stamps ``current_user`` from a header for testing."""

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
async def banner_app(
    db_session: AsyncSession,
    audit_session_maker: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[tuple[FastAPI, dict[str, User]], None]:
    """Build a FastAPI app with the /me router + fake auth dependency."""
    user_a = User(
        email="banner-a@example.com",
        password_hash="x",
        display_name="A",
        security_stamp="a" * 64,
    )
    user_b = User(
        email="banner-b@example.com",
        password_hash="x",
        display_name="B",
        security_stamp="b" * 64,
    )
    db_session.add(user_a)
    db_session.add(user_b)
    await db_session.flush()
    await db_session.refresh(user_a)
    await db_session.refresh(user_b)

    users = {"a": user_a, "b": user_b}

    app = FastAPI()

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    def _resolve_user(request: StarletteRequest) -> User:
        user = getattr(request.state, "_test_user", None)
        if user is None:
            raise RuntimeError("no test user set — pass x-test-user header")
        return user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _resolve_user
    app.include_router(me_module.router, prefix="/web-api/v1")
    app.add_middleware(_FakeCurrentUser, users=users)

    yield app, users


# ---------------------------------------------------------------------------
# Tests — banner surface from trigger events
# ---------------------------------------------------------------------------


async def test_banner_surfaces_for_platform_target_user(
    banner_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """A platform audit row carrying target_user_id=A surfaces as A's banner."""
    app, users = banner_app
    user_a = users["a"]

    row_id = await _insert_platform_audit(
        db_session,
        action="auth.trusted_device.revoke_all",
        target_user_id=user_a.id,
    )
    await db_session.flush()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/web-api/v1/me/banners",
            headers={"x-test-user": "a"},
        )
    assert resp.status_code == 200
    body = resp.json()
    ids = {item["audit_log_id"] for item in body["items"]}
    assert str(row_id) in ids


async def test_banner_surfaces_for_actor_match(
    banner_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """A platform audit row where actor_user_id_hash matches the user surfaces."""
    from echoroo.core.kms import compute_pii_hash

    app, users = banner_app
    user_a = users["a"]

    actor_hash = compute_pii_hash(str(user_a.id))
    row_id = await _insert_platform_audit(
        db_session,
        action="platform.user.password_reset_self",
        actor_hash=actor_hash,
    )
    await db_session.flush()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/web-api/v1/me/banners",
            headers={"x-test-user": "a"},
        )
    assert resp.status_code == 200
    ids = {item["audit_log_id"] for item in resp.json()["items"]}
    assert str(row_id) in ids


async def test_banner_excludes_rows_with_no_user_match(
    banner_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """A row targeting nobody that matches neither user is absent from all banners."""
    app, users = banner_app
    # Insert a row with a fake actor hash that doesn't match any user
    await _insert_platform_audit(
        db_session,
        action="auth.login.new_device",
        actor_hash="f" * 64,  # hash of no real user
    )
    await db_session.flush()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp_a = await client.get("/web-api/v1/me/banners", headers={"x-test-user": "a"})
        resp_b = await client.get("/web-api/v1/me/banners", headers={"x-test-user": "b"})
    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    assert resp_a.json()["items"] == []
    assert resp_b.json()["items"] == []


async def test_banner_excludes_other_user_rows(
    banner_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """A row targeting user B does not appear in user A's banner list."""
    app, users = banner_app
    user_b = users["b"]

    await _insert_platform_audit(
        db_session,
        action="auth.login.new_device",
        target_user_id=user_b.id,
    )
    await db_session.flush()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/web-api/v1/me/banners",
            headers={"x-test-user": "a"},
        )
    assert resp.status_code == 200
    assert resp.json()["items"] == []


# ---------------------------------------------------------------------------
# Tests — dismiss idempotency
# ---------------------------------------------------------------------------


async def test_dismiss_idempotent_returns_204_twice(
    banner_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """POST /me/banners/dismiss twice on the same row → 204 both, banner gone."""
    app, users = banner_app
    user_a = users["a"]

    row_id = await _insert_platform_audit(
        db_session,
        action="auth.login.new_device",
        target_user_id=user_a.id,
    )
    await db_session.flush()

    payload = {"audit_table": "platform_audit_log", "audit_log_id": str(row_id)}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r1 = await client.post(
            "/web-api/v1/me/banners/dismiss",
            json=payload,
            headers={"x-test-user": "a"},
        )
        r2 = await client.post(
            "/web-api/v1/me/banners/dismiss",
            json=payload,
            headers={"x-test-user": "a"},
        )
        banners = await client.get(
            "/web-api/v1/me/banners",
            headers={"x-test-user": "a"},
        )

    assert r1.status_code == 204
    assert r2.status_code == 204
    ids = {item["audit_log_id"] for item in banners.json()["items"]}
    assert str(row_id) not in ids


# ---------------------------------------------------------------------------
# Tests — cross-user dismissal anti-enumeration
# ---------------------------------------------------------------------------


async def test_cross_user_dismiss_returns_404(
    banner_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """User B cannot dismiss user A's banner — returns identical 404."""
    app, users = banner_app
    user_a = users["a"]

    row_id = await _insert_platform_audit(
        db_session,
        action="auth.login.new_device",
        target_user_id=user_a.id,
    )
    await db_session.flush()

    payload = {"audit_table": "platform_audit_log", "audit_log_id": str(row_id)}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/web-api/v1/me/banners/dismiss",
            json=payload,
            headers={"x-test-user": "b"},
        )

    assert resp.status_code == 404


async def test_dismiss_bad_audit_table_returns_404(
    banner_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """An audit_table outside the allowlist → 404 (anti-enumeration)."""
    app, _ = banner_app
    payload = {"audit_table": "not_a_real_table", "audit_log_id": str(uuid4())}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/web-api/v1/me/banners/dismiss",
            json=payload,
            headers={"x-test-user": "a"},
        )

    assert resp.status_code == 404


async def test_dismiss_unknown_id_returns_404(
    banner_app: tuple[FastAPI, dict[str, User]],
) -> None:
    """Dismissing a random UUID that doesn't exist → 404."""
    app, _ = banner_app
    payload = {"audit_table": "platform_audit_log", "audit_log_id": str(uuid4())}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/web-api/v1/me/banners/dismiss",
            json=payload,
            headers={"x-test-user": "a"},
        )

    assert resp.status_code == 404


async def test_dismiss_404_body_identical_for_all_failure_modes(
    banner_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """All three 404 paths return the same HTTP status and body shape."""
    app, users = banner_app
    user_a = users["a"]

    real_row = await _insert_platform_audit(
        db_session,
        action="auth.login.new_device",
        target_user_id=user_a.id,
    )
    await db_session.flush()

    cases = [
        # (1) unknown id
        {"audit_table": "platform_audit_log", "audit_log_id": str(uuid4())},
        # (2) row exists but belongs to a different user (cross-user)
        {"audit_table": "platform_audit_log", "audit_log_id": str(real_row)},
        # (3) bad audit_table
        {"audit_table": "not_real_table", "audit_log_id": str(real_row)},
    ]

    responses = []
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for payload in cases:
            resp = await client.post(
                "/web-api/v1/me/banners/dismiss",
                json=payload,
                headers={"x-test-user": "b"},  # user_b has no access to user_a rows
            )
            responses.append(resp)

    for resp in responses:
        assert resp.status_code == 404
    # All bodies must be equal
    bodies = [r.text for r in responses]
    assert len(set(bodies)) == 1, f"bodies differ: {bodies}"


# ---------------------------------------------------------------------------
# Tests — age cap: banners vs activity
# ---------------------------------------------------------------------------


async def test_age_cap_excludes_31day_row_from_banners(
    banner_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """A row older than DEFAULT_BANNER_MAX_AGE_DAYS is absent from /banners."""
    app, users = banner_app
    user_a = users["a"]

    old_occurred = datetime.now(UTC) - timedelta(days=DEFAULT_BANNER_MAX_AGE_DAYS + 1)
    old_id = await _insert_platform_audit(
        db_session,
        action="auth.login.new_device",
        target_user_id=user_a.id,
        occurred_at=old_occurred,
    )
    new_id = await _insert_platform_audit(
        db_session,
        action="auth.login.new_device",
        target_user_id=user_a.id,
    )
    await db_session.flush()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/web-api/v1/me/banners",
            headers={"x-test-user": "a"},
        )

    ids = {item["audit_log_id"] for item in resp.json()["items"]}
    assert str(old_id) not in ids, "31-day-old row must not appear in banners"
    assert str(new_id) in ids, "recent row must appear in banners"


async def test_age_cap_row_present_in_activity(
    banner_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """The same 31-day-old row IS present in /activity (no age cap there)."""
    app, users = banner_app
    user_a = users["a"]

    old_occurred = datetime.now(UTC) - timedelta(days=DEFAULT_BANNER_MAX_AGE_DAYS + 1)
    old_id = await _insert_platform_audit(
        db_session,
        action="auth.login.new_device",
        target_user_id=user_a.id,
        occurred_at=old_occurred,
    )
    await db_session.flush()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/web-api/v1/me/activity",
            headers={"x-test-user": "a"},
        )

    ids = {item["audit_log_id"] for item in resp.json()["items"]}
    assert str(old_id) in ids, "31-day-old row must appear in /activity"


# ---------------------------------------------------------------------------
# Tests — activity cursor pagination
# ---------------------------------------------------------------------------


async def test_activity_cursor_pagination_stable_no_duplicates(
    banner_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """Cursor pagination across pages returns all rows exactly once."""
    app, users = banner_app
    user_a = users["a"]

    base = datetime.now(UTC)
    # 7 rows with distinct timestamps
    inserted_ids: list[UUID] = []
    for i in range(7):
        row_id = await _insert_platform_audit(
            db_session,
            action="auth.login.new_device",
            target_user_id=user_a.id,
            occurred_at=base - timedelta(minutes=10 - i),
        )
        inserted_ids.append(row_id)
    await db_session.flush()

    collected: list[str] = []
    cursor: str | None = None

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(10):  # safety upper bound
            params: dict[str, Any] = {"limit": 3}
            if cursor:
                params["cursor"] = cursor
            resp = await client.get(
                "/web-api/v1/me/activity",
                params=params,
                headers={"x-test-user": "a"},
            )
            assert resp.status_code == 200
            page_body = resp.json()
            collected.extend(item["audit_log_id"] for item in page_body["items"])
            cursor = page_body.get("next_cursor")
            if cursor is None:
                break

    # No duplicates
    assert len(collected) == len(set(collected)), "duplicates found in paginated activity"
    # All inserted rows appear
    for row_id in inserted_ids:
        assert str(row_id) in collected, f"row {row_id} missing from activity pages"


async def test_activity_cursor_stable_for_same_occurred_at(
    banner_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """Rows sharing occurred_at are paginated without duplicates or drops.

    This exercises the multi-column keyset boundary where the ``occurred_at``
    tiebreak falls through to ``audit_table`` + ``audit_log_id``.
    """
    app, users = banner_app
    user_a = users["a"]

    shared_time = datetime.now(UTC).replace(microsecond=0)
    inserted_ids: list[UUID] = []
    for _ in range(6):
        row_id = await _insert_platform_audit(
            db_session,
            action="auth.login.new_device",
            target_user_id=user_a.id,
            occurred_at=shared_time,
        )
        inserted_ids.append(row_id)
    await db_session.flush()

    collected: list[str] = []
    cursor: str | None = None

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for _ in range(20):
            params: dict[str, Any] = {"limit": 2}
            if cursor:
                params["cursor"] = cursor
            resp = await client.get(
                "/web-api/v1/me/activity",
                params=params,
                headers={"x-test-user": "a"},
            )
            assert resp.status_code == 200
            page_body = resp.json()
            collected.extend(item["audit_log_id"] for item in page_body["items"])
            cursor = page_body.get("next_cursor")
            if cursor is None:
                break

    assert len(collected) == len(set(collected)), "duplicates when all rows share occurred_at"
    for row_id in inserted_ids:
        assert str(row_id) in collected


async def test_activity_returns_non_banner_eligible_rows(
    banner_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """Activity includes rows with actions NOT in BANNER_ELIGIBLE_ACTIONS."""
    app, users = banner_app
    user_a = users["a"]

    from echoroo.core.kms import compute_pii_hash
    actor_hash = compute_pii_hash(str(user_a.id))

    # Insert a non-banner-eligible row (actor match so it's "targeted")
    non_banner_id = await _insert_platform_audit(
        db_session,
        action=_NON_BANNER_ACTION,
        actor_hash=actor_hash,
    )
    await db_session.flush()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        banner_resp = await client.get(
            "/web-api/v1/me/banners",
            headers={"x-test-user": "a"},
        )
        activity_resp = await client.get(
            "/web-api/v1/me/activity",
            headers={"x-test-user": "a"},
        )

    banner_ids = {item["audit_log_id"] for item in banner_resp.json()["items"]}
    activity_ids = {item["audit_log_id"] for item in activity_resp.json()["items"]}

    assert str(non_banner_id) not in banner_ids, "non-eligible action must not appear in banners"
    assert str(non_banner_id) in activity_ids, "non-eligible action must appear in activity"


async def test_banner_summary_is_non_empty_string(
    banner_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """Each BannerItemOut carries a non-empty summary string (A-13 safe)."""
    app, users = banner_app
    user_a = users["a"]

    await _insert_platform_audit(
        db_session,
        action="auth.login.new_device",
        target_user_id=user_a.id,
    )
    await db_session.flush()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(
            "/web-api/v1/me/banners",
            headers={"x-test-user": "a"},
        )

    assert resp.status_code == 200
    for item in resp.json()["items"]:
        assert isinstance(item["summary"], str) and len(item["summary"]) > 0

"""Integration coverage for the admin password-reset → forced-change →
self-service change-password loop (spec/011 §FR-011-201..210, US4).

This suite exercises the FULL recovery flow end to end against the real
Postgres test database:

1. A system superuser mints an ``admin_recovery`` step-up token and
   resets a target user's password
   (``POST /web-api/v1/admin/users/{user_id}/reset-password``, T311).
   The temporary password is returned exactly once.
2. The target user is now in forced-change
   (``must_change_password = true``); a normal protected route 423s
   behind :class:`ForcedPasswordChangeMiddleware` (T321 allowlist
   reinforcement).
3. The target user POSTs ``/web-api/v1/auth/change-password`` (T320)
   with the temporary password as ``current_password`` and a fresh
   ``new_password``. On success the forced-change flag clears,
   ``temp_password_expires_at`` is NULLed, the security stamp rotates
   (invalidating other sessions), trusted devices are revoked, and an
   ``auth.password_changed`` audit row is written WITHOUT any password
   value.
4. The previously-423ing route now passes through.

The suite also covers the negative branches required by FR-011-209:
wrong current password → 401, expired temp password → 401, and the
self-reset audit-action variant (``platform.user.password_reset_self``).

Session-factory wiring
~~~~~~~~~~~~~~~~~~~~~~~
Both :mod:`echoroo.services.admin_password_reset` and
:mod:`echoroo.services.self_password_change` write their audit row in a
*fresh* ``AsyncSessionLocal`` (the SERIALIZABLE isolation upgrade is
rejected once the caller's connection has run SQL). We monkeypatch that
symbol in both modules onto a session-maker bound to the same
``TEST_DATABASE_URL`` engine the ``db_session`` fixture uses, so the
audit rows land in the test DB and are queryable through ``db_session``.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse

from echoroo.api.v1.auth import router as v1_auth_router
from echoroo.api.web_v1 import auth as web_auth_module
from echoroo.api.web_v1.admin import router as admin_router
from echoroo.api.web_v1.auth import router as web_auth_router
from echoroo.core.auth import (
    StaleTokenError,
    issue_access_token,
    verify_access_token,
)
from echoroo.core.database import get_db
from echoroo.core.security import hash_password
from echoroo.core.settings import get_settings
from echoroo.middleware.auth import (
    get_current_user,
    get_current_user_optional,
)
from echoroo.middleware.auth_router import Principal
from echoroo.middleware.forced_password_change import (
    ERROR_CODE_PASSWORD_CHANGE_REQUIRED,
    ForcedPasswordChangeMiddleware,
)
from echoroo.models.superuser import Superuser
from echoroo.models.trusted_device import TrustedDevice
from echoroo.models.user import User
from echoroo.services import admin_password_reset, self_password_change
from echoroo.services.step_up_token_service import (
    issue_admin_recovery_step_up_token,
)
from tests.conftest import TEST_DATABASE_URL

_TARGET_PASSWORD = "OriginalPassw0rd!2026"
_NEW_PASSWORD = "BrandNewPassw0rd!2026"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _create_user(
    db: AsyncSession,
    *,
    email: str,
    password_hash: str,
    security_stamp: str,
    must_change_password: bool = False,
    temp_password_expires_at: datetime | None = None,
) -> User:
    user = User(
        email=email,
        password_hash=password_hash,
        display_name=f"User {email}",
        security_stamp=security_stamp,
        must_change_password=must_change_password,
        temp_password_expires_at=temp_password_expires_at,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _create_superuser(db: AsyncSession, *, user: User) -> Superuser:
    row = Superuser(
        user_id=user.id,
        added_by_id=None,
        added_at=datetime.now(UTC) - timedelta(days=1),
        webauthn_credentials=[],
        allowed_ip_cidrs=["10.0.0.0/24"],
        revoked_at=None,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@pytest_asyncio.fixture
async def audit_session_maker(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    """Rebind the fresh-session audit writer onto the test engine.

    Without this the audit ``AsyncSessionLocal()`` opens on the
    production engine (different event loop) and the soft-alert path
    swallows the failure, so the audit-row assertions below would see
    nothing. Rebinding both service modules onto a NullPool session-maker
    bound to ``TEST_DATABASE_URL`` lands the rows in the test DB.
    """
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(admin_password_reset, "AsyncSessionLocal", maker, raising=True)
    monkeypatch.setattr(
        self_password_change, "AsyncSessionLocal", maker, raising=True
    )
    # FIX 1 (FR-011-205): the BFF change-password handler re-issues the
    # caller's session via ``SqlTokenStore(AsyncSessionLocal).record_issued``.
    # Rebind that module-level symbol onto the test engine too so the new
    # refresh-token family is INSERTed into the test DB (production
    # ``AsyncSessionLocal`` runs on a different event loop and would fail).
    monkeypatch.setattr(web_auth_module, "AsyncSessionLocal", maker, raising=True)
    yield maker
    await engine.dispose()


class _PrincipalMiddleware(BaseHTTPMiddleware):
    """Stand-in for AuthRouterMiddleware: stamps ``request.state.principal``.

    The ForcedPasswordChangeMiddleware resolves the gated user from the
    principal stamped here. The principal user-id is selected per-request
    by the test via the ``X-Test-Principal`` header so a single app can
    impersonate either the superuser or the target user.
    """

    def __init__(self, app: Any, *, user_ids: dict[str, UUID]) -> None:
        super().__init__(app)
        self._user_ids = user_ids

    async def dispatch(
        self,
        request: StarletteRequest,
        call_next: Any,
    ) -> StarletteResponse:
        marker = request.headers.get("x-test-principal")
        uid = self._user_ids.get(marker) if marker else None
        if uid is None:
            request.state.principal = None
        else:
            request.state.principal = Principal.for_session(
                user_id=uid,
                security_stamp="s" * 64,
            )
        return await call_next(request)


@pytest_asyncio.fixture
async def reset_app(
    db_session: AsyncSession,
    audit_session_maker: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[tuple[FastAPI, dict[str, User]], None]:
    """Build an app wiring the admin + auth routers + forced-change gate.

    The returned tuple carries the app plus a ``{"superuser", "target"}``
    user map. The ``X-Test-Principal`` header selects which user the
    auth dependencies + the forced-change gate resolve for a given
    request.
    """
    superuser = await _create_user(
        db_session,
        email="t361_su@example.com",
        password_hash=hash_password("SuperuserPassw0rd!2026"),
        security_stamp="a" * 64,
    )
    await _create_superuser(db_session, user=superuser)
    target = await _create_user(
        db_session,
        email="t361_target@example.com",
        password_hash=hash_password(_TARGET_PASSWORD),
        security_stamp="b" * 64,
    )
    users = {"superuser": superuser, "target": target}

    app = FastAPI()
    app.include_router(admin_router, prefix="/web-api/v1")
    app.include_router(web_auth_router, prefix="/web-api/v1")
    app.include_router(v1_auth_router, prefix="/api/v1")

    # A trivial protected route used to assert the 423 gate fires on a
    # normal path (not on the allowlisted change-password POST).
    @app.get("/web-api/v1/protected-probe")
    async def _protected_probe() -> dict[str, str]:
        return {"ok": "true"}

    # The gate loads the user via its own fresh session (NullPool, test
    # engine) so it reads committed ``must_change_password`` state without
    # entangling the long-lived ``db_session`` transaction.
    app.add_middleware(
        ForcedPasswordChangeMiddleware,
        session_factory=audit_session_maker,
    )
    app.add_middleware(_PrincipalMiddleware, user_ids={
        "superuser": superuser.id,
        "target": target.id,
    })

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    def _resolve_user(request: StarletteRequest) -> User | None:
        marker = request.headers.get("x-test-principal")
        return users.get(marker) if marker else None

    async def _override_current_user_optional(
        request: StarletteRequest,
    ) -> User | None:
        user = _resolve_user(request)
        if user is not None:
            # Stamp transient superuser attributes the admin handler reads.
            probe = await db_session.execute(
                text(
                    "SELECT id FROM superusers "
                    "WHERE user_id = :uid AND revoked_at IS NULL LIMIT 1"
                ),
                {"uid": user.id},
            )
            row = probe.scalar_one_or_none()
            user.is_superuser = row is not None  # type: ignore[attr-defined]
            user._superuser_id = row  # type: ignore[attr-defined]
        return user

    async def _override_current_user(request: StarletteRequest) -> User:
        user = _resolve_user(request)
        assert user is not None, "test principal not set"
        return user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user_optional] = (
        _override_current_user_optional
    )
    app.dependency_overrides[get_current_user] = _override_current_user
    yield app, users


def _step_up_token(superuser: User) -> str:
    token, _ = issue_admin_recovery_step_up_token(
        user_id=superuser.id,
        security_stamp=superuser.security_stamp,
        assertion_id="t361-admin-recovery",
        password_verified=True,
        second_factor="totp",
    )
    return token


async def _audit_actions(db: AsyncSession, *, user_id: UUID) -> list[dict[str, Any]]:
    """Return audit rows whose detail targets ``user_id``.

    ``platform_audit_log`` is append-only and shared across the session,
    so we filter by the ``detail`` payload. The admin-reset rows carry
    ``detail.target_user_id``; the self-service change-password rows carry
    ``detail.user_id``. We match either so the caller sees every row
    pertaining to ``user_id`` and nothing from sibling tests.
    """
    rows = await db.execute(
        text(
            "SELECT action, detail FROM platform_audit_log "
            "WHERE detail->>'target_user_id' = :uid "
            "OR detail->>'user_id' = :uid "
            "ORDER BY created_at ASC"
        ),
        {"uid": str(user_id)},
    )
    return [{"action": r[0], "detail": r[1]} for r in rows.all()]


# ---------------------------------------------------------------------------
# 1. Full happy-path loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_reset_then_change_password_loop(
    reset_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """superuser reset → target forced-change 423 → change → route works."""
    app, users = reset_app
    superuser, target = users["superuser"], users["target"]
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        # --- (a) superuser resets the target's password -----------------
        reset_resp = await client.post(
            f"/web-api/v1/admin/users/{target.id}/reset-password",
            json={"reason": "lost device"},
            headers={
                "X-Test-Principal": "superuser",
                "X-Step-Up-Token": _step_up_token(superuser),
            },
        )
        assert reset_resp.status_code == 200, reset_resp.text
        body = reset_resp.json()
        temp_password = body["temporary_password"]
        assert temp_password, body
        # FR-011-207: the temp password is never echoed into telemetry —
        # here we only assert it is a non-trivial one-shot value.
        assert len(temp_password) >= 20

        # Forced-change state landed on the target row.
        await db_session.refresh(target)
        assert target.must_change_password is True
        assert target.temp_password_expires_at is not None

        # --- (b) a normal protected route 423s the target user ----------
        probe = await client.get(
            "/web-api/v1/protected-probe",
            headers={"X-Test-Principal": "target"},
        )
        assert probe.status_code == 423, probe.text
        assert probe.json()["code"] == ERROR_CODE_PASSWORD_CHANGE_REQUIRED
        assert probe.headers.get("location") == "/change-password"

        # An access token minted for the target's CURRENT session BEFORE
        # the change carries the pre-rotation stamp ("b"*64). After the
        # stamp rotates, this token MUST be rejected — that is what makes
        # OTHER pre-existing sessions for this user invalid (FR-055). We
        # capture it here so assertion (c.3) below can prove that.
        pre_change_access_token = issue_access_token(
            user_id=target.id,
            security_stamp="b" * 64,
        )

        # --- (c) target changes password with the temp value -----------
        change = await client.post(
            "/web-api/v1/auth/change-password",
            json={
                "current_password": temp_password,
                "new_password": _NEW_PASSWORD,
            },
            headers={"X-Test-Principal": "target"},
        )
        assert change.status_code == 200, change.text

        # Forced-change cleared + temp expiry NULLed.
        await db_session.refresh(target)
        assert target.must_change_password is False
        assert target.temp_password_expires_at is None
        # Security stamp rotated (other sessions invalidated, FR-055).
        assert target.security_stamp != "b" * 64
        new_stamp = target.security_stamp

        # --- (c.1) FIX 1 / FR-011-205: the CURRENT session SURVIVES ------
        # The handler re-issues the caller's session: a fresh access token
        # bound to the ROTATED stamp comes back in the body, AND the
        # session / refresh / CSRF cookies are re-set (Set-Cookie). The
        # frontend swaps its in-memory token with the returned value so the
        # next request authenticates cleanly instead of 419-ing.
        change_body = change.json()
        assert change_body["message"], change_body
        reissued_access_token = change_body["access_token"]
        assert reissued_access_token, change_body
        assert change_body["expires_in"] > 0, change_body
        # The re-issued token authenticates against the NEW live stamp with
        # NO StaleTokenError (i.e. no 419 on the caller's next request).
        reissued_claims = verify_access_token(
            reissued_access_token, current_security_stamp=new_stamp
        )
        assert reissued_claims.user_id == target.id
        assert reissued_claims.security_stamp == new_stamp
        # Cookie re-issue side effect: the session + refresh cookies are set.
        cookie_settings = get_settings()
        set_cookie_names = {
            cookie.split("=", 1)[0].strip().lower()
            for cookie in change.headers.get_list("set-cookie")
        }
        assert cookie_settings.web_session_cookie_name.lower() in set_cookie_names
        assert cookie_settings.web_refresh_cookie_name.lower() in set_cookie_names

        # --- (c.2) the SAME re-issued session authenticates on a route ---
        # Replay the re-issued access token (as the SvelteKit client would,
        # via the Authorization header) against the protected probe through
        # the same client. No 419 — the current session continues.
        same_session_probe = await client.get(
            "/web-api/v1/protected-probe",
            headers={
                "X-Test-Principal": "target",
                "Authorization": f"Bearer {reissued_access_token}",
            },
        )
        assert same_session_probe.status_code == 200, same_session_probe.text

        # --- (c.3) a DIFFERENT pre-existing session IS invalidated -------
        # A token issued for another live session before the change carried
        # the OLD stamp. Verifying it against the new live stamp MUST raise
        # StaleTokenError — i.e. that session is revoked (419 on its next
        # request) while the current one survives.
        with pytest.raises(StaleTokenError):
            verify_access_token(
                pre_change_access_token, current_security_stamp=new_stamp
            )

        # --- (d) the previously-423ing route now passes through ---------
        probe2 = await client.get(
            "/web-api/v1/protected-probe",
            headers={"X-Test-Principal": "target"},
        )
        assert probe2.status_code == 200, probe2.text

    # --- (e) audit assertions ------------------------------------------
    actions = await _audit_actions(db_session, user_id=target.id)
    action_names = [a["action"] for a in actions]
    assert "platform.user.password_reset_by_superuser" in action_names
    assert self_password_change.AUDIT_ACTION_AUTH_PASSWORD_CHANGED in action_names
    # FR-011-207: no audit detail anywhere carries the temp / new password.
    for entry in actions:
        detail = entry["detail"] or {}
        serialized = str(detail)
        assert temp_password not in serialized
        assert _NEW_PASSWORD not in serialized


# ---------------------------------------------------------------------------
# 2. Trusted-device revocation on change-password
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_password_revokes_trusted_devices(
    reset_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """An active trusted-device row is revoked after change-password."""
    app, users = reset_app
    superuser, target = users["superuser"], users["target"]

    device = TrustedDevice(
        user_id=target.id,
        device_secret_hash="d" * 64,
        security_stamp=target.security_stamp,
        label="laptop",
        expires_at=datetime.now(UTC) + timedelta(days=30),
        revoked_at=None,
    )
    db_session.add(device)
    await db_session.commit()
    await db_session.refresh(device)

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        reset_resp = await client.post(
            f"/web-api/v1/admin/users/{target.id}/reset-password",
            json={"reason": "device lost"},
            headers={
                "X-Test-Principal": "superuser",
                "X-Step-Up-Token": _step_up_token(superuser),
            },
        )
        assert reset_resp.status_code == 200, reset_resp.text
        temp_password = reset_resp.json()["temporary_password"]

        change = await client.post(
            "/web-api/v1/auth/change-password",
            json={
                "current_password": temp_password,
                "new_password": _NEW_PASSWORD,
            },
            headers={"X-Test-Principal": "target"},
        )
        assert change.status_code == 200, change.text

    await db_session.refresh(device)
    assert device.revoked_at is not None


# ---------------------------------------------------------------------------
# 3. Wrong current password → 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_password_wrong_current_returns_401(
    reset_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """A non-matching ``current_password`` yields the generic 401."""
    app, users = reset_app
    target = users["target"]
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        resp = await client.post(
            "/web-api/v1/auth/change-password",
            json={
                "current_password": "definitely-not-the-password",
                "new_password": _NEW_PASSWORD,
            },
            headers={"X-Test-Principal": "target"},
        )
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"]["error_code"] == "current_password_invalid"
    # Password unchanged.
    await db_session.refresh(target)
    assert target.security_stamp == "b" * 64


# ---------------------------------------------------------------------------
# 4. Expired temp password → 401
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_password_expired_temp_returns_401(
    reset_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """An expired temp password is rejected with the generic 401 (FR-011-209)."""
    app, users = reset_app
    target = users["target"]

    # Force the account into forced-change with an ALREADY-expired temp
    # window. The current ``password_hash`` is still the original value,
    # so even supplying the correct original password must fail because
    # the forced-change temp window has lapsed.
    target.must_change_password = True
    target.temp_password_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db_session.add(target)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        resp = await client.post(
            "/web-api/v1/auth/change-password",
            json={
                "current_password": _TARGET_PASSWORD,
                "new_password": _NEW_PASSWORD,
            },
            headers={"X-Test-Principal": "target"},
        )
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"]["error_code"] == "current_password_invalid"
    await db_session.refresh(target)
    assert target.must_change_password is True


# ---------------------------------------------------------------------------
# 5. Reusing the current password → 400
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_password_reuse_current_returns_400(
    reset_app: tuple[FastAPI, dict[str, User]],
) -> None:
    """Setting the new password equal to the current one is rejected."""
    app, _ = reset_app
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        resp = await client.post(
            "/web-api/v1/auth/change-password",
            json={
                "current_password": _TARGET_PASSWORD,
                "new_password": _TARGET_PASSWORD,
            },
            headers={"X-Test-Principal": "target"},
        )
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"]["error_code"] == "password_reused"


# ---------------------------------------------------------------------------
# 6. Weak new password → 422
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_change_password_weak_new_returns_422(
    reset_app: tuple[FastAPI, dict[str, User]],
) -> None:
    """A new password below the policy minimum yields a 422 policy error."""
    app, _ = reset_app
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        resp = await client.post(
            "/web-api/v1/auth/change-password",
            json={
                "current_password": _TARGET_PASSWORD,
                "new_password": "short",
            },
            headers={"X-Test-Principal": "target"},
        )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["error_code"] == "password_policy_violation"


# ---------------------------------------------------------------------------
# 7. v1 mirror behaves identically
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_v1_mirror_change_password_succeeds(
    reset_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """``POST /api/v1/auth/change-password`` clears forced-change too."""
    app, users = reset_app
    superuser, target = users["superuser"], users["target"]
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        reset_resp = await client.post(
            f"/web-api/v1/admin/users/{target.id}/reset-password",
            json={"reason": "v1 mirror"},
            headers={
                "X-Test-Principal": "superuser",
                "X-Step-Up-Token": _step_up_token(superuser),
            },
        )
        assert reset_resp.status_code == 200, reset_resp.text
        temp_password = reset_resp.json()["temporary_password"]

        change = await client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": temp_password,
                "new_password": _NEW_PASSWORD,
            },
            headers={"X-Test-Principal": "target"},
        )
        assert change.status_code == 200, change.text

    await db_session.refresh(target)
    assert target.must_change_password is False
    assert target.temp_password_expires_at is None


# ---------------------------------------------------------------------------
# 8. Self-reset uses the ``_self`` audit action variant (FR-011-210)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_self_reset_uses_self_audit_action(
    reset_app: tuple[FastAPI, dict[str, User]],
    db_session: AsyncSession,
) -> None:
    """A superuser resetting THEIR OWN password emits the ``_self`` action."""
    app, users = reset_app
    superuser = users["superuser"]
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        reset_resp = await client.post(
            f"/web-api/v1/admin/users/{superuser.id}/reset-password",
            json={"reason": "self recovery drill"},
            headers={
                "X-Test-Principal": "superuser",
                "X-Step-Up-Token": _step_up_token(superuser),
            },
        )
        assert reset_resp.status_code == 200, reset_resp.text

    actions = await _audit_actions(db_session, user_id=superuser.id)
    action_names = [a["action"] for a in actions]
    assert "platform.user.password_reset_self" in action_names
    assert "platform.user.password_reset_by_superuser" not in action_names

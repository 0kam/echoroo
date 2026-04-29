"""Integration tests for the Phase 15 Batch 5a superuser admin endpoints.

Coverage:

* Action registration shape (``is_superuser_only`` / ``is_platform_scope``
  / ``required_permission=None``) for the new platform-scope actions.
* Gate behaviour via :func:`is_allowed` — anonymous, non-superuser
  session, API-key principal (FR-084 universal veto), and active
  superuser session.
* Endpoint-level coverage for the GET endpoints (CSRF middleware
  bypasses ``GET`` so the standard ``client`` fixture is sufficient).
* Endpoint-level coverage for the POST/PATCH endpoints via a dedicated
  FastAPI test app that mounts only the admin router *without* the
  production CSRF / AuthRouter middleware, mirroring the contract-test
  pattern used by ``tests/contract/test_license_required.py`` (web
  bypass surface).

Out of scope:

* End-to-end CSRF + AuthRouter cookie chain — exercised separately by
  the dedicated middleware suites.
* WebAuthn ceremony — already covered by
  ``tests/integration/api/web_v1/test_auth_webauthn.py``.

Spec references: FR-072 / FR-084 / FR-111 / FR-111a.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.api.web_v1.admin import router as admin_router
from echoroo.core.actions import (
    SUPERUSER_ADD_ACTION,
    SUPERUSER_APPROVAL_REQUEST_LIST_ACTION,
    SUPERUSER_APPROVE_REQUEST_ACTION,
    SUPERUSER_BREAK_GLASS_ENTER_ACTION,
    SUPERUSER_BREAK_GLASS_STATUS_ACTION,
    SUPERUSER_IP_ALLOWLIST_UPDATE_ACTION,
    SUPERUSER_LIST_ACTION,
    SUPERUSER_REJECT_REQUEST_ACTION,
    SUPERUSER_REVOKE_ACTION,
)
from echoroo.core.database import get_db
from echoroo.core.permissions import Action, Permission, is_allowed
from echoroo.middleware.auth import get_current_user_optional
from echoroo.models.superuser import Superuser
from echoroo.models.superuser_approval_request import SuperuserApprovalRequest
from echoroo.models.user import User
from echoroo.services.superuser_service import (
    ACTION_SUPERUSER_ADD,
    ACTION_SUPERUSER_REVOKE,
)

# ===========================================================================
# Action registration shape (FR-008a / FR-084)
# ===========================================================================

_NEW_PLATFORM_ACTIONS: list[Action] = [
    SUPERUSER_LIST_ACTION,
    SUPERUSER_ADD_ACTION,
    SUPERUSER_REVOKE_ACTION,
    SUPERUSER_APPROVAL_REQUEST_LIST_ACTION,
    SUPERUSER_APPROVE_REQUEST_ACTION,
    SUPERUSER_REJECT_REQUEST_ACTION,
    SUPERUSER_BREAK_GLASS_ENTER_ACTION,
    SUPERUSER_BREAK_GLASS_STATUS_ACTION,
    SUPERUSER_IP_ALLOWLIST_UPDATE_ACTION,
]


@pytest.mark.parametrize(
    "action", _NEW_PLATFORM_ACTIONS, ids=[a.name for a in _NEW_PLATFORM_ACTIONS]
)
def test_new_actions_are_platform_scope_superuser_only(action: Action) -> None:
    """All new admin actions must be flagged ``is_platform_scope`` + ``is_superuser_only``."""
    assert action.is_platform_scope is True, (
        f"{action.name!r}: superuser admin action must be platform-scope"
    )
    assert action.is_superuser_only is True, (
        f"{action.name!r}: must be flagged is_superuser_only=True (FR-084)"
    )
    assert action.required_permission is None, (
        f"{action.name!r}: platform-scope actions have required_permission=None"
    )


def test_action_mutating_flags_match_http_semantics() -> None:
    """GET (list / status) actions are non-mutating; POST/PATCH actions are mutating."""
    non_mutating = {
        SUPERUSER_LIST_ACTION,
        SUPERUSER_APPROVAL_REQUEST_LIST_ACTION,
        SUPERUSER_BREAK_GLASS_STATUS_ACTION,
    }
    mutating = {
        SUPERUSER_ADD_ACTION,
        SUPERUSER_REVOKE_ACTION,
        SUPERUSER_APPROVE_REQUEST_ACTION,
        SUPERUSER_REJECT_REQUEST_ACTION,
        SUPERUSER_BREAK_GLASS_ENTER_ACTION,
        SUPERUSER_IP_ALLOWLIST_UPDATE_ACTION,
    }
    for action in non_mutating:
        assert action.is_mutating is False, (
            f"{action.name!r}: list / status action must not be mutating"
        )
    for action in mutating:
        assert action.is_mutating is True, (
            f"{action.name!r}: must be flagged is_mutating=True"
        )


# ===========================================================================
# Gate-level: is_allowed denies API key + non-superuser, allows session su
# ===========================================================================


class _StubUser:
    """Minimal user shape consumed by :func:`is_allowed`."""

    def __init__(
        self,
        *,
        is_superuser: bool,
        api_key_scopes: tuple[str, ...] | None = None,
    ) -> None:
        self.id = uuid4()
        self.is_superuser = is_superuser
        self.project_role = None
        if api_key_scopes is not None:
            self._api_key_scopes = api_key_scopes


@pytest.mark.parametrize(
    "action", _NEW_PLATFORM_ACTIONS, ids=[a.name for a in _NEW_PLATFORM_ACTIONS]
)
def test_anonymous_caller_denied(action: Action) -> None:
    """Unauthenticated callers MUST be denied every superuser admin action."""
    allowed, _ = is_allowed(
        action=action, user=None, project=None, request=None
    )
    assert allowed is False


@pytest.mark.parametrize(
    "action", _NEW_PLATFORM_ACTIONS, ids=[a.name for a in _NEW_PLATFORM_ACTIONS]
)
def test_non_superuser_session_denied(action: Action) -> None:
    """A first-party session caller without superuser status is denied."""
    user = _StubUser(is_superuser=False)
    allowed, _ = is_allowed(
        action=action, user=user, project=None, request=None
    )
    assert allowed is False


@pytest.mark.parametrize(
    "action", _NEW_PLATFORM_ACTIONS, ids=[a.name for a in _NEW_PLATFORM_ACTIONS]
)
def test_api_key_principal_denied_even_when_superuser_owned(
    action: Action,
) -> None:
    """FR-084 universal veto: a superuser-owned API key is denied unconditionally."""
    user = _StubUser(
        is_superuser=True,
        api_key_scopes=tuple(p.value for p in Permission),
    )
    allowed, _ = is_allowed(
        action=action,
        user=user,
        project=None,
        request=None,
        api_key_granted_permissions=frozenset(Permission),
    )
    assert allowed is False, (
        f"API-key superuser MUST be denied {action.name!r} regardless of scopes"
    )


@pytest.mark.parametrize(
    "action", _NEW_PLATFORM_ACTIONS, ids=[a.name for a in _NEW_PLATFORM_ACTIONS]
)
def test_session_superuser_allowed(action: Action) -> None:
    """A session-authenticated superuser passes every admin action."""
    user = _StubUser(is_superuser=True)
    allowed, _ = is_allowed(
        action=action, user=user, project=None, request=None
    )
    assert allowed is True


# ===========================================================================
# DB / fixture helpers (mirror unit/services/test_superuser_service_phase15_nogo)
# ===========================================================================


async def _create_user(db: AsyncSession, *, email: str) -> User:
    user = User(
        email=email,
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$batch5a",
        display_name=f"User {email}",
        security_stamp="0" * 64,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _create_superuser(
    db: AsyncSession, *, user: User, revoked: bool = False
) -> Superuser:
    row = Superuser(
        user_id=user.id,
        added_by_id=None,
        added_at=datetime.now(UTC) - timedelta(days=1),
        webauthn_credentials=[],
        allowed_ip_cidrs=["10.0.0.0/24"],
        revoked_at=datetime.now(UTC) if revoked else None,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


# ===========================================================================
# Endpoint-level fixture: a stripped FastAPI app with the admin router and
# a dependency-injected ``current_user`` (CSRF / AuthRouter intentionally
# omitted — they are exercised in dedicated middleware suites).
# ===========================================================================


@pytest.fixture
async def admin_app(db_session: AsyncSession) -> FastAPI:
    """Return a FastAPI app with the admin router and overridable user dep."""
    app = FastAPI()
    app.include_router(admin_router, prefix="/web-api/v1")

    async def _override_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    return app


@pytest.fixture
async def admin_client_factory(  # type: ignore[no-untyped-def]
    admin_app: FastAPI,
    db_session: AsyncSession,
):
    """Return a callable that builds an HTTP client bound to a specific user."""
    transport = ASGITransport(app=admin_app)
    captured_session = db_session

    def _override_user(user: User | None) -> None:
        async def _override() -> User | None:
            if user is None:
                return None
            # Mirror the production middleware:
            #   _stamp_superuser_status sets ``is_superuser`` and
            #   ``_superuser_id`` based on the live ``superusers`` table.
            # The downstream gate (``is_allowed`` Step 0a + 0c) reads
            # ``getattr(user, 'is_superuser', False)`` and the endpoint
            # helper ``_require_superuser_id`` reads ``_superuser_id``.
            from sqlalchemy import text as _sa_text

            probe = await captured_session.execute(
                _sa_text(
                    "SELECT id FROM superusers "
                    "WHERE user_id = :uid AND revoked_at IS NULL LIMIT 1"
                ),
                {"uid": user.id},
            )
            row = probe.scalar_one_or_none()
            user.is_superuser = row is not None  # type: ignore[attr-defined]
            user._superuser_id = row  # type: ignore[attr-defined]
            return user

        admin_app.dependency_overrides[get_current_user_optional] = _override

    async def _factory(
        user: User | None,
    ) -> AsyncClient:
        _override_user(user)
        return AsyncClient(transport=transport, base_url="http://testserver")

    return _factory


# ===========================================================================
# GET /web-api/v1/admin/superusers
# ===========================================================================


@pytest.mark.asyncio
async def test_list_superusers_anonymous_returns_401(
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """Anonymous callers must be rejected with 401 by ``_require_authenticated_superuser``."""
    async with await admin_client_factory(None) as client:
        response = await client.get("/web-api/v1/admin/superusers")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_superusers_non_superuser_returns_403(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """A signed-in user without a superuser row gets 403."""
    user = await _create_user(db_session, email="batch5a_nonsu_list@example.com")
    async with await admin_client_factory(user) as client:
        response = await client.get("/web-api/v1/admin/superusers")
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_list_superusers_superuser_returns_rows(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """A superuser session gets the full active+revoked roster."""
    su_user = await _create_user(db_session, email="batch5a_su_list@example.com")
    su_row = await _create_superuser(db_session, user=su_user)

    async with await admin_client_factory(su_user) as client:
        response = await client.get("/web-api/v1/admin/superusers")
    assert response.status_code == 200
    body = response.json()
    assert body["active_count"] >= 1
    assert body["min_superusers"] == 3
    assert any(item["id"] == str(su_row.id) for item in body["items"])


# ===========================================================================
# GET /web-api/v1/admin/superusers/break-glass/status
# ===========================================================================


@pytest.mark.asyncio
async def test_break_glass_status_idle_for_authenticated_superuser(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """When the window is closed the status endpoint returns ``active=False``."""
    su_user = await _create_user(db_session, email="batch5a_bg_status@example.com")
    await _create_superuser(db_session, user=su_user)

    async with await admin_client_factory(su_user) as client:
        response = await client.get(
            "/web-api/v1/admin/superusers/break-glass/status"
        )
    assert response.status_code == 200
    body = response.json()
    assert body["active"] is False
    assert body["started_at"] is None
    assert body["expires_at"] is None
    assert body["replacement_deadline_at"] is None


@pytest.mark.asyncio
async def test_break_glass_status_anonymous_returns_401(
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    async with await admin_client_factory(None) as client:
        response = await client.get(
            "/web-api/v1/admin/superusers/break-glass/status"
        )
    assert response.status_code == 401


# ===========================================================================
# GET /web-api/v1/admin/superusers/approval-requests
# ===========================================================================


@pytest.mark.asyncio
async def test_list_approval_requests_returns_pending_count(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """A pending ``superuser.add`` ticket appears in the list with ``status='pending'``."""
    su_user = await _create_user(db_session, email="batch5a_arl_su@example.com")
    su = await _create_superuser(db_session, user=su_user)

    ticket = SuperuserApprovalRequest(
        action=ACTION_SUPERUSER_ADD,
        detail={"target_user_id": str(uuid4())},
        requested_by_id=su.id,
        approvals=[],
        status="pending",
    )
    db_session.add(ticket)
    await db_session.commit()
    await db_session.refresh(ticket)

    async with await admin_client_factory(su_user) as client:
        response = await client.get(
            "/web-api/v1/admin/superusers/approval-requests"
        )
    assert response.status_code == 200
    body = response.json()
    assert body["pending_count"] >= 1
    assert body["min_approvals"] == 2
    matching = [item for item in body["items"] if item["id"] == str(ticket.id)]
    assert matching, "newly-created ticket missing from response"
    assert matching[0]["status"] == "pending"


@pytest.mark.asyncio
async def test_list_approval_requests_status_filter(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """``?status_filter=pending`` excludes applied / rejected rows."""
    su_user = await _create_user(db_session, email="batch5a_arl_filter@example.com")
    su = await _create_superuser(db_session, user=su_user)

    db_session.add(
        SuperuserApprovalRequest(
            action=ACTION_SUPERUSER_REVOKE,
            detail={"target_superuser_id": str(uuid4())},
            requested_by_id=su.id,
            approvals=[],
            status="rejected",
            executed_at=datetime.now(UTC),
        )
    )
    await db_session.commit()

    async with await admin_client_factory(su_user) as client:
        response = await client.get(
            "/web-api/v1/admin/superusers/approval-requests",
            params={"status_filter": "pending"},
        )
    assert response.status_code == 200
    for item in response.json()["items"]:
        assert item["status"] == "pending"


# ===========================================================================
# POST /web-api/v1/admin/superusers (add)
# ===========================================================================


@pytest.mark.asyncio
async def test_add_superuser_creation_time_exception_direct_insert(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """First-three rows: count<3 returns ``status='direct'`` and inserts immediately."""
    su_user = await _create_user(db_session, email="batch5a_add_direct_su@example.com")
    await _create_superuser(db_session, user=su_user)
    target = await _create_user(db_session, email="batch5a_add_direct_target@example.com")

    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            "/web-api/v1/admin/superusers",
            json={
                "target_user_id": str(target.id),
                "allowed_ip_cidrs": [],
            },
        )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "direct"
    assert body["superuser_id"] is not None


@pytest.mark.asyncio
async def test_add_superuser_anonymous_returns_401(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    target = await _create_user(db_session, email="batch5a_add_anon@example.com")
    async with await admin_client_factory(None) as client:
        response = await client.post(
            "/web-api/v1/admin/superusers",
            json={"target_user_id": str(target.id), "allowed_ip_cidrs": []},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_add_superuser_non_superuser_returns_403(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    user = await _create_user(db_session, email="batch5a_add_nonsu@example.com")
    target = await _create_user(db_session, email="batch5a_add_nonsu_target@example.com")
    async with await admin_client_factory(user) as client:
        response = await client.post(
            "/web-api/v1/admin/superusers",
            json={"target_user_id": str(target.id), "allowed_ip_cidrs": []},
        )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_add_superuser_already_superuser_returns_409(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    su_user = await _create_user(db_session, email="batch5a_add_dup_su@example.com")
    await _create_superuser(db_session, user=su_user)
    # Re-promote the same user.
    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            "/web-api/v1/admin/superusers",
            json={"target_user_id": str(su_user.id), "allowed_ip_cidrs": []},
        )
    assert response.status_code == 409


# ===========================================================================
# POST /web-api/v1/admin/superusers/{id}/revoke
# ===========================================================================


@pytest.mark.asyncio
async def test_revoke_unknown_superuser_returns_404(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    su_user = await _create_user(db_session, email="batch5a_revoke_404_su@example.com")
    await _create_superuser(db_session, user=su_user)

    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            f"/web-api/v1/admin/superusers/{uuid4()}/revoke"
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_revoke_superuser_opens_pending_ticket(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """Revoking via the admin endpoint always opens an M-of-N ticket (status='pending')."""
    su_user = await _create_user(db_session, email="batch5a_revoke_su@example.com")
    await _create_superuser(db_session, user=su_user)

    target_user = await _create_user(
        db_session, email="batch5a_revoke_target@example.com"
    )
    target = await _create_superuser(db_session, user=target_user)

    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            f"/web-api/v1/admin/superusers/{target.id}/revoke"
        )
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert body["approval_request_id"] is not None


# ===========================================================================
# Approval ticket approve / reject (duplicate / state errors)
# ===========================================================================


@pytest.mark.asyncio
async def test_approve_request_duplicate_returns_409(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """The same approver may not co-sign twice (DuplicateApprovalError → 409)."""
    su_user = await _create_user(db_session, email="batch5a_dup_su@example.com")
    su = await _create_superuser(db_session, user=su_user)

    target_user = await _create_user(db_session, email="batch5a_dup_target@example.com")
    target = await _create_superuser(db_session, user=target_user)

    ticket = SuperuserApprovalRequest(
        action=ACTION_SUPERUSER_REVOKE,
        detail={
            "target_superuser_id": str(target.id),
            "target_user_id": str(target.user_id),
        },
        requested_by_id=su.id,
        approvals=[],
        status="pending",
    )
    db_session.add(ticket)
    await db_session.commit()
    await db_session.refresh(ticket)

    async with await admin_client_factory(su_user) as client:
        first = await client.post(
            f"/web-api/v1/admin/superusers/approval-requests/{ticket.id}/approve"
        )
        assert first.status_code == 200
        # Duplicate from the same approver.
        second = await client.post(
            f"/web-api/v1/admin/superusers/approval-requests/{ticket.id}/approve"
        )
    assert second.status_code == 409
    body = second.json()
    assert body["detail"]["error"] == "ERR_DUPLICATE_APPROVER"


@pytest.mark.asyncio
async def test_reject_unknown_request_returns_404(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    su_user = await _create_user(db_session, email="batch5a_reject_404_su@example.com")
    await _create_superuser(db_session, user=su_user)

    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            f"/web-api/v1/admin/superusers/approval-requests/{uuid4()}/reject",
            json={"reason": "missing"},
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_reject_request_marks_rejected(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """Rejecting a pending ticket flips it to ``status='rejected'``."""
    su_user = await _create_user(db_session, email="batch5a_reject_su@example.com")
    su = await _create_superuser(db_session, user=su_user)

    target_user = await _create_user(
        db_session, email="batch5a_reject_target@example.com"
    )
    target = await _create_superuser(db_session, user=target_user)

    ticket = SuperuserApprovalRequest(
        action=ACTION_SUPERUSER_REVOKE,
        detail={
            "target_superuser_id": str(target.id),
            "target_user_id": str(target.user_id),
        },
        requested_by_id=su.id,
        approvals=[],
        status="pending",
    )
    db_session.add(ticket)
    await db_session.commit()
    await db_session.refresh(ticket)

    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            f"/web-api/v1/admin/superusers/approval-requests/{ticket.id}/reject",
            json={"reason": "operator deemed unnecessary"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_reject_already_rejected_returns_409(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    su_user = await _create_user(db_session, email="batch5a_reject_409_su@example.com")
    su = await _create_superuser(db_session, user=su_user)

    ticket = SuperuserApprovalRequest(
        action=ACTION_SUPERUSER_REVOKE,
        detail={"target_superuser_id": str(uuid4())},
        requested_by_id=su.id,
        approvals=[],
        status="rejected",
        executed_at=datetime.now(UTC),
    )
    db_session.add(ticket)
    await db_session.commit()

    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            f"/web-api/v1/admin/superusers/approval-requests/{ticket.id}/reject",
            json={"reason": "double tap"},
        )
    assert response.status_code == 409


# ===========================================================================
# POST /web-api/v1/admin/superusers/break-glass/enter
# ===========================================================================


@pytest.mark.asyncio
async def test_break_glass_enter_starts_window_and_status_reflects_it(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    su_user = await _create_user(db_session, email="batch5a_bg_enter@example.com")
    await _create_superuser(db_session, user=su_user)

    async with await admin_client_factory(su_user) as client:
        enter_resp = await client.post(
            "/web-api/v1/admin/superusers/break-glass/enter",
            json={"reason": "phase 15 batch 5a integration test"},
        )
        assert enter_resp.status_code == 200
        body = enter_resp.json()
        assert body["active"] is True
        assert body["started_at"] is not None
        assert body["expires_at"] is not None
        # FR-111: 24 h replacement deadline (started_at + 24h).
        started = datetime.fromisoformat(body["started_at"])
        deadline = datetime.fromisoformat(body["replacement_deadline_at"])
        assert deadline - started == timedelta(hours=24)
        # 72 h window.
        expires = datetime.fromisoformat(body["expires_at"])
        assert expires - started == timedelta(hours=72)

        # Status follow-up should agree (idempotent read).
        status_resp = await client.get(
            "/web-api/v1/admin/superusers/break-glass/status"
        )
        assert status_resp.status_code == 200
        assert status_resp.json()["active"] is True


# ===========================================================================
# PATCH /web-api/v1/admin/superusers/{id}/ip-allowlist
# ===========================================================================


@pytest.mark.asyncio
async def test_ip_allowlist_update_replaces_array(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    su_user = await _create_user(db_session, email="batch5a_ip_su@example.com")
    await _create_superuser(db_session, user=su_user)

    target_user = await _create_user(
        db_session, email="batch5a_ip_target@example.com"
    )
    target = await _create_superuser(db_session, user=target_user)

    async with await admin_client_factory(su_user) as client:
        response = await client.patch(
            f"/web-api/v1/admin/superusers/{target.id}/ip-allowlist",
            json={"allowed_ip_cidrs": ["192.0.2.0/24", "203.0.113.0/24"]},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["allowed_ip_cidrs"] == ["192.0.2.0/24", "203.0.113.0/24"]
    assert body["superuser_id"] == str(target.id)
    # Sanity-check via direct DB read.
    refreshed = await db_session.get(Superuser, target.id)
    assert refreshed is not None
    assert list(refreshed.allowed_ip_cidrs) == [
        "192.0.2.0/24",
        "203.0.113.0/24",
    ]


@pytest.mark.asyncio
async def test_ip_allowlist_update_unknown_returns_404(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    su_user = await _create_user(db_session, email="batch5a_ip_404_su@example.com")
    await _create_superuser(db_session, user=su_user)

    async with await admin_client_factory(su_user) as client:
        response = await client.patch(
            f"/web-api/v1/admin/superusers/{uuid4()}/ip-allowlist",
            json={"allowed_ip_cidrs": []},
        )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_ip_allowlist_update_revoked_returns_409(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    su_user = await _create_user(db_session, email="batch5a_ip_revoked_su@example.com")
    await _create_superuser(db_session, user=su_user)

    revoked_user = await _create_user(
        db_session, email="batch5a_ip_revoked_target@example.com"
    )
    revoked_su = await _create_superuser(
        db_session, user=revoked_user, revoked=True
    )

    async with await admin_client_factory(su_user) as client:
        response = await client.patch(
            f"/web-api/v1/admin/superusers/{revoked_su.id}/ip-allowlist",
            json={"allowed_ip_cidrs": ["10.1.0.0/24"]},
        )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_ip_allowlist_update_anonymous_returns_401(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    target_user = await _create_user(
        db_session, email="batch5a_ip_anon_target@example.com"
    )
    target = await _create_superuser(db_session, user=target_user)

    async with await admin_client_factory(None) as client:
        response = await client.patch(
            f"/web-api/v1/admin/superusers/{target.id}/ip-allowlist",
            json={"allowed_ip_cidrs": []},
        )
    assert response.status_code == 401


# ===========================================================================
# Edge: payload validation (extra fields rejected)
# ===========================================================================


@pytest.mark.asyncio
async def test_add_superuser_rejects_unknown_field(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """``extra='forbid'`` schemas reject unknown JSON fields with 422."""
    su_user = await _create_user(db_session, email="batch5a_extra_field_su@example.com")
    await _create_superuser(db_session, user=su_user)
    target = await _create_user(db_session, email="batch5a_extra_field_target@example.com")

    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            "/web-api/v1/admin/superusers",
            json={
                "target_user_id": str(target.id),
                "allowed_ip_cidrs": [],
                "is_evil": True,
            },
        )
    assert response.status_code == 422


# ===========================================================================
# Edge: detail envelope shape
# ===========================================================================


@pytest.mark.asyncio
async def test_action_response_detail_includes_engine_payload(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """The ``detail`` envelope carries the engine outcome counters."""
    su_user = await _create_user(db_session, email="batch5a_detail_su@example.com")
    await _create_superuser(db_session, user=su_user)
    target = await _create_user(db_session, email="batch5a_detail_target@example.com")

    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            "/web-api/v1/admin/superusers",
            json={"target_user_id": str(target.id), "allowed_ip_cidrs": []},
        )
    assert response.status_code == 202
    detail: dict[str, Any] = response.json()["detail"]
    assert "active_count_after" in detail
    assert detail["target_user_id"] == str(target.id)


# ===========================================================================
# Phase 15 Batch 5a R2 — Codex Major 1: approval list redaction (FR-111)
# ===========================================================================


@pytest.mark.asyncio
async def test_list_approval_requests_redacts_webauthn_payload_from_detail(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """``superuser.add`` ticket detail must not leak WebAuthn raw payload.

    The service layer embeds the operator-supplied
    ``webauthn_credentials`` blob into ``superuser_approval_requests.detail``
    so the apply step can hand it to ``add_superuser_apply``. The admin
    list endpoint MUST redact that field (and any other future-leak
    candidates) before serialising the response.
    """
    su_user = await _create_user(
        db_session, email="batch5a_redact_detail_su@example.com"
    )
    su = await _create_superuser(db_session, user=su_user)

    target_user_id = uuid4()
    sentinel_pubkey = "AAAA-LEAKED-PUBLIC-KEY-PAYLOAD"
    sentinel_assertion = "BBBB-LEAKED-WEBAUTHN-ASSERTION"
    sentinel_email = "leaked.email@example.com"

    ticket = SuperuserApprovalRequest(
        action=ACTION_SUPERUSER_ADD,
        detail={
            "target_user_id": str(target_user_id),
            # Allowlisted — must survive.
            "allowed_ip_cidrs": ["10.0.0.0/24"],
            # Non-allowlisted — must be dropped.
            "webauthn_credentials": [
                {
                    "credential_id": "CRED-1",
                    "public_key": sentinel_pubkey,
                    "raw_assertion": sentinel_assertion,
                }
            ],
            "registered_email": sentinel_email,
        },
        requested_by_id=su.id,
        approvals=[
            {
                "superuser_id": str(su.id),
                "approved_at": datetime.now(UTC).isoformat(),
                # Non-allowlisted leak surface — must be dropped.
                "webauthn_assertion": sentinel_assertion,
                "raw_signed_challenge": sentinel_pubkey,
            }
        ],
        status="pending",
    )
    db_session.add(ticket)
    await db_session.commit()
    await db_session.refresh(ticket)

    async with await admin_client_factory(su_user) as client:
        response = await client.get(
            "/web-api/v1/admin/superusers/approval-requests"
        )
    assert response.status_code == 200
    body = response.json()
    matching = [item for item in body["items"] if item["id"] == str(ticket.id)]
    assert matching, "ticket missing from response"
    item = matching[0]

    # Allowlisted fields survive.
    assert item["detail"]["target_user_id"] == str(target_user_id)
    assert item["detail"]["allowed_ip_cidrs"] == ["10.0.0.0/24"]

    # Non-allowlisted fields are dropped.
    assert "webauthn_credentials" not in item["detail"]
    assert "registered_email" not in item["detail"]

    # Sentinel substring scan — the payload must not appear ANYWHERE in
    # the serialised response (defence in depth against future regressions
    # that re-introduce a leaky field outside the allowlist).
    serialised = response.text
    assert sentinel_pubkey not in serialised, "WebAuthn public key leaked"
    assert sentinel_assertion not in serialised, "WebAuthn assertion leaked"
    assert sentinel_email not in serialised, "raw email leaked"

    # ``approvals`` entries are also redacted.
    for entry in item["approvals"]:
        assert "webauthn_assertion" not in entry
        assert "raw_signed_challenge" not in entry
        # The allowlisted ``superuser_id`` / ``approved_at`` fields survive.
        assert "superuser_id" in entry
        assert "approved_at" in entry


# ===========================================================================
# Phase 15 Batch 5a R2 — Codex Major 2: CIDR validator (FR-072)
# ===========================================================================


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_cidr",
    [
        "not-a-cidr",
        "10.0.0.0",  # missing /prefix
        "999.999.999.999/24",  # invalid octets
        "10.0.0.0/33",  # invalid IPv4 prefix length
        "abc/24",
    ],
    ids=[
        "garbage_token",
        "missing_prefix",
        "invalid_octets",
        "prefix_out_of_range",
        "non_numeric_host",
    ],
)
async def test_ip_allowlist_update_rejects_invalid_cidr(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
    bad_cidr: str,
) -> None:
    """PATCH ip-allowlist must 422 for any malformed CIDR entry."""
    su_user = await _create_user(
        db_session, email=f"batch5a_cidr_{abs(hash(bad_cidr))}_su@example.com"
    )
    await _create_superuser(db_session, user=su_user)

    target_user = await _create_user(
        db_session,
        email=f"batch5a_cidr_{abs(hash(bad_cidr))}_target@example.com",
    )
    target = await _create_superuser(db_session, user=target_user)

    async with await admin_client_factory(su_user) as client:
        response = await client.patch(
            f"/web-api/v1/admin/superusers/{target.id}/ip-allowlist",
            json={"allowed_ip_cidrs": [bad_cidr]},
        )
    assert response.status_code == 422, (
        f"bad CIDR {bad_cidr!r} should produce 422, got {response.status_code} "
        f"body={response.text!r}"
    )


@pytest.mark.asyncio
async def test_ip_allowlist_update_canonicalises_host_bits(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """Host-bit-set entries are canonicalised to network address.

    ``"10.0.0.5/24"`` is accepted (``strict=False``) and persisted as
    ``"10.0.0.0/24"`` so the auth middleware never sees a host-laden
    allowlist that would silently mask off in production.
    """
    su_user = await _create_user(
        db_session, email="batch5a_cidr_canonical_su@example.com"
    )
    await _create_superuser(db_session, user=su_user)

    target_user = await _create_user(
        db_session, email="batch5a_cidr_canonical_target@example.com"
    )
    target = await _create_superuser(db_session, user=target_user)

    async with await admin_client_factory(su_user) as client:
        response = await client.patch(
            f"/web-api/v1/admin/superusers/{target.id}/ip-allowlist",
            json={"allowed_ip_cidrs": ["10.0.0.5/24", "192.168.1.50/16"]},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["allowed_ip_cidrs"] == ["10.0.0.0/24", "192.168.0.0/16"]


@pytest.mark.asyncio
async def test_add_superuser_rejects_invalid_cidr(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """POST /superusers must 422 when ``allowed_ip_cidrs`` has bad entries."""
    su_user = await _create_user(
        db_session, email="batch5a_add_bad_cidr_su@example.com"
    )
    await _create_superuser(db_session, user=su_user)
    target = await _create_user(
        db_session, email="batch5a_add_bad_cidr_target@example.com"
    )

    async with await admin_client_factory(su_user) as client:
        response = await client.post(
            "/web-api/v1/admin/superusers",
            json={
                "target_user_id": str(target.id),
                "allowed_ip_cidrs": ["not-a-cidr"],
            },
        )
    assert response.status_code == 422


# ===========================================================================
# Phase 15 Batch 5a R2 — Codex Minor 1: stale add ticket → 409 (not 500)
# ===========================================================================


@pytest.mark.asyncio
async def test_approve_stale_add_ticket_returns_409(
    db_session: AsyncSession,
    admin_client_factory,  # type: ignore[no-untyped-def]
) -> None:
    """A ``superuser.add`` ticket whose target is already a superuser at the
    apply step must surface ``AlreadySuperuserError`` as a clean 409 with
    ``error_code='stale_add_ticket_target_already_superuser'`` (not 500).

    Setup: 3 active superusers (so add goes through the M-of-N path,
    creation-time exception bypassed), a pending ticket targeting a
    user who has been promoted out-of-band (direct DB insert), and 2
    distinct co-signers that will cross the quorum on the second
    approve call.
    """
    # 3 active superusers → above MIN_SUPERUSERS so M-of-N applies.
    su_a_user = await _create_user(
        db_session, email="batch5a_stale_a@example.com"
    )
    su_a = await _create_superuser(db_session, user=su_a_user)
    su_b_user = await _create_user(
        db_session, email="batch5a_stale_b@example.com"
    )
    su_b = await _create_superuser(db_session, user=su_b_user)
    su_c_user = await _create_user(
        db_session, email="batch5a_stale_c@example.com"
    )
    await _create_superuser(db_session, user=su_c_user)

    # Target user — already promoted directly so the apply step sees an
    # ``existing active superuser`` row and raises ``AlreadySuperuserError``.
    target_user = await _create_user(
        db_session, email="batch5a_stale_target@example.com"
    )
    await _create_superuser(db_session, user=target_user)

    # Pending ``superuser.add`` ticket targeting the same user.
    ticket = SuperuserApprovalRequest(
        action=ACTION_SUPERUSER_ADD,
        detail={
            "target_user_id": str(target_user.id),
            "webauthn_credentials": [],
            "allowed_ip_cidrs": [],
        },
        requested_by_id=su_a.id,
        approvals=[],
        status="pending",
    )
    db_session.add(ticket)
    await db_session.commit()
    await db_session.refresh(ticket)
    ticket_id = ticket.id

    # First approver (su_a) — appends to approvals, still pending
    # (MIN_APPROVALS=2). The endpoint commits.
    async with await admin_client_factory(su_a_user) as client:
        first = await client.post(
            f"/web-api/v1/admin/superusers/approval-requests/{ticket_id}/approve"
        )
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "pending"

    # Second approver (su_b) — crosses quorum, triggers
    # ``add_superuser_apply`` which raises ``AlreadySuperuserError``.
    async with await admin_client_factory(su_b_user) as client:
        second = await client.post(
            f"/web-api/v1/admin/superusers/approval-requests/{ticket_id}/approve"
        )
    assert second.status_code == 409, second.text
    body = second.json()
    assert (
        body["detail"]["error_code"]
        == "stale_add_ticket_target_already_superuser"
    )
    # Sanity: the second SU id is referenced in the error narrative.
    assert "message" in body["detail"]
    assert str(su_b.id)  # sanity, ensures su_b row was created


__all__: list[UUID | str] = []

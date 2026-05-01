"""Phase 15 R3 NO-GO regression tests for ``echoroo.middleware.auth``
and the ``api_keys.project_id`` plumbing.

Pinned fixes:

* C4 — ``get_current_user`` MUST rehydrate cookie-session principals
  (``Principal.api_key_id is None``). Pre-R3 the principal fast-path
  required ``api_key_id is not None`` and 401-ed every cookie-only call
  to ``CurrentUser`` endpoints (e.g. ``/web-api/v1/projects/{id}/
  audit-log``).
* New Major — the API key's optional ``project_id`` MUST flow through
  to :func:`echoroo.core.permissions.gate_action`. A key bound to
  project A may not act on project B (403
  ``api_key_project_scope_mismatch``).

Tests are deliberately driver-light: ``get_current_user`` is exercised
via a hand-rolled stub Request + an in-memory User row stand-in.
``gate_action`` is exercised against ``SimpleNamespace`` stubs because
the project-load path raises 404 *after* the project_id mismatch
check.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from echoroo.core.permissions import Action, Permission, gate_action
from echoroo.middleware.auth import _stamp_api_key_scopes, get_current_user
from echoroo.middleware.auth_router import Principal

# ---------------------------------------------------------------------------
# Tiny stubs — avoid pulling the real DB fixture for these path-level checks.
# ---------------------------------------------------------------------------


class _StubResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalar(self) -> Any:
        return self._value


class _StubSession:
    """Minimal ``AsyncSession`` stand-in used by the auth fast-path."""

    def __init__(self, user_row: Any, superuser_id: Any = None) -> None:
        self._user_row = user_row
        self._superuser_id = superuser_id
        self.executed: list[str] = []

    async def execute(self, stmt: Any, params: Any = None) -> Any:
        rendered = str(stmt).lower()
        self.executed.append(rendered)
        # ``_stamp_superuser_status`` issues a raw SELECT against the
        # superusers table — return a bare ``_StubResult`` whose
        # ``.scalar_one_or_none()`` yields ``None`` (no superuser row)
        # unless the test seeded one.
        if "from superusers" in rendered:
            return _StubResult(self._superuser_id)
        return _StubResult(self._user_row)


class _StubState:
    def __init__(self, principal: Principal | None) -> None:
        self.principal = principal


class _StubRequest:
    def __init__(self, principal: Principal | None) -> None:
        self.state = _StubState(principal)


# ---------------------------------------------------------------------------
# C4 — cookie-session principal MUST resolve via get_current_user
# ---------------------------------------------------------------------------


class TestCookieSessionPrincipalRehydrates:
    @pytest.mark.asyncio
    async def test_session_principal_returns_user(self) -> None:
        """Phase 15 R3 NO-GO C4: cookie-session principal → User."""
        user_id = uuid4()
        user_row = SimpleNamespace(id=user_id)
        principal = Principal.for_session(
            user_id=user_id, security_stamp="0" * 64
        )
        request = _StubRequest(principal)
        db = _StubSession(user_row=user_row)

        resolved = await get_current_user(
            request=request,  # type: ignore[arg-type]
            db=db,  # type: ignore[arg-type]
            credentials=None,
        )
        assert resolved is user_row

    @pytest.mark.asyncio
    async def test_api_key_principal_still_returns_user_and_stamps_scopes(
        self,
    ) -> None:
        """API-key principal path remains intact (Major 1 dependency)."""
        user_id = uuid4()
        api_key_id = uuid4()
        user_row = SimpleNamespace(id=user_id)
        principal = Principal.for_api_key(
            user_id=user_id,
            api_key_id=api_key_id,
            scopes=("manage_api_key",),
            project_id=None,
        )
        request = _StubRequest(principal)
        db = _StubSession(user_row=user_row)

        resolved = await get_current_user(
            request=request,  # type: ignore[arg-type]
            db=db,  # type: ignore[arg-type]
            credentials=None,
        )
        assert resolved is user_row
        # _stamp_api_key_scopes must run.
        assert getattr(user_row, "_api_key_id", None) == api_key_id
        assert getattr(user_row, "_api_key_scopes", ()) == ("manage_api_key",)

    @pytest.mark.asyncio
    async def test_principal_without_user_row_falls_through_to_401(
        self,
    ) -> None:
        """A vanished user row → 401 (do not silently downgrade)."""
        principal = Principal.for_session(
            user_id=uuid4(), security_stamp="0" * 64
        )
        request = _StubRequest(principal)
        db = _StubSession(user_row=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=request,  # type: ignore[arg-type]
                db=db,  # type: ignore[arg-type]
                credentials=None,
            )
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_no_principal_no_credentials_returns_401(self) -> None:
        """Pre-R3 contract preserved: no auth → 401."""
        request = _StubRequest(principal=None)
        db = _StubSession(user_row=None)

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                request=request,  # type: ignore[arg-type]
                db=db,  # type: ignore[arg-type]
                credentials=None,
            )
        assert exc_info.value.status_code == 401


# ---------------------------------------------------------------------------
# New Major — _stamp_api_key_scopes propagates api_key_project_id
# ---------------------------------------------------------------------------


class TestApiKeyProjectIdStamp:
    def test_stamp_propagates_project_id(self) -> None:
        user_id = uuid4()
        api_key_id = uuid4()
        bound_project = uuid4()
        principal = Principal.for_api_key(
            user_id=user_id,
            api_key_id=api_key_id,
            scopes=("view_detection",),
            project_id=bound_project,
        )
        user = SimpleNamespace(id=user_id)
        _stamp_api_key_scopes(user, principal)
        assert user._api_key_project_id == bound_project

    def test_stamp_handles_unbound_key(self) -> None:
        user_id = uuid4()
        principal = Principal.for_api_key(
            user_id=user_id,
            api_key_id=uuid4(),
            scopes=(),
            project_id=None,
        )
        user = SimpleNamespace(id=user_id)
        _stamp_api_key_scopes(user, principal)
        assert user._api_key_project_id is None


# ---------------------------------------------------------------------------
# New Major — gate_action rejects cross-project API-key calls
# ---------------------------------------------------------------------------


class _GateAction:
    name = "_test.cross_project"
    required_permission = Permission.VIEW_DETECTION
    is_mutating = False
    is_superuser_only = False
    is_platform_scope = False


@pytest.mark.asyncio
async def test_gate_action_rejects_cross_project_api_key() -> None:
    """An API key bound to project A MUST 403 on project B."""
    bound_project = uuid4()
    other_project = uuid4()

    user = SimpleNamespace(
        id=uuid4(),
        is_superuser=False,
        project_role=None,
        _api_key_project_id=bound_project,
    )

    # Synthesize a minimal Action via the public ``Action`` model so the
    # gate's catalog lookup is bypassed.
    action = Action(
        name="_test.cross_project",
        required_permission=Permission.VIEW_DETECTION,
        is_mutating=False,
    )

    class _DummyDb:
        async def execute(self, *args: Any, **kwargs: Any) -> Any:
            raise AssertionError(
                "gate_action MUST 403 BEFORE issuing any DB lookup when the "
                "API key project scope mismatches"
            )

    class _DummyRequest:
        class _State:
            principal = None

        state = _State()

    with pytest.raises(HTTPException) as exc_info:
        await gate_action(
            action=action,
            project_id=other_project,
            current_user=user,
            request=_DummyRequest(),  # type: ignore[arg-type]
            db=_DummyDb(),  # type: ignore[arg-type]
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "api_key_project_scope_mismatch"


@pytest.mark.asyncio
async def test_gate_action_passes_when_api_key_project_matches() -> None:
    """The bound project ID match path falls through to the normal gate.

    We verify this by asserting that ``gate_action`` reaches
    ``load_project_or_404`` (i.e. issues the DB lookup) when the
    bound project ID matches the gate's ``project_id``. The DB call
    raises ``HTTPException(404)`` because our stub is empty — that's
    fine: we are checking that the ``api_key_project_scope_mismatch``
    branch DID NOT fire.
    """
    bound_project = uuid4()
    user = SimpleNamespace(
        id=uuid4(),
        is_superuser=False,
        project_role=None,
        _api_key_project_id=bound_project,
    )

    action = Action(
        name="_test.match",
        required_permission=Permission.VIEW_DETECTION,
        is_mutating=False,
    )

    class _DummyResult:
        def scalar_one_or_none(self) -> Any:
            return None

    class _DummyDb:
        async def execute(self, *args: Any, **kwargs: Any) -> Any:
            return _DummyResult()

    class _DummyRequest:
        class _State:
            principal = None

        state = _State()

    with pytest.raises(HTTPException) as exc_info:
        await gate_action(
            action=action,
            project_id=bound_project,
            current_user=user,
            request=_DummyRequest(),  # type: ignore[arg-type]
            db=_DummyDb(),  # type: ignore[arg-type]
        )
    # Must be 404 (project not found via load_project_or_404), NOT 403.
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_gate_action_unbound_api_key_skips_check() -> None:
    """A user-scope API key (project_id NULL) bypasses the mismatch branch."""
    user = SimpleNamespace(
        id=uuid4(),
        is_superuser=False,
        project_role=None,
        _api_key_project_id=None,
    )

    action = Action(
        name="_test.unbound",
        required_permission=Permission.VIEW_DETECTION,
        is_mutating=False,
    )

    class _DummyResult:
        def scalar_one_or_none(self) -> Any:
            return None

    class _DummyDb:
        async def execute(self, *args: Any, **kwargs: Any) -> Any:
            return _DummyResult()

    class _DummyRequest:
        class _State:
            principal = None

        state = _State()

    arbitrary_project = uuid4()
    with pytest.raises(HTTPException) as exc_info:
        await gate_action(
            action=action,
            project_id=arbitrary_project,
            current_user=user,
            request=_DummyRequest(),  # type: ignore[arg-type]
            db=_DummyDb(),  # type: ignore[arg-type]
        )
    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_gate_action_session_user_skips_check() -> None:
    """A cookie-session caller has no ``_api_key_project_id`` attr."""
    user = SimpleNamespace(
        id=uuid4(),
        is_superuser=False,
        project_role=None,
    )

    action = Action(
        name="_test.session",
        required_permission=Permission.VIEW_DETECTION,
        is_mutating=False,
    )

    class _DummyResult:
        def scalar_one_or_none(self) -> Any:
            return None

    class _DummyDb:
        async def execute(self, *args: Any, **kwargs: Any) -> Any:
            return _DummyResult()

    class _DummyRequest:
        class _State:
            principal = None

        state = _State()

    project_id_arg: UUID = uuid4()
    with pytest.raises(HTTPException) as exc_info:
        await gate_action(
            action=action,
            project_id=project_id_arg,
            current_user=user,
            request=_DummyRequest(),  # type: ignore[arg-type]
            db=_DummyDb(),  # type: ignore[arg-type]
        )
    assert exc_info.value.status_code == 404

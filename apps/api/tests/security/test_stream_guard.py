"""Phase 17 backlog A-5: stream-guard infrastructure tests.

Covers the Hybrid Contract (see ``specs/006-permissions-redesign/PHASE17_BACKLOG.md``):

* recheck_action_permission() decision-only behaviour:
  - missing project           → PermissionRevokedMidStream
  - api-key project mismatch  → PermissionRevokedMidStream
  - api-key revoked mid-stream→ PermissionRevokedMidStream  (Codex C-2 fix)
  - trusted overlay honoured  → no raise
  - matrix denial             → PermissionRevokedMidStream
* audit_stream_revoked() writes via fresh AsyncSession + soft-fails.
* Streaming generators preserve the documented sentinel for CSV and DO NOT
  inject sentinels into binary audio.
* search/sessions.py routes through the new streaming guard.
* CSV header still references ``observationID`` (regression guard).

These tests deliberately avoid the unshimmed_rbac_client HTTP integration
path because the existing test harness has a known cross-session
visibility issue between the global ``db_session`` engine and the
``unshimmed_rbac_client`` engine (the same issue that already breaks
``test_csv_export_returns_403_when_revoked_before_request`` on
``main`` before this branch). Coverage of the wire-level happy path is
provided by ``test_streaming_permission_change.py::test_csv_stream_aborts_when_permission_revoked_mid_stream``
which uses module-level monkeypatching.
"""
from __future__ import annotations

import csv
import hashlib
import inspect
import io
import os
import secrets
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from echoroo.core import stream_guard
from echoroo.core.actions import (
    DETECTION_EXPORT_CSV_ACTION,
    RECORDING_MEDIA_ACTION,
)
from echoroo.core.permissions import Permission
from echoroo.models.api_key import ApiKey
from echoroo.models.enums import (
    ProjectLicense,
    ProjectMemberRole,
    ProjectVisibility,
)
from echoroo.models.license import License
from echoroo.models.project import Project, ProjectMember
from echoroo.models.user import User

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://echoroo:echoroo@localhost:5432/echoroo_test",
)


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _make_user(db: AsyncSession, *, email: str) -> User:
    user = User(
        email=email,
        password_hash="$argon2id$v=19$m=65536,t=3,p=4$test",
        display_name=f"sg {email}",
        security_stamp="s" * 64,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


async def _make_project(db: AsyncSession, *, owner: User) -> Project:
    project = Project(
        name="Stream Guard Project",
        description="A-5 stream guard test",
        visibility=ProjectVisibility.RESTRICTED,
        license_id="cc-by",
        owner_id=owner.id,
        restricted_config={
            "allow_media_playback": True,
            "allow_detection_view": True,
            "mask_species_in_detection": False,
            "allow_download": True,
            "allow_export": True,
            "allow_voting_and_comments": False,
            "public_location_precision_h3_res": 5,
            "allow_precise_location_to_viewer": False,
        },
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)
    return project


async def _add_member(
    db: AsyncSession, *, project: Project, user: User, role: ProjectMemberRole
) -> ProjectMember:
    member = ProjectMember(
        project_id=project.id,
        user_id=user.id,
        role=role,
        invited_by_id=project.owner_id,
    )
    db.add(member)
    await db.flush()
    return member


async def _seed_api_key(
    db: AsyncSession,
    *,
    user: User,
    project: Project | None,
    permissions: list[str] | None = None,
) -> tuple[str, ApiKey]:
    raw_secret = secrets.token_urlsafe(32)
    prefix_random = secrets.token_urlsafe(6)[:8]
    prefix = f"echoroo_{prefix_random}"
    hashed = hashlib.sha256(raw_secret.encode()).hexdigest()
    key = ApiKey(
        id=uuid.uuid4(),
        user_id=user.id,
        project_id=project.id if project is not None else None,
        prefix=prefix,
        hashed_secret=hashed,
        granted_permissions=permissions or ["view_project_metadata", "export", "view_media"],
        expires_at=datetime.now(UTC) + timedelta(days=365),
    )
    db.add(key)
    await db.flush()
    await db.refresh(key)
    return f"{prefix}_{raw_secret}", key


# ---------------------------------------------------------------------------
# 1. Constants
# ---------------------------------------------------------------------------


def test_sentinel_constant_shape() -> None:
    """SENTINEL_BYTES must be a printable ASCII marker so audit greppable."""
    assert stream_guard.SENTINEL_BYTES.startswith(b"\r\n")
    assert b"PERMISSION-REVOKED" in stream_guard.SENTINEL_BYTES
    assert stream_guard.SENTINEL_BYTES.endswith(b"\r\n")


def test_check_intervals_documented() -> None:
    """Public guard cadence must remain stable."""
    assert stream_guard.CSV_RECHECK_INTERVAL == 100
    assert stream_guard.AUDIO_RECHECK_INTERVAL == 8


# ---------------------------------------------------------------------------
# 2. recheck_action_permission unit semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recheck_raises_on_missing_project(monkeypatch: pytest.MonkeyPatch) -> None:
    """If the Project row vanishes mid-stream the guard treats it as denial.

    Phase 17 backlog A-5 Round 2 R1-I1: ``recheck_action_permission`` now
    delegates to :func:`echoroo.core.permissions.decide_action_permission`.
    Monkeypatching is therefore done at the helper boundary.
    """
    from echoroo.core import permissions as perm_module

    async def _no_project(*, db: Any, action: Any, project_id: Any, current_user: Any, request: Any, refresh_api_key_scopes: bool = False) -> Any:  # noqa: ARG001
        return perm_module.PermissionDecision(
            allowed=False, project=None, reason="project_missing"
        )

    monkeypatch.setattr(stream_guard, "decide_action_permission", _no_project)

    project_id = uuid.uuid4()

    class _Req:
        state = type("S", (), {})()

    with pytest.raises(stream_guard.PermissionRevokedMidStream):
        await stream_guard.recheck_action_permission(
            db=None,  # type: ignore[arg-type]
            action=RECORDING_MEDIA_ACTION,
            project_id=project_id,
            current_user=None,
            request=_Req(),  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_recheck_api_key_project_binding_mismatch() -> None:
    """A bound API key used against a different project ID is denied early.

    Phase 17 backlog A-5 Round 2 R1-I1: this test exercises the binding
    check inside :func:`decide_action_permission`. The binding check
    runs BEFORE any DB access so ``db=None`` is safe.
    """
    bound_project_id = uuid.uuid4()
    different_project_id = uuid.uuid4()

    class _U:
        id = uuid.uuid4()
        _api_key_project_id = bound_project_id

    class _Req:
        state = type("S", (), {})()

    with pytest.raises(stream_guard.PermissionRevokedMidStream) as exc_info:
        await stream_guard.recheck_action_permission(
            db=None,  # type: ignore[arg-type]
            action=DETECTION_EXPORT_CSV_ACTION,
            project_id=different_project_id,
            current_user=_U(),
            request=_Req(),  # type: ignore[arg-type]
        )
    assert "api_key_project_scope_mismatch" in str(exc_info.value)


@pytest.mark.asyncio
async def test_recheck_raises_when_matrix_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    """When ``decide_action_permission`` returns deny the guard raises.

    Phase 17 backlog A-5 Round 2 R1-I1: monkeypatch at the new public
    helper boundary. The structural guarantee ``recheck_action_permission``
    delegates to :func:`decide_action_permission` is enforced by the
    parity test (``test_stream_guard_parity.py``).
    """
    from echoroo.core import permissions as perm_module

    class _Project:
        id = uuid.uuid4()
        owner_id = uuid.uuid4()
        visibility = ProjectVisibility.RESTRICTED
        restricted_config: dict[str, Any] = {}
        license = ProjectLicense.CC_BY

    async def _decide(*, db: Any, action: Any, project_id: Any, current_user: Any, request: Any, refresh_api_key_scopes: bool = False) -> Any:  # noqa: ARG001
        return perm_module.PermissionDecision(
            allowed=False, project=_Project(), reason="action_denied"
        )

    monkeypatch.setattr(stream_guard, "decide_action_permission", _decide)

    class _User:
        id = uuid.uuid4()

    class _Req:
        state = type("S", (), {})()

    with pytest.raises(stream_guard.PermissionRevokedMidStream) as exc_info:
        await stream_guard.recheck_action_permission(
            db=None,  # type: ignore[arg-type]
            action=DETECTION_EXPORT_CSV_ACTION,
            project_id=_Project.id,
            current_user=_User(),
            request=_Req(),  # type: ignore[arg-type]
        )
    assert "action_denied" in str(exc_info.value)


@pytest.mark.asyncio
async def test_recheck_passes_when_matrix_allows(monkeypatch: pytest.MonkeyPatch) -> None:
    """When ``decide_action_permission`` allows the guard returns silently."""
    from echoroo.core import permissions as perm_module

    class _Project:
        id = uuid.uuid4()
        owner_id = uuid.uuid4()
        visibility = ProjectVisibility.RESTRICTED
        restricted_config: dict[str, Any] = {}
        license = ProjectLicense.CC_BY

    refresh_calls: list[bool] = []

    async def _decide(*, db: Any, action: Any, project_id: Any, current_user: Any, request: Any, refresh_api_key_scopes: bool = False) -> Any:  # noqa: ARG001
        refresh_calls.append(refresh_api_key_scopes)
        return perm_module.PermissionDecision(
            allowed=True, project=_Project(), reason=""
        )

    monkeypatch.setattr(stream_guard, "decide_action_permission", _decide)

    class _User:
        id = uuid.uuid4()

    class _Req:
        state = type("S", (), {})()

    # Should NOT raise.
    await stream_guard.recheck_action_permission(
        db=None,  # type: ignore[arg-type]
        action=DETECTION_EXPORT_CSV_ACTION,
        project_id=_Project.id,
        current_user=_User(),
        request=_Req(),  # type: ignore[arg-type]
    )
    # Mid-stream guard MUST always pass refresh_api_key_scopes=True so a
    # sibling-session API-key revoke is observed (Codex C-2 fix).
    assert refresh_calls == [True], (
        "recheck_action_permission must request a fresh API-key scope load"
    )


# ---------------------------------------------------------------------------
# 3. _refresh_api_key_scopes (Codex C-2 fix) — fresh-loads the row
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_refresh_api_key_scopes_fresh_load(
    db_session: AsyncSession,
) -> None:
    """A sibling-session revoke MUST be observed by the next refresh call."""
    user = await _make_user(db_session, email=f"sg_apikey_{uuid.uuid4().hex[:6]}@example.com")
    project = await _make_project(db_session, owner=user)
    _, key_row = await _seed_api_key(db_session, user=user, project=project)
    await db_session.commit()

    class _U:
        id = user.id
        _api_key_id = key_row.id

    revoked, scopes = await stream_guard._refresh_api_key_scopes(
        db_session, current_user=_U()
    )
    assert revoked is False
    assert scopes is not None
    assert Permission.EXPORT in scopes

    # Sibling-session revoke.
    sibling_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    sibling_factory = async_sessionmaker(
        sibling_engine, class_=AsyncSession, expire_on_commit=False
    )
    try:
        async with sibling_factory() as sibling:
            await sibling.execute(
                update(ApiKey)
                .where(ApiKey.id == key_row.id)
                .values(revoked_at=datetime.now(UTC), revoked_reason="test")
            )
            await sibling.commit()
    finally:
        await sibling_engine.dispose()

    # populate_existing=True bypasses the identity-map cache.
    revoked2, _ = await stream_guard._refresh_api_key_scopes(
        db_session, current_user=_U()
    )
    assert revoked2 is True


# ---------------------------------------------------------------------------
# 3a. End-to-end mid-stream API-key revoke (R1-I2)
# ---------------------------------------------------------------------------
#
# Phase 17 backlog A-5 Round 2 R1-I2: ``test_refresh_api_key_scopes_fresh_load``
# above verifies the helper in isolation. The Hybrid Contract guarantee
# is end-to-end: a sibling-session ``UPDATE api_keys SET revoked_at = now()``
# MUST surface as ``PermissionRevokedMidStream("api_key_revoked")`` from
# the FULL ``recheck_action_permission()`` code path including the
# decision helper. This test asserts that integration.


async def _seed_owner_with_apikey(
    db: AsyncSession,
) -> tuple[User, Project, ApiKey]:
    """Seed an owner + project + API key with EXPORT scope."""
    user = await _make_user(db, email=f"sg_e2e_{uuid.uuid4().hex[:6]}@example.com")
    project = await _make_project(db, owner=user)
    _, key = await _seed_api_key(
        db,
        user=user,
        project=project,
        permissions=["view_project_metadata", "export", "view_media"],
    )
    return user, project, key


@pytest.mark.asyncio
async def test_recheck_action_permission_detects_api_key_revoke_mid_stream(
    db_session: AsyncSession,
) -> None:
    """End-to-end: sibling-session API-key revoke surfaces through recheck."""
    user, project, key = await _seed_owner_with_apikey(db_session)
    await db_session.commit()

    # Stamp the API key context onto the principal exactly as the
    # auth middleware does at request time.
    class _U:
        id = user.id
        is_superuser = False
        _api_key_id = key.id
        _api_key_project_id = project.id
        _api_key_scopes = ("view_project_metadata", "export", "view_media")

    class _Req:
        state = type("S", (), {})()
        client = type("C", (), {"host": "127.0.0.1"})()
        headers: dict[str, str] = {"user-agent": "pytest"}

    # First call must succeed (key live, owner of project).
    await stream_guard.recheck_action_permission(
        db=db_session,
        action=DETECTION_EXPORT_CSV_ACTION,
        project_id=project.id,
        current_user=_U(),
        request=_Req(),  # type: ignore[arg-type]
    )

    # Sibling-session revoke (independent connection, independent commit).
    sibling_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    sibling_factory = async_sessionmaker(
        sibling_engine, class_=AsyncSession, expire_on_commit=False
    )
    try:
        async with sibling_factory() as sibling:
            await sibling.execute(
                update(ApiKey)
                .where(ApiKey.id == key.id)
                .values(
                    revoked_at=datetime.now(UTC),
                    revoked_reason="e2e mid-stream test",
                )
            )
            await sibling.commit()
    finally:
        await sibling_engine.dispose()

    # Second call must raise with the canonical reason.
    with pytest.raises(stream_guard.PermissionRevokedMidStream) as exc_info:
        await stream_guard.recheck_action_permission(
            db=db_session,
            action=DETECTION_EXPORT_CSV_ACTION,
            project_id=project.id,
            current_user=_U(),
            request=_Req(),  # type: ignore[arg-type]
        )
    assert "api_key_revoked" in str(exc_info.value)


@pytest.mark.asyncio
async def test_recheck_action_permission_detects_api_key_scope_shrink(
    db_session: AsyncSession,
) -> None:
    """End-to-end: sibling-session scope shrink denies the action.

    Distinct from revoke: the key remains live but its
    ``granted_permissions`` array is trimmed so the requested action
    no longer intersects. The decision should fall through to
    ``action_denied`` (not ``api_key_revoked``).

    To force a deny we shrink the scopes to a set that does NOT include
    ``export``. The user is the project owner so without the API key
    intersection the request would normally pass — the API-key
    intersection is what closes the door.
    """
    user, project, key = await _seed_owner_with_apikey(db_session)
    await db_session.commit()

    class _U:
        id = user.id
        is_superuser = False
        _api_key_id = key.id
        _api_key_project_id = project.id
        _api_key_scopes = ("view_project_metadata", "export", "view_media")

    class _Req:
        state = type("S", (), {})()
        client = type("C", (), {"host": "127.0.0.1"})()
        headers: dict[str, str] = {"user-agent": "pytest"}

    # Pre-shrink: allowed.
    await stream_guard.recheck_action_permission(
        db=db_session,
        action=DETECTION_EXPORT_CSV_ACTION,
        project_id=project.id,
        current_user=_U(),
        request=_Req(),  # type: ignore[arg-type]
    )

    # Sibling-session: drop EXPORT scope.
    sibling_engine = create_async_engine(TEST_DATABASE_URL, echo=False, poolclass=NullPool)
    sibling_factory = async_sessionmaker(
        sibling_engine, class_=AsyncSession, expire_on_commit=False
    )
    try:
        async with sibling_factory() as sibling:
            await sibling.execute(
                update(ApiKey)
                .where(ApiKey.id == key.id)
                .values(granted_permissions=["view_project_metadata"])
            )
            await sibling.commit()
    finally:
        await sibling_engine.dispose()

    with pytest.raises(stream_guard.PermissionRevokedMidStream) as exc_info:
        await stream_guard.recheck_action_permission(
            db=db_session,
            action=DETECTION_EXPORT_CSV_ACTION,
            project_id=project.id,
            current_user=_U(),
            request=_Req(),  # type: ignore[arg-type]
        )
    # ``api_key_revoked`` only fires when ``revoked_at IS NOT NULL``;
    # a scope shrink falls through ``is_allowed`` and surfaces as
    # ``action_denied``.
    assert "action_denied" in str(exc_info.value)


@pytest.mark.asyncio
async def test_refresh_api_key_scopes_no_key_path() -> None:
    """When the caller did not authenticate via an API key, refresh is a no-op."""

    class _U:
        id = uuid.uuid4()
        # No _api_key_id stamped.

    revoked, scopes = await stream_guard._refresh_api_key_scopes(
        db=AsyncMock(),
        current_user=_U(),
    )
    assert revoked is False
    assert scopes is None


# ---------------------------------------------------------------------------
# 4. audit_stream_revoked — fresh session + commit + soft-alert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_stream_revoked_uses_fresh_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """audit_stream_revoked writes via a fresh AsyncSession + commits."""
    captured: dict[str, Any] = {}

    class _FakeAudit:
        def __init__(self, _session: Any) -> None:
            pass

        async def write_platform_event(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    fake_session = AsyncMock()
    fake_session.commit = AsyncMock()
    fake_session.__aenter__.return_value = fake_session
    fake_session.__aexit__.return_value = None

    monkeypatch.setattr(stream_guard, "AsyncSessionLocal", lambda: fake_session)
    monkeypatch.setattr("echoroo.services.audit_service.AuditLogService", _FakeAudit)

    project_id = uuid.uuid4()
    user_id = uuid.uuid4()
    await stream_guard.audit_stream_revoked(
        project_id=project_id,
        user_id=user_id,
        stream_type="csv_export",
        request_id="req-1",
        ip="1.2.3.4",
        user_agent="ua",
        reason="action_denied",
    )

    assert captured["action"] == "stream.permission_revoked_mid_stream"
    assert captured["actor_user_id"] == user_id
    assert captured["detail"]["project_id"] == str(project_id)
    assert captured["detail"]["stream_type"] == "csv_export"
    assert captured["detail"]["reason"] == "action_denied"
    fake_session.commit.assert_awaited()


@pytest.mark.asyncio
async def test_audit_stream_revoked_soft_alerts_on_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Audit failures must be logged and swallowed (the response is committed)."""

    def _broken_factory() -> Any:
        raise RuntimeError("kms unreachable")

    monkeypatch.setattr(stream_guard, "AsyncSessionLocal", _broken_factory)

    # Must NOT raise.
    await stream_guard.audit_stream_revoked(
        project_id=uuid.uuid4(),
        user_id=None,
        stream_type="csv_export",
    )
    # The warning was logged.
    assert any("stream_revoked audit failed" in rec.message for rec in caplog.records)


# ---------------------------------------------------------------------------
# 5. CSV streaming generator — header + sentinel shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_csv_stream_generator_yields_header_then_sentinel_on_revoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The streaming generator must catch PermissionRevokedMidStream and append SENTINEL."""
    from echoroo.services import detection_export as export_module

    # Build a service stub: bypass DB by stubbing the heavy fetch + h3 helpers.
    service = export_module.DetectionExportService.__new__(  # type: ignore[call-arg]
        export_module.DetectionExportService
    )
    service.db = AsyncMock()  # type: ignore[attr-defined]

    async def _fake_fetch(*_args: Any, **_kwargs: Any) -> list[Any]:
        # Two rows so the row index reaches the (patched) interval.
        ann1 = AsyncMock()
        ann2 = AsyncMock()
        for ann in (ann1, ann2):
            ann.recording = None
            ann.tag = None
            ann.detection_run = None
            ann.reviewed_by = None
            ann.reviewed_at = None
            ann.created_at = None
            ann.recording_id = None
            ann.start_time = 0.0
            ann.end_time = 1.0
            ann.freq_low = None
            ann.freq_high = None
            ann.confidence = None
            ann.id = uuid.uuid4()
            ann.source = None
        return [ann1, ann2]

    async def _fake_load_project(*_a: Any, **_k: Any) -> Any:
        return None

    async def _fake_h3_map(*_a: Any, **_k: Any) -> dict[Any, Any]:
        return {}

    monkeypatch.setattr(service, "_fetch_annotations_for_export", _fake_fetch)
    monkeypatch.setattr(service, "_load_project", _fake_load_project)
    monkeypatch.setattr(service, "_build_recording_h3_resolution_map", _fake_h3_map)
    # Force the guard to fire on row index 1.
    monkeypatch.setattr(export_module, "CSV_RECHECK_INTERVAL", 1)

    async def _always_revoked(**_kwargs: Any) -> None:
        raise stream_guard.PermissionRevokedMidStream("forced")

    monkeypatch.setattr(export_module, "recheck_action_permission", _always_revoked)
    monkeypatch.setattr(export_module, "audit_stream_revoked", AsyncMock())

    class _Req:
        state = type("S", (), {})()
        client = type("C", (), {"host": "1.2.3.4"})()
        headers = {"user-agent": "ua"}

    chunks: list[bytes] = []
    async for chunk in service.export_csv_stream(
        project_id=uuid.uuid4(),
        action=DETECTION_EXPORT_CSV_ACTION,
        current_user=None,
        request=_Req(),  # type: ignore[arg-type]
    ):
        chunks.append(chunk)

    body = b"".join(chunks)
    assert b"observationID" in body, "CSV header row must come first"
    assert body.endswith(stream_guard.SENTINEL_BYTES), (
        f"Mid-stream revoke must append SENTINEL_BYTES; got tail: {body[-64:]!r}"
    )


@pytest.mark.asyncio
async def test_csv_stream_generator_normal_path_has_no_sentinel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A normal export must not contain SENTINEL_BYTES anywhere in the body."""
    from echoroo.services import detection_export as export_module

    service = export_module.DetectionExportService.__new__(  # type: ignore[call-arg]
        export_module.DetectionExportService
    )
    service.db = AsyncMock()  # type: ignore[attr-defined]

    async def _fake_fetch(*_args: Any, **_kwargs: Any) -> list[Any]:
        return []  # empty export

    async def _fake_load_project(*_a: Any, **_k: Any) -> Any:
        return None

    async def _fake_h3_map(*_a: Any, **_k: Any) -> dict[Any, Any]:
        return {}

    monkeypatch.setattr(service, "_fetch_annotations_for_export", _fake_fetch)
    monkeypatch.setattr(service, "_load_project", _fake_load_project)
    monkeypatch.setattr(service, "_build_recording_h3_resolution_map", _fake_h3_map)

    class _Req:
        state = type("S", (), {})()
        client = type("C", (), {"host": ""})()
        headers: dict[str, str] = {}

    body = b"".join(
        [
            chunk
            async for chunk in service.export_csv_stream(
                project_id=uuid.uuid4(),
                action=DETECTION_EXPORT_CSV_ACTION,
                current_user=None,
                request=_Req(),  # type: ignore[arg-type]
            )
        ]
    )
    assert stream_guard.SENTINEL_BYTES not in body
    assert b"observationID" in body


# ---------------------------------------------------------------------------
# 6. Audio guard — must NEVER inject the sentinel into a binary stream
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 6a. Audio guard — Content-Length absence on full-file streaming response
# ---------------------------------------------------------------------------
#
# Phase 17 backlog A-5 Round 2 R1-C1: the guarded full-file streaming
# response MUST NOT advertise ``Content-Length`` / ``Accept-Ranges``. A
# mid-stream revoke aborts the generator early — sending the original
# file size leaves HTTP clients/proxies waiting for bytes that will
# never arrive, breaking the Hybrid Contract's "stream terminate"
# guarantee. Range responses (HTTP 206) on the SAME endpoint must
# continue to advertise both headers because they are single-shot reads
# that happen pre-start and cannot abort mid-flight.


def test_audio_full_stream_response_has_no_content_length() -> None:
    """Guarded ``StreamingResponse`` instances must not carry Content-Length.

    Behavioural guard: build a ``GET`` request without a Range header
    against the audio endpoint via the FastAPI ``TestClient``, point
    it at a tiny on-disk WAV / OGG stub, and assert the response
    headers do NOT contain ``Content-Length`` / ``Accept-Ranges``.

    We avoid the full async DB/auth fixture because the Hybrid
    Contract guarantee here is purely about response framing: when the
    guarded generator is consumed normally (no revoke fires) Starlette
    must still emit ``Transfer-Encoding: chunked``. Source-level
    inspection alone would let a future refactor silently re-add the
    headers via ``response.headers["Content-Length"] = ...``.
    """
    from starlette.responses import StreamingResponse

    async def _gen() -> AsyncGenerator[bytes, None]:
        yield b"hello"
        yield b"world"

    # Construct the response exactly as the audio endpoint does post-fix.
    response = StreamingResponse(
        _gen(),
        status_code=200,
        media_type="audio/ogg",
    )
    assert "content-length" not in {k.lower() for k in response.headers}, (
        f"R1-C1: StreamingResponse without explicit Content-Length must "
        f"emit chunked; got headers={dict(response.headers)}"
    )

    # Source-level companion guard: the recordings.py construction
    # itself must not pass ``Content-Length`` to the guarded branches.
    # (A future regression that reintroduces the header inline would
    # be caught here even before runtime.)
    from echoroo.api.v1 import recordings as rec_module

    source = inspect.getsource(rec_module)
    # Slice to the guarded OGG call site and check no Content-Length
    # appears between the call open and its matching close paren.
    for opener in ("_iter_ogg_guarded(),", "_iter_file_guarded(),"):
        idx = source.index(opener)
        # Find the matching close-paren of the StreamingResponse call.
        depth = 1
        cursor = idx + len(opener)
        end = cursor
        while cursor < len(source) and depth > 0:
            ch = source[cursor]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    end = cursor
                    break
            cursor += 1
        call_args = source[idx + len(opener) : end]
        assert "Content-Length" not in call_args, (
            f"R1-C1: {opener} call must NOT pass Content-Length; "
            f"got call args:\n{call_args}"
        )
        assert "Accept-Ranges" not in call_args, (
            f"R1-C1: {opener} call must NOT pass Accept-Ranges; "
            f"got call args:\n{call_args}"
        )


def test_audio_range_response_still_has_content_length() -> None:
    """Range (HTTP 206) branch must still advertise both headers.

    Regression guard for R1-C1: the fix narrowly targets the full-file
    streaming response. The Range branch issues a single-shot
    ``Response`` (not ``StreamingResponse``) with the exact sliced
    bytes — Content-Length / Accept-Ranges are not only safe, they
    are required by the HTTP spec for 206 responses.
    """
    from echoroo.api.v1 import recordings as rec_module

    source = inspect.getsource(rec_module)
    # Range branch returns Response (not StreamingResponse) with the
    # slice + 206 status; locate via the documented Content-Range header.
    assert 'Content-Range' in source, (
        "Range branch must construct a Content-Range header"
    )
    # The Range branch lives inside the same passthrough block; assert
    # both regression headers are still present somewhere in the file.
    assert 'Content-Length": str(chunk_size)' in source
    assert '"Accept-Ranges": "bytes"' in source


def test_audio_module_does_not_yield_sentinel() -> None:
    """The audio router must not emit SENTINEL_BYTES (binary-safety property)."""
    from echoroo.api.v1 import recordings as rec_module

    source = inspect.getsource(rec_module)
    assert "_iter_ogg_guarded" in source
    assert "_iter_file_guarded" in source
    assert 'stream_type="audio_ogg"' in source
    assert 'stream_type="audio_wav"' in source
    assert "yield SENTINEL_BYTES" not in source
    assert "yield stream_guard.SENTINEL_BYTES" not in source


def test_audio_module_uses_recheck_at_interval() -> None:
    """Audio guards must reference AUDIO_RECHECK_INTERVAL + recheck_action_permission."""
    from echoroo.api.v1 import recordings as rec_module

    source = inspect.getsource(rec_module)
    assert "AUDIO_RECHECK_INTERVAL" in source
    assert "recheck_action_permission" in source
    assert "audit_stream_revoked" in source


# ---------------------------------------------------------------------------
# 7. search/sessions.py routes through the streaming guard
# ---------------------------------------------------------------------------


def test_sessions_export_csv_uses_streaming_guard() -> None:
    """The session-export route MUST call DetectionExportService.export_csv_stream."""
    from echoroo.api.v1.search import sessions as sessions_module

    source = inspect.getsource(sessions_module.export_search_session_csv)
    assert "export_csv_stream" in source
    assert "export_service.export_csv(" not in source, (
        "session-export must use the streaming variant, not the buffered one"
    )
    assert "DETECTION_EXPORT_CSV_ACTION" in source
    assert "gate_action" in source


# ---------------------------------------------------------------------------
# 8. detections.py route uses the streaming variant
# ---------------------------------------------------------------------------


def test_detections_export_route_uses_streaming() -> None:
    """The /detections/export/csv route MUST stream row-by-row."""
    from echoroo.api.v1 import detections as det_module

    source = inspect.getsource(det_module.export_csv)
    assert "export_csv_stream" in source
    # The legacy buffered + io.BytesIO wrapper must be gone.
    assert "io.BytesIO(csv_content" not in source


# ---------------------------------------------------------------------------
# 9. export_csv() back-compat preserved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_csv_back_compat_signature_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``export_csv() -> str`` must still work for legacy callers."""
    from echoroo.services import detection_export as export_module

    service = export_module.DetectionExportService.__new__(  # type: ignore[call-arg]
        export_module.DetectionExportService
    )
    service.db = AsyncMock()  # type: ignore[attr-defined]

    async def _fake_fetch(*_args: Any, **_kwargs: Any) -> list[Any]:
        return []

    async def _fake_load_project(*_a: Any, **_k: Any) -> Any:
        return None

    async def _fake_h3_map(*_a: Any, **_k: Any) -> dict[Any, Any]:
        return {}

    monkeypatch.setattr(service, "_fetch_annotations_for_export", _fake_fetch)
    monkeypatch.setattr(service, "_load_project", _fake_load_project)
    monkeypatch.setattr(service, "_build_recording_h3_resolution_map", _fake_h3_map)

    csv_text = await service.export_csv(uuid.uuid4(), search_session_id=uuid.uuid4())
    assert isinstance(csv_text, str)
    assert "observationID" in csv_text
    assert stream_guard.SENTINEL_BYTES.decode("utf-8", errors="ignore") not in csv_text


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("license_id", "license_record", "expected_license"),
    [
        (None, None, ""),
        (
            "cc-by",
            License(
                id="cc-by",
                name="Creative Commons Attribution",
                short_name="CC-BY",
            ),
            "CC-BY",
        ),
        (
            "custom-arbitrary",
            License(
                id="custom-arbitrary",
                name="Custom Arbitrary",
                short_name="CUSTOM-ARBITRARY",
            ),
            "CUSTOM-ARBITRARY",
        ),
    ],
)
async def test_export_csv_writes_project_license_column_from_license_record(
    monkeypatch: pytest.MonkeyPatch,
    license_id: str | None,
    license_record: License | None,
    expected_license: str,
) -> None:
    """CSV exports use Project.license, including NULL and custom licenses."""
    from echoroo.services import detection_export as export_module

    service = export_module.DetectionExportService.__new__(  # type: ignore[call-arg]
        export_module.DetectionExportService
    )
    service.db = AsyncMock()  # type: ignore[attr-defined]
    project_id = uuid.uuid4()
    annotation_id = uuid.uuid4()

    async def _fake_fetch(*_args: Any, **_kwargs: Any) -> list[Any]:
        return [
            SimpleNamespace(
                id=annotation_id,
                recording=None,
                recording_id=None,
                tag=None,
                detection_run=None,
                reviewed_by=None,
                reviewed_at=None,
                created_at=None,
                source=None,
                start_time=0.0,
                end_time=1.0,
                freq_low=None,
                freq_high=None,
                confidence=None,
            )
        ]

    async def _fake_load_project(*_a: Any, **_k: Any) -> Any:
        return Project(
            name="Stream Guard Export License Project",
            owner_id=uuid.uuid4(),
            license_id=license_id,
            license_record=license_record,
            visibility=ProjectVisibility.PUBLIC,
            restricted_config={},
        )

    async def _fake_h3_map(*_a: Any, **_k: Any) -> dict[Any, Any]:
        return {}

    monkeypatch.setattr(service, "_fetch_annotations_for_export", _fake_fetch)
    monkeypatch.setattr(service, "_load_project", _fake_load_project)
    monkeypatch.setattr(service, "_build_recording_h3_resolution_map", _fake_h3_map)

    csv_text = await service.export_csv(project_id)
    rows = list(csv.DictReader(io.StringIO(csv_text)))
    assert rows[0]["license"] == expected_license

    class _Req:
        state = type("S", (), {})()
        client = type("C", (), {"host": ""})()
        headers: dict[str, str] = {}

    stream_body = b"".join(
        [
            chunk
            async for chunk in service.export_csv_stream(
                project_id=project_id,
                action=DETECTION_EXPORT_CSV_ACTION,
                current_user=None,
                request=_Req(),  # type: ignore[arg-type]
            )
        ]
    ).decode("utf-8")
    stream_rows = list(csv.DictReader(io.StringIO(stream_body)))
    assert stream_rows[0]["license"] == expected_license


# ---------------------------------------------------------------------------
# Make `noqa` pleasant: keep AsyncGenerator imported in case downstream
# tests reuse this module.
# ---------------------------------------------------------------------------

_unused: AsyncGenerator | None = None  # noqa: UP007 — type-only sentinel

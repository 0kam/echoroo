"""Smoke tests for :mod:`echoroo.middleware.auth_router` (T070)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from echoroo.core.auth import issue_access_token, issue_media_token
from echoroo.middleware.auth_router import (
    ApiKeyRecord,
    AuthRouterConfig,
    AuthRouterMiddleware,
    Principal,
)

# ---------------------------------------------------------------------------
# Stubs for the verifier protocols
# ---------------------------------------------------------------------------


class _StubApiKeyVerifier:
    def __init__(self, expected: str, record: ApiKeyRecord) -> None:
        self._expected = expected
        self._record = record

    async def verify(self, raw_key: str) -> ApiKeyRecord | None:
        if raw_key == self._expected:
            return self._record
        return None


class _StubSessionVerifier:
    def __init__(self, mapping: dict[str, tuple[UUID, str]]) -> None:
        self._mapping = mapping

    async def verify(self, session_id: str) -> tuple[UUID, str] | None:
        return self._mapping.get(session_id)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_app(config: AuthRouterConfig) -> TestClient:
    async def echo(request: Request) -> JSONResponse:
        principal: Principal | None = getattr(request.state, "principal", None)
        return JSONResponse(
            {
                "auth_kind": principal.auth_kind if principal else None,
                "user_id": str(principal.user_id) if principal else None,
            }
        )

    app = Starlette(
        routes=[
            Route("/api/v1/ping", echo),
            Route("/web-api/v1/ping", echo),
            Route(
                "/web-api/v1/projects/{project_id}/recordings/{recording_id}/playback",
                echo,
            ),
            Route(
                "/web-api/v1/projects/{project_id}/recordings/{recording_id}/download",
                echo,
            ),
            Route(
                "/web-api/v1/projects/{project_id}/recordings/{recording_id}"
                "/clips/{clip_id}/download",
                echo,
            ),
            Route(
                "/web-api/v1/projects/{project_id}/search/sessions/{session_id}"
                "/reference-audio/{source_index}",
                echo,
            ),
            Route("/health", echo),
        ]
    )
    app.add_middleware(AuthRouterMiddleware, config=config)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_health_passes_through_without_principal() -> None:
    """Paths outside both prefixes must not require auth."""
    config = AuthRouterConfig()
    client = _build_app(config)
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"auth_kind": None, "user_id": None}


def test_api_v1_requires_bearer_api_key() -> None:
    """Missing Authorization header returns 401 with the right error code."""
    config = AuthRouterConfig(
        api_key_verifier=_StubApiKeyVerifier(
            expected="never-used",
            record=ApiKeyRecord(
                api_key_id=uuid4(),
                user_id=uuid4(),
                granted_permissions=(),
            ),
        )
    )
    client = _build_app(config)
    resp = client.get("/api/v1/ping")
    assert resp.status_code == 401
    body = resp.json()
    assert body["error_code"] in {"auth_required", "auth_invalid"}


def test_api_v1_accepts_valid_api_key() -> None:
    """A valid Bearer key resolves a Principal with auth_kind=api_key."""
    user_id = uuid4()
    api_key_id = uuid4()
    record = ApiKeyRecord(
        api_key_id=api_key_id,
        user_id=user_id,
        granted_permissions=("read", "vote"),
    )
    config = AuthRouterConfig(
        api_key_verifier=_StubApiKeyVerifier("ek_live_secret", record)
    )
    client = _build_app(config)
    resp = client.get(
        "/api/v1/ping",
        headers={"Authorization": "Bearer ek_live_secret"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_kind"] == "api_key"
    assert body["user_id"] == str(user_id)


def test_web_api_v1_requires_session_cookie() -> None:
    """Missing session cookie returns 401."""
    config = AuthRouterConfig(session_verifier=_StubSessionVerifier({}))
    client = _build_app(config)
    resp = client.get("/web-api/v1/ping")
    assert resp.status_code == 401


def test_web_api_v1_accepts_session_with_matching_stamp() -> None:
    """Session cookie + JWT (matching live stamp) yields auth_kind=session."""
    user_id = uuid4()
    stamp = "a" * 64
    session_id = "sess-1"
    config = AuthRouterConfig(
        session_verifier=_StubSessionVerifier({session_id: (user_id, stamp)})
    )
    token = issue_access_token(
        user_id=user_id,
        security_stamp=stamp,
        now=datetime.now(UTC),
    )

    client = _build_app(config)
    resp = client.get(
        "/web-api/v1/ping",
        cookies={"session_id": session_id, "access_token": token},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_kind"] == "session"
    assert body["user_id"] == str(user_id)


def test_web_api_v1_rejects_stale_security_stamp() -> None:
    """A revoked session (stamp rotated) yields 419."""
    user_id = uuid4()
    issuance_stamp = "a" * 64
    live_stamp = "b" * 64
    session_id = "sess-2"
    config = AuthRouterConfig(
        session_verifier=_StubSessionVerifier({session_id: (user_id, live_stamp)})
    )
    token = issue_access_token(
        user_id=user_id,
        security_stamp=issuance_stamp,
        now=datetime.now(UTC),
    )

    client = _build_app(config)
    resp = client.get(
        "/web-api/v1/ping",
        cookies={"session_id": session_id, "access_token": token},
    )
    assert resp.status_code == 419
    assert resp.json()["error_code"] == "session_revoked"


def test_web_api_media_get_accepts_scoped_media_token() -> None:
    """Native media GETs may authenticate with session cookie + media_token."""
    user_id = uuid4()
    stamp = "c" * 64
    session_id = "sess-media"
    project_id = uuid4()
    recording_id = uuid4()
    config = AuthRouterConfig(
        session_verifier=_StubSessionVerifier({session_id: (user_id, stamp)})
    )
    token = issue_media_token(
        user_id=user_id,
        security_stamp=stamp,
        project_id=project_id,
        resource_type="recording",
        resource_id=recording_id,
        scope="playback",
        now=datetime.now(UTC),
    )

    client = _build_app(config)
    resp = client.get(
        f"/web-api/v1/projects/{project_id}/recordings/{recording_id}/playback",
        params={"media_token": token},
        cookies={"session_id": session_id},
    )
    assert resp.status_code == 200
    assert resp.json()["auth_kind"] == "session"
    assert resp.json()["user_id"] == str(user_id)


def test_web_api_media_get_rejects_old_token_query_fallback() -> None:
    """The old ?token=<access JWT> media fallback is not accepted anymore."""
    user_id = uuid4()
    stamp = "d" * 64
    session_id = "sess-old-query"
    project_id = uuid4()
    recording_id = uuid4()
    config = AuthRouterConfig(
        session_verifier=_StubSessionVerifier({session_id: (user_id, stamp)})
    )
    access_token = issue_access_token(
        user_id=user_id,
        security_stamp=stamp,
        now=datetime.now(UTC),
    )

    client = _build_app(config)
    resp = client.get(
        f"/web-api/v1/projects/{project_id}/recordings/{recording_id}/playback",
        params={"token": access_token},
        cookies={"session_id": session_id},
    )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "auth_required"


def test_web_api_media_get_rejects_wrong_media_scope() -> None:
    """Media tokens are bound to the concrete audio/playback/spectrogram path."""
    user_id = uuid4()
    stamp = "e" * 64
    session_id = "sess-wrong-scope"
    project_id = uuid4()
    recording_id = uuid4()
    config = AuthRouterConfig(
        session_verifier=_StubSessionVerifier({session_id: (user_id, stamp)})
    )
    token = issue_media_token(
        user_id=user_id,
        security_stamp=stamp,
        project_id=project_id,
        resource_type="recording",
        resource_id=recording_id,
        scope="audio",
        now=datetime.now(UTC),
    )

    client = _build_app(config)
    resp = client.get(
        f"/web-api/v1/projects/{project_id}/recordings/{recording_id}/playback",
        params={"media_token": token},
        cookies={"session_id": session_id},
    )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "auth_invalid"


def test_web_api_recording_download_accepts_download_scoped_token() -> None:
    """The recording download surface accepts a download-scoped media token."""
    user_id = uuid4()
    stamp = "f" * 64
    session_id = "sess-dl"
    project_id = uuid4()
    recording_id = uuid4()
    config = AuthRouterConfig(
        session_verifier=_StubSessionVerifier({session_id: (user_id, stamp)})
    )
    token = issue_media_token(
        user_id=user_id,
        security_stamp=stamp,
        project_id=project_id,
        resource_type="recording",
        resource_id=recording_id,
        scope="download",
        now=datetime.now(UTC),
    )

    client = _build_app(config)
    resp = client.get(
        f"/web-api/v1/projects/{project_id}/recordings/{recording_id}/download",
        params={"media_token": token},
        cookies={"session_id": session_id},
    )
    assert resp.status_code == 200
    assert resp.json()["auth_kind"] == "session"


def test_web_api_recording_download_rejects_playback_scoped_token() -> None:
    """A playback token must not authenticate the download surface (fixed scope)."""
    user_id = uuid4()
    stamp = "g" * 64
    session_id = "sess-dl-scope"
    project_id = uuid4()
    recording_id = uuid4()
    config = AuthRouterConfig(
        session_verifier=_StubSessionVerifier({session_id: (user_id, stamp)})
    )
    token = issue_media_token(
        user_id=user_id,
        security_stamp=stamp,
        project_id=project_id,
        resource_type="recording",
        resource_id=recording_id,
        scope="playback",
        now=datetime.now(UTC),
    )

    client = _build_app(config)
    resp = client.get(
        f"/web-api/v1/projects/{project_id}/recordings/{recording_id}/download",
        params={"media_token": token},
        cookies={"session_id": session_id},
    )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "auth_invalid"


def test_web_api_clip_download_accepts_clip_scoped_token() -> None:
    """The clip download surface accepts a clip-bound download token."""
    user_id = uuid4()
    stamp = "h" * 64
    session_id = "sess-clip-dl"
    project_id = uuid4()
    recording_id = uuid4()
    clip_id = uuid4()
    config = AuthRouterConfig(
        session_verifier=_StubSessionVerifier({session_id: (user_id, stamp)})
    )
    token = issue_media_token(
        user_id=user_id,
        security_stamp=stamp,
        project_id=project_id,
        resource_type="clip",
        resource_id=clip_id,
        scope="download",
        parent_id=recording_id,
        now=datetime.now(UTC),
    )

    client = _build_app(config)
    resp = client.get(
        f"/web-api/v1/projects/{project_id}/recordings/{recording_id}"
        f"/clips/{clip_id}/download",
        params={"media_token": token},
        cookies={"session_id": session_id},
    )
    assert resp.status_code == 200
    assert resp.json()["auth_kind"] == "session"


def test_web_api_clip_download_rejects_token_under_other_recording() -> None:
    """A clip token is bound to its parent recording path segment."""
    user_id = uuid4()
    stamp = "m" * 64
    session_id = "sess-clip-parent"
    project_id = uuid4()
    recording_id = uuid4()
    other_recording_id = uuid4()
    clip_id = uuid4()
    config = AuthRouterConfig(
        session_verifier=_StubSessionVerifier({session_id: (user_id, stamp)})
    )
    token = issue_media_token(
        user_id=user_id,
        security_stamp=stamp,
        project_id=project_id,
        resource_type="clip",
        resource_id=clip_id,
        scope="download",
        parent_id=recording_id,
        now=datetime.now(UTC),
    )

    client = _build_app(config)
    resp = client.get(
        f"/web-api/v1/projects/{project_id}/recordings/{other_recording_id}"
        f"/clips/{clip_id}/download",
        params={"media_token": token},
        cookies={"session_id": session_id},
    )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "auth_invalid"


def test_web_api_clip_download_rejects_recording_scoped_token() -> None:
    """A recording token cannot authenticate the clip download surface."""
    user_id = uuid4()
    stamp = "i" * 64
    session_id = "sess-clip-rtype"
    project_id = uuid4()
    recording_id = uuid4()
    clip_id = uuid4()
    config = AuthRouterConfig(
        session_verifier=_StubSessionVerifier({session_id: (user_id, stamp)})
    )
    # Recording-scoped download token whose resource id happens to equal the
    # clip id — the resource_type mismatch (recording vs clip) must still reject.
    token = issue_media_token(
        user_id=user_id,
        security_stamp=stamp,
        project_id=project_id,
        resource_type="recording",
        resource_id=clip_id,
        scope="download",
        now=datetime.now(UTC),
    )

    client = _build_app(config)
    resp = client.get(
        f"/web-api/v1/projects/{project_id}/recordings/{recording_id}"
        f"/clips/{clip_id}/download",
        params={"media_token": token},
        cookies={"session_id": session_id},
    )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "auth_invalid"


def test_web_api_clip_download_rejects_token_for_other_clip() -> None:
    """A clip token for clip X must not authenticate clip Y's download."""
    user_id = uuid4()
    stamp = "j" * 64
    session_id = "sess-clip-x"
    project_id = uuid4()
    recording_id = uuid4()
    clip_x = uuid4()
    clip_y = uuid4()
    config = AuthRouterConfig(
        session_verifier=_StubSessionVerifier({session_id: (user_id, stamp)})
    )
    token = issue_media_token(
        user_id=user_id,
        security_stamp=stamp,
        project_id=project_id,
        resource_type="clip",
        resource_id=clip_x,
        scope="download",
        parent_id=recording_id,
        now=datetime.now(UTC),
    )

    client = _build_app(config)
    resp = client.get(
        f"/web-api/v1/projects/{project_id}/recordings/{recording_id}"
        f"/clips/{clip_y}/download",
        params={"media_token": token},
        cookies={"session_id": session_id},
    )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "auth_invalid"


def test_web_api_media_get_rejects_duplicate_media_token_param() -> None:
    """A duplicated ``media_token`` query param is rejected (ambiguous)."""
    user_id = uuid4()
    stamp = "k" * 64
    session_id = "sess-dup"
    project_id = uuid4()
    recording_id = uuid4()
    config = AuthRouterConfig(
        session_verifier=_StubSessionVerifier({session_id: (user_id, stamp)})
    )
    token = issue_media_token(
        user_id=user_id,
        security_stamp=stamp,
        project_id=project_id,
        resource_type="recording",
        resource_id=recording_id,
        scope="playback",
        now=datetime.now(UTC),
    )

    client = _build_app(config)
    # Two media_token params: the matcher must refuse to pick one, so it falls
    # back to the cookie/Bearer chain, which has no access token -> 401.
    resp = client.get(
        f"/web-api/v1/projects/{project_id}/recordings/{recording_id}/playback"
        f"?media_token={token}&media_token={token}",
        cookies={"session_id": session_id},
    )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "auth_required"


def test_web_api_media_get_ignores_non_uuid_path_ids() -> None:
    """Non-UUID path ids do not match the media matcher (falls back to auth)."""
    user_id = uuid4()
    stamp = "l" * 64
    session_id = "sess-badid"
    project_id = uuid4()
    config = AuthRouterConfig(
        session_verifier=_StubSessionVerifier({session_id: (user_id, stamp)})
    )
    token = issue_media_token(
        user_id=user_id,
        security_stamp=stamp,
        project_id=project_id,
        resource_type="recording",
        resource_id=uuid4(),
        scope="playback",
        now=datetime.now(UTC),
    )

    client = _build_app(config)
    # ``not-a-uuid`` as the recording id: the matcher rejects it, so the media
    # token is ignored and the request falls back to the (missing) access token.
    resp = client.get(
        f"/web-api/v1/projects/{project_id}/recordings/not-a-uuid/playback",
        params={"media_token": token},
        cookies={"session_id": session_id},
    )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "auth_required"


def test_web_api_reference_audio_accepts_scoped_media_token() -> None:
    """The reference-audio surface accepts a session+index-scoped audio token."""
    user_id = uuid4()
    stamp = "n" * 64
    session_id_cookie = "sess-ref-audio"
    project_id = uuid4()
    session_id = uuid4()
    config = AuthRouterConfig(
        session_verifier=_StubSessionVerifier({session_id_cookie: (user_id, stamp)})
    )
    token = issue_media_token(
        user_id=user_id,
        security_stamp=stamp,
        project_id=project_id,
        resource_type="search_session",
        resource_id=session_id,
        scope="audio",
        source_index=1,
        now=datetime.now(UTC),
    )

    client = _build_app(config)
    resp = client.get(
        f"/web-api/v1/projects/{project_id}/search/sessions/{session_id}"
        f"/reference-audio/1",
        params={"media_token": token},
        cookies={"session_id": session_id_cookie},
    )
    assert resp.status_code == 200
    assert resp.json()["auth_kind"] == "session"
    assert resp.json()["user_id"] == str(user_id)


def test_web_api_reference_audio_rejects_wrong_source_index() -> None:
    """A reference-audio token is bound to one source index in the path."""
    user_id = uuid4()
    stamp = "o" * 64
    session_id_cookie = "sess-ref-idx"
    project_id = uuid4()
    session_id = uuid4()
    config = AuthRouterConfig(
        session_verifier=_StubSessionVerifier({session_id_cookie: (user_id, stamp)})
    )
    token = issue_media_token(
        user_id=user_id,
        security_stamp=stamp,
        project_id=project_id,
        resource_type="search_session",
        resource_id=session_id,
        scope="audio",
        source_index=1,
        now=datetime.now(UTC),
    )

    client = _build_app(config)
    resp = client.get(
        f"/web-api/v1/projects/{project_id}/search/sessions/{session_id}"
        f"/reference-audio/2",
        params={"media_token": token},
        cookies={"session_id": session_id_cookie},
    )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "auth_invalid"


def test_web_api_reference_audio_rejects_wrong_session_id() -> None:
    """A reference-audio token cannot authenticate a different session's path."""
    user_id = uuid4()
    stamp = "p" * 64
    session_id_cookie = "sess-ref-sid"
    project_id = uuid4()
    session_id = uuid4()
    other_session_id = uuid4()
    config = AuthRouterConfig(
        session_verifier=_StubSessionVerifier({session_id_cookie: (user_id, stamp)})
    )
    token = issue_media_token(
        user_id=user_id,
        security_stamp=stamp,
        project_id=project_id,
        resource_type="search_session",
        resource_id=session_id,
        scope="audio",
        source_index=0,
        now=datetime.now(UTC),
    )

    client = _build_app(config)
    resp = client.get(
        f"/web-api/v1/projects/{project_id}/search/sessions/{other_session_id}"
        f"/reference-audio/0",
        params={"media_token": token},
        cookies={"session_id": session_id_cookie},
    )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "auth_invalid"


def test_web_api_reference_audio_rejects_recording_token() -> None:
    """A recording token must not authenticate the reference-audio surface."""
    user_id = uuid4()
    stamp = "q" * 64
    session_id_cookie = "sess-ref-rtype"
    project_id = uuid4()
    session_id = uuid4()
    config = AuthRouterConfig(
        session_verifier=_StubSessionVerifier({session_id_cookie: (user_id, stamp)})
    )
    # Recording-scoped audio token whose resource id equals the session id —
    # the resource_type mismatch (recording vs search_session) must still reject.
    token = issue_media_token(
        user_id=user_id,
        security_stamp=stamp,
        project_id=project_id,
        resource_type="recording",
        resource_id=session_id,
        scope="audio",
        now=datetime.now(UTC),
    )

    client = _build_app(config)
    resp = client.get(
        f"/web-api/v1/projects/{project_id}/search/sessions/{session_id}"
        f"/reference-audio/0",
        params={"media_token": token},
        cookies={"session_id": session_id_cookie},
    )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "auth_invalid"


def test_web_api_reference_audio_non_numeric_index_falls_through() -> None:
    """A non-numeric source index does not match the media rule (falls through)."""
    user_id = uuid4()
    stamp = "r" * 64
    session_id_cookie = "sess-ref-nan"
    project_id = uuid4()
    session_id = uuid4()
    config = AuthRouterConfig(
        session_verifier=_StubSessionVerifier({session_id_cookie: (user_id, stamp)})
    )
    token = issue_media_token(
        user_id=user_id,
        security_stamp=stamp,
        project_id=project_id,
        resource_type="search_session",
        resource_id=session_id,
        scope="audio",
        source_index=0,
        now=datetime.now(UTC),
    )

    client = _build_app(config)
    # ``abc`` as the source index: the matcher rejects it, so the media token
    # is ignored and the request falls back to the (missing) access token.
    resp = client.get(
        f"/web-api/v1/projects/{project_id}/search/sessions/{session_id}"
        f"/reference-audio/abc",
        params={"media_token": token},
        cookies={"session_id": session_id_cookie},
    )
    assert resp.status_code == 401
    assert resp.json()["error_code"] == "auth_required"


def test_public_path_allowlist_skips_auth() -> None:
    """Login MUST be reachable without credentials."""
    config = AuthRouterConfig(
        session_verifier=_StubSessionVerifier({}),
        public_path_allowlist=("/web-api/v1/auth/login",),
    )

    async def login(request: Request) -> JSONResponse:
        return JSONResponse({"principal": None})

    app = Starlette(
        routes=[Route("/web-api/v1/auth/login", login, methods=["POST"])]
    )
    app.add_middleware(AuthRouterMiddleware, config=config)
    client = TestClient(app)
    resp = client.post("/web-api/v1/auth/login", json={"email": "x", "password": "y"})
    assert resp.status_code == 200

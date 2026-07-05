"""Smoke coverage for spec/009 PR 4 search BFF adapters.

PR 4 moves the entire similarity-search + xeno-canto + embedding-stats
+ search-annotation surface from ``/api/v1`` to ``/web-api/v1``. Each
BFF handler is a thin adapter that re-uses :func:`gate_action` and
delegates to the legacy handler. Tests assert:

* delegation: legacy handler is called with the right kwargs.
* gating: the canonical per-endpoint Action constant is captured.
* OpenAPI: every path is declared on the router.
* surface separation: every path rejects ``Authorization: Bearer
  echoroo_*`` (D-2a #3 / FR-006 mirror).
* streaming shape: the two CSV exports + the Xeno-canto audio proxy
  pass the legacy ``StreamingResponse`` through unchanged.

The legacy ``AuthorizedSearchServiceDep`` / ``AuthorizedSearchSessionServiceDep``
factories themselves fire ``gate_action(SEARCH_SESSION_LIST_ACTION)``
inside the dep resolver, so the smoke tests override those factories
with simple lambdas that return the test service object directly. The
BFF's own ``gate_action`` is then monkey-patched with a capturing fake
to assert the per-endpoint Action constant.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.responses import Response, StreamingResponse
from httpx import ASGITransport, AsyncClient

from echoroo.api.v1 import xeno_canto as legacy_xeno_canto
from echoroo.api.v1.search import annotations as legacy_search_annotations
from echoroo.api.v1.search import batch as legacy_search_batch
from echoroo.api.v1.search import deps as legacy_search_deps
from echoroo.api.v1.search import sessions as legacy_search_sessions
from echoroo.api.v1.search import similarity as legacy_search_similarity
from echoroo.api.web_v1.projects import _search as bff_search
from echoroo.core.actions import (
    SEARCH_ANNOTATION_ACTION,
    SEARCH_BATCH_CREATE_ACTION,
    SEARCH_BATCH_JOB_GET_ACTION,
    SEARCH_EMBEDDING_STATS_ACTION,
    SEARCH_SESSION_DELETE_ACTION,
    SEARCH_SESSION_DISTRIBUTION_ACTION,
    SEARCH_SESSION_EXPORT_CSV_ACTION,
    SEARCH_SESSION_EXPORT_RECORDINGS_ACTION,
    SEARCH_SESSION_GET_ACTION,
    SEARCH_SESSION_LIST_ACTION,
    SEARCH_SESSION_REFERENCE_AUDIO_ACTION,
    SEARCH_SESSION_RERUN_ACTION,
    SEARCH_SESSION_SAMPLE_ACTION,
    SEARCH_SESSION_TIME_DISTRIBUTION_ACTION,
    SEARCH_SESSION_UPDATE_ACTION,
    XENO_CANTO_AUDIO_ACTION,
)
from echoroo.core.auth import verify_media_token
from echoroo.core.database import get_db
from echoroo.middleware.auth import get_current_user
from echoroo.models.enums import DetectionSource, DetectionStatus
from echoroo.schemas.detection import DetectionResponse
from echoroo.schemas.search import (
    EmbeddingStatsResponse,
    SearchJobAcceptedResponse,
    SearchJobStatusResponse,
    SearchSessionListResponse,
    SearchSessionResponse,
    SessionDistributionResponse,
    SessionSampleResponse,
    SessionTimeDistributionResponse,
)
from echoroo.schemas.xeno_canto import XenoCantoSearchResponse
from tests.integration.api.web_v1._helpers import assert_api_key_cross_rejected

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


async def _fake_db() -> AsyncIterator[object]:
    yield object()


def _make_capturing_gate_action(captured: dict[str, object]) -> Any:
    async def fake(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    return fake


def _build_app(*, user: object, service: object) -> FastAPI:
    """Wire the BFF search router with the legacy deps shimmed.

    ``AuthorizedSearchServiceDep`` and ``AuthorizedSearchSessionServiceDep``
    are ``Annotated[..., Depends(...)]`` aliases whose underlying dep
    factories (``get_authorized_search_service`` /
    ``get_authorized_session_service``) themselves fire ``gate_action``
    against the live permission stack. The shim returns the
    ``service`` argument directly so the smoke tests do not need a real
    DB or Principal.
    """
    app = FastAPI()
    app.include_router(bff_search.router, prefix="/web-api/v1/projects")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[
        legacy_search_deps.get_authorized_search_service
    ] = lambda: service
    app.dependency_overrides[
        legacy_search_deps.get_authorized_session_service
    ] = lambda: service
    app.dependency_overrides[legacy_search_deps.get_search_service] = (
        lambda: service
    )
    app.dependency_overrides[
        legacy_search_deps.get_search_session_service
    ] = lambda: service
    return app


def _fake_session_response(
    *, project_id: UUID, session_id: UUID
) -> SearchSessionResponse:
    now = datetime(2026, 5, 24, tzinfo=UTC)
    return SearchSessionResponse(
        id=session_id,
        project_id=project_id,
        user_id=None,
        name="fake",
        status="completed",
        model_name="perch",
        parameters=None,
        species_config=None,
        results=None,
        result_count=0,
        confirmed_count=0,
        rejected_count=0,
        celery_job_id=None,
        reference_audio_keys=None,
        started_at=None,
        completed_at=None,
        error_message=None,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Delegation + gate_action capture per endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embedding_stats_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_stats(**kwargs: object) -> EmbeddingStatsResponse:
        captured.update(kwargs)
        return EmbeddingStatsResponse(total_count=0, by_model={}, by_dataset={})

    monkeypatch.setattr(legacy_search_similarity, "get_embedding_stats", fake_stats)
    monkeypatch.setattr(
        bff_search, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/search/embedding-stats"
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["service"] is service
    assert gate_captured["action"] is SEARCH_EMBEDDING_STATS_ACTION


@pytest.mark.asyncio
async def test_search_xeno_canto_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_search(**kwargs: object) -> XenoCantoSearchResponse:
        captured.update(kwargs)
        return XenoCantoSearchResponse(
            total_recordings=0,
            total_species=0,
            page=1,
            total_pages=1,
            recordings=[],
        )

    monkeypatch.setattr(legacy_xeno_canto, "search_xeno_canto", fake_search)
    monkeypatch.setattr(
        bff_search, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/xeno-canto/search?query=Larus"
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["query"] == "Larus"
    # Legacy XC search has no dedicated Action — BFF mirrors via
    # SEARCH_SESSION_LIST_ACTION baseline.
    assert gate_captured["action"] is SEARCH_SESSION_LIST_ACTION


@pytest.mark.asyncio
async def test_xeno_canto_audio_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_proxy(**kwargs: object) -> StreamingResponse:
        captured.update(kwargs)
        return StreamingResponse(
            iter([b"audio-bytes"]),
            media_type="audio/mpeg",
            headers={"Content-Disposition": 'inline; filename="XC1.mp3"'},
        )

    monkeypatch.setattr(legacy_xeno_canto, "proxy_audio", fake_proxy)
    monkeypatch.setattr(
        bff_search, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/xeno-canto/audio/1234"
        )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("audio/")
    assert captured["xc_id"] == "1234"
    assert captured["project_id"] == project_id
    assert gate_captured["action"] is XENO_CANTO_AUDIO_ACTION


@pytest.mark.asyncio
async def test_xeno_canto_sonogram_bff_delegates_to_legacy_ungated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sonogram twin delegates verbatim and is intentionally un-gated.

    Native ``<img src=...>`` elements render the server-emitted
    ``sonogram_url`` and cannot attach a Bearer header, so the twin carries
    NO ``CurrentUser`` dependency and fires NO ``gate_action`` (the SSRF
    allowlist inside ``proxy_sonogram`` is the control). This test asserts
    both the delegation kwargs and that gating is NOT invoked.
    """
    project_id = uuid4()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_sonogram(**kwargs: object) -> Response:
        captured.update(kwargs)
        return Response(content=b"\x89PNG", media_type="image/png")

    monkeypatch.setattr(legacy_xeno_canto, "proxy_sonogram", fake_sonogram)
    monkeypatch.setattr(
        bff_search, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    # No user override needed — the twin has no CurrentUser dependency.
    app = _build_app(user=SimpleNamespace(id=uuid4()), service=object())
    sono_url = "https://xeno-canto.org/sounds/spectrogram/1234-small.png"
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/xeno-canto/sonogram",
            params={"url": sono_url},
        )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("image/")
    assert captured["project_id"] == project_id
    assert captured["url"] == sono_url
    # Un-gated: no gate_action should have fired.
    assert gate_captured == {}


@pytest.mark.asyncio
async def test_submit_batch_search_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_batch(**kwargs: object) -> SearchJobAcceptedResponse:
        captured.update(kwargs)
        return SearchJobAcceptedResponse(
            job_id="job-uuid", status="pending", session_id=uuid4()
        )

    monkeypatch.setattr(legacy_search_batch, "batch_search", fake_batch)
    monkeypatch.setattr(
        bff_search, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/search/batch",
            data={"metadata": '{"species": [], "model_name": "perch"}'},
        )

    assert response.status_code == 202, response.text
    assert captured["project_id"] == project_id
    assert captured["metadata"] == '{"species": [], "model_name": "perch"}'
    assert gate_captured["action"] is SEARCH_BATCH_CREATE_ACTION


@pytest.mark.asyncio
async def test_get_search_job_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    job_id = "job-uuid-string"
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_get_job(**kwargs: object) -> SearchJobStatusResponse:
        captured.update(kwargs)
        return SearchJobStatusResponse(job_id=job_id, status="processing")

    monkeypatch.setattr(legacy_search_batch, "get_search_job", fake_get_job)
    monkeypatch.setattr(
        bff_search, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/search/jobs/{job_id}?locale=ja"
        )

    assert response.status_code == 200, response.text
    assert captured["job_id"] == job_id
    assert captured["locale"] == "ja"
    assert gate_captured["action"] is SEARCH_BATCH_JOB_GET_ACTION


@pytest.mark.asyncio
async def test_create_annotation_from_search_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    recording_id = uuid4()
    tag_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    now = datetime(2026, 5, 24, tzinfo=UTC)

    async def fake_create(**kwargs: object) -> DetectionResponse:
        captured.update(kwargs)
        return DetectionResponse(
            id=uuid4(),
            recording_id=recording_id,
            tag_id=tag_id,
            detection_run_id=None,
            source=DetectionSource.SIMILARITY_SEARCH,
            status=DetectionStatus.CONFIRMED,
            confidence=0.9,
            start_time=0.0,
            end_time=1.0,
            freq_low=None,
            freq_high=None,
            reviewed_by_id=None,
            reviewed_at=None,
            created_at=now,
            updated_at=now,
        )

    monkeypatch.setattr(
        legacy_search_annotations, "create_search_annotation", fake_create
    )
    monkeypatch.setattr(
        bff_search, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/annotations",
            json={
                "recording_id": str(recording_id),
                "tag_id": str(tag_id),
                "start_time": 0.0,
                "end_time": 1.0,
                "confidence": 0.9,
            },
        )

    assert response.status_code == 201, response.text
    assert captured["project_id"] == project_id
    assert gate_captured["action"] is SEARCH_ANNOTATION_ACTION


@pytest.mark.asyncio
async def test_list_search_sessions_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_list(**kwargs: object) -> SearchSessionListResponse:
        captured.update(kwargs)
        return SearchSessionListResponse(sessions=[], total=0)

    monkeypatch.setattr(legacy_search_sessions, "list_search_sessions", fake_list)
    monkeypatch.setattr(
        bff_search, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/search/sessions?limit=10&offset=5"
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["limit"] == 10
    assert captured["offset"] == 5
    assert gate_captured["action"] is SEARCH_SESSION_LIST_ACTION


@pytest.mark.asyncio
async def test_get_search_session_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    session_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_get(**kwargs: object) -> SearchSessionResponse:
        captured.update(kwargs)
        return _fake_session_response(
            project_id=project_id, session_id=session_id
        )

    monkeypatch.setattr(legacy_search_sessions, "get_search_session", fake_get)
    monkeypatch.setattr(
        bff_search, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/search/sessions/{session_id}"
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["session_id"] == session_id
    assert gate_captured["action"] is SEARCH_SESSION_GET_ACTION


@pytest.mark.asyncio
async def test_delete_search_session_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    session_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    from fastapi import Response as FastAPIResponse

    async def fake_delete(**kwargs: object) -> FastAPIResponse:
        captured.update(kwargs)
        return FastAPIResponse(status_code=204)

    monkeypatch.setattr(
        legacy_search_sessions, "delete_search_session", fake_delete
    )
    monkeypatch.setattr(
        bff_search, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.delete(
            f"/web-api/v1/projects/{project_id}/search/sessions/{session_id}"
        )

    assert response.status_code == 204, response.text
    assert captured["project_id"] == project_id
    assert captured["session_id"] == session_id
    assert gate_captured["action"] is SEARCH_SESSION_DELETE_ACTION


@pytest.mark.asyncio
async def test_update_search_session_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    session_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_update(**kwargs: object) -> SearchSessionResponse:
        captured.update(kwargs)
        return _fake_session_response(
            project_id=project_id, session_id=session_id
        )

    monkeypatch.setattr(
        legacy_search_sessions, "update_search_session", fake_update
    )
    monkeypatch.setattr(
        bff_search, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.patch(
            f"/web-api/v1/projects/{project_id}/search/sessions/{session_id}",
            json={"name": "renamed"},
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["session_id"] == session_id
    assert captured["name"] == "renamed"
    assert gate_captured["action"] is SEARCH_SESSION_UPDATE_ACTION


@pytest.mark.asyncio
async def test_rerun_search_session_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    session_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_rerun(**kwargs: object) -> SearchJobAcceptedResponse:
        captured.update(kwargs)
        return SearchJobAcceptedResponse(
            job_id="rerun-uuid", status="pending", session_id=session_id
        )

    monkeypatch.setattr(
        legacy_search_sessions, "rerun_search_session", fake_rerun
    )
    monkeypatch.setattr(
        bff_search, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.put(
            f"/web-api/v1/projects/{project_id}/search/sessions/{session_id}/rerun",
            data={"metadata": '{"species": [], "model_name": "perch"}'},
        )

    assert response.status_code == 202, response.text
    assert captured["project_id"] == project_id
    assert captured["session_id"] == session_id
    assert gate_captured["action"] is SEARCH_SESSION_RERUN_ACTION


@pytest.mark.asyncio
async def test_get_session_distribution_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    session_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_dist(**kwargs: object) -> SessionDistributionResponse:
        captured.update(kwargs)
        return SessionDistributionResponse(
            session_id=session_id, bins=[], total_count=0
        )

    monkeypatch.setattr(
        legacy_search_sessions,
        "get_session_similarity_distribution",
        fake_dist,
    )
    monkeypatch.setattr(
        bff_search, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/search/sessions/{session_id}"
            "/distribution?bin_width=0.1"
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["session_id"] == session_id
    assert captured["bin_width"] == pytest.approx(0.1)
    assert gate_captured["action"] is SEARCH_SESSION_DISTRIBUTION_ACTION


@pytest.mark.asyncio
async def test_get_session_time_distribution_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    session_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_time(
        **kwargs: object,
    ) -> SessionTimeDistributionResponse:
        captured.update(kwargs)
        return SessionTimeDistributionResponse(
            session_id=session_id, cells=[], timezone="UTC"
        )

    monkeypatch.setattr(
        legacy_search_sessions, "get_session_time_distribution", fake_time
    )
    monkeypatch.setattr(
        bff_search, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/search/sessions/{session_id}"
            "/time-distribution"
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["session_id"] == session_id
    assert (
        gate_captured["action"] is SEARCH_SESSION_TIME_DISTRIBUTION_ACTION
    )


@pytest.mark.asyncio
async def test_get_session_sample_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    session_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_sample(**kwargs: object) -> SessionSampleResponse:
        captured.update(kwargs)
        return SessionSampleResponse(
            session_id=session_id, results=[], total_in_range=0
        )

    monkeypatch.setattr(
        legacy_search_sessions, "sample_session_similarity_range", fake_sample
    )
    monkeypatch.setattr(
        bff_search, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/search/sessions/{session_id}"
            "/sample?min_similarity=0.3&max_similarity=0.8&limit=5"
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["session_id"] == session_id
    assert captured["min_similarity"] == pytest.approx(0.3)
    assert captured["max_similarity"] == pytest.approx(0.8)
    assert captured["limit"] == 5
    assert gate_captured["action"] is SEARCH_SESSION_SAMPLE_ACTION


@pytest.mark.asyncio
async def test_export_session_csv_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    session_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_export(**kwargs: object) -> StreamingResponse:
        captured.update(kwargs)
        return StreamingResponse(
            iter([b"a,b\n"]),
            media_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="session.csv"'
            },
        )

    monkeypatch.setattr(
        legacy_search_sessions, "export_search_session_csv", fake_export
    )
    monkeypatch.setattr(
        bff_search, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/search/sessions/{session_id}"
            "/export/csv"
        )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert "session.csv" in response.headers["content-disposition"]
    assert captured["project_id"] == project_id
    assert captured["session_id"] == session_id
    assert gate_captured["action"] is SEARCH_SESSION_EXPORT_CSV_ACTION


@pytest.mark.asyncio
async def test_export_session_recordings_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    session_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_export(**kwargs: object) -> StreamingResponse:
        captured.update(kwargs)
        return StreamingResponse(
            iter([b"a,b\n"]),
            media_type="text/csv",
            headers={
                "Content-Disposition": 'attachment; filename="recordings.csv"'
            },
        )

    monkeypatch.setattr(
        legacy_search_sessions,
        "export_search_session_recordings_csv",
        fake_export,
    )
    monkeypatch.setattr(
        bff_search, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/search/sessions/{session_id}"
            "/export-recordings?locale=ja"
        )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert "recordings.csv" in response.headers["content-disposition"]
    assert captured["project_id"] == project_id
    assert captured["session_id"] == session_id
    assert captured["locale"] == "ja"
    assert (
        gate_captured["action"] is SEARCH_SESSION_EXPORT_RECORDINGS_ACTION
    )


# ---------------------------------------------------------------------------
# Reference audio (media-token surface, W2-4 PR-B)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reference_audio_media_token_bff_gates_and_issues_scoped_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reference-audio media-token endpoint issues a session+index token."""
    project_id = uuid4()
    session_id = uuid4()
    user = SimpleNamespace(id=uuid4(), security_stamp="ref-audio-stamp")

    class _Service:
        async def get_session(self, sid: object, pid: object) -> object:
            return SimpleNamespace(
                id=sid,
                project_id=pid,
                reference_audio_keys=["k0", "k1", "k2"],
            )

    service = _Service()
    gate_captured: dict[str, object] = {}

    monkeypatch.setattr(
        bff_search, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/search/sessions/{session_id}"
            "/reference-audio/1/media-token"
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["expires_in"] > 0
    assert gate_captured["action"] is SEARCH_SESSION_REFERENCE_AUDIO_ACTION

    claims = verify_media_token(
        body["token"],
        current_security_stamp=user.security_stamp,
        project_id=project_id,
        resource_type="search_session",
        resource_id=session_id,
        scope="audio",
        source_index=1,
    )
    assert claims.user_id == user.id
    assert claims.resource_type == "search_session"
    assert claims.source_index == 1


@pytest.mark.asyncio
async def test_reference_audio_media_token_bff_out_of_range_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An out-of-range source index returns 404 (anti-enumeration)."""
    project_id = uuid4()
    session_id = uuid4()
    user = SimpleNamespace(id=uuid4(), security_stamp="ref-audio-stamp")

    class _Service:
        async def get_session(self, sid: object, pid: object) -> object:
            return SimpleNamespace(
                id=sid,
                project_id=pid,
                reference_audio_keys=["only-one"],
            )

    service = _Service()
    gate_captured: dict[str, object] = {}

    monkeypatch.setattr(
        bff_search, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/search/sessions/{session_id}"
            "/reference-audio/5/media-token"
        )

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Reference audio not found"


@pytest.mark.asyncio
async def test_reference_audio_media_token_bff_missing_session_404(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing session returns 404 with the same anti-enumeration detail."""
    project_id = uuid4()
    session_id = uuid4()
    user = SimpleNamespace(id=uuid4(), security_stamp="ref-audio-stamp")

    class _Service:
        async def get_session(self, sid: object, pid: object) -> object:
            return None

    service = _Service()
    gate_captured: dict[str, object] = {}

    monkeypatch.setattr(
        bff_search, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/search/sessions/{session_id}"
            "/reference-audio/0/media-token"
        )

    assert response.status_code == 404, response.text
    assert response.json()["detail"] == "Reference audio not found"


@pytest.mark.asyncio
async def test_stream_reference_audio_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reference-audio streaming GET gates + delegates to the legacy handler."""
    project_id = uuid4()
    session_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_stream(**kwargs: object) -> StreamingResponse:
        captured.update(kwargs)
        return StreamingResponse(
            iter([b"audio-bytes"]),
            media_type="audio/wav",
            headers={"Accept-Ranges": "bytes"},
        )

    monkeypatch.setattr(
        legacy_search_sessions, "stream_reference_audio", fake_stream
    )
    monkeypatch.setattr(
        bff_search, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/search/sessions/{session_id}"
            "/reference-audio/2"
        )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("audio/")
    assert captured["project_id"] == project_id
    assert captured["session_id"] == session_id
    assert captured["source_index"] == 2
    assert captured["session_service"] is service
    assert gate_captured["action"] is SEARCH_SESSION_REFERENCE_AUDIO_ACTION


# ---------------------------------------------------------------------------
# OpenAPI surface declaration
# ---------------------------------------------------------------------------


def test_search_bff_paths_declared_in_openapi() -> None:
    app = _build_app(user=SimpleNamespace(id=uuid4()), service=object())
    paths = app.openapi()["paths"]

    project_prefix = "/web-api/v1/projects/{project_id}"

    assert "get" in paths[f"{project_prefix}/search/embedding-stats"]
    assert "get" in paths[f"{project_prefix}/xeno-canto/search"]
    assert "get" in paths[f"{project_prefix}/xeno-canto/audio/{{xc_id}}"]
    assert "get" in paths[f"{project_prefix}/xeno-canto/sonogram"]
    assert "post" in paths[f"{project_prefix}/search/batch"]
    assert "get" in paths[f"{project_prefix}/search/jobs/{{job_id}}"]
    assert "post" in paths[f"{project_prefix}/annotations"]
    assert "get" in paths[f"{project_prefix}/search/sessions"]

    session_path = f"{project_prefix}/search/sessions/{{session_id}}"
    assert "get" in paths[session_path]
    assert "patch" in paths[session_path]
    assert "delete" in paths[session_path]
    assert "put" in paths[f"{session_path}/rerun"]
    assert "get" in paths[f"{session_path}/distribution"]
    assert "get" in paths[f"{session_path}/time-distribution"]
    assert "get" in paths[f"{session_path}/sample"]
    assert "get" in paths[f"{session_path}/export/csv"]
    assert "get" in paths[f"{session_path}/export-recordings"]

    ref_audio_path = f"{session_path}/reference-audio/{{source_index}}"
    assert "get" in paths[ref_audio_path]
    assert "post" in paths[f"{ref_audio_path}/media-token"]


# ---------------------------------------------------------------------------
# API-key cross-rejection sweep (D-2a #3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_bff_paths_reject_api_key_bearer(
    client: AsyncClient,
) -> None:
    project_id = uuid4()
    session_id = uuid4()
    job_id = "job-id"

    project_prefix = f"/web-api/v1/projects/{project_id}"

    await assert_api_key_cross_rejected(
        client, "GET", f"{project_prefix}/search/embedding-stats"
    )
    await assert_api_key_cross_rejected(
        client, "GET", f"{project_prefix}/xeno-canto/search?query=Larus"
    )
    await assert_api_key_cross_rejected(
        client, "GET", f"{project_prefix}/xeno-canto/audio/1"
    )
    await assert_api_key_cross_rejected(
        client, "POST", f"{project_prefix}/search/batch"
    )
    await assert_api_key_cross_rejected(
        client, "GET", f"{project_prefix}/search/jobs/{job_id}"
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"{project_prefix}/annotations",
        body={
            "recording_id": str(uuid4()),
            "tag_id": str(uuid4()),
            "start_time": 0.0,
            "end_time": 1.0,
        },
    )
    await assert_api_key_cross_rejected(
        client, "GET", f"{project_prefix}/search/sessions"
    )
    await assert_api_key_cross_rejected(
        client, "GET", f"{project_prefix}/search/sessions/{session_id}"
    )
    await assert_api_key_cross_rejected(
        client, "DELETE", f"{project_prefix}/search/sessions/{session_id}"
    )
    await assert_api_key_cross_rejected(
        client,
        "PATCH",
        f"{project_prefix}/search/sessions/{session_id}",
        body={"name": "x"},
    )
    await assert_api_key_cross_rejected(
        client,
        "PUT",
        f"{project_prefix}/search/sessions/{session_id}/rerun",
    )
    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"{project_prefix}/search/sessions/{session_id}/distribution",
    )
    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"{project_prefix}/search/sessions/{session_id}/time-distribution",
    )
    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"{project_prefix}/search/sessions/{session_id}/sample",
    )
    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"{project_prefix}/search/sessions/{session_id}/export/csv",
    )
    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"{project_prefix}/search/sessions/{session_id}/export-recordings",
    )
    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"{project_prefix}/search/sessions/{session_id}/reference-audio/0",
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"{project_prefix}/search/sessions/{session_id}/reference-audio/0/media-token",
    )

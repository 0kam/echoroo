"""Smoke coverage for the annotation + detection vote BFF adapters.

Spec/009 PR 3a moved the generic annotation-vote endpoints (used by
search-result review screens where annotations are created on the fly
and are not tied to a detection-run) from ``/api/v1`` to ``/web-api/v1``.
W2-1 extends the same pattern to the detection-vote path
(``/detections/{id}/votes`` — used by the detection review grid), which
delegates to the legacy ``detections.py`` handlers under cookie + CSRF
gating.

HONESTY NOTE: the ``*_bff_delegates_to_legacy`` tests **monkeypatch** the
legacy handler and assert on the kwargs the BFF forwards. They verify the
transport wiring (route → gate_action → correct legacy callable with the
right kwargs), NOT real DB-backed delegation. The legacy handler's own
BOLA guard, voter classification, response masking, and consensus
recomputation are covered by the legacy ``/api/v1`` handler's own tests
and are intentionally out of scope here (W2-1 is transport-only).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from echoroo.api.v1 import annotation_votes as legacy_annotation_votes
from echoroo.api.v1 import detections as legacy_detections
from echoroo.api.web_v1.projects import _votes as bff_votes
from echoroo.core.actions import (
    ANNOTATION_VOTE_CREATE_ACTION,
    ANNOTATION_VOTE_LIST_ACTION,
)
from echoroo.core.database import get_db
from echoroo.middleware.auth import get_current_user
from echoroo.models.enums import DetectionStatus
from echoroo.schemas.annotation_vote import VoteSummaryResponse
from tests.integration.api.web_v1._helpers import assert_api_key_cross_rejected


def _fake_vote_summary(*, annotation_id: UUID) -> VoteSummaryResponse:
    return VoteSummaryResponse(
        annotation_id=annotation_id,
        agree_count=0,
        disagree_count=0,
        unsure_count=0,
        user_vote=None,
        user_signal_quality=None,
        signal_quality_counts={},
        consensus_status=DetectionStatus.UNREVIEWED,
        voters=[],
    )


async def _fake_db() -> AsyncIterator[object]:
    yield object()


def _make_capturing_gate_action(captured: dict[str, object]) -> Any:
    async def fake(**kwargs: object) -> object:
        captured.update(kwargs)
        return object()

    return fake


def _build_app(*, user: object, service: object) -> FastAPI:
    app = FastAPI()
    app.include_router(bff_votes.router, prefix="/web-api/v1/projects")
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[legacy_annotation_votes.get_vote_service] = (
        lambda: service
    )
    # The detection-vote adapters inject ``legacy_detections.VoteServiceDep``,
    # a DIFFERENT dependency callable from the annotation-votes module above.
    # Without this override the new endpoints would hit a real DB session.
    app.dependency_overrides[legacy_detections.get_vote_service] = (
        lambda: service
    )
    return app


@pytest.mark.asyncio
async def test_vote_summary_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    annotation_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_get_votes(**kwargs: object) -> VoteSummaryResponse:
        captured.update(kwargs)
        return _fake_vote_summary(annotation_id=annotation_id)

    monkeypatch.setattr(
        legacy_annotation_votes, "get_annotation_votes", fake_get_votes
    )
    monkeypatch.setattr(
        bff_votes, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/annotations/{annotation_id}/votes"
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["annotation_id"] == annotation_id
    assert captured["current_user"] is user
    assert captured["vote_service"] is service
    assert gate_captured["action"] is ANNOTATION_VOTE_LIST_ACTION


@pytest.mark.asyncio
async def test_vote_cast_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    annotation_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_cast_vote(**kwargs: object) -> VoteSummaryResponse:
        captured.update(kwargs)
        return _fake_vote_summary(annotation_id=annotation_id)

    monkeypatch.setattr(
        legacy_annotation_votes, "cast_annotation_vote", fake_cast_vote
    )
    monkeypatch.setattr(
        bff_votes, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/annotations/{annotation_id}/votes",
            json={"vote": "agree"},
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["annotation_id"] == annotation_id
    payload = captured["request"]
    assert isinstance(payload, legacy_annotation_votes.VoteCastRequest)
    assert payload.vote.value == "agree"
    assert gate_captured["action"] is ANNOTATION_VOTE_CREATE_ACTION


@pytest.mark.asyncio
async def test_vote_delete_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    annotation_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_delete_vote(**kwargs: object) -> VoteSummaryResponse:
        captured.update(kwargs)
        return _fake_vote_summary(annotation_id=annotation_id)

    monkeypatch.setattr(
        legacy_annotation_votes, "delete_annotation_vote", fake_delete_vote
    )
    monkeypatch.setattr(
        bff_votes, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.delete(
            f"/web-api/v1/projects/{project_id}/annotations/{annotation_id}/votes"
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["annotation_id"] == annotation_id
    assert gate_captured["action"] is ANNOTATION_VOTE_CREATE_ACTION


def test_vote_bff_paths_declared_in_openapi() -> None:
    app = _build_app(user=SimpleNamespace(id=uuid4()), service=object())
    paths = app.openapi()["paths"]

    votes_path = (
        "/web-api/v1/projects/{project_id}/annotations/{annotation_id}/votes"
    )
    assert "get" in paths[votes_path]
    assert "post" in paths[votes_path]
    assert "delete" in paths[votes_path]


@pytest.mark.asyncio
async def test_vote_bff_paths_reject_api_key_bearer(
    client: AsyncClient,
) -> None:
    project_id = uuid4()
    annotation_id = uuid4()

    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"/web-api/v1/projects/{project_id}/annotations/{annotation_id}/votes",
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"/web-api/v1/projects/{project_id}/annotations/{annotation_id}/votes",
        body={"vote": "agree"},
    )
    await assert_api_key_cross_rejected(
        client,
        "DELETE",
        f"/web-api/v1/projects/{project_id}/annotations/{annotation_id}/votes",
    )


@pytest.mark.asyncio
async def test_detection_vote_summary_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    detection_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_get_votes(**kwargs: object) -> VoteSummaryResponse:
        captured.update(kwargs)
        return _fake_vote_summary(annotation_id=detection_id)

    # Monkeypatch the legacy handler: this asserts the BFF forwards the
    # correct kwargs (transport wiring), not real DB delegation.
    monkeypatch.setattr(legacy_detections, "get_votes", fake_get_votes)
    monkeypatch.setattr(
        bff_votes, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get(
            f"/web-api/v1/projects/{project_id}/detections/{detection_id}/votes"
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["detection_id"] == detection_id
    assert captured["current_user"] is user
    assert captured["vote_service"] is service
    assert gate_captured["action"] is ANNOTATION_VOTE_LIST_ACTION


@pytest.mark.asyncio
async def test_detection_vote_cast_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    detection_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_cast_vote(**kwargs: object) -> VoteSummaryResponse:
        captured.update(kwargs)
        return _fake_vote_summary(annotation_id=detection_id)

    # Monkeypatch the legacy handler: this asserts the BFF forwards the
    # correct kwargs (transport wiring), not real DB delegation.
    monkeypatch.setattr(legacy_detections, "cast_vote", fake_cast_vote)
    monkeypatch.setattr(
        bff_votes, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.post(
            f"/web-api/v1/projects/{project_id}/detections/{detection_id}/votes",
            json={"vote": "agree"},
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["detection_id"] == detection_id
    assert captured["current_user"] is user
    assert captured["vote_service"] is service
    payload = captured["request"]
    assert isinstance(payload, legacy_detections.VoteCastRequest)
    assert payload.vote.value == "agree"
    assert gate_captured["action"] is ANNOTATION_VOTE_CREATE_ACTION


@pytest.mark.asyncio
async def test_detection_vote_delete_bff_delegates_to_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()
    detection_id = uuid4()
    user = SimpleNamespace(id=uuid4())
    service = object()
    captured: dict[str, object] = {}
    gate_captured: dict[str, object] = {}

    async def fake_delete_vote(**kwargs: object) -> VoteSummaryResponse:
        captured.update(kwargs)
        return _fake_vote_summary(annotation_id=detection_id)

    # Monkeypatch the legacy handler: this asserts the BFF forwards the
    # correct kwargs (transport wiring), not real DB delegation.
    monkeypatch.setattr(legacy_detections, "delete_vote", fake_delete_vote)
    monkeypatch.setattr(
        bff_votes, "gate_action", _make_capturing_gate_action(gate_captured)
    )

    app = _build_app(user=user, service=service)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.delete(
            f"/web-api/v1/projects/{project_id}/detections/{detection_id}/votes"
        )

    assert response.status_code == 200, response.text
    assert captured["project_id"] == project_id
    assert captured["detection_id"] == detection_id
    assert captured["current_user"] is user
    assert captured["vote_service"] is service
    assert gate_captured["action"] is ANNOTATION_VOTE_CREATE_ACTION


def test_detection_vote_bff_paths_declared_in_openapi() -> None:
    app = _build_app(user=SimpleNamespace(id=uuid4()), service=object())
    paths = app.openapi()["paths"]

    votes_path = (
        "/web-api/v1/projects/{project_id}/detections/{detection_id}/votes"
    )
    assert "get" in paths[votes_path]
    assert "post" in paths[votes_path]
    assert "delete" in paths[votes_path]


@pytest.mark.asyncio
async def test_detection_vote_bff_paths_reject_api_key_bearer(
    client: AsyncClient,
) -> None:
    project_id = uuid4()
    detection_id = uuid4()

    await assert_api_key_cross_rejected(
        client,
        "GET",
        f"/web-api/v1/projects/{project_id}/detections/{detection_id}/votes",
    )
    await assert_api_key_cross_rejected(
        client,
        "POST",
        f"/web-api/v1/projects/{project_id}/detections/{detection_id}/votes",
        body={"vote": "agree"},
    )
    await assert_api_key_cross_rejected(
        client,
        "DELETE",
        f"/web-api/v1/projects/{project_id}/detections/{detection_id}/votes",
    )

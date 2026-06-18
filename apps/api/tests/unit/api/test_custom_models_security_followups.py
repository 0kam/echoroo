"""Security follow-up tests for custom model handlers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.api.v1 import custom_models as custom_models_api
from echoroo.middleware.auth import CurrentUser
from echoroo.schemas.custom_model import CustomModelCreate, CustomModelResponse
from echoroo.services.custom_model import CustomModelService


async def _noop_gate_action(**_kwargs: object) -> None:
    return None


@pytest.mark.asyncio
async def test_create_custom_model_rejects_unknown_target_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A target_tag_id absent from the project must 404, never reach the FK (500)."""

    lookup_calls: list[tuple[object, object]] = []

    class _TagRepository:
        def __init__(self, _db: object) -> None:
            pass

        async def get_by_id_in_project(self, tag_id: object, project_id: object) -> None:
            lookup_calls.append((tag_id, project_id))
            return None

    create_model = AsyncMock()
    service = cast(CustomModelService, SimpleNamespace(create_model=create_model))

    monkeypatch.setattr(custom_models_api, "gate_action", _noop_gate_action)
    monkeypatch.setattr(custom_models_api, "TagRepository", _TagRepository)

    project_id = uuid4()
    target_tag_id = uuid4()

    with pytest.raises(HTTPException) as exc_info:
        await custom_models_api.create_custom_model(
            project_id=project_id,
            request_body=CustomModelCreate(name="m", target_tag_id=target_tag_id),
            request=cast(Request, SimpleNamespace()),
            current_user=cast(CurrentUser, SimpleNamespace(id=uuid4())),
            db=cast(AsyncSession, SimpleNamespace()),
            service=service,
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Target tag not found"
    # The 404 must come from a project-scoped lookup with the exact identifiers,
    # not an unscoped/oracle query, before any create work is attempted.
    assert lookup_calls == [(target_tag_id, project_id)]
    create_model.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_custom_model_accepts_valid_target_tag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A target_tag_id present in the project must reach the create service path."""

    lookup_calls: list[tuple[object, object]] = []

    class _TagRepository:
        def __init__(self, _db: object) -> None:
            pass

        async def get_by_id_in_project(self, tag_id: object, project_id: object) -> object:
            lookup_calls.append((tag_id, project_id))
            return SimpleNamespace()

    model = SimpleNamespace()
    create_model = AsyncMock(return_value=model)
    service = cast(CustomModelService, SimpleNamespace(create_model=create_model))

    monkeypatch.setattr(custom_models_api, "gate_action", _noop_gate_action)
    monkeypatch.setattr(custom_models_api, "TagRepository", _TagRepository)
    monkeypatch.setattr(
        CustomModelResponse,
        "model_validate",
        classmethod(lambda _cls, _model: SimpleNamespace()),
    )

    project_id = uuid4()
    target_tag_id = uuid4()

    await custom_models_api.create_custom_model(
        project_id=project_id,
        request_body=CustomModelCreate(name="m", target_tag_id=target_tag_id),
        request=cast(Request, SimpleNamespace()),
        current_user=cast(CurrentUser, SimpleNamespace(id=uuid4())),
        db=cast(AsyncSession, SimpleNamespace()),
        service=service,
    )

    # The BOLA guard must scope the existence check to the request's project,
    # passing the exact (target_tag_id, project_id) it received.
    assert lookup_calls == [(target_tag_id, project_id)]
    create_model.assert_awaited_once()


@pytest.mark.asyncio
async def test_list_custom_models_rejects_cross_project_search_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Filtering by another project's search session must not become an oracle."""

    class _SearchSessionRepository:
        def __init__(self, _db: object) -> None:
            pass

        async def exists_in_project(self, _session_id: object, _project_id: object) -> bool:
            return False

    list_models = AsyncMock(return_value=([], 0))
    service = cast(CustomModelService, SimpleNamespace(list_models=list_models))

    monkeypatch.setattr(custom_models_api, "gate_action", _noop_gate_action)
    monkeypatch.setattr(custom_models_api, "SearchSessionRepository", _SearchSessionRepository)

    with pytest.raises(HTTPException) as exc_info:
        await custom_models_api.list_custom_models(
            project_id=uuid4(),
            request=cast(Request, SimpleNamespace()),
            current_user=cast(CurrentUser, SimpleNamespace(id=uuid4())),
            db=cast(AsyncSession, SimpleNamespace()),
            service=service,
            search_session_id=uuid4(),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "Search session not found"
    list_models.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_custom_model_uses_single_project_scoped_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The endpoint should not preflight with a second custom-model SELECT."""

    model = SimpleNamespace()
    service = cast(
        CustomModelService,
        SimpleNamespace(get_model_or_404=AsyncMock(return_value=model)),
    )

    monkeypatch.setattr(custom_models_api, "gate_action", _noop_gate_action)
    monkeypatch.setattr(
        CustomModelResponse,
        "model_validate",
        classmethod(lambda _cls, _model: SimpleNamespace()),
    )

    project_id = uuid4()
    model_id = uuid4()

    await custom_models_api.get_custom_model(
        project_id=project_id,
        model_id=model_id,
        request=cast(Request, SimpleNamespace()),
        current_user=cast(CurrentUser, SimpleNamespace(id=uuid4())),
        db=cast(AsyncSession, SimpleNamespace()),
        service=service,
    )

    cast(Any, service.get_model_or_404).assert_awaited_once_with(model_id, project_id)

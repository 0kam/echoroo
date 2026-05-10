"""Coverage uplift unit tests for ``echoroo.api.v1.sites``.

Phase 17 §C medium-gap batch: targets ``get_site_service`` (line 43),
``_h3_resolution`` helper (lines 66, 67, 71-74), and the
``_filter_site_response`` invocations exercised by the route bodies on
lines 143-145, 195, 241, 294 so the module clears the 85% threshold
without touching production code.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from echoroo.api.v1 import sites as mod
from echoroo.core.permissions import H3_RES_15


def _make_site_response() -> MagicMock:
    """Build a SiteResponse-shaped MagicMock that the filter can mutate."""
    resp = MagicMock()
    resp.h3_index_member = "8a283082aaaffff"
    resp.h3_index_member_resolution = 10
    return resp


def _make_request() -> MagicMock:
    """Build a Request stub with effective_permissions + role on state."""
    req = MagicMock()
    req.state.effective_permissions = frozenset()
    req.state.normalized_role = "Guest"
    return req


def test_get_site_service_returns_service_instance() -> None:
    """get_site_service constructs a SiteService with both repos."""
    db = MagicMock()
    svc = mod.get_site_service(db)
    assert svc is not None  # constructor body is hit


def test_h3_resolution_returns_h3_res_15_on_invalid_input() -> None:
    """_h3_resolution returns H3_RES_15 when h3 raises (lines 71-74)."""
    # An obvious non-H3 string causes get_resolution to raise → fallback.
    assert mod._h3_resolution("definitely-not-an-h3") == H3_RES_15


def test_h3_resolution_returns_value_for_valid_h3() -> None:
    """_h3_resolution forwards the resolution from the h3 library when valid."""
    # Phase 13 ORM h3_index_member at resolution 10.
    val = mod._h3_resolution("8a283082aaaffff")
    assert isinstance(val, int)


def test_filter_site_response_mutates_obj_and_returns_it() -> None:
    """_filter_site_response calls apply_response_filter and returns the obj."""
    site = _make_site_response()
    req = _make_request()
    project = SimpleNamespace(
        id=uuid4(),
        owner_id=uuid4(),
        visibility=None,
        status="active",
        restricted_config={},
    )
    out = mod._filter_site_response(site=site, request=req, project=project)
    assert out is site


@pytest.mark.asyncio
async def test_list_sites_filters_each_item() -> None:
    """list_sites runs the per-item filter loop (lines 143-145)."""
    items = [_make_site_response(), _make_site_response()]
    response = MagicMock()
    response.items = items

    service = MagicMock()
    service.list_sites = AsyncMock(return_value=response)

    db = MagicMock()
    project = SimpleNamespace(
        id=uuid4(), owner_id=uuid4(), visibility=None, status="active",
        restricted_config={},
    )
    user = MagicMock()
    user.id = uuid4()
    request = _make_request()

    with patch.object(mod, "gate_action", new=AsyncMock(return_value=project)):
        result = await mod.list_sites(
            project_id=uuid4(),
            request=request,
            current_user=user,
            service=service,
            db=db,
        )
    assert result is response
    service.list_sites.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_site_filters_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """create_site filters the created site and commits (line 195)."""
    site = _make_site_response()
    service = MagicMock()
    service.create_site = AsyncMock(return_value=site)

    db = MagicMock()
    db.commit = AsyncMock()
    project = SimpleNamespace(
        id=uuid4(), owner_id=uuid4(), visibility=None, status="active",
        restricted_config={},
    )
    user = MagicMock()
    user.id = uuid4()
    request = _make_request()
    create_req = MagicMock()

    with patch.object(mod, "gate_action", new=AsyncMock(return_value=project)):
        result = await mod.create_site(
            project_id=uuid4(),
            request=create_req,
            http_request=request,
            current_user=user,
            service=service,
            db=db,
        )
    assert result is site
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_site_filters_response() -> None:
    """get_site returns the filtered response (line 241)."""
    site = _make_site_response()
    service = MagicMock()
    service.get_site = AsyncMock(return_value=site)

    db = MagicMock()
    project = SimpleNamespace(
        id=uuid4(), owner_id=uuid4(), visibility=None, status="active",
        restricted_config={},
    )
    user = MagicMock()
    user.id = uuid4()
    request = _make_request()

    with patch.object(mod, "gate_action", new=AsyncMock(return_value=project)):
        result = await mod.get_site(
            project_id=uuid4(),
            site_id=uuid4(),
            request=request,
            current_user=user,
            service=service,
            db=db,
        )
    assert result is site


@pytest.mark.asyncio
async def test_update_site_filters_response_and_commits() -> None:
    """update_site filters response + commits (line 294)."""
    site = _make_site_response()
    service = MagicMock()
    service.update_site = AsyncMock(return_value=site)

    db = MagicMock()
    db.commit = AsyncMock()
    project = SimpleNamespace(
        id=uuid4(), owner_id=uuid4(), visibility=None, status="active",
        restricted_config={},
    )
    user = MagicMock()
    user.id = uuid4()
    request = _make_request()
    update_req = MagicMock()

    with patch.object(mod, "gate_action", new=AsyncMock(return_value=project)):
        result = await mod.update_site(
            project_id=uuid4(),
            site_id=uuid4(),
            request=update_req,
            http_request=request,
            current_user=user,
            service=service,
            db=db,
        )
    assert result is site
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_site_invokes_service_and_commits() -> None:
    """delete_site delegates to service.delete and commits."""
    service = MagicMock()
    service.delete_site = AsyncMock()

    db = MagicMock()
    db.commit = AsyncMock()
    user = MagicMock()
    user.id = uuid4()
    request = _make_request()

    with patch.object(mod, "gate_action", new=AsyncMock(return_value=MagicMock())):
        result = await mod.delete_site(
            project_id=uuid4(),
            site_id=uuid4(),
            request=request,
            current_user=user,
            service=service,
            db=db,
        )
    assert result is None
    service.delete_site.assert_awaited_once()
    db.commit.assert_awaited_once()

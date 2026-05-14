"""Spec/009 PR C coverage for taxa BFF search endpoints."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from echoroo.core.settings import get_settings
from echoroo.models.taxon import Taxon
from echoroo.models.taxon_vernacular_name import TaxonVernacularName
from echoroo.models.user import User
from tests.integration.api.web_v1._helpers import (
    assert_api_key_cross_rejected,
    assert_legacy_v1_rejects_bff_token,
    assert_rate_limit_bucket_web,
)
from tests.integration.api.web_v1.test_projects_read_smoke import (
    _create_user,
    _seed_refresh_token,
)


async def _bff_session_headers(
    client: AsyncClient,
    db: AsyncSession,
    user: User,
) -> dict[str, str]:
    client.cookies.clear()
    refresh_token = await _seed_refresh_token(db, user)
    response = await client.post(
        "/web-api/v1/auth/refresh",
        cookies={get_settings().web_refresh_cookie_name: refresh_token},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _seed_taxon(db: AsyncSession) -> Taxon:
    taxon = Taxon(
        scientific_name="Spec009 Taxa Cyanistes caeruleus",
        gbif_taxon_key=2473958,
        rank="SPECIES",
        is_non_biological=False,
    )
    db.add(taxon)
    await db.flush()
    db.add_all(
        [
            TaxonVernacularName(
                taxon_id=taxon.id,
                locale="en",
                name="Eurasian blue tit",
                source="gbif",
                is_primary=True,
            ),
            TaxonVernacularName(
                taxon_id=taxon.id,
                locale="ja",
                name="アオガラ",
                source="gbif",
                is_primary=True,
            ),
        ]
    )
    await db.commit()
    await db.refresh(taxon)
    return taxon


@pytest.mark.asyncio
async def test_taxa_search_bff_contract(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, email="spec009-prc-taxa@example.com")
    taxon = await _seed_taxon(db_session)
    headers = await _bff_session_headers(client, db_session, user)

    response = await client.get(
        "/web-api/v1/taxa/search",
        params={"q": "アオ", "locale": "ja", "limit": "5"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == [
        {
            "id": str(taxon.id),
            "scientific_name": taxon.scientific_name,
            "gbif_taxon_key": 2473958,
            "rank": "SPECIES",
            "is_non_biological": False,
            "common_name": "アオガラ",
        }
    ]
    assert_rate_limit_bucket_web(response)

    unauthenticated = await client.get(
        "/web-api/v1/taxa/search",
        params={"q": "アオ"},
    )
    assert unauthenticated.status_code == 401, unauthenticated.text

    await assert_api_key_cross_rejected(
        client,
        "GET",
        "/web-api/v1/taxa/search?q=Parus",
    )


@pytest.mark.asyncio
async def test_taxa_gbif_search_bff_contract(
    client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = await _create_user(db_session, email="spec009-prc-gbif@example.com")
    headers = await _bff_session_headers(client, db_session, user)

    gbif_search = AsyncMock(
        return_value=[
            {
                "gbif_key": 2492562,
                "scientific_name": "Parus major",
                "canonical_name": "Parus major",
                "rank": "SPECIES",
                "vernacular_name": "Great Tit",
                "vernacular_names": [{"name": "Great Tit", "language": "eng"}],
                "kingdom": "Animalia",
                "phylum": "Chordata",
                "class_name": "Aves",
                "order": "Passeriformes",
                "family": "Paridae",
            }
        ]
    )

    class _FakeGBIFService:
        search_species_full = gbif_search

    from echoroo.api.web_v1 import taxa as taxa_module

    monkeypatch.setattr(taxa_module, "GBIFService", _FakeGBIFService)

    response = await client.get(
        "/web-api/v1/taxa/gbif-search",
        params={"q": "great tit", "limit": "3"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()[0]["scientific_name"] == "Parus major"
    assert response.json()[0]["gbif_key"] == 2492562
    gbif_search.assert_awaited_once_with(query="great tit", limit=3)
    assert_rate_limit_bucket_web(response)

    await assert_api_key_cross_rejected(
        client,
        "GET",
        "/web-api/v1/taxa/gbif-search?q=Parus",
    )


@pytest.mark.asyncio
async def test_legacy_v1_taxa_rejects_bff_jwt(
    unshimmed_client: AsyncClient,
    bff_jwt_factory: Any,
    db_session: AsyncSession,
) -> None:
    user = await _create_user(db_session, email="spec009-prc-legacy@example.com")
    await assert_legacy_v1_rejects_bff_token(
        unshimmed_client,
        "GET",
        "/api/v1/taxa/search?q=Parus",
        bff_token=bff_jwt_factory(user_id=user.id),
    )

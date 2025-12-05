"""Tests for the species search endpoints."""

from fastapi.testclient import TestClient

from echoroo import schemas


async def test_species_search_returns_candidates(
    client: TestClient,
    monkeypatch,
):
    async def fake_search(query: str, limit: int = 10):
        assert query == "falco"
        assert limit == 5
        return [
            schemas.SpeciesCandidate(
                usage_key="123",
                canonical_name="Falco peregrinus",
                scientific_name="Falco peregrinus Tunstall, 1771",
                rank="SPECIES",
                synonym=False,
                dataset_key="fake-dataset",
            )
        ]

    monkeypatch.setattr(
        "echoroo.routes.species.api.search_gbif_species",
        fake_search,
    )

    response = client.get(
        "/api/v1/species/search/",
        params={"q": "falco", "limit": 5},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload == [
        {
            "usage_key": "123",
            "canonical_name": "Falco peregrinus",
            "scientific_name": "Falco peregrinus Tunstall, 1771",
            "rank": "SPECIES",
            "synonym": False,
            "dataset_key": "fake-dataset",
        }
    ]

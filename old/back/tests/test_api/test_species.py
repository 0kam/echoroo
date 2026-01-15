"""Tests for the species API helpers."""

import pytest

from echoroo.api import species as species_api
from echoroo import schemas


@pytest.mark.asyncio
async def test_search_gbif_species_accepts_key(monkeypatch):
    """Ensure GBIF responses using `key` are handled."""

    def fake_name_suggest(**kwargs):
        assert kwargs["q"] == "falco"
        assert kwargs["rank"] == "species"
        return [
            {
                "key": 123,
                "canonicalName": "Falco peregrinus",
                "rank": "SPECIES",
            },
            {
                "usageKey": 456,
                "canonicalName": "Falco naumanni",
                "rank": "SPECIES",
            },
        ]

    monkeypatch.setattr(
        species_api.gbif_species,
        "name_suggest",
        fake_name_suggest,
    )

    results = await species_api.search_gbif_species("falco", limit=2)

    assert [candidate.model_dump() for candidate in results] == [
        schemas.SpeciesCandidate(
            usage_key="123",
            canonical_name="Falco peregrinus",
            scientific_name=None,
            rank="SPECIES",
            synonym=False,
            dataset_key=None,
        ).model_dump(),
        schemas.SpeciesCandidate(
            usage_key="456",
            canonical_name="Falco naumanni",
            scientific_name=None,
            rank="SPECIES",
            synonym=False,
            dataset_key=None,
        ).model_dump(),
    ]

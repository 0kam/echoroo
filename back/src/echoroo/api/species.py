"""Utilities for interacting with external species catalogues."""

from __future__ import annotations

import asyncio
from typing import Iterable, Sequence

from pygbif import species as gbif_species

from echoroo import schemas

__all__ = ["search_gbif_species"]


def _extract_candidates(  # pragma: no cover - simple data parser
    payload: Sequence[dict],
) -> list[schemas.SpeciesCandidate]:
    candidates: list[schemas.SpeciesCandidate] = []
    for item in payload:
        usage_key = item.get("usageKey") or item.get("key")
        if usage_key is None:
            continue
        rank = (item.get("rank") or "").lower()
        if rank != "species":
            continue
        canonical = item.get("canonicalName") or item.get("scientificName")
        if canonical is None:
            continue
        candidates.append(
            schemas.SpeciesCandidate(
                usage_key=str(usage_key),
                canonical_name=canonical,
                scientific_name=item.get("scientificName"),
                rank=item.get("rank"),
                synonym=item.get("synonym", False),
                dataset_key=item.get("datasetKey"),
            )
        )
    # Remove duplicates by usage key while preserving order.
    unique: dict[str, schemas.SpeciesCandidate] = {}
    for candidate in candidates:
        if candidate.usage_key not in unique:
            unique[candidate.usage_key] = candidate
    return list(unique.values())


async def search_gbif_species(
    query: str,
    *,
    limit: int = 10,
) -> list[schemas.SpeciesCandidate]:
    """Search GBIF species suggestions asynchronously."""

    if not query.strip():
        return []

    loop = asyncio.get_running_loop()
    response: dict | Iterable[dict] | None = await loop.run_in_executor(
        None,
        lambda: gbif_species.name_suggest(  # type: ignore[arg-type]
            q=query,
            limit=limit,
            rank="species",
        ),
    )
    if response is None:
        return []

    payload: Sequence[dict]
    if isinstance(response, dict):
        payload = response.get("results", []) or []
    else:
        payload = list(response)

    return _extract_candidates(payload)

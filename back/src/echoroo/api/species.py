"""Utilities for interacting with external species catalogues."""

from __future__ import annotations

import asyncio
from typing import Any, Sequence

from pygbif import species as gbif_species

from echoroo import schemas

__all__ = ["search_gbif_species", "get_gbif_species_by_key", "get_gbif_vernacular_name"]

# Mapping from ISO 639-1 (2-letter) to ISO 639-2/3 (3-letter) language codes
# GBIF API uses 3-letter codes
_LANG_CODE_MAP: dict[str, str] = {
    "ja": "jpn",
    "en": "eng",
    "de": "deu",
    "fr": "fra",
    "es": "spa",
    "it": "ita",
    "pt": "por",
    "nl": "nld",
    "sv": "swe",
    "fi": "fin",
    "da": "dan",
    "no": "nor",
    "pl": "pol",
    "ru": "rus",
    "zh": "zho",
    "ko": "kor",
}


def _extract_candidates(  # pragma: no cover - simple data parser
    payload: Sequence[dict[str, Any]],
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
    response: dict[str, Any] | list[dict[str, Any]] | None = await loop.run_in_executor(
        None,
        lambda: gbif_species.name_suggest(  # type: ignore[arg-type]
            q=query,
            limit=limit,
            rank="species",
        ),
    )
    if response is None:
        return []

    payload: Sequence[dict[str, Any]]
    if isinstance(response, dict):
        results = response.get("results")
        payload = results if results else []
    else:
        payload = list(response)

    return _extract_candidates(payload)


async def get_gbif_species_by_key(
    taxon_key: str,
) -> str | None:
    """Get scientific name from GBIF taxon key.

    Parameters
    ----------
    taxon_key : str
        GBIF taxon key (e.g., "5231630").

    Returns
    -------
    str | None
        Canonical scientific name (e.g., "Parus minor"), or None if not found.
    """
    if not taxon_key.strip():
        return None

    loop = asyncio.get_running_loop()
    try:
        response: dict | None = await loop.run_in_executor(
            None,
            lambda: gbif_species.name_usage(key=int(taxon_key)),  # type: ignore[arg-type]
        )
        if response is None:
            return None

        # Return canonical name or scientific name
        return response.get("canonicalName") or response.get("scientificName")
    except Exception:
        return None


async def get_gbif_vernacular_name(
    taxon_key: str,
    locale: str = "en",
) -> str | None:
    """Get vernacular (common) name from GBIF taxon key for a specific locale.

    Parameters
    ----------
    taxon_key : str
        GBIF taxon key (e.g., "5231630").
    locale : str
        Language code (e.g., "en", "ja", "de"). Defaults to "en".

    Returns
    -------
    str | None
        Vernacular name in the requested locale, or None if not found.
    """
    if not taxon_key.strip():
        return None

    loop = asyncio.get_running_loop()
    try:
        response: dict | list | None = await loop.run_in_executor(
            None,
            lambda: gbif_species.name_usage(  # type: ignore[arg-type]
                key=int(taxon_key),
                data="vernacularNames",
            ),
        )
        if response is None:
            return None

        # Response can be a dict with "results" key or a list
        vernacular_names: list[dict]
        if isinstance(response, dict):
            vernacular_names = response.get("results", []) or []
        else:
            vernacular_names = list(response)

        # Convert 2-letter code to 3-letter code for GBIF API
        locale_lower = locale.lower()
        target_lang = _LANG_CODE_MAP.get(locale_lower, locale_lower)

        # Find matching locale (try both original and mapped code)
        for item in vernacular_names:
            language = item.get("language", "").lower()
            if language == target_lang or language == locale_lower:
                return item.get("vernacularName")

        return None
    except Exception:
        return None

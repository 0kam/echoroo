"""Utilities for interacting with external species catalogues."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Sequence

import requests
from pygbif import species as gbif_species

from echoroo import schemas

logger = logging.getLogger(__name__)

# GBIF Backbone Taxonomy dataset key
GBIF_BACKBONE_DATASET_KEY = "d7dddbf4-2cf0-4f39-9b2a-bb099caae36c"

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
    """Extract species candidates from GBIF API response.

    Deduplicates entries by canonical name, preferring GBIF Backbone Taxonomy
    entries over regional datasets. When multiple entries share the same
    canonical name and dataset priority, prefers the entry with more
    vernacular names.

    Parameters
    ----------
    payload : Sequence[dict[str, Any]]
        List of species results from GBIF API.

    Returns
    -------
    list[schemas.SpeciesCandidate]
        Filtered and deduplicated list of species candidates.
    """
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

        # Extract vernacular names
        vernacular_names_raw = item.get("vernacularNames", [])
        vernacular_name = None
        vernacular_names = None

        if vernacular_names_raw:
            # Convert GBIF camelCase to snake_case for consistency with schema
            vernacular_names = [
                {
                    "vernacular_name": vn.get("vernacularName"),
                    "language": vn.get("language"),
                    "source": vn.get("source"),
                }
                for vn in vernacular_names_raw
            ]
            # Try to find English vernacular name as primary
            for vn in vernacular_names_raw:
                lang = vn.get("language", "").lower()
                if lang in ("eng", "en"):
                    vernacular_name = vn.get("vernacularName")
                    break
            # If no English name found, use the first available
            if vernacular_name is None and vernacular_names_raw:
                vernacular_name = vernacular_names_raw[0].get("vernacularName")

        candidates.append(
            schemas.SpeciesCandidate(
                usage_key=str(usage_key),
                canonical_name=canonical,
                scientific_name=item.get("scientificName"),
                rank=item.get("rank"),
                synonym=item.get("synonym", False),
                dataset_key=item.get("datasetKey"),
                vernacular_name=vernacular_name,
                vernacular_names=vernacular_names,
            )
        )
    # Remove duplicates by canonical name while preserving order.
    # When duplicates exist, prefer GBIF Backbone Taxonomy entries.
    unique: dict[str, schemas.SpeciesCandidate] = {}
    for candidate in candidates:
        canonical_key = candidate.canonical_name

        # Skip if no canonical name (defensive programming)
        if not canonical_key:
            continue

        # If this canonical name not seen yet, add it
        if canonical_key not in unique:
            unique[canonical_key] = candidate
        else:
            # Prefer GBIF Backbone Taxonomy entries
            existing = unique[canonical_key]

            # Check if current entry is from Backbone Taxonomy
            is_current_backbone = candidate.dataset_key == GBIF_BACKBONE_DATASET_KEY
            is_existing_backbone = existing.dataset_key == GBIF_BACKBONE_DATASET_KEY

            # Replace if current is from Backbone and existing is not
            if is_current_backbone and not is_existing_backbone:
                unique[canonical_key] = candidate
            # If neither or both are from Backbone, prefer entry with more vernacular names
            elif is_current_backbone == is_existing_backbone:
                existing_vn_count = len(existing.vernacular_names or [])
                current_vn_count = len(candidate.vernacular_names or [])
                if current_vn_count > existing_vn_count:
                    unique[canonical_key] = candidate

    return list(unique.values())


def _call_gbif_species_search(
    query: str,
    limit: int,
    q_field: str | None = None,
) -> list[dict[str, Any]]:
    """Call GBIF species search API synchronously.

    Parameters
    ----------
    query : str
        Search query string.
    limit : int
        Maximum number of results to return.
    q_field : str | None
        Query field to search in (e.g., "VERNACULAR", "SCIENTIFIC").
        If None, searches all fields.

    Returns
    -------
    list[dict[str, Any]]
        List of species results from GBIF API.
    """
    url = "https://api.gbif.org/v1/species/search"
    params: dict[str, Any] = {
        "q": query,
        "limit": limit,
        "rank": "SPECIES",
    }
    if q_field:
        params["qField"] = q_field

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("results", [])
    except requests.exceptions.RequestException as e:
        logger.error(f"GBIF API request failed: {e}")
        return []
    except Exception as e:
        logger.error(f"Unexpected error during GBIF search: {e}")
        return []


async def search_gbif_species(
    query: str,
    *,
    limit: int = 10,
    q_field: str | None = None,
) -> list[schemas.SpeciesCandidate]:
    """Search GBIF species asynchronously.

    Parameters
    ----------
    query : str
        Search query string (scientific name, vernacular name, etc.).
    limit : int
        Maximum number of results to return (default: 10).
    q_field : str | None
        Query field to search in:
        - "VERNACULAR": Search in vernacular (common) names
        - "SCIENTIFIC": Search in scientific names
        - None: Search all fields (default)

    Returns
    -------
    list[schemas.SpeciesCandidate]
        List of matching species candidates with vernacular names included.

    Examples
    --------
    Search by scientific name:
    >>> await search_gbif_species("Passer montanus")

    Search by vernacular name:
    >>> await search_gbif_species("robin", q_field="VERNACULAR")

    Search by Japanese vernacular name:
    >>> await search_gbif_species("スズメ", q_field="VERNACULAR")
    """
    if not query.strip():
        return []

    loop = asyncio.get_running_loop()
    payload = await loop.run_in_executor(
        None,
        _call_gbif_species_search,
        query,
        limit,
        q_field,
    )

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

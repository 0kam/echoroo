"""GBIF species resolution service."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Rate limiter: 10 calls per second
GBIF_RATE_LIMIT_CALLS = 10
GBIF_RATE_LIMIT_PERIOD = 1.0

GBIF_BASE_URL = "https://api.gbif.org/v1"
INATURALIST_BASE_URL = "https://api.inaturalist.org/v1"
GBIF_BACKBONE_DATASET_KEY = "d7dddbf4-2cf0-4f39-9b2a-bb099caae36c"

# Non-species labels from BirdNET that should not be resolved via GBIF
NON_SPECIES_LABELS: frozenset[str] = frozenset({
    "Dog", "Engine", "Environmental", "Fireworks", "Gun",
    "Human non-vocal", "Human vocal", "Human whistle",
    "Noise", "Power tools", "Siren",
})

# ISO 639-1/3 to GBIF language code mapping
GBIF_LANG_CODE_MAP: dict[str, str] = {
    "ja": "jpn", "en": "eng", "de": "deu", "fr": "fra",
    "es": "spa", "it": "ita", "pt": "por", "nl": "nld",
    "sv": "swe", "fi": "fin", "da": "dan", "no": "nor",
    "pl": "pol", "ru": "rus", "zh": "zho", "ko": "kor",
    "cs": "ces", "sk": "slk", "hu": "hun", "ro": "ron",
    "tr": "tur", "th": "tha", "uk": "ukr", "ar": "ara",
    "af": "afr", "sl": "slv",
}


@dataclass
class GBIFResolveResult:
    """Result of GBIF species resolution."""

    taxon_key: int
    scientific_name: str
    rank: str
    metadata: dict[str, object]


@dataclass
class RateLimiter:
    """Simple token-bucket rate limiter."""

    max_calls: int = GBIF_RATE_LIMIT_CALLS
    period: float = GBIF_RATE_LIMIT_PERIOD
    _timestamps: list[float] = field(default_factory=list)

    async def acquire(self) -> None:
        now = time.monotonic()
        self._timestamps = [t for t in self._timestamps if now - t < self.period]
        if len(self._timestamps) >= self.max_calls:
            sleep_time = self.period - (now - self._timestamps[0])
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
        self._timestamps.append(time.monotonic())


class GBIFService:
    """Service for interacting with the GBIF API."""

    def __init__(self) -> None:
        self._rate_limiter = RateLimiter()

    async def search_species_full(
        self,
        query: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search GBIF species using the /v1/species/search endpoint.

        Uses the GBIF Backbone Taxonomy dataset and returns results with
        embedded vernacular names. Deduplicates by gbif_key, preferring
        Backbone Taxonomy entries over regional datasets.

        When the GBIF backbone search returns no results (e.g. for Japanese
        vernacular names like "ニホンジカ"), falls back to iNaturalist taxa
        search and resolves each result to a GBIF taxon key via /species/match.

        Args:
            query: Search query string (scientific or vernacular name).
            limit: Maximum number of results to return.

        Returns:
            List of parsed species result dicts with vernacular names.
        """
        await self._rate_limiter.acquire()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{GBIF_BASE_URL}/species/search",
                    params={
                        "q": query,
                        "limit": limit,
                        "datasetKey": GBIF_BACKBONE_DATASET_KEY,
                        "status": "ACCEPTED",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            logger.warning("GBIF search_species_full failed for query=%s", query, exc_info=True)
            return []

        raw_results: list[dict[str, Any]] = data.get("results", [])
        if raw_results:
            return self._parse_species_search_results(raw_results)

        # Fallback: query iNaturalist for vernacular name search (e.g. Japanese names)
        # then resolve each hit to a GBIF taxon key via /species/match.
        logger.debug(
            "GBIF backbone returned 0 results for query=%s, falling back to iNaturalist",
            query,
        )
        return await self._search_via_inaturalist(query, limit)

    async def _search_via_inaturalist(
        self,
        query: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Search iNaturalist taxa and resolve results to GBIF backbone entries.

        Used as a fallback when GBIF /species/search returns no results for a
        query, which typically happens for non-Latin vernacular names such as
        Japanese katakana/hiragana.

        Args:
            query: Search query string (any language vernacular or scientific).
            limit: Maximum number of results to return.

        Returns:
            List of parsed species result dicts compatible with the standard
            search_species_full output format.
        """
        await self._rate_limiter.acquire()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{INATURALIST_BASE_URL}/taxa",
                    params={"q": query, "limit": limit, "locale": "ja"},
                )
                resp.raise_for_status()
                inat_data = resp.json()
        except Exception:
            logger.warning(
                "iNaturalist taxa search failed for query=%s", query, exc_info=True
            )
            return []

        inat_results: list[dict[str, Any]] = inat_data.get("results", [])
        if not inat_results:
            return []

        parsed: list[dict[str, Any]] = []
        seen_keys: set[int] = set()

        async with httpx.AsyncClient(timeout=10.0) as client:
            for inat in inat_results[:limit]:
                sci_name: str = inat.get("name") or ""
                common_name: str = inat.get("preferred_common_name") or ""
                rank: str = (inat.get("rank") or "").upper()

                if not sci_name:
                    continue

                # Resolve scientific name to GBIF backbone taxon key
                await self._rate_limiter.acquire()
                try:
                    match_resp = await client.get(
                        f"{GBIF_BASE_URL}/species/match",
                        params={"name": sci_name, "strict": "false"},
                    )
                    match_resp.raise_for_status()
                    gbif_match = match_resp.json()
                except Exception:
                    logger.warning(
                        "GBIF species/match failed for name=%s", sci_name, exc_info=True
                    )
                    continue

                if gbif_match.get("matchType") == "NONE" or "usageKey" not in gbif_match:
                    continue

                gbif_key = int(gbif_match["usageKey"])
                if gbif_key in seen_keys:
                    continue
                seen_keys.add(gbif_key)

                # Build vernacular names list; inject iNaturalist common name as Japanese entry
                vernacular_names: list[dict[str, str]] = []
                if common_name:
                    vernacular_names.append({"name": common_name, "language": "ja"})

                entry: dict[str, Any] = {
                    "gbif_key": gbif_key,
                    "scientific_name": gbif_match.get("scientificName") or sci_name,
                    "canonical_name": gbif_match.get("canonicalName") or sci_name,
                    "rank": gbif_match.get("rank") or rank or None,
                    "vernacular_name": common_name or None,
                    "vernacular_names": vernacular_names if vernacular_names else None,
                    "kingdom": gbif_match.get("kingdom"),
                    "phylum": gbif_match.get("phylum"),
                    "class_name": gbif_match.get("class"),
                    "order": gbif_match.get("order"),
                    "family": gbif_match.get("family"),
                }
                parsed.append(entry)

        return parsed

    def _parse_species_search_results(
        self,
        raw: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Parse and deduplicate GBIF species search results.

        Deduplication is by gbif_key. When multiple entries share the same
        key, backbone entries are preferred over regional ones.

        Args:
            raw: Raw result items from GBIF /v1/species/search response.

        Returns:
            Deduplicated list of parsed species dicts.
        """
        # Reverse lookup: ISO 639-3 -> ISO 639-1
        iso3_to_iso1: dict[str, str] = {v: k for k, v in GBIF_LANG_CODE_MAP.items()}

        seen: dict[int, dict[str, Any]] = {}

        for item in raw:
            usage_key = item.get("key") or item.get("usageKey")
            if usage_key is None:
                continue

            gbif_key = int(usage_key)
            scientific_name = str(item.get("scientificName") or "")
            canonical_name = str(item.get("canonicalName") or scientific_name)

            # Parse vernacular names
            vernacular_names_raw: list[dict[str, Any]] = item.get("vernacularNames") or []
            vernacular_names: list[dict[str, str]] = []
            for vn in vernacular_names_raw:
                raw_name: str = vn.get("vernacularName") or ""
                raw_lang: str = (vn.get("language") or "").lower()
                if not raw_name:
                    continue
                # Normalise to ISO 639-1 where possible
                lang = iso3_to_iso1.get(raw_lang, raw_lang)
                vernacular_names.append({"name": raw_name, "language": lang})

            # Deduplicate vernacular names (same lang+name)
            seen_vn: set[tuple[str, str]] = set()
            unique_vn: list[dict[str, str]] = []
            for vn in vernacular_names:
                key_vn = (vn["language"], vn["name"])
                if key_vn not in seen_vn:
                    seen_vn.add(key_vn)
                    unique_vn.append(vn)

            # Choose best vernacular name: prefer English, then first available
            best_vernacular: str | None = None
            for vn in unique_vn:
                if vn["language"] == "en":
                    best_vernacular = vn["name"]
                    break
            if best_vernacular is None and unique_vn:
                best_vernacular = unique_vn[0]["name"]

            parsed: dict[str, Any] = {
                "gbif_key": gbif_key,
                "scientific_name": scientific_name,
                "canonical_name": canonical_name,
                "rank": item.get("rank"),
                "vernacular_name": best_vernacular,
                "vernacular_names": unique_vn if unique_vn else None,
                "kingdom": item.get("kingdom"),
                "phylum": item.get("phylum"),
                "class_name": item.get("class"),
                "order": item.get("order"),
                "family": item.get("family"),
                "dataset_key": item.get("datasetKey"),
            }

            if gbif_key not in seen:
                seen[gbif_key] = parsed
            else:
                # Prefer Backbone Taxonomy entry; otherwise prefer entry with more vn names
                existing = seen[gbif_key]
                is_current_backbone = parsed.get("dataset_key") == GBIF_BACKBONE_DATASET_KEY
                is_existing_backbone = existing.get("dataset_key") == GBIF_BACKBONE_DATASET_KEY
                if is_current_backbone and not is_existing_backbone:
                    seen[gbif_key] = parsed
                elif is_current_backbone == is_existing_backbone:
                    existing_vn: list[Any] = existing.get("vernacular_names") or []
                    current_vn: list[Any] = parsed.get("vernacular_names") or []
                    if len(current_vn) > len(existing_vn):
                        seen[gbif_key] = parsed

        # Return without internal dataset_key field
        results: list[dict[str, Any]] = []
        for entry in seen.values():
            results.append({k: v for k, v in entry.items() if k != "dataset_key"})
        return results

    async def search_species(self, query: str, limit: int = 10) -> list[dict[str, object]]:
        """Search GBIF species suggest API."""
        await self._rate_limiter.acquire()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{GBIF_BASE_URL}/species/suggest",
                    params={"q": query, "limit": limit},
                )
                resp.raise_for_status()
                return resp.json()  # type: ignore[no-any-return]
        except Exception:
            logger.warning("GBIF search failed for query=%s", query, exc_info=True)
            return []

    async def resolve_taxon(self, scientific_name: str) -> GBIFResolveResult | None:
        """Resolve a scientific name to a GBIF taxon key + metadata."""
        await self._rate_limiter.acquire()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{GBIF_BASE_URL}/species/match",
                    params={"name": scientific_name, "strict": "false"},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            logger.warning("GBIF resolve failed for %s", scientific_name, exc_info=True)
            return None

        if data.get("matchType") == "NONE" or "usageKey" not in data:
            return None

        metadata: dict[str, object] = {}
        for key in ("kingdom", "phylum", "class", "order", "family", "genus"):
            if key in data:
                metadata[key] = data[key]

        return GBIFResolveResult(
            taxon_key=data["usageKey"],
            scientific_name=data.get("canonicalName", scientific_name),
            rank=data.get("rank", "UNKNOWN"),
            metadata=metadata,
        )

    async def get_vernacular_names(
        self,
        taxon_key: int,
        locales: list[str] | None = None,
    ) -> list[dict[str, str]]:
        """Get vernacular names for a GBIF taxon key.

        Returns list of dicts with keys: locale, name.
        """
        await self._rate_limiter.acquire()
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{GBIF_BASE_URL}/species/{taxon_key}/vernacularNames",
                    params={"limit": 200},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            logger.warning("GBIF vernacular names failed for key=%s", taxon_key, exc_info=True)
            return []

        results: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()

        for item in data.get("results", []):
            lang = item.get("language", "")
            name = item.get("vernacularName", "")
            if not lang or not name:
                continue

            # Convert GBIF 3-letter code to 2-letter if possible
            locale = lang.lower()
            for iso2, iso3 in GBIF_LANG_CODE_MAP.items():
                if iso3 == locale:
                    locale = iso2
                    break

            if locales and locale not in locales:
                continue

            key = (locale, name)
            if key in seen:
                continue
            seen.add(key)

            results.append({"locale": locale, "name": name})

        return results

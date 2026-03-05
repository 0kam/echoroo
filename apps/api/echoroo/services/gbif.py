"""GBIF species resolution service."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

# Rate limiter: 10 calls per second
GBIF_RATE_LIMIT_CALLS = 10
GBIF_RATE_LIMIT_PERIOD = 1.0

GBIF_BASE_URL = "https://api.gbif.org/v1"

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

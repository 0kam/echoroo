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

# --- Search-time vernacular enrichment tuning (non-en locales only) ---------
# Number of top search results whose vernacular name we live-enrich.
_ENRICH_TOP_N = 8
# Maximum concurrent external (iNat/GBIF) HTTP calls during enrichment.
_ENRICH_CONCURRENCY = 4
# Per-source HTTP timeout (seconds).
_ENRICH_SOURCE_TIMEOUT = 0.7
# Total enrichment budget (seconds). When exceeded, whatever resolved so far is
# kept and the rest falls back to English/scientific name.
_ENRICH_TOTAL_BUDGET = 1.5
# Redis cache TTLs.
_ENRICH_CACHE_TTL_HIT = 14 * 24 * 60 * 60  # 14 days for resolved names
_ENRICH_CACHE_TTL_MISS = 24 * 60 * 60  # 1 day for explicit misses
# Sentinel value stored in Redis to represent a cached "no name found" miss.
_ENRICH_CACHE_MISS_SENTINEL = "\x00MISS"

# Non-species labels from BirdNET that should not be resolved via GBIF
NON_SPECIES_LABELS: frozenset[str] = frozenset({
    "Dog", "Engine", "Environmental", "Fireworks", "Gun",
    "Human non-vocal", "Human vocal", "Human whistle",
    "Noise", "Power tools", "Siren",
})

# Locales written in a non-latin script. For these a real vernacular name
# contains non-ASCII characters, so a pure-ASCII iNaturalist candidate is
# treated as an English/default fallback and rejected (see
# ``GBIFService._inat_name_in_locale``). Latin-script and unknown locales are
# left untouched by the ASCII guard.
_NON_LATIN_SCRIPT_LOCALES: frozenset[str] = frozenset({
    "ja", "zh", "ko", "ru", "uk", "ar", "th", "he", "el", "hi",
    "bg", "sr", "mk", "be", "ka", "hy", "fa", "ur", "bn", "ta",
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


def _normalize_locale(locale: str) -> str:
    """Reduce a locale to its lowercase primary subtag.

    Strips a BCP-47 region/script suffix and lowercases the primary subtag so
    inputs like ``ja-JP`` / ``en_US`` / ``EN`` normalize to ``ja`` / ``en`` /
    ``en``. This is applied at the service boundary BEFORE the ``!= "en"``
    enrichment gate (so ``en-US`` makes no extra calls and ``ja-JP`` enriches
    like ``ja``) and consistently for cache keys, GBIF language lookup, and the
    inline-name picker.
    """
    return locale.strip().split("-", 1)[0].split("_", 1)[0].lower()


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
        locale: str = "en",
    ) -> list[dict[str, Any]]:
        """Search GBIF species using the /v1/species/search endpoint.

        Uses the GBIF Backbone Taxonomy dataset and returns results with
        embedded vernacular names. Deduplicates by gbif_key, preferring
        Backbone Taxonomy entries over regional datasets.

        When the GBIF backbone search returns no results (e.g. for Japanese
        vernacular names like "ニホンジカ"), falls back to iNaturalist taxa
        search and resolves each result to a GBIF taxon key via /species/match.

        Locale-aware enrichment: for any ``locale`` other than ``"en"``, the top
        results' vernacular names are live-enriched for the requested locale
        (iNaturalist → GBIF /vernacularNames → existing English → scientific).
        For ``locale == "en"`` NO extra external calls are made — this keeps the
        common English path on its existing single-request latency budget.

        Args:
            query: Search query string (scientific or vernacular name).
            limit: Maximum number of results to return.
            locale: Display locale (e.g. ``"en"``, ``"ja"``). Non-en locales
                trigger best-effort vernacular enrichment.

        Returns:
            List of parsed species result dicts with vernacular names.
        """
        # Normalize the incoming locale to its primary subtag at the boundary so
        # the gate, cache keys, GBIF lang lookup and persistence all agree
        # (``ja-JP`` → ``ja``, ``EN`` → ``en``). This keeps ``en``/``en-US`` on
        # the zero-extra-call path and lets ``ja-JP`` enrich like ``ja``.
        locale = _normalize_locale(locale)

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
            parsed = self._parse_species_search_results(raw_results, locale=locale)
        else:
            # Fallback: query iNaturalist for vernacular name search (e.g.
            # Japanese names) then resolve each hit to a GBIF taxon key via
            # /species/match. The iNat fallback already requests ja names.
            logger.debug(
                "GBIF backbone returned 0 results for query=%s, falling back to iNaturalist",
                query,
            )
            parsed = await self._search_via_inaturalist(query, limit)

        # Live-enrich vernacular names ONLY for non-en locales. The English path
        # is intentionally left untouched (zero extra external calls).
        if locale != "en" and parsed:
            await self._enrich_vernacular_locale(parsed, locale)

        return parsed

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
        locale: str = "en",
    ) -> list[dict[str, Any]]:
        """Parse and deduplicate GBIF species search results.

        Deduplication is by gbif_key. When multiple entries share the same
        key, backbone entries are preferred over regional ones.

        Args:
            raw: Raw result items from GBIF /v1/species/search response.
            locale: Preferred display locale for picking ``vernacular_name``
                from the parsed inline names (requested locale → English →
                first available). This only affects which already-parsed name
                is surfaced; live enrichment is handled separately.

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
                # GBIF returns some vernacular rows with a null/empty language
                # (or, rarely, an empty name). Such entries would later fail the
                # ``VernacularNameInput`` (min_length=1) constraint on the
                # from-GBIF materialize, so drop them at the source.
                if not raw_name or not raw_lang:
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

            # Choose best vernacular name with a locale-aware preference chain:
            # requested locale → English → first available. This avoids the old
            # English-only bias so a ja UI surfaces a ja inline name when one is
            # present among the parsed names.
            best_vernacular: str | None = None
            for vn in unique_vn:
                if vn["language"] == locale:
                    best_vernacular = vn["name"]
                    break
            if best_vernacular is None and locale != "en":
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

    # ------------------------------------------------------------------
    # Search-time vernacular enrichment (non-en locales only)
    # ------------------------------------------------------------------

    async def _enrich_vernacular_locale(
        self,
        results: list[dict[str, Any]],
        locale: str,
    ) -> None:
        """Best-effort, in-place enrichment of vernacular names for ``locale``.

        For the top ``_ENRICH_TOP_N`` results this resolves a locale-specific
        vernacular name using the chain:

            iNaturalist (exact scientific/canonical match) →
            GBIF /species/{key}/vernacularNames →
            existing English vernacular → scientific name.

        When a name is resolved it is injected into the result's
        ``vernacular_names`` list (``{name, language, source}``) and the
        result's ``vernacular_name`` is OVERWRITTEN with the locale value so the
        display is no longer English-biased.

        Concurrency is capped at ``_ENRICH_CONCURRENCY`` and the whole pass is
        bounded by ``_ENRICH_TOTAL_BUDGET``; on timeout whatever resolved so far
        is kept and the rest is left as-is (English/scientific fallback). This
        method NEVER raises — any failure degrades gracefully.
        """
        targets = results[:_ENRICH_TOP_N]
        if not targets:
            return

        semaphore = asyncio.Semaphore(_ENRICH_CONCURRENCY)

        async def enrich_one(entry: dict[str, Any]) -> None:
            async with semaphore:
                try:
                    resolved = await self._resolve_locale_vernacular(entry, locale)
                except Exception:  # noqa: BLE001 — enrichment must never raise
                    logger.debug(
                        "vernacular enrichment failed for entry=%s",
                        entry.get("scientific_name"),
                        exc_info=True,
                    )
                    return
                if resolved is None:
                    return
                name, source = resolved
                self._inject_vernacular(entry, name, locale, source)

        try:
            await asyncio.wait_for(
                asyncio.gather(*(enrich_one(e) for e in targets)),
                timeout=_ENRICH_TOTAL_BUDGET,
            )
        except TimeoutError:
            # Budget exceeded — keep whatever resolved so far and fall back to
            # English/scientific for the remainder. Never propagate.
            logger.debug(
                "vernacular enrichment budget exceeded for locale=%s", locale
            )
        except Exception:  # noqa: BLE001 — defensive: never break search
            logger.debug(
                "vernacular enrichment pass failed for locale=%s",
                locale,
                exc_info=True,
            )

    @staticmethod
    def _inject_vernacular(
        entry: dict[str, Any],
        name: str,
        locale: str,
        source: str,
    ) -> None:
        """Inject a resolved locale name into an entry (in place)."""
        existing: list[dict[str, str]] = list(entry.get("vernacular_names") or [])
        # Never inject an entry with an empty name or locale: it would later be
        # rejected by ``VernacularNameInput`` (min_length=1) on the from-GBIF
        # materialize. Resolution normally yields a truthy name/locale, but guard
        # defensively so a degenerate value cannot poison the payload.
        if not name or not locale:
            return
        # Avoid duplicating a (locale, name) pair that is already present.
        if not any(
            vn.get("language") == locale and vn.get("name") == name
            for vn in existing
        ):
            existing.append({"name": name, "language": locale, "source": source})
        entry["vernacular_names"] = existing
        entry["vernacular_name"] = name

    async def _resolve_locale_vernacular(
        self,
        entry: dict[str, Any],
        locale: str,
    ) -> tuple[str, str] | None:
        """Resolve a single entry's vernacular name for ``locale``.

        Returns ``(name, source)`` or ``None`` when no locale-specific name is
        found. Resolution order: iNaturalist (exact match) → GBIF vernacular
        names. Each source is independently cached in Redis.
        """
        # If the entry already carries a name in the requested locale (e.g. from
        # the iNat fallback path), keep it without any extra external calls.
        for vn in entry.get("vernacular_names") or []:
            if vn.get("language") == locale and vn.get("name"):
                return str(vn["name"]), str(vn.get("source") or "gbif")

        canonical = str(entry.get("canonical_name") or entry.get("scientific_name") or "")
        gbif_key_raw = entry.get("gbif_key")
        gbif_key = int(gbif_key_raw) if gbif_key_raw is not None else None

        # 1) iNaturalist (exact scientific/canonical name match).
        if canonical:
            inat_name = await self._resolve_inat_vernacular(canonical, locale)
            if inat_name:
                return inat_name, "inaturalist"

        # 2) GBIF /species/{key}/vernacularNames.
        if gbif_key is not None:
            gbif_name = await self._resolve_gbif_vernacular(gbif_key, locale)
            if gbif_name:
                return gbif_name, "gbif"

        return None

    async def _resolve_inat_vernacular(
        self,
        canonical_name: str,
        locale: str,
    ) -> str | None:
        """Resolve a locale vernacular via iNaturalist with EXACT name match.

        Uses ``/v1/taxa?q=<name>&locale=<locale>`` and accepts only a result
        whose scientific name matches ``canonical_name`` exactly (genus +
        species, case-insensitive). Fuzzy matches are rejected. Cached in Redis.

        Locale verification (data integrity): iNaturalist populates
        ``preferred_common_name`` with an ENGLISH/default fallback when no name
        exists in the requested locale, which would otherwise inject an English
        name persisted as ``language=<locale>``. The candidate is therefore
        accepted only when it is genuinely in the requested locale:

        * Reject when ``preferred_common_name`` equals the result's
          ``english_common_name`` (case-insensitive) — that signals the English
          fallback, so GBIF/English resolution should apply instead.
        * For non-latin locales (e.g. ``ja``) additionally reject a pure-ASCII
          candidate, since a real 和名 contains non-ASCII characters. Latin-script
          locales are left untouched by this guard.
        """
        cache_key = f"vernacular:inat:{canonical_name.lower()}:{locale}"
        cached = await self._cache_get(cache_key)
        if cached is not None:
            return None if cached == _ENRICH_CACHE_MISS_SENTINEL else cached

        name: str | None = None
        try:
            async with httpx.AsyncClient(timeout=_ENRICH_SOURCE_TIMEOUT) as client:
                resp = await client.get(
                    f"{INATURALIST_BASE_URL}/taxa",
                    params={"q": canonical_name, "locale": locale, "per_page": 10},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            logger.debug(
                "iNat vernacular lookup failed for name=%s", canonical_name,
                exc_info=True,
            )
            return None  # transient error: do not cache

        target = canonical_name.strip().lower()
        for item in data.get("results", []):
            sci = str(item.get("name") or "").strip().lower()
            if sci != target:
                continue  # exact match only; reject fuzzy hits
            common = item.get("preferred_common_name")
            if common and self._inat_name_in_locale(item, str(common), locale):
                name = str(common)
            break

        await self._cache_set(cache_key, name)
        return name

    @staticmethod
    def _inat_name_in_locale(
        item: dict[str, Any],
        candidate: str,
        locale: str,
    ) -> bool:
        """Return True only when ``candidate`` is genuinely in ``locale``.

        Detects iNaturalist's English/default fallback for
        ``preferred_common_name`` (see :meth:`_resolve_inat_vernacular`). For a
        non-English ``locale`` the candidate is rejected when it matches the
        result's ``english_common_name`` (case-insensitive). For non-latin
        locales a pure-ASCII candidate is also rejected.
        """
        if locale == "en":
            return True

        # English fallback: iNat returned its English/default name verbatim.
        english = item.get("english_common_name")
        if english and candidate.strip().lower() == str(english).strip().lower():
            return False

        # Non-latin locales (e.g. ja) must carry non-ASCII characters; a
        # pure-ASCII candidate is an English/default fallback in disguise.
        return not (locale in _NON_LATIN_SCRIPT_LOCALES and candidate.isascii())

    async def _resolve_gbif_vernacular(
        self,
        gbif_key: int,
        locale: str,
    ) -> str | None:
        """Resolve a locale vernacular via GBIF /vernacularNames. Cached."""
        cache_key = f"vernacular:search:gbif:{gbif_key}:{locale}"
        cached = await self._cache_get(cache_key)
        if cached is not None:
            return None if cached == _ENRICH_CACHE_MISS_SENTINEL else cached

        # GBIF expects the 3-letter language code on the result rows; the
        # existing get_vernacular_names already normalises jpn→ja internally and
        # filters by the 2-letter ``locale``.
        # Route through the shared GBIF rate limiter like every other GBIF call.
        # If the limiter wait pushes past the per-source timeout/total budget the
        # existing timeout/fallback handles it gracefully. The iNat host is on a
        # separate origin and is intentionally NOT throttled here.
        name: str | None = None
        try:
            await self._rate_limiter.acquire()
            async with httpx.AsyncClient(timeout=_ENRICH_SOURCE_TIMEOUT) as client:
                resp = await client.get(
                    f"{GBIF_BASE_URL}/species/{gbif_key}/vernacularNames",
                    params={"limit": 200},
                )
                resp.raise_for_status()
                data = resp.json()
        except Exception:
            logger.debug(
                "GBIF vernacular lookup failed for key=%s", gbif_key, exc_info=True
            )
            return None  # transient error: do not cache

        iso3 = GBIF_LANG_CODE_MAP.get(locale, locale)
        for item in data.get("results", []):
            row_lang = str(item.get("language") or "").lower()
            row_name = item.get("vernacularName")
            if not row_name:
                continue
            if row_lang in (locale, iso3):
                name = str(row_name)
                break

        await self._cache_set(cache_key, name)
        return name

    # ------------------------------------------------------------------
    # Redis cache helpers (reuse the app's shared connection)
    # ------------------------------------------------------------------

    async def _cache_get(self, key: str) -> str | None:
        """Return a cached value, or ``None`` on miss/redis error.

        A returned ``_ENRICH_CACHE_MISS_SENTINEL`` represents a cached explicit
        miss (no name found) and is distinguished from ``None`` (cache miss).
        """
        try:
            from echoroo.core.redis import get_redis_connection  # noqa: PLC0415

            client = await get_redis_connection()
            value = await client.get(key)
        except Exception:  # noqa: BLE001 — cache is best-effort
            return None
        if value is None:
            return None
        # ``decode_responses=True`` yields str; be defensive about bytes.
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)

    async def _cache_set(self, key: str, name: str | None) -> None:
        """Cache a hit (14d) or an explicit miss (1d). Best-effort."""
        try:
            from echoroo.core.redis import get_redis_connection  # noqa: PLC0415

            client = await get_redis_connection()
            if name is None:
                await client.set(
                    key, _ENRICH_CACHE_MISS_SENTINEL, ex=_ENRICH_CACHE_TTL_MISS
                )
            else:
                await client.set(key, name, ex=_ENRICH_CACHE_TTL_HIT)
        except Exception:  # noqa: BLE001 — cache write must never fail search
            return

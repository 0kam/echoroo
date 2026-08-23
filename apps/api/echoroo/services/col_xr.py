"""Catalogue of Life XR identity resolution (WS-A v2 slice 3).

GBIF's legacy backbone taxonomy is frozen, so the re-matchable external
identity of a :class:`~echoroo.models.taxon.Taxon` is resolved against the
**Catalogue of Life XR** checklist instead. COL XR is served by GBIF's v2
matching API and therefore needs no separate credentials:

``GET https://api.gbif.org/v2/species/match?checklistKey=<COL_XR_CHECKLIST_KEY>``

Two things about that endpoint are load-bearing and easy to get wrong:

* **The ``checklistKey`` is mandatory.** Without it the request silently falls
  back to the legacy GBIF backbone and you get GBIF keys, not COL ids.
* **Gate on ``diagnostics.matchType``, never on ``usage.status``.** A
  ``HIGHERRANK`` result returns a genus/kingdom usage whose status is
  ``ACCEPTED``; treating that as a hit would bind a species label to
  "Animalia". On ``NONE`` there is no ``usage`` at all and ``confidence`` is
  reported as ``100`` (a sentinel, not a score).

COL XR is cross-domain *identity* only. For birds the bundled AviList
crosswalk stays the *name* authority — nothing here rewrites a display name.

The release the resolution was pinned to is read ONCE per batch run via
:meth:`COLXRService.get_index_metadata` and stamped on every row that run
touches — **including rejects**, which were still evaluated at that release.
That pin is both the audit trail and the selector the ``force=True``
re-resolution uses to walk the catalogue, so the metadata read is mandatory:
it raises rather than resolve against an unknown release.
"""

from __future__ import annotations

import asyncio
import email.utils
import logging
import random
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import httpx

from echoroo.core.exceptions import COLXRMetadataError, COLXRUnavailableError
from echoroo.services.gbif import RateLimiter

logger = logging.getLogger(__name__)

#: GBIF v2 matching API host. COL XR is one of the checklists it serves.
COL_XR_BASE_URL: Final = "https://api.gbif.org/v2"

#: Catalogue of Life XR checklist key. The alias ``xcol`` also resolves, but
#: the explicit UUID is pinned here so a rename upstream cannot silently
#: repoint us at a different checklist.
COL_XR_CHECKLIST_KEY: Final = "7ddf754f-d193-4cc9-b351-99906754a03b"

#: Ranks kept out of ``classification[]``. COL returns the full lineage
#: including DOMAIN / SUBPHYLUM / MEGACLASS / PARVORDER / ... — we persist only
#: the seven principal ranks so the stored JSON stays comparable across taxa.
PRINCIPAL_RANKS: Final[tuple[str, ...]] = (
    "KINGDOM",
    "PHYLUM",
    "CLASS",
    "ORDER",
    "FAMILY",
    "GENUS",
    "SPECIES",
)

#: HTTP timeout for a single match/metadata call (seconds).
_REQUEST_TIMEOUT: Final = 15.0

#: Total attempts for a request that comes back 429 (1 initial + 2 retries).
_MAX_ATTEMPTS: Final = 3

#: Base delay for the exponential backoff applied between 429 retries.
_RETRY_BACKOFF_SECONDS: Final = 1.0

#: Multiplicative jitter band applied to the computed backoff. Without it a
#: fleet of workers that got 429ed together would retry in lockstep and
#: re-trigger the throttle; the spread is what breaks the synchronisation.
_RETRY_JITTER_RANGE: Final[tuple[float, float]] = (0.5, 1.5)

#: Ceiling on an upstream-supplied ``Retry-After``. The header is honoured when
#: present (it is the server telling us exactly how long to wait), but a bogus
#: or hostile value must not park a Celery task past its soft time limit.
_RETRY_AFTER_MAX_SECONDS: Final = 60.0

#: Query-parameter name for the rank hint. The v2 ``/species/match`` endpoint
#: answers to ``rank`` (live-verified 2026-08-23); the v2 docs also mention
#: ``taxonRank`` for the same hint, so this is a constant to make flipping it a
#: one-line change if the accepted spelling ever moves.
_RANK_PARAM_NAME: Final = "rank"

#: Minimum confidence a non-EXACT (VARIANT/FUZZY) match needs to be worth
#: storing for human review. Below it the match is not trustworthy enough to
#: record an identity for.
REVIEW_CONFIDENCE_FLOOR: Final = 90

#: matchTypes that are never an identity, whatever their confidence.
_REJECTED_MATCH_TYPES: Final[frozenset[str]] = frozenset({"HIGHERRANK", "NONE"})

#: matchTypes that are an identity outright.
_ACCEPTED_MATCH_TYPES: Final[frozenset[str]] = frozenset({"EXACT"})

#: httpx failure modes meaning "upstream unreachable / erroring" as opposed to
#: a successful response that merely carries no match. Mirrors ``gbif.py``.
_HTTP_FAILURE = (httpx.HTTPStatusError, httpx.RequestError)


@dataclass(frozen=True, slots=True)
class COLXRIndex:
    """The COL XR release a batch run is pinned to.

    Attributes:
        alias: Human-readable release alias (e.g. ``"COL26.6 XR"``).
        clb_dataset_key: ChecklistBank dataset key of that release, when the
            upstream reports a numeric one.
        created: Upstream-reported build timestamp, verbatim (never parsed —
            it is only carried for logging/debugging).
    """

    alias: str | None
    clb_dataset_key: int | None
    created: str | None


@dataclass(frozen=True, slots=True)
class COLXRMatch:
    """A single COL XR ``/species/match`` result, normalized.

    ``usage_*`` fields describe the name as COL knows it (which may be a
    synonym); ``accepted_*`` fields describe the currently accepted name. When
    the usage is not a synonym both sides carry the same values, so callers
    never have to branch on :attr:`synonym` to read the accepted identity.
    """

    usage_key: str | None
    canonical_name: str | None
    authorship: str | None
    rank: str | None
    status: str | None
    accepted_key: str | None
    accepted_canonical_name: str | None
    accepted_authorship: str | None
    accepted_rank: str | None
    synonym: bool
    match_type: str
    confidence: int | None
    classification: dict[str, dict[str, str]]
    note: str | None


def decide_match(match: COLXRMatch | None) -> str:
    """Classify a match into ``"accept"`` / ``"review"`` / ``"reject"``.

    Pure function — the single place the acceptance policy lives:

    * ``EXACT``                                   -> ``"accept"``
    * ``VARIANT`` / ``FUZZY`` with confidence>=90 -> ``"review"``
    * everything else (``HIGHERRANK``, ``NONE``,
      low-confidence fuzz, missing usage key)     -> ``"reject"``

    ``"review"`` rows still store the full identity; ``col_xr_match_type``
    records how it was obtained so an operator can audit them later.
    ``"reject"`` rows store only the match type and the resolution timestamp.
    """
    if match is None:
        return "reject"
    match_type = (match.match_type or "").upper()
    if match_type in _REJECTED_MATCH_TYPES:
        return "reject"
    if not match.usage_key:
        # Defensive: a hit without a usage key carries no identity to store.
        return "reject"
    if match_type in _ACCEPTED_MATCH_TYPES:
        return "accept"
    if match.confidence is not None and match.confidence >= REVIEW_CONFIDENCE_FLOOR:
        return "review"
    return "reject"


def _as_int(value: Any) -> int | None:
    """Coerce an upstream numeric-ish value to ``int``; ``None`` when it isn't."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _as_str(value: Any) -> str | None:
    """Return a non-empty stripped string, else ``None``."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _canonical_name(usage: dict[str, Any]) -> str | None:
    """Extract the AUTHORSHIP-FREE canonical name from a COL usage object.

    ``usage.name`` is the full scientific name INCLUDING the authorship
    ("Acacia acuminata Benth."). Storing that in ``accepted_scientific_name``
    would poison every downstream name comparison (crosswalk lookups, the IOC
    bundle join, operator eyeballing), so the authorship is never allowed to
    leak into a canonical slot. Resolution order:

    1. ``canonicalName`` — COL's own authorship-free rendering, when present;
    2. assembled from ``genericName`` + ``specificEpithet``
       (+ ``infraspecificEpithet``) — the structured fields, which cannot
       contain an authorship by construction;
    3. as a last resort, ``name`` with the ``authorship`` substring removed.

    Returns ``None`` when the usage carries no usable name at all.
    """
    canonical = _as_str(usage.get("canonicalName"))
    if canonical:
        return canonical

    generic = _as_str(usage.get("genericName")) or _as_str(usage.get("genus"))
    specific = _as_str(usage.get("specificEpithet"))
    if generic and specific:
        parts = [generic, specific]
        infraspecific = _as_str(usage.get("infraspecificEpithet"))
        if infraspecific:
            parts.append(infraspecific)
        return " ".join(parts)
    if generic and not specific:
        # Genus-rank (or higher) usage: the generic name IS the canonical name.
        return generic

    name = _as_str(usage.get("name"))
    if not name:
        return None
    authorship = _as_str(usage.get("authorship"))
    if authorship and name.endswith(authorship):
        stripped = name[: -len(authorship)].strip()
        if stripped:
            return stripped
    return name


def _retry_after_seconds(response: httpx.Response | None) -> float | None:
    """Parse a ``Retry-After`` header into seconds, if it is usable.

    Accepts both RFC 9110 forms: a delay in seconds, or an HTTP-date. Values
    that are absent, unparseable or negative yield ``None`` so the caller falls
    back to its own jittered backoff; values above
    ``_RETRY_AFTER_MAX_SECONDS`` are capped to it so a hostile header cannot
    park the task.
    """
    if response is None:
        return None
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    raw = raw.strip()

    try:
        seconds = float(raw)
    except ValueError:
        try:
            # Python 3.11 raises ValueError (rather than returning None) on an
            # unparseable value, and TypeError on some malformed inputs.
            parsed = email.utils.parsedate_to_datetime(raw)
        except (ValueError, TypeError):
            return None
        if parsed is None:  # pragma: no cover - defensive across versions
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        seconds = (parsed - datetime.now(UTC)).total_seconds()

    if seconds < 0:
        return None
    return min(seconds, _RETRY_AFTER_MAX_SECONDS)


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff for ``attempt`` (1-based), with jitter."""
    base = _RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
    low, high = _RETRY_JITTER_RANGE
    return float(base * random.uniform(low, high))  # noqa: S311 — not crypto


def _filter_classification(raw: Any) -> dict[str, dict[str, str]]:
    """Keep only the principal ranks from COL's full lineage array."""
    result: dict[str, dict[str, str]] = {}
    if not isinstance(raw, list):
        return result
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        rank = _as_str(entry.get("rank"))
        name = _as_str(entry.get("name"))
        key = _as_str(entry.get("key"))
        if rank is None or rank.upper() not in PRINCIPAL_RANKS:
            continue
        if name is None and key is None:
            continue
        result[rank.upper()] = {"key": key or "", "name": name or ""}
    return result


class COLXRService:
    """Thin client for the COL XR slice of GBIF's v2 matching API.

    Shares the 10 req/s :class:`~echoroo.services.gbif.RateLimiter` policy used
    by the GBIF paths — the two talk to the same host, so a single, per-instance
    limiter keeps one batch run polite. Instantiate ONE service per batch run.

    Unlike the older GBIF paths this keeps ONE ``httpx.AsyncClient`` alive for
    the service's lifetime instead of opening a fresh one per request. A full
    catalogue pass is thousands of sequential calls to a single TLS host, and
    the per-request TLS handshake measurably dominated the round trip (~0.72s
    vs ~0.34s per call in dev). Close it with :meth:`aclose`, or use the
    service as an async context manager.
    """

    def __init__(self, rate_limiter: RateLimiter | None = None) -> None:
        self._rate_limiter = rate_limiter or RateLimiter()
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> COLXRService:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        """Release the pooled HTTP connection, if one was opened."""
        client, self._client = self._client, None
        if client is not None:
            await client.aclose()

    def _get_client(self) -> httpx.AsyncClient:
        """Return the pooled client, creating it on first use."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=_REQUEST_TIMEOUT)
        return self._client

    # -- HTTP ------------------------------------------------------------

    async def _get_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """GET ``path``, retrying 429s with exponential backoff.

        Raises:
            COLXRUnavailableError: transport error, timeout, 5xx, or a 429 that
                survived every retry.
        """
        url = f"{COL_XR_BASE_URL}{path}"
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            await self._rate_limiter.acquire()
            try:
                resp = await self._get_client().get(url, params=params)
                resp.raise_for_status()
                payload = resp.json()
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                status_code = exc.response.status_code
                if (
                    status_code == httpx.codes.TOO_MANY_REQUESTS
                    and attempt < _MAX_ATTEMPTS
                ):
                    # Prefer the server's own instruction; fall back to a
                    # jittered exponential backoff when it does not give one.
                    retry_after = _retry_after_seconds(exc.response)
                    delay = (
                        retry_after
                        if retry_after is not None
                        else _backoff_delay(attempt)
                    )
                    logger.warning(
                        "COL XR rate-limited (429) on %s; retry %d/%d in %.1fs "
                        "(retry_after=%s)",
                        path,
                        attempt,
                        _MAX_ATTEMPTS - 1,
                        delay,
                        retry_after,
                    )
                    await asyncio.sleep(delay)
                    continue
                break
            except httpx.RequestError as exc:
                last_exc = exc
                break
            except ValueError as exc:
                # ``resp.json()`` on a truncated / non-JSON body. That is an
                # upstream problem, so it must surface as an outage rather than
                # as a per-taxon "no match" (or an unhandled crash).
                last_exc = exc
                break
            else:
                if not isinstance(payload, dict):
                    raise COLXRUnavailableError(
                        f"COL XR returned a non-object payload for {path!r}"
                    )
                return payload

        logger.error(
            "COL XR request failed for %s params=%s: %s",
            path,
            params,
            last_exc,
            exc_info=isinstance(last_exc, _HTTP_FAILURE),
        )
        raise COLXRUnavailableError(
            f"COL XR request to {path!r} failed"
        ) from last_exc

    # -- Public API ------------------------------------------------------

    async def get_index_metadata(self) -> COLXRIndex:
        """Read the COL XR release currently backing the matching index.

        Call this ONCE per batch run and stamp the result on every row that run
        resolves — including rejects. That pin is what makes "re-resolve after
        a release bump" a well-defined operation instead of a guess, and it is
        also the column the ``force`` re-resolution selects on.

        Two response layouts are accepted: the ``mainIndex`` object served by
        the live endpoint (``datasetAlias`` / ``clbDatasetKey``) and the flat
        ``alias`` / ``key`` shape documented in the GBIF matching-ws README.

        Raises:
            COLXRMetadataError: neither layout yielded BOTH a release alias and
                a dataset key. Resolving without a complete pin is refused.
        """
        payload = await self._get_json(
            "/species/match/metadata", {"checklistKey": COL_XR_CHECKLIST_KEY}
        )
        index = self._parse_index_metadata(payload)
        if index.alias is None or index.clb_dataset_key is None:
            logger.error(
                "COL XR index metadata incomplete (alias=%r key=%r); refusing "
                "to resolve without a release pin",
                index.alias,
                index.clb_dataset_key,
            )
            raise COLXRMetadataError(
                "COL XR index metadata did not report both a release alias and "
                "a dataset key"
            )
        return index

    @staticmethod
    def _parse_index_metadata(payload: dict[str, Any]) -> COLXRIndex:
        """Read the release pin out of either documented payload layout."""
        main_index = payload.get("mainIndex")
        if not isinstance(main_index, dict):
            main_index = {}

        # Layout 1: ``mainIndex`` (what api.gbif.org serves today).
        alias = _as_str(main_index.get("datasetAlias"))
        key = _as_int(main_index.get("clbDatasetKey"))
        created = _as_str(main_index.get("created"))

        # Layout 2: flat ``alias`` / ``key`` (matching-ws README). Each field
        # falls back independently so a partial mix still resolves.
        if alias is None:
            alias = _as_str(payload.get("alias")) or _as_str(
                payload.get("datasetAlias")
            )
        if key is None:
            key = _as_int(payload.get("key")) or _as_int(
                payload.get("clbDatasetKey")
            )
        if created is None:
            created = _as_str(payload.get("created"))

        return COLXRIndex(alias=alias, clb_dataset_key=key, created=created)

    async def match(
        self,
        scientific_name: str,
        *,
        kingdom: str | None = "Animalia",
        rank: str | None = "SPECIES",
    ) -> COLXRMatch | None:
        """Match ``scientific_name`` against COL XR.

        Args:
            scientific_name: The name to resolve.
            kingdom: Kingdom hint. ``"Animalia"`` disambiguates cross-kingdom
                homonyms (e.g. *Oenanthe*, a wheatear AND a plant genus).
            rank: Rank hint passed straight through to the API.

        Returns:
            A :class:`COLXRMatch`, or ``None`` when ``scientific_name`` is
            blank. A ``NONE`` matchType still returns a match object (with
            ``usage_key=None`` and no confidence) so callers can record *that*
            the taxon was processed.

        Raises:
            COLXRUnavailableError: the upstream failed (see :meth:`_get_json`).
        """
        name = (scientific_name or "").strip()
        if not name:
            return None

        params: dict[str, Any] = {
            "checklistKey": COL_XR_CHECKLIST_KEY,
            "scientificName": name,
            "strict": "false",
            "verbose": "true",
        }
        if kingdom:
            params["kingdom"] = kingdom
        if rank:
            params[_RANK_PARAM_NAME] = rank

        payload = await self._get_json("/species/match", params)
        return self._parse_match(payload)

    # -- Parsing ---------------------------------------------------------

    @staticmethod
    def _parse_match(payload: dict[str, Any]) -> COLXRMatch:
        """Normalize a raw ``/species/match`` payload into a :class:`COLXRMatch`."""
        diagnostics = payload.get("diagnostics")
        if not isinstance(diagnostics, dict):
            diagnostics = {}
        match_type = (_as_str(diagnostics.get("matchType")) or "NONE").upper()

        usage = payload.get("usage")
        if not isinstance(usage, dict):
            usage = {}
        accepted = payload.get("acceptedUsage")
        if not isinstance(accepted, dict):
            accepted = {}

        synonym = bool(payload.get("synonym"))

        usage_key = _as_str(usage.get("key"))
        # NEVER ``usage["name"]`` directly: that string carries the authorship.
        canonical_name = _canonical_name(usage)
        authorship = _as_str(usage.get("authorship"))
        usage_rank = _as_str(usage.get("rank"))
        status = _as_str(usage.get("status"))

        # Fall back to the usage itself when there is no separate accepted
        # usage, so callers never branch on ``synonym`` to read identity.
        accepted_key = _as_str(accepted.get("key")) or usage_key
        accepted_canonical = (
            _canonical_name(accepted) if accepted else None
        ) or canonical_name
        accepted_authorship = (
            _as_str(accepted.get("authorship")) if accepted else authorship
        )
        accepted_rank = _as_str(accepted.get("rank")) or usage_rank

        # ``confidence`` is a sentinel 100 on NONE (there is nothing to score),
        # so drop it rather than persist a misleading number.
        confidence = (
            None if match_type == "NONE" else _as_int(diagnostics.get("confidence"))
        )

        return COLXRMatch(
            usage_key=usage_key,
            canonical_name=canonical_name,
            authorship=authorship,
            rank=usage_rank,
            status=status,
            accepted_key=accepted_key,
            accepted_canonical_name=accepted_canonical,
            accepted_authorship=accepted_authorship,
            accepted_rank=accepted_rank,
            synonym=synonym,
            match_type=match_type,
            confidence=confidence,
            classification=_filter_classification(payload.get("classification")),
            note=_as_str(diagnostics.get("note")),
        )

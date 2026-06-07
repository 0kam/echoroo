"""Unit tests for locale-aware GBIF search vernacular enrichment.

Covers the WS-A 和名 display fix backend (``services/gbif.py``):

* ``en`` search makes ZERO extra external (enrichment) calls.
* a non-en (``ja``) search live-enriches the top results' vernacular names,
  preferring iNaturalist (exact match) then GBIF /vernacularNames.
* enrichment timeouts/errors degrade gracefully (search still returns).
* the locale-aware inline-name picker no longer hard-prefers English.

All external HTTP is faked; no live network is used. The Redis cache helpers
are stubbed to no-ops so the tests do not require a running Redis.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from echoroo.schemas.taxon import GBIFSpeciesResult
from echoroo.services import gbif as gbif_module
from echoroo.services.gbif import GBIFService

# ---------------------------------------------------------------------------
# Fake httpx client
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:  # noqa: D401 - mimic httpx
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeAsyncClient:
    """Routes GET calls to canned payloads keyed by URL substring.

    ``calls`` accumulates the requested URLs so a test can assert which
    external endpoints were (not) hit.
    """

    calls: list[str] = []

    def __init__(self, routes: dict[str, dict[str, Any]]) -> None:
        self._routes = routes

    def __call__(self, *args: Any, **kwargs: Any) -> _FakeAsyncClient:
        return self

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def get(self, url: str, params: dict[str, Any] | None = None) -> _FakeResponse:
        type(self).calls.append(url)
        for fragment, payload in self._routes.items():
            if fragment in url:
                return _FakeResponse(payload)
        return _FakeResponse({"results": []})


@pytest.fixture(autouse=True)
def _no_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the Redis cache helpers so tests never touch a live Redis."""
    async def _get(self: GBIFService, key: str) -> None:
        return None

    async def _set(self: GBIFService, key: str, name: str | None) -> None:
        return None

    monkeypatch.setattr(GBIFService, "_cache_get", _get)
    monkeypatch.setattr(GBIFService, "_cache_set", _set)


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the rate limiter a no-op so tests stay fast."""
    async def _acquire(self: Any) -> None:
        return None

    monkeypatch.setattr(gbif_module.RateLimiter, "acquire", _acquire)


def _install_client(
    monkeypatch: pytest.MonkeyPatch, routes: dict[str, dict[str, Any]]
) -> type[_FakeAsyncClient]:
    _FakeAsyncClient.calls = []
    fake_cls = _FakeAsyncClient

    def _factory(*args: Any, **kwargs: Any) -> _FakeAsyncClient:
        return fake_cls(routes)

    monkeypatch.setattr(gbif_module.httpx, "AsyncClient", _factory)
    return fake_cls


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_en_search_makes_no_enrichment_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ``en`` search must NOT issue any extra (enrichment) external calls."""
    search_payload = {
        "results": [
            {
                "key": 1001,
                "scientificName": "Hirundo rustica",
                "canonicalName": "Hirundo rustica",
                "rank": "SPECIES",
                "datasetKey": gbif_module.GBIF_BACKBONE_DATASET_KEY,
                "vernacularNames": [
                    {"vernacularName": "Barn Swallow", "language": "eng"},
                ],
            }
        ]
    }
    fake = _install_client(monkeypatch, {"/species/search": search_payload})

    # Guard: enrichment helpers must never run for en.
    async def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("enrichment should not run for en")

    monkeypatch.setattr(GBIFService, "_resolve_inat_vernacular", _boom)
    monkeypatch.setattr(GBIFService, "_resolve_gbif_vernacular", _boom)

    svc = GBIFService()
    results = await svc.search_species_full("swallow", limit=10, locale="en")

    assert len(results) == 1
    assert results[0]["vernacular_name"] == "Barn Swallow"
    # Exactly one external call (the search itself) — no enrichment calls.
    assert fake.calls == [f"{gbif_module.GBIF_BASE_URL}/species/search"]


@pytest.mark.asyncio
async def test_ja_search_enriches_via_inaturalist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``ja`` search injects the iNat ja name and overwrites vernacular_name."""
    search_payload = {
        "results": [
            {
                "key": 1001,
                "scientificName": "Hirundo rustica",
                "canonicalName": "Hirundo rustica",
                "rank": "SPECIES",
                "datasetKey": gbif_module.GBIF_BACKBONE_DATASET_KEY,
                "vernacularNames": [
                    {"vernacularName": "Barn Swallow", "language": "eng"},
                ],
            }
        ]
    }
    inat_payload = {
        "results": [
            {"name": "Hirundo rustica", "preferred_common_name": "ツバメ"},
        ]
    }
    _install_client(
        monkeypatch,
        {"/species/search": search_payload, "inaturalist.org/v1/taxa": inat_payload},
    )

    svc = GBIFService()
    results = await svc.search_species_full("swallow", limit=10, locale="ja")

    assert len(results) == 1
    entry = results[0]
    assert entry["vernacular_name"] == "ツバメ"
    ja_names = [
        vn for vn in entry["vernacular_names"] if vn["language"] == "ja"
    ]
    assert ja_names and ja_names[0]["name"] == "ツバメ"
    assert ja_names[0]["source"] == "inaturalist"


@pytest.mark.asyncio
async def test_ja_search_falls_back_to_gbif_vernacular(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When iNat has no exact match, GBIF /vernacularNames provides the ja name."""
    search_payload = {
        "results": [
            {
                "key": 2002,
                "scientificName": "Passer montanus",
                "canonicalName": "Passer montanus",
                "rank": "SPECIES",
                "datasetKey": gbif_module.GBIF_BACKBONE_DATASET_KEY,
                "vernacularNames": [
                    {"vernacularName": "Eurasian Tree Sparrow", "language": "eng"},
                ],
            }
        ]
    }
    # iNat returns only a fuzzy (non-exact) hit → must be rejected.
    inat_payload = {
        "results": [
            {"name": "Passer domesticus", "preferred_common_name": "イエスズメ"},
        ]
    }
    gbif_vn_payload = {
        "results": [
            {"vernacularName": "スズメ", "language": "jpn"},
            {"vernacularName": "Tree Sparrow", "language": "eng"},
        ]
    }
    _install_client(
        monkeypatch,
        {
            "/species/search": search_payload,
            "inaturalist.org/v1/taxa": inat_payload,
            "/vernacularNames": gbif_vn_payload,
        },
    )

    svc = GBIFService()
    results = await svc.search_species_full("sparrow", limit=10, locale="ja")

    entry = results[0]
    assert entry["vernacular_name"] == "スズメ"
    ja_names = [vn for vn in entry["vernacular_names"] if vn["language"] == "ja"]
    assert ja_names and ja_names[0]["name"] == "スズメ"
    assert ja_names[0]["source"] == "gbif"


@pytest.mark.asyncio
async def test_ja_search_no_match_keeps_english_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When no ja name exists anywhere, the English/scientific fallback stays."""
    search_payload = {
        "results": [
            {
                "key": 3003,
                "scientificName": "Genus species",
                "canonicalName": "Genus species",
                "rank": "SPECIES",
                "datasetKey": gbif_module.GBIF_BACKBONE_DATASET_KEY,
                "vernacularNames": [
                    {"vernacularName": "English Name", "language": "eng"},
                ],
            }
        ]
    }
    _install_client(
        monkeypatch,
        {
            "/species/search": search_payload,
            "inaturalist.org/v1/taxa": {"results": []},
            "/vernacularNames": {"results": []},
        },
    )

    svc = GBIFService()
    results = await svc.search_species_full("foo", limit=10, locale="ja")

    entry = results[0]
    # No ja name resolved → English inline name is retained as the display.
    assert entry["vernacular_name"] == "English Name"
    assert all(vn["language"] != "ja" for vn in entry["vernacular_names"])


@pytest.mark.asyncio
async def test_enrichment_error_does_not_break_search(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An enrichment exception is swallowed; search still returns results."""
    search_payload = {
        "results": [
            {
                "key": 4004,
                "scientificName": "Errus testus",
                "canonicalName": "Errus testus",
                "rank": "SPECIES",
                "datasetKey": gbif_module.GBIF_BACKBONE_DATASET_KEY,
                "vernacularNames": [
                    {"vernacularName": "Error Bird", "language": "eng"},
                ],
            }
        ]
    }
    _install_client(monkeypatch, {"/species/search": search_payload})

    async def _boom(self: GBIFService, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("inat down")

    monkeypatch.setattr(GBIFService, "_resolve_inat_vernacular", _boom)
    monkeypatch.setattr(GBIFService, "_resolve_gbif_vernacular", _boom)

    svc = GBIFService()
    results = await svc.search_species_full("err", limit=10, locale="ja")

    assert len(results) == 1
    # Falls back to the English inline name; no exception propagated.
    assert results[0]["vernacular_name"] == "Error Bird"


@pytest.mark.asyncio
async def test_enrichment_timeout_returns_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A budget timeout keeps already-resolved names and returns the search."""
    search_payload = {
        "results": [
            {
                "key": 5005,
                "scientificName": "Slowus testus",
                "canonicalName": "Slowus testus",
                "rank": "SPECIES",
                "datasetKey": gbif_module.GBIF_BACKBONE_DATASET_KEY,
                "vernacularNames": [
                    {"vernacularName": "Slow Bird", "language": "eng"},
                ],
            }
        ]
    }
    _install_client(monkeypatch, {"/species/search": search_payload})

    # Make enrichment hang past the budget so wait_for trips.
    async def _hang(self: GBIFService, *args: Any, **kwargs: Any) -> Any:
        await asyncio.sleep(5)
        return None

    monkeypatch.setattr(GBIFService, "_resolve_inat_vernacular", _hang)
    monkeypatch.setattr(GBIFService, "_resolve_gbif_vernacular", _hang)
    # Shrink the budget so the test is fast.
    monkeypatch.setattr(gbif_module, "_ENRICH_TOTAL_BUDGET", 0.05)

    svc = GBIFService()
    results = await svc.search_species_full("slow", limit=10, locale="ja")

    assert len(results) == 1
    # Timed out before resolving ja → English fallback retained, no exception.
    assert results[0]["vernacular_name"] == "Slow Bird"


@pytest.mark.asyncio
async def test_ja_search_rejects_inat_english_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """iNat preferred_common_name == english_common_name → rejected (F1).

    iNaturalist returns its English/default name in ``preferred_common_name``
    when no ja name exists; that must NOT be injected as a ja name. With no GBIF
    ja name either, the English inline fallback is retained.
    """
    search_payload = {
        "results": [
            {
                "key": 7007,
                "scientificName": "Falsus jacus",
                "canonicalName": "Falsus jacus",
                "rank": "SPECIES",
                "datasetKey": gbif_module.GBIF_BACKBONE_DATASET_KEY,
                "vernacularNames": [
                    {"vernacularName": "Fake Jay", "language": "eng"},
                ],
            }
        ]
    }
    # iNat exact match but the ja-requested name IS the English fallback.
    inat_payload = {
        "results": [
            {
                "name": "Falsus jacus",
                "preferred_common_name": "Fake Jay",
                "english_common_name": "Fake Jay",
            },
        ]
    }
    _install_client(
        monkeypatch,
        {
            "/species/search": search_payload,
            "inaturalist.org/v1/taxa": inat_payload,
            "/vernacularNames": {"results": []},
        },
    )

    svc = GBIFService()
    results = await svc.search_species_full("jay", limit=10, locale="ja")

    entry = results[0]
    # English fallback rejected → no ja row injected; English inline retained.
    assert entry["vernacular_name"] == "Fake Jay"
    assert all(vn["language"] != "ja" for vn in entry["vernacular_names"])


@pytest.mark.asyncio
async def test_ja_search_rejects_pure_ascii_inat_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """For ja, a pure-ASCII iNat candidate is rejected as a fallback (F1).

    Even without english_common_name, a real 和名 contains non-ASCII chars;
    a pure-ASCII candidate is treated as the English/default fallback. GBIF
    then supplies the genuine ja name.
    """
    search_payload = {
        "results": [
            {
                "key": 8008,
                "scientificName": "Asciius birdus",
                "canonicalName": "Asciius birdus",
                "rank": "SPECIES",
                "datasetKey": gbif_module.GBIF_BACKBONE_DATASET_KEY,
                "vernacularNames": [
                    {"vernacularName": "Ascii Bird", "language": "eng"},
                ],
            }
        ]
    }
    inat_payload = {
        "results": [
            {"name": "Asciius birdus", "preferred_common_name": "Ascii Bird"},
        ]
    }
    gbif_vn_payload = {
        "results": [
            {"vernacularName": "アスキーチョウ", "language": "jpn"},
        ]
    }
    _install_client(
        monkeypatch,
        {
            "/species/search": search_payload,
            "inaturalist.org/v1/taxa": inat_payload,
            "/vernacularNames": gbif_vn_payload,
        },
    )

    svc = GBIFService()
    results = await svc.search_species_full("ascii", limit=10, locale="ja")

    entry = results[0]
    # Pure-ASCII iNat candidate rejected → GBIF ja name used instead.
    assert entry["vernacular_name"] == "アスキーチョウ"
    ja_names = [vn for vn in entry["vernacular_names"] if vn["language"] == "ja"]
    assert ja_names and ja_names[0]["name"] == "アスキーチョウ"
    assert ja_names[0]["source"] == "gbif"


@pytest.mark.asyncio
async def test_ja_jp_locale_enriches_like_ja(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``ja-JP`` locale normalizes to ``ja`` and enriches (F3)."""
    search_payload = {
        "results": [
            {
                "key": 9009,
                "scientificName": "Regionus testus",
                "canonicalName": "Regionus testus",
                "rank": "SPECIES",
                "datasetKey": gbif_module.GBIF_BACKBONE_DATASET_KEY,
                "vernacularNames": [
                    {"vernacularName": "Region Bird", "language": "eng"},
                ],
            }
        ]
    }
    inat_payload = {
        "results": [
            {"name": "Regionus testus", "preferred_common_name": "リージョン鳥"},
        ]
    }
    _install_client(
        monkeypatch,
        {"/species/search": search_payload, "inaturalist.org/v1/taxa": inat_payload},
    )

    svc = GBIFService()
    results = await svc.search_species_full("region", limit=10, locale="ja-JP")

    entry = results[0]
    assert entry["vernacular_name"] == "リージョン鳥"
    ja_names = [vn for vn in entry["vernacular_names"] if vn["language"] == "ja"]
    assert ja_names and ja_names[0]["name"] == "リージョン鳥"


@pytest.mark.asyncio
async def test_en_us_locale_makes_no_enrichment_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``en-US`` normalizes to ``en`` → zero extra external calls (F3)."""
    search_payload = {
        "results": [
            {
                "key": 9100,
                "scientificName": "Enus usus",
                "canonicalName": "Enus usus",
                "rank": "SPECIES",
                "datasetKey": gbif_module.GBIF_BACKBONE_DATASET_KEY,
                "vernacularNames": [
                    {"vernacularName": "En Us Bird", "language": "eng"},
                ],
            }
        ]
    }
    fake = _install_client(monkeypatch, {"/species/search": search_payload})

    async def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("enrichment should not run for en-US")

    monkeypatch.setattr(GBIFService, "_resolve_inat_vernacular", _boom)
    monkeypatch.setattr(GBIFService, "_resolve_gbif_vernacular", _boom)

    svc = GBIFService()
    results = await svc.search_species_full("enus", limit=10, locale="en-US")

    assert results[0]["vernacular_name"] == "En Us Bird"
    assert fake.calls == [f"{gbif_module.GBIF_BASE_URL}/species/search"]


@pytest.mark.asyncio
async def test_gbif_vernacular_enrichment_uses_rate_limiter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The enrichment GBIF /vernacularNames GET goes through the limiter (F5)."""
    acquired: list[int] = []

    async def _counting_acquire(self: Any) -> None:
        acquired.append(1)

    monkeypatch.setattr(gbif_module.RateLimiter, "acquire", _counting_acquire)

    search_payload = {
        "results": [
            {
                "key": 9200,
                "scientificName": "Limitus testus",
                "canonicalName": "Limitus testus",
                "rank": "SPECIES",
                "datasetKey": gbif_module.GBIF_BACKBONE_DATASET_KEY,
                "vernacularNames": [
                    {"vernacularName": "Limit Bird", "language": "eng"},
                ],
            }
        ]
    }
    gbif_vn_payload = {"results": [{"vernacularName": "リミット鳥", "language": "jpn"}]}
    _install_client(
        monkeypatch,
        {
            "/species/search": search_payload,
            # No iNat exact match so GBIF /vernacularNames is reached.
            "inaturalist.org/v1/taxa": {"results": []},
            "/vernacularNames": gbif_vn_payload,
        },
    )

    svc = GBIFService()
    results = await svc.search_species_full("limit", limit=10, locale="ja")

    assert results[0]["vernacular_name"] == "リミット鳥"
    # At least the search acquire + the enrichment /vernacularNames acquire.
    assert len(acquired) >= 2


@pytest.mark.asyncio
async def test_enriched_source_survives_response_serialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An enriched ja entry serializes with ``source: inaturalist`` (F2).

    Guards against Pydantic dropping the enrichment ``source`` from the GBIF
    search response (so it survives all the way to the from-GBIF materialize).
    """
    search_payload = {
        "results": [
            {
                "key": 9300,
                "scientificName": "Sourceus testus",
                "canonicalName": "Sourceus testus",
                "rank": "SPECIES",
                "datasetKey": gbif_module.GBIF_BACKBONE_DATASET_KEY,
                "vernacularNames": [
                    {"vernacularName": "Source Bird", "language": "eng"},
                ],
            }
        ]
    }
    inat_payload = {
        "results": [
            {"name": "Sourceus testus", "preferred_common_name": "ソース鳥"},
        ]
    }
    _install_client(
        monkeypatch,
        {"/species/search": search_payload, "inaturalist.org/v1/taxa": inat_payload},
    )

    svc = GBIFService()
    results = await svc.search_species_full("source", limit=10, locale="ja")

    # Serialize exactly as the API route does.
    serialized = GBIFSpeciesResult.model_validate(results[0])
    dumped = serialized.model_dump()
    ja_names = [
        vn for vn in (dumped["vernacular_names"] or []) if vn["language"] == "ja"
    ]
    assert ja_names and ja_names[0]["name"] == "ソース鳥"
    assert ja_names[0]["source"] == "inaturalist"


@pytest.mark.asyncio
async def test_parse_inline_name_is_locale_aware() -> None:
    """The inline-name picker prefers the requested locale over English."""
    svc = GBIFService()
    raw = [
        {
            "key": 6006,
            "scientificName": "Inline testus",
            "canonicalName": "Inline testus",
            "rank": "SPECIES",
            "datasetKey": gbif_module.GBIF_BACKBONE_DATASET_KEY,
            "vernacularNames": [
                {"vernacularName": "English Name", "language": "eng"},
                {"vernacularName": "和名イン", "language": "jpn"},
            ],
        }
    ]
    parsed = svc._parse_species_search_results(raw, locale="ja")
    assert parsed[0]["vernacular_name"] == "和名イン"

    parsed_en = svc._parse_species_search_results(raw, locale="en")
    assert parsed_en[0]["vernacular_name"] == "English Name"


def test_parse_excludes_empty_language_vernacular_entries() -> None:
    """GBIF rows with an empty/None language (or name) are dropped at parse.

    Regression: GBIF returns vernacular rows with null/empty ``language``; if
    they survive into the from-GBIF payload they trip the ``min_length=1``
    constraint on ``VernacularNameInput`` and 422 the whole add.
    """
    svc = GBIFService()
    raw = [
        {
            "key": 7007,
            "scientificName": "Empty langus",
            "canonicalName": "Empty langus",
            "rank": "SPECIES",
            "datasetKey": gbif_module.GBIF_BACKBONE_DATASET_KEY,
            "vernacularNames": [
                {"vernacularName": "Good English", "language": "eng"},
                {"vernacularName": "和名グッド", "language": "jpn"},
                {"vernacularName": "No Language", "language": ""},
                {"vernacularName": "Null Language"},  # missing language key
                {"vernacularName": "", "language": "eng"},  # empty name
            ],
        }
    ]

    parsed = svc._parse_species_search_results(raw, locale="en")
    vns = parsed[0]["vernacular_names"]

    # Every surviving entry has a non-blank name AND a non-blank language.
    assert all(vn["name"] and vn["language"] for vn in vns)
    # The two valid entries are kept (eng normalised + jpn→ja).
    assert {"name": "Good English", "language": "en"} in vns
    assert {"name": "和名グッド", "language": "ja"} in vns
    # The three junk entries are excluded.
    names = {vn["name"] for vn in vns}
    assert "No Language" not in names
    assert "Null Language" not in names
    assert "" not in names

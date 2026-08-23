"""Unit tests for the Catalogue of Life XR identity client (WS-A v2 slice 3).

All external HTTP is faked — no live network is used and the rate limiter is a
no-op so the tests stay fast. The behaviours locked here are exactly the ones
that are easy to get wrong against the real API:

* the ``checklistKey`` must always be sent (without it GBIF silently answers
  from its frozen legacy backbone);
* the verdict is driven by ``diagnostics.matchType``, never by
  ``usage.status`` — a ``HIGHERRANK`` hit returns an ``ACCEPTED`` genus;
* on ``NONE`` there is no ``usage`` at all and ``confidence`` is a sentinel
  ``100`` that must not be persisted as a score;
* a synonym's accepted identity comes from ``acceptedUsage``;
* the classification is filtered down to the seven principal ranks;
* HTTP 429 is retried with backoff, other failures raise a typed error.

Mirrors the fake-client pattern of ``test_gbif_typed_errors.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from typing import Any

import httpx
import pytest

from echoroo.core.exceptions import (
    COLXRMetadataError,
    COLXRUnavailableError,
    ExternalServiceError,
)
from echoroo.services import col_xr as col_xr_module
from echoroo.services.col_xr import (
    COL_XR_CHECKLIST_KEY,
    PRINCIPAL_RANKS,
    COLXRMatch,
    COLXRService,
    _canonical_name,
    decide_match,
)


@pytest.fixture(autouse=True)
def _no_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _acquire(self: Any) -> None:
        return None

    monkeypatch.setattr(col_xr_module.RateLimiter, "acquire", _acquire)


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Collapse the 429 backoff so retry tests do not actually wait."""

    async def _sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(col_xr_module.asyncio, "sleep", _sleep)


# ---------------------------------------------------------------------------
# Fake HTTP plumbing
# ---------------------------------------------------------------------------


class _Response:
    def __init__(
        self,
        payload: dict[str, Any],
        status_code: int = 200,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"status {self.status_code}",
                request=httpx.Request("GET", "https://example.invalid"),
                response=httpx.Response(self.status_code, headers=self.headers),
            )

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    """Replays a scripted list of outcomes and records the params it saw.

    Each scripted entry is either a :class:`_Response` or an exception
    instance to raise.
    """

    def __init__(self, *script: Any) -> None:
        self._script = list(script)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get(self, url: str, params: dict[str, Any] | None = None) -> _Response:
        self.calls.append((url, dict(params or {})))
        outcome = self._script.pop(0) if self._script else self._script_exhausted()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    @staticmethod
    def _script_exhausted() -> Any:  # pragma: no cover - defensive
        raise AssertionError("fake client called more times than scripted")


def _service(*script: Any) -> tuple[COLXRService, _FakeClient]:
    service = COLXRService()
    client = _FakeClient(*script)
    # Inject the fake in place of the pooled ``httpx.AsyncClient``.
    service._get_client = lambda: client  # type: ignore[method-assign, assignment]
    return service, client


def _rate_limited(headers: dict[str, str] | None = None) -> httpx.HTTPStatusError:
    return httpx.HTTPStatusError(
        "429",
        request=httpx.Request("GET", "https://example.invalid"),
        response=httpx.Response(429, headers=headers or {}),
    )


# ---------------------------------------------------------------------------
# Payload builders (shapes verified against the live API)
# ---------------------------------------------------------------------------


_FULL_CLASSIFICATION: list[dict[str, str]] = [
    {"key": "CS5HF", "name": "Eukaryota", "rank": "DOMAIN"},
    {"key": "N", "name": "Animalia", "rank": "KINGDOM"},
    {"key": "CH2", "name": "Chordata", "rank": "PHYLUM"},
    {"key": "8V4V3", "name": "Vertebrata", "rank": "SUBPHYLUM"},
    {"key": "9CK8W", "name": "Tetrapoda", "rank": "MEGACLASS"},
    {"key": "V2", "name": "Aves", "rank": "CLASS"},
    {"key": "6222V", "name": "Passeriformes", "rank": "ORDER"},
    {"key": "9BQ", "name": "Passeridae", "rank": "FAMILY"},
    {"key": "62DTG", "name": "Passer", "rank": "GENUS"},
    {"key": "4DXY4", "name": "Passer montanus", "rank": "SPECIES"},
]


def _exact_payload() -> dict[str, Any]:
    return {
        "usage": {
            "key": "4DXY4",
            "name": "Passer montanus (Linnaeus, 1758)",
            "canonicalName": "Passer montanus",
            "authorship": "(Linnaeus, 1758)",
            "rank": "SPECIES",
            "status": "ACCEPTED",
        },
        "acceptedUsage": None,
        "synonym": False,
        "classification": _FULL_CLASSIFICATION,
        "diagnostics": {"matchType": "EXACT", "confidence": 99},
    }


def _synonym_payload() -> dict[str, Any]:
    return {
        "usage": {
            "key": "93V8",
            "canonicalName": "Accipiter gularis",
            "authorship": "(Temminck & Schlegel, 1845)",
            "rank": "SPECIES",
            "status": "SYNONYM",
        },
        "acceptedUsage": {
            "key": "CVWBS",
            "canonicalName": "Tachyspiza gularis",
            "authorship": "(Temminck & Schlegel, 1845)",
            "rank": "SPECIES",
            "status": "ACCEPTED",
        },
        "synonym": True,
        "classification": _FULL_CLASSIFICATION,
        "diagnostics": {"matchType": "EXACT", "confidence": 98},
    }


def _variant_payload(confidence: int = 93) -> dict[str, Any]:
    payload = _exact_payload()
    payload["diagnostics"] = {
        "matchType": "VARIANT",
        "confidence": confidence,
        "note": "Similarity: name=90",
    }
    return payload


def _higherrank_payload() -> dict[str, Any]:
    return {
        "usage": {
            "key": "N",
            "canonicalName": "Animalia",
            "rank": "KINGDOM",
            # NOTE: status is ACCEPTED even though this is NOT an identity.
            "status": "ACCEPTED",
        },
        "acceptedUsage": None,
        "synonym": False,
        "classification": [
            {"key": "CS5HF", "name": "Eukaryota", "rank": "DOMAIN"},
            {"key": "N", "name": "Animalia", "rank": "KINGDOM"},
        ],
        "diagnostics": {"matchType": "HIGHERRANK", "confidence": 99},
    }


def _none_payload() -> dict[str, Any]:
    # Live shape: no ``usage`` key at all, and confidence is a sentinel 100.
    return {
        "synonym": False,
        "classification": [],
        "diagnostics": {"matchType": "NONE", "confidence": 100},
    }


# ---------------------------------------------------------------------------
# get_index_metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_index_metadata_reads_release_pin() -> None:
    service, client = _service(
        _Response(
            {
                "mainIndex": {
                    "clbDatasetKey": "315557",
                    "datasetAlias": "COL26.6 XR",
                    "created": "2026-08-01T00:00:00Z",
                }
            }
        )
    )

    index = await service.get_index_metadata()

    assert index.alias == "COL26.6 XR"
    # The upstream reports the key as a STRING; we persist an int column.
    assert index.clb_dataset_key == 315557
    assert index.created == "2026-08-01T00:00:00Z"
    _url, params = client.calls[0]
    assert params["checklistKey"] == COL_XR_CHECKLIST_KEY


@pytest.mark.asyncio
async def test_index_metadata_accepts_top_level_alias_key_layout() -> None:
    """The matching-ws README documents a flat ``alias`` / ``key`` shape."""
    service, _client = _service(
        _Response({"alias": "COL26.6 XR", "key": 315557, "created": "2026-08-01"})
    )

    index = await service.get_index_metadata()

    assert index.alias == "COL26.6 XR"
    assert index.clb_dataset_key == 315557
    assert index.created == "2026-08-01"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({}, id="empty"),
        pytest.param({"mainIndex": {}}, id="empty-main-index"),
        pytest.param(
            {"mainIndex": {"datasetAlias": "COL26.6 XR"}}, id="alias-without-key"
        ),
        pytest.param({"mainIndex": {"clbDatasetKey": "315557"}}, id="key-without-alias"),
        pytest.param({"alias": "COL26.6 XR"}, id="flat-alias-without-key"),
    ],
)
async def test_index_metadata_requires_a_complete_release_pin(
    payload: dict[str, Any],
) -> None:
    """An incomplete pin is refused: rows stamped with it could never be
    re-selected by the forced re-resolution, which keys on exactly that pin."""
    service, _client = _service(_Response(payload))

    with pytest.raises(COLXRMetadataError):
        await service.get_index_metadata()


@pytest.mark.asyncio
async def test_index_metadata_error_is_an_upstream_error_subclass() -> None:
    """Existing outage handling must keep catching it unchanged."""
    service, _client = _service(_Response({}))

    with pytest.raises(COLXRUnavailableError) as exc_info:
        await service.get_index_metadata()

    assert isinstance(exc_info.value, ExternalServiceError)


# ---------------------------------------------------------------------------
# match()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_match_always_sends_the_checklist_key_and_hints() -> None:
    """Without ``checklistKey`` GBIF answers from the frozen legacy backbone."""
    service, client = _service(_Response(_exact_payload()))

    await service.match("Passer montanus")

    _url, params = client.calls[0]
    assert params["checklistKey"] == COL_XR_CHECKLIST_KEY
    assert params["scientificName"] == "Passer montanus"
    assert params["kingdom"] == "Animalia"
    assert params["rank"] == "SPECIES"
    assert params["strict"] == "false"


@pytest.mark.asyncio
async def test_match_exact_accepted() -> None:
    service, _client = _service(_Response(_exact_payload()))

    result = await service.match("Passer montanus")

    assert result is not None
    assert result.match_type == "EXACT"
    assert result.confidence == 99
    assert result.usage_key == "4DXY4"
    assert result.canonical_name == "Passer montanus"
    assert result.authorship == "(Linnaeus, 1758)"
    assert result.status == "ACCEPTED"
    assert result.synonym is False
    # Not a synonym: the accepted side mirrors the usage so callers never have
    # to branch on ``synonym``.
    assert result.accepted_key == "4DXY4"
    assert result.accepted_canonical_name == "Passer montanus"
    assert result.accepted_authorship == "(Linnaeus, 1758)"
    assert result.accepted_rank == "SPECIES"
    assert decide_match(result) == "accept"


@pytest.mark.asyncio
async def test_match_synonym_takes_accepted_fields_from_accepted_usage() -> None:
    service, _client = _service(_Response(_synonym_payload()))

    result = await service.match("Accipiter gularis")

    assert result is not None
    assert result.synonym is True
    assert result.status == "SYNONYM"
    assert result.usage_key == "93V8"
    assert result.canonical_name == "Accipiter gularis"
    assert result.accepted_key == "CVWBS"
    assert result.accepted_canonical_name == "Tachyspiza gularis"
    assert result.accepted_rank == "SPECIES"
    # A synonym is still an identity when the match itself was EXACT.
    assert decide_match(result) == "accept"


@pytest.mark.asyncio
async def test_match_accepted_usage_may_be_subspecies() -> None:
    """COL lumps: the accepted usage of a species can be a subspecies."""
    payload = _synonym_payload()
    payload["acceptedUsage"]["rank"] = "SUBSPECIES"
    payload["acceptedUsage"]["canonicalName"] = "Mirafra javanica cantillans"
    service, _client = _service(_Response(payload))

    result = await service.match("Mirafra cantillans")

    assert result is not None
    assert result.accepted_rank == "SUBSPECIES"
    assert result.accepted_canonical_name == "Mirafra javanica cantillans"


@pytest.mark.asyncio
async def test_match_variant_above_floor_is_review() -> None:
    service, _client = _service(_Response(_variant_payload(93)))

    result = await service.match("Passer montanuss")

    assert result is not None
    assert result.match_type == "VARIANT"
    assert result.confidence == 93
    assert result.note == "Similarity: name=90"
    # Review still carries the full identity — the match type records how.
    assert result.usage_key == "4DXY4"
    assert decide_match(result) == "review"


@pytest.mark.asyncio
async def test_match_variant_below_floor_is_rejected() -> None:
    service, _client = _service(_Response(_variant_payload(70)))

    result = await service.match("Passer montanussss")

    assert decide_match(result) == "reject"


@pytest.mark.asyncio
async def test_match_higherrank_is_rejected_despite_accepted_status() -> None:
    """Gate on matchType: a HIGHERRANK usage reports status ACCEPTED."""
    service, _client = _service(_Response(_higherrank_payload()))

    result = await service.match("Zzzz qqqq")

    assert result is not None
    assert result.match_type == "HIGHERRANK"
    assert result.status == "ACCEPTED"
    assert result.usage_key == "N"
    assert decide_match(result) == "reject"


@pytest.mark.asyncio
async def test_match_none_has_no_usage_and_drops_sentinel_confidence() -> None:
    service, _client = _service(_Response(_none_payload()))

    result = await service.match("Not a name at all")

    assert result is not None
    assert result.match_type == "NONE"
    assert result.usage_key is None
    assert result.canonical_name is None
    # The API reports 100 on NONE; that is a sentinel, not a score.
    assert result.confidence is None
    assert decide_match(result) == "reject"


@pytest.mark.asyncio
async def test_match_filters_classification_to_principal_ranks() -> None:
    service, _client = _service(_Response(_exact_payload()))

    result = await service.match("Passer montanus")

    assert result is not None
    assert set(result.classification) == set(PRINCIPAL_RANKS)
    # The extra ranks COL returns are dropped, not merely ignored.
    assert "DOMAIN" not in result.classification
    assert "SUBPHYLUM" not in result.classification
    assert "MEGACLASS" not in result.classification
    assert result.classification["CLASS"] == {"key": "V2", "name": "Aves"}


@pytest.mark.asyncio
async def test_match_blank_name_short_circuits() -> None:
    service, client = _service()

    assert await service.match("   ") is None
    assert client.calls == []


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_match_retries_429_then_succeeds() -> None:
    service, client = _service(
        _rate_limited(), _rate_limited(), _Response(_exact_payload())
    )

    result = await service.match("Passer montanus")

    assert result is not None
    assert result.usage_key == "4DXY4"
    assert len(client.calls) == 3


@pytest.mark.asyncio
async def test_match_honours_numeric_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []

    async def _record_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(col_xr_module.asyncio, "sleep", _record_sleep)

    service, _client = _service(
        _rate_limited({"Retry-After": "7"}), _Response(_exact_payload())
    )

    await service.match("Passer montanus")

    # The server told us exactly how long to wait; jitter must not override it.
    assert slept == [7.0]


@pytest.mark.asyncio
async def test_match_honours_http_date_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []

    async def _record_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(col_xr_module.asyncio, "sleep", _record_sleep)

    when = datetime.now(UTC) + timedelta(seconds=5)
    service, _client = _service(
        _rate_limited({"Retry-After": format_datetime(when, usegmt=True)}),
        _Response(_exact_payload()),
    )

    await service.match("Passer montanus")

    assert len(slept) == 1
    assert 2.0 <= slept[0] <= 8.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "header",
    [
        pytest.param("not-a-date", id="garbage"),
        pytest.param("-30", id="negative"),
    ],
)
async def test_match_falls_back_to_jittered_backoff_on_bad_retry_after(
    monkeypatch: pytest.MonkeyPatch, header: str
) -> None:
    slept: list[float] = []

    async def _record_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(col_xr_module.asyncio, "sleep", _record_sleep)

    service, _client = _service(
        _rate_limited({"Retry-After": header}), _Response(_exact_payload())
    )

    await service.match("Passer montanus")

    # First attempt: base 1.0s * jitter in [0.5, 1.5].
    assert len(slept) == 1
    assert 0.5 <= slept[0] <= 1.5


@pytest.mark.asyncio
async def test_match_caps_an_absurd_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hostile header must not park the task past its soft time limit."""
    slept: list[float] = []

    async def _record_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(col_xr_module.asyncio, "sleep", _record_sleep)

    service, _client = _service(
        _rate_limited({"Retry-After": "999999"}), _Response(_exact_payload())
    )

    await service.match("Passer montanus")

    assert slept == [col_xr_module._RETRY_AFTER_MAX_SECONDS]


def test_backoff_is_jittered_not_deterministic() -> None:
    """Without jitter a throttled fleet would retry in lockstep."""
    samples = {col_xr_module._backoff_delay(1) for _ in range(50)}

    assert len(samples) > 1
    assert all(0.5 <= value <= 1.5 for value in samples)
    # Attempt 2 doubles the base band.
    assert all(1.0 <= col_xr_module._backoff_delay(2) <= 3.0 for _ in range(20))


@pytest.mark.asyncio
async def test_match_429_beyond_retry_budget_raises_typed_error() -> None:
    service, client = _service(_rate_limited(), _rate_limited(), _rate_limited())

    with pytest.raises(COLXRUnavailableError):
        await service.match("Passer montanus")

    assert len(client.calls) == 3


@pytest.mark.asyncio
async def test_match_5xx_raises_typed_error_without_retrying() -> None:
    service, client = _service(_Response({}, status_code=503))

    with pytest.raises(COLXRUnavailableError) as exc_info:
        await service.match("Passer montanus")

    # Batch callers catch the shared base class.
    assert isinstance(exc_info.value, ExternalServiceError)
    assert exc_info.value.service == "col_xr"
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_match_transport_error_raises_typed_error() -> None:
    service, _client = _service(httpx.ConnectError("boom"))

    with pytest.raises(COLXRUnavailableError):
        await service.match("Passer montanus")


@pytest.mark.asyncio
async def test_non_object_payload_raises_typed_error() -> None:
    class _ListResponse(_Response):
        def json(self) -> Any:  # type: ignore[override]
            return ["not", "an", "object"]

    service, _client = _service(_ListResponse({}))

    with pytest.raises(COLXRUnavailableError):
        await service.match("Passer montanus")


@pytest.mark.asyncio
async def test_malformed_json_body_raises_typed_error() -> None:
    class _BadJson(_Response):
        def json(self) -> Any:  # type: ignore[override]
            raise ValueError("Expecting value: line 1 column 1")

    service, _client = _service(_BadJson({}))

    with pytest.raises(COLXRUnavailableError):
        await service.match("Passer montanus")


@pytest.mark.asyncio
async def test_aclose_is_safe_without_a_client() -> None:
    service = COLXRService()

    await service.aclose()  # must not raise
    async with COLXRService():
        pass


# ---------------------------------------------------------------------------
# decide_match table
# ---------------------------------------------------------------------------


def _match(match_type: str, confidence: int | None, usage_key: str | None = "K") -> COLXRMatch:
    return COLXRMatch(
        usage_key=usage_key,
        canonical_name="X y",
        authorship=None,
        rank="SPECIES",
        status="ACCEPTED",
        accepted_key=usage_key,
        accepted_canonical_name="X y",
        accepted_authorship=None,
        accepted_rank="SPECIES",
        synonym=False,
        match_type=match_type,
        confidence=confidence,
        classification={},
        note=None,
    )


@pytest.mark.parametrize(
    ("match_type", "confidence", "usage_key", "expected"),
    [
        ("EXACT", 100, "K", "accept"),
        ("EXACT", 60, "K", "accept"),  # EXACT wins regardless of confidence
        ("exact", 99, "K", "accept"),  # case-insensitive
        ("VARIANT", 90, "K", "review"),  # exactly on the floor
        ("VARIANT", 89, "K", "reject"),
        ("FUZZY", 95, "K", "review"),
        ("FUZZY", 50, "K", "reject"),
        ("FUZZY", None, "K", "reject"),
        ("HIGHERRANK", 99, "K", "reject"),
        ("NONE", None, None, "reject"),
        ("EXACT", 100, None, "reject"),  # no usage key => no identity
    ],
)
def test_decide_match_table(
    match_type: str, confidence: int | None, usage_key: str | None, expected: str
) -> None:
    assert decide_match(_match(match_type, confidence, usage_key)) == expected


def test_decide_match_none_input_is_rejected() -> None:
    assert decide_match(None) == "reject"


# ---------------------------------------------------------------------------
# Canonical (authorship-free) name extraction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_accepted_name_never_carries_authorship() -> None:
    """``usage.name`` includes the authorship; a canonical slot must not.

    Storing "Acacia acuminata Benth." in ``accepted_scientific_name`` would
    poison every downstream name comparison (crosswalk lookups, the IOC bundle
    join, operator eyeballing).
    """
    payload = {
        "usage": {
            "key": "AAA",
            "name": "Acacia acuminata Benth.",
            "authorship": "Benth.",
            "genericName": "Acacia",
            "specificEpithet": "acuminata",
            "rank": "SPECIES",
            "status": "SYNONYM",
        },
        "acceptedUsage": {
            "key": "BBB",
            # No ``canonicalName`` at all — the assembly path must kick in.
            "name": "Acacia acuminata Benth.",
            "authorship": "Benth.",
            "genericName": "Acacia",
            "specificEpithet": "acuminata",
            "rank": "SPECIES",
            "status": "ACCEPTED",
        },
        "synonym": True,
        "classification": [],
        "diagnostics": {"matchType": "EXACT", "confidence": 98},
    }
    service, _client = _service(_Response(payload))

    result = await service.match("Acacia acuminata")

    assert result is not None
    assert result.accepted_canonical_name == "Acacia acuminata"
    assert result.canonical_name == "Acacia acuminata"
    # The authorship still travels, just in its own field.
    assert result.accepted_authorship == "Benth."
    assert "Benth." not in (result.accepted_canonical_name or "")


@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        pytest.param(
            {"canonicalName": "Passer montanus", "name": "Passer montanus L."},
            "Passer montanus",
            id="canonicalName-wins",
        ),
        pytest.param(
            {
                "name": "Acacia acuminata Benth.",
                "authorship": "Benth.",
                "genericName": "Acacia",
                "specificEpithet": "acuminata",
            },
            "Acacia acuminata",
            id="assembled-from-epithets",
        ),
        pytest.param(
            {
                "name": "Mirafra javanica cantillans Blyth, 1845",
                "authorship": "Blyth, 1845",
                "genericName": "Mirafra",
                "specificEpithet": "javanica",
                "infraspecificEpithet": "cantillans",
            },
            "Mirafra javanica cantillans",
            id="assembled-trinomial",
        ),
        pytest.param(
            {"name": "Corvus Linnaeus, 1758", "genericName": "Corvus"},
            "Corvus",
            id="genus-rank",
        ),
        pytest.param(
            {"name": "Acacia acuminata Benth.", "authorship": "Benth."},
            "Acacia acuminata",
            id="strip-authorship-suffix",
        ),
        pytest.param(
            {"name": "Acacia acuminata"},
            "Acacia acuminata",
            id="name-without-authorship",
        ),
        pytest.param({}, None, id="nothing-usable"),
        pytest.param(
            # Authorship not actually a suffix of name: keep the name intact
            # rather than mangling it.
            {"name": "Acacia acuminata", "authorship": "Benth."},
            "Acacia acuminata",
            id="authorship-not-a-suffix",
        ),
    ],
)
def test_canonical_name_resolution_order(
    usage: dict[str, Any], expected: str | None
) -> None:
    assert _canonical_name(usage) == expected

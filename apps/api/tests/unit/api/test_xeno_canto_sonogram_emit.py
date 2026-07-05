"""W2-4 PR-D: server-emitted sonogram_url must target the /web-api/v1 BFF.

The legacy ``search_xeno_canto`` rewrites each recording's ``sonogram_url``
to point at our same-origin sonogram proxy (to dodge Chrome ORB blocking on
cross-origin ``<img>`` loads). W2-4 PR-D unmounted the legacy ``/api/v1``
sonogram route and moved the proxy to the ``/web-api/v1`` BFF surface, so the
emitted URL must now carry the ``/web-api/v1`` prefix. This test locks that
contract by exercising ``search_xeno_canto`` with a stubbed Xeno-canto
upstream.
"""

from __future__ import annotations

import urllib.parse
from types import SimpleNamespace
from uuid import uuid4

import pytest

from echoroo.api.v1 import xeno_canto as xc_module


class _FakeResponse:
    """Minimal httpx.Response stand-in for the Xeno-canto search call."""

    def raise_for_status(self) -> None:  # noqa: D401 - stub
        return None

    def json(self) -> dict[str, object]:
        return {
            "numRecordings": 1,
            "numSpecies": 1,
            "page": 1,
            "numPages": 1,
            "recordings": [
                {
                    "id": "1234",
                    "gen": "Larus",
                    "sp": "fuscus",
                    # Protocol-relative sono URL, as the real API returns.
                    "sono": {"small": "//xeno-canto.org/sounds/spectrogram/1234-small.png"},
                }
            ],
        }


class _FakeAsyncClient:
    """Async context manager returning a canned search response."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    async def get(self, *args: object, **kwargs: object) -> _FakeResponse:
        return _FakeResponse()


@pytest.mark.asyncio
async def test_sonogram_url_emitted_with_web_api_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_id = uuid4()

    async def _fake_access(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(xc_module, "check_project_access", _fake_access)
    monkeypatch.setattr(xc_module, "_get_api_key", lambda: "real-key")
    monkeypatch.setattr(xc_module.httpx, "AsyncClient", _FakeAsyncClient)

    # Pass every optional filter explicitly as None: calling the handler
    # directly (not via FastAPI) means unset params would otherwise be the
    # ``Query(...)`` default objects rather than ``None``.
    result = await xc_module.search_xeno_canto(
        project_id=project_id,
        current_user=SimpleNamespace(id=uuid4()),
        db=object(),
        query="Larus fuscus",
        country=None,
        area=None,
        quality_min=None,
        recording_type=None,
        page=1,
        per_page=25,
    )

    assert len(result.recordings) == 1
    emitted = result.recordings[0].sonogram_url
    assert emitted is not None
    # New BFF-prefixed proxy URL (W2-4 PR-D), NOT the unmounted /api/v1 route.
    expected_prefix = f"/web-api/v1/projects/{project_id}/xeno-canto/sonogram?url="
    assert emitted.startswith(expected_prefix), emitted
    assert "/api/v1/" not in emitted
    # The upstream sono URL is normalised to https and URL-encoded in the query.
    encoded = emitted[len(expected_prefix):]
    decoded = urllib.parse.unquote(encoded)
    assert decoded == "https://xeno-canto.org/sounds/spectrogram/1234-small.png"

"""Unit tests for the Xeno-canto 'not configured' contract.

The historical ``_get_api_key`` returned the literal string ``"demo"`` when
``XENO_CANTO_API_KEY`` was unset; the v3 API rejects that placeholder, so a
deployment without a real key failed at first use with a confusing upstream
error. The W1 boot-validation feature replaces that with:

  * ``_get_api_key`` returning ``None`` when no usable key is configured.
  * A typed ``xeno_canto_not_configured`` 409 raised by the search endpoint.
  * A ``Settings.xeno_canto_enabled`` capability flag (non-empty, != 'demo').
  * The flag surfaced on the embedding-stats response the search page fetches.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import HTTPException, status

from echoroo.api.v1 import xeno_canto as xc_module
from echoroo.core.settings import Settings, get_settings


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _patch_settings(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setattr(xc_module, "get_settings", lambda: settings)


# ---------------------------------------------------------------------------
# Settings.xeno_canto_enabled property
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        (None, False),
        ("", False),
        ("   ", False),
        ("demo", False),
        ("DEMO", False),
        ("  demo  ", False),
        ("real-api-key-123", True),
    ],
)
def test_xeno_canto_enabled_property(key: str | None, expected: bool) -> None:
    settings = Settings(ENVIRONMENT="development", XENO_CANTO_API_KEY=key)
    assert settings.xeno_canto_enabled is expected


# ---------------------------------------------------------------------------
# _get_api_key None path
# ---------------------------------------------------------------------------


def test_get_api_key_returns_none_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(ENVIRONMENT="development", XENO_CANTO_API_KEY=None)
    _patch_settings(monkeypatch, settings)
    assert xc_module._get_api_key() is None


def test_get_api_key_returns_none_for_demo_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(ENVIRONMENT="development", XENO_CANTO_API_KEY="demo")
    _patch_settings(monkeypatch, settings)
    assert xc_module._get_api_key() is None


def test_get_api_key_returns_key_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(ENVIRONMENT="development", XENO_CANTO_API_KEY="  abc123  ")
    _patch_settings(monkeypatch, settings)
    # Returned value is stripped.
    assert xc_module._get_api_key() == "abc123"


# ---------------------------------------------------------------------------
# Typed 409 envelope
# ---------------------------------------------------------------------------


def test_not_configured_exception_shape() -> None:
    exc = xc_module._xeno_canto_not_configured_exception()
    assert isinstance(exc, HTTPException)
    assert exc.status_code == status.HTTP_409_CONFLICT
    assert isinstance(exc.detail, dict)
    assert exc.detail["error"] == "xeno_canto_not_configured"
    # The message must point operators at the env var to set.
    assert "XENO_CANTO_API_KEY" in exc.detail["message"]


# ---------------------------------------------------------------------------
# Capability flag on the embedding-stats response (search page bootstrap)
# ---------------------------------------------------------------------------


def test_embedding_stats_response_carries_capability_flag() -> None:
    from echoroo.schemas.search import EmbeddingStatsResponse

    # Default is False (fail-safe: hide XC entry points unless explicitly on).
    default = EmbeddingStatsResponse(total_count=0, by_model={}, by_dataset={})
    assert default.xeno_canto_enabled is False

    enabled = EmbeddingStatsResponse(
        total_count=0, by_model={}, by_dataset={}, xeno_canto_enabled=True
    )
    assert enabled.xeno_canto_enabled is True

"""Storage configuration errors must fail fast, not become per-item failures.

Callers no longer hold an S3 client (storage migration slice 1), so the client
is built inside each helper call — often inside a per-item ``except``.
``ensure_configured()`` keeps a malformed configuration surfacing where
``get_s3_client()`` used to raise.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from echoroo.core import s3 as s3_mod
from echoroo.services.audio.service import AudioService


def _broken_client() -> None:
    raise ValueError("Invalid endpoint: not-a-url")


def test_ensure_configured_propagates_client_construction_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(s3_mod, "get_s3_client", _broken_client)
    with pytest.raises(ValueError, match="Invalid endpoint"):
        s3_mod.ensure_configured()


def test_ensure_file_local_does_not_mask_configuration_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bad endpoint is not a missing recording: no FileNotFoundError, no mkdir."""
    monkeypatch.setattr(s3_mod, "get_s3_client", _broken_client)
    cache_dir = tmp_path / "cache"
    service = AudioService(
        audio_root=str(tmp_path / "audio"),
        s3_audio_cache_dir=str(cache_dir),
    )

    with pytest.raises(ValueError, match="Invalid endpoint"):
        service.ensure_file_local("recordings/p/d/r.wav")

    assert not (cache_dir / "recordings").exists()

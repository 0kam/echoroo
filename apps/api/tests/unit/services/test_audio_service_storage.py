"""Storage-backed AudioService cache behavior."""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest
import soundfile as sf
from starlette.requests import Request

from echoroo.api.v1 import recordings
from echoroo.core import storage
from echoroo.core.settings import get_settings
from echoroo.services.audio.service import AudioService


def _wav_bytes() -> bytes:
    import io

    output = io.BytesIO()
    sf.write(output, np.zeros(800, dtype=np.float32), 8000, format="WAV")
    return output.getvalue()


def test_ogg_cache_hit_refreshes_mtime_and_encoder_temps_are_unique(
    storage_root: Path, tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(get_settings(), "COMPRESSED_CACHE_DIR", str(tmp_path))
    key_a = "recordings/project/dataset/a.wav"
    key_b = "recordings/project/dataset/b.wav"
    storage.write_bytes(key_a, _wav_bytes())
    storage.write_bytes(key_b, _wav_bytes())
    outputs: list[Path] = []

    def _run(command: list[str], **kwargs: object) -> SimpleNamespace:
        output = Path(command[-1])
        outputs.append(output)
        output.write_bytes(b"ogg")
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr("echoroo.services.audio.service.subprocess.run", _run)
    service = AudioService()
    first = service.get_compressed_for_playback(key_a)
    first_mtime = first.stat().st_mtime_ns
    time.sleep(0.001)
    assert service.get_compressed_for_playback(key_a) == first
    assert first.stat().st_mtime_ns > first_mtime

    service.get_compressed_for_playback(key_b)
    assert len(outputs) == 2
    assert outputs[0].name.startswith(".echoroo-tmp-")
    assert outputs[1].name.startswith(".echoroo-tmp-")
    assert outputs[0] != outputs[1]
    assert not list(tmp_path.glob(".echoroo-tmp-*"))


def test_ogg_cache_source_path_is_resolved_from_storage(storage_root: Path, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "COMPRESSED_CACHE_DIR", str(tmp_path))
    key = "recordings/project/dataset/source.wav"
    storage.write_bytes(key, _wav_bytes())

    def _run(command: list[str], **kwargs: object) -> SimpleNamespace:
        Path(command[-1]).write_bytes(b"ogg")
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr("echoroo.services.audio.service.subprocess.run", _run)
    assert AudioService().get_compressed_for_playback(key).read_bytes() == b"ogg"


def test_missing_recording_rechecks_storage_readiness(
    storage_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing_path = storage_root / "recordings/project/dataset/missing.wav"
    readiness_checks: list[bool] = []
    monkeypatch.setattr(storage, "path_for", lambda _key: missing_path)
    monkeypatch.setattr(storage, "ensure_ready", lambda: readiness_checks.append(True))

    with pytest.raises(FileNotFoundError, match="missing.wav"):
        AudioService().ensure_file_local("recordings/project/dataset/missing.wav")

    assert readiness_checks == [True]


def test_ogg_cache_evicted_between_is_file_and_utime_is_reencoded(
    storage_root: Path, tmp_path: Path, monkeypatch
) -> None:
    key = "recordings/project/dataset/evicted.wav"
    storage.write_bytes(key, _wav_bytes())
    monkeypatch.setattr(get_settings(), "COMPRESSED_CACHE_DIR", str(tmp_path))
    outputs: list[Path] = []

    def _run(command: list[str], **kwargs: object) -> SimpleNamespace:
        output = Path(command[-1])
        outputs.append(output)
        output.write_bytes(b"ogg")
        return SimpleNamespace(returncode=0, stderr=b"")

    monkeypatch.setattr("echoroo.services.audio.service.subprocess.run", _run)
    service = AudioService()
    cache_path = service.get_compressed_for_playback(key)
    cache_path.write_bytes(b"old-ogg")

    def _evict_before_utime(path: Path, _times: object) -> None:
        assert path == cache_path
        path.unlink()
        raise FileNotFoundError(path)

    monkeypatch.setattr("echoroo.services.audio.service.os.utime", _evict_before_utime)

    replacement = service.get_compressed_for_playback(key)

    assert replacement == cache_path
    assert replacement.read_bytes() == b"ogg"
    assert len(outputs) == 2


@pytest.mark.asyncio
async def test_recording_route_reencodes_cache_vanished_before_open(
    storage_root: Path, tmp_path: Path, monkeypatch
) -> None:
    key = "recordings/project/dataset/vanished.wav"
    source = storage_root / key
    storage.write_bytes(key, _wav_bytes())
    missing_cache = tmp_path / "missing.ogg"
    replacement_cache = tmp_path / "replacement.ogg"
    calls = 0

    class _Audio:
        def ensure_file_local(self, path: str) -> Path:
            return storage.path_for(path)

        def get_compressed_for_playback(self, path: str) -> Path:
            nonlocal calls
            calls += 1
            if calls == 1:
                return missing_cache
            replacement_cache.write_bytes(b"ogg")
            return replacement_cache

    class _RecordingService:
        audio_service = _Audio()

        async def get_by_id_in_project(self, recording_id: object, project_id: object):
            return SimpleNamespace(path=key, time_expansion=1.0)

    async def _allow(**kwargs: object) -> None:
        return None

    monkeypatch.setattr(recordings, "gate_action", _allow)
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/audio",
            "headers": [],
            "query_string": b"",
            "client": ("test", 0),
            "server": ("test", 80),
            "scheme": "http",
        }
    )
    response = await recordings.stream_audio(
        project_id=uuid4(),
        recording_id=uuid4(),
        request=request,
        current_user=SimpleNamespace(id=uuid4()),
        service=_RecordingService(),
        db=object(),
    )

    body = b"".join([chunk async for chunk in response.body_iterator])
    assert body == b"ogg"
    assert calls == 2
    assert source.exists()

"""ML worker audio resolution tests without model weights."""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import soundfile as sf

from echoroo.core import storage
from echoroo.services.audio import AudioService
from echoroo.workers.ml.utils import _download_recordings_to_local


def test_ml_loader_resolves_storage_recording_without_model_weights(storage_root: Path) -> None:
    buffer = io.BytesIO()
    sf.write(buffer, np.zeros(800, dtype=np.float32), 8000, format="WAV")
    key = "recordings/project/dataset/recording.wav"
    storage.write_bytes(key, buffer.getvalue())

    recordings = [SimpleNamespace(id="recording-id", filename="recording.wav", path=key)]
    paths, failures = _download_recordings_to_local(recordings, AudioService())

    assert failures == 0
    assert paths == [(recordings[0], storage.path_for(key))]
    assert Path(paths[0][1]).read_bytes() == buffer.getvalue()

"""Integration coverage for storage-backed classifier artifacts."""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np

from echoroo.core import storage
from echoroo.ml.classifiers import UnifiedClassifier
from echoroo.workers.classifier.utils import _store_model, _stored_model_path


def _trained_classifier(offset: float) -> UnifiedClassifier:
    """Train a small deterministic classifier without database fixtures."""
    embeddings = np.array(
        [
            [1.0 + offset, 0.0],
            [0.8 + offset, 0.2],
            [0.0, 1.0 + offset],
            [0.2, 0.8 + offset],
        ],
        dtype=np.float32,
    )
    labels = np.array([1, 1, 0, 0], dtype=np.int32)
    return UnifiedClassifier().fit(embeddings, labels)


def test_classifier_artifact_replaces_atomically_and_keeps_existing_readers(
    storage_root: Path, tmp_path: Path
) -> None:
    """A retrain replaces the key while an existing handle reads old bytes."""
    key = "models/project/model/model.joblib"
    first_local = tmp_path / "first.joblib"
    second_local = tmp_path / "second.joblib"
    _trained_classifier(0.0).save(first_local)
    _trained_classifier(0.1).save(second_local)

    asyncio.run(_store_model(first_local, key))
    first_bytes = storage.path_for(key).read_bytes()
    assert _stored_model_path(key) == storage_root / key

    with storage.open_read(key) as previous_reader:
        asyncio.run(_store_model(second_local, key))
        assert previous_reader.read() == first_bytes

    assert storage.path_for(key).read_bytes() == second_local.read_bytes()
    assert storage.path_for(key).read_bytes() != first_bytes
    loaded = UnifiedClassifier.load(_stored_model_path(key))
    assert loaded.is_fitted

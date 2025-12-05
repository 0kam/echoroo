"""Common fixtures for ML integration tests."""

import numpy as np
import pytest
from pathlib import Path
from unittest.mock import Mock, MagicMock

from echoroo.ml.base import ModelLoader, ModelSpecification, InferenceEngine


@pytest.fixture
def mock_model():
    """Create a mock ML model object."""
    model = Mock()
    model.species_list = ["species_a", "species_b", "species_c"]
    model.n_species = 3
    model.get_sample_rate = Mock(return_value=48000)
    model.get_embeddings_dim = Mock(return_value=1024)
    return model


@pytest.fixture
def sample_audio_segment():
    """Create a sample audio segment for testing.

    Returns 3 seconds of random audio at 48kHz (BirdNET format).
    """
    return np.random.randn(144000).astype(np.float32)


@pytest.fixture
def perch_audio_segment():
    """Create a sample audio segment for Perch testing.

    Returns 5 seconds of random audio at 32kHz (Perch format).
    """
    return np.random.randn(160000).astype(np.float32)


@pytest.fixture
def sample_embedding():
    """Create a sample embedding vector."""
    return np.random.randn(1024).astype(np.float32)


@pytest.fixture
def sample_predictions():
    """Create sample prediction results."""
    return [
        ("species_a", 0.95),
        ("species_b", 0.82),
        ("species_c", 0.65),
    ]


class MockModelLoader(ModelLoader):
    """Mock model loader for testing."""

    def __init__(self, mock_model=None, should_fail=False):
        super().__init__()
        self._mock_model_obj = mock_model or Mock()
        self._should_fail = should_fail

    @property
    def specification(self) -> ModelSpecification:
        return ModelSpecification(
            name="mock_model",
            version="1.0",
            sample_rate=48000,
            segment_duration=3.0,
            embedding_dim=1024,
            supports_classification=True,
            species_list=["species_a", "species_b", "species_c"],
        )

    def _load_model(self):
        if self._should_fail:
            raise RuntimeError("Mock loading failed")
        return self._mock_model_obj


class MockInferenceEngine(InferenceEngine):
    """Mock inference engine for testing."""

    def __init__(self, loader: ModelLoader, return_predictions=True):
        super().__init__(loader)
        self._return_predictions = return_predictions

    def predict_segment(self, audio, start_time=0.0):
        from echoroo.ml.base import InferenceResult

        embedding = np.random.randn(1024).astype(np.float32)
        predictions = []

        if self._return_predictions:
            predictions = [
                ("species_a", 0.95),
                ("species_b", 0.82),
            ]

        return InferenceResult(
            start_time=start_time,
            end_time=start_time + 3.0,
            embedding=embedding,
            predictions=predictions,
        )

    def predict_batch(self, segments, start_times):
        return [
            self.predict_segment(seg, start)
            for seg, start in zip(segments, start_times)
        ]


@pytest.fixture
def mock_loader(mock_model):
    """Create a mock model loader."""
    loader = MockModelLoader(mock_model)
    loader.load()
    return loader


@pytest.fixture
def mock_inference_engine(mock_loader):
    """Create a mock inference engine."""
    return MockInferenceEngine(mock_loader)

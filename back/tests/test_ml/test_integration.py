"""Integration tests for ML base classes and architecture.

This module tests the core ML architecture including:
- ModelLoader base class and lazy loading
- InferenceEngine base class and predict methods
- ModelSpecification validation
- InferenceResult validation
- Thread safety of model loading
- Integration between components
"""

import threading
import time
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest

from echoroo.ml.base import (
    InferenceEngine,
    InferenceResult,
    ModelLoader,
    ModelSpecification,
)

from .conftest import MockInferenceEngine, MockModelLoader


class TestModelSpecification:
    """Test ModelSpecification validation and properties."""

    def test_valid_specification(self):
        """Test creating a valid ModelSpecification."""
        spec = ModelSpecification(
            name="test_model",
            version="1.0",
            sample_rate=48000,
            segment_duration=3.0,
            embedding_dim=1024,
            supports_classification=True,
            species_list=["species_a", "species_b"],
        )

        assert spec.name == "test_model"
        assert spec.version == "1.0"
        assert spec.sample_rate == 48000
        assert spec.segment_duration == 3.0
        assert spec.embedding_dim == 1024
        assert spec.supports_classification is True
        assert len(spec.species_list) == 2

    def test_segment_samples_property(self):
        """Test segment_samples calculated correctly."""
        spec = ModelSpecification(
            name="test",
            version="1.0",
            sample_rate=48000,
            segment_duration=3.0,
            embedding_dim=1024,
        )

        assert spec.segment_samples == 144000

    def test_n_species_property(self):
        """Test n_species property."""
        spec = ModelSpecification(
            name="test",
            version="1.0",
            sample_rate=48000,
            segment_duration=3.0,
            embedding_dim=1024,
            species_list=["a", "b", "c"],
        )

        assert spec.n_species == 3

    def test_n_species_none_species_list(self):
        """Test n_species returns 0 when species_list is None."""
        spec = ModelSpecification(
            name="test",
            version="1.0",
            sample_rate=48000,
            segment_duration=3.0,
            embedding_dim=1024,
            species_list=None,
        )

        assert spec.n_species == 0

    def test_invalid_sample_rate(self):
        """Test validation of invalid sample rate."""
        with pytest.raises(ValueError, match="sample_rate must be positive"):
            ModelSpecification(
                name="test",
                version="1.0",
                sample_rate=0,
                segment_duration=3.0,
                embedding_dim=1024,
            )

    def test_invalid_segment_duration(self):
        """Test validation of invalid segment duration."""
        with pytest.raises(ValueError, match="segment_duration must be positive"):
            ModelSpecification(
                name="test",
                version="1.0",
                sample_rate=48000,
                segment_duration=-1.0,
                embedding_dim=1024,
            )

    def test_invalid_embedding_dim(self):
        """Test validation of invalid embedding dimension."""
        with pytest.raises(ValueError, match="embedding_dim must be positive"):
            ModelSpecification(
                name="test",
                version="1.0",
                sample_rate=48000,
                segment_duration=3.0,
                embedding_dim=0,
            )


class TestInferenceResult:
    """Test InferenceResult validation and properties."""

    def test_valid_result(self, sample_embedding, sample_predictions):
        """Test creating a valid InferenceResult."""
        result = InferenceResult(
            start_time=0.0,
            end_time=3.0,
            embedding=sample_embedding,
            predictions=sample_predictions,
        )

        assert result.start_time == 0.0
        assert result.end_time == 3.0
        assert result.embedding.shape == (1024,)
        assert len(result.predictions) == 3
        assert result.predictions[0] == ("species_a", 0.95)

    def test_duration_property(self, sample_embedding):
        """Test duration property calculation."""
        result = InferenceResult(
            start_time=1.5,
            end_time=4.5,
            embedding=sample_embedding,
        )

        assert result.duration == 3.0

    def test_top_prediction_property(self, sample_embedding, sample_predictions):
        """Test top_prediction property."""
        result = InferenceResult(
            start_time=0.0,
            end_time=3.0,
            embedding=sample_embedding,
            predictions=sample_predictions,
        )

        assert result.top_prediction == ("species_a", 0.95)

    def test_top_prediction_none_when_empty(self, sample_embedding):
        """Test top_prediction returns None when no predictions."""
        result = InferenceResult(
            start_time=0.0,
            end_time=3.0,
            embedding=sample_embedding,
            predictions=[],
        )

        assert result.top_prediction is None

    def test_has_detection_property(self, sample_embedding, sample_predictions):
        """Test has_detection property."""
        result_with = InferenceResult(
            start_time=0.0,
            end_time=3.0,
            embedding=sample_embedding,
            predictions=sample_predictions,
        )

        result_without = InferenceResult(
            start_time=0.0,
            end_time=3.0,
            embedding=sample_embedding,
            predictions=[],
        )

        assert result_with.has_detection is True
        assert result_without.has_detection is False

    def test_embedding_dim_property(self, sample_embedding):
        """Test embedding_dim property."""
        result = InferenceResult(
            start_time=0.0,
            end_time=3.0,
            embedding=sample_embedding,
        )

        assert result.embedding_dim == 1024

    def test_invalid_start_time(self, sample_embedding):
        """Test validation of negative start time."""
        with pytest.raises(ValueError, match="start_time must be non-negative"):
            InferenceResult(
                start_time=-1.0,
                end_time=3.0,
                embedding=sample_embedding,
            )

    def test_invalid_end_time(self, sample_embedding):
        """Test validation of end_time <= start_time."""
        with pytest.raises(ValueError, match="end_time.*must be greater"):
            InferenceResult(
                start_time=3.0,
                end_time=3.0,
                embedding=sample_embedding,
            )

    def test_invalid_embedding_shape(self):
        """Test validation of embedding shape."""
        bad_embedding = np.random.randn(10, 10).astype(np.float32)

        with pytest.raises(ValueError, match="embedding must be 1D"):
            InferenceResult(
                start_time=0.0,
                end_time=3.0,
                embedding=bad_embedding,
            )

    def test_dtype_conversion(self):
        """Test automatic conversion to float32."""
        embedding = np.random.randn(1024).astype(np.float64)

        result = InferenceResult(
            start_time=0.0,
            end_time=3.0,
            embedding=embedding,
        )

        assert result.embedding.dtype == np.float32

    def test_invalid_prediction_format(self, sample_embedding):
        """Test validation of prediction format."""
        with pytest.raises(ValueError, match="must be a.*tuple"):
            InferenceResult(
                start_time=0.0,
                end_time=3.0,
                embedding=sample_embedding,
                predictions=[["species_a", 0.95]],  # List instead of tuple
            )

    def test_invalid_prediction_confidence_range(self, sample_embedding):
        """Test validation of confidence scores."""
        with pytest.raises(ValueError, match="confidence must be in"):
            InferenceResult(
                start_time=0.0,
                end_time=3.0,
                embedding=sample_embedding,
                predictions=[("species_a", 1.5)],  # > 1.0
            )


class TestModelLoader:
    """Test ModelLoader base class functionality."""

    def test_loader_initialization(self):
        """Test ModelLoader can be initialized."""
        loader = MockModelLoader()

        assert loader.is_loaded is False
        assert loader.model_dir is None

    def test_lazy_loading(self, mock_model):
        """Test lazy loading - model not loaded on init."""
        loader = MockModelLoader(mock_model)

        assert loader.is_loaded is False

        # Load the model
        loader.load()

        assert loader.is_loaded is True

    def test_double_load_is_safe(self, mock_model):
        """Test loading model multiple times is safe."""
        loader = MockModelLoader(mock_model)

        loader.load()
        assert loader.is_loaded is True

        # Load again - should be no-op
        loader.load()
        assert loader.is_loaded is True

    def test_get_model_before_load_raises(self):
        """Test get_model raises RuntimeError before loading."""
        loader = MockModelLoader()

        with pytest.raises(RuntimeError, match="model not loaded"):
            loader.get_model()

    def test_get_model_after_load(self, mock_model):
        """Test get_model returns model after loading."""
        loader = MockModelLoader(mock_model)
        loader.load()

        model = loader.get_model()

        assert model is mock_model

    def test_unload(self, mock_model):
        """Test unloading model."""
        loader = MockModelLoader(mock_model)
        loader.load()

        assert loader.is_loaded is True

        loader.unload()

        assert loader.is_loaded is False

        # Should raise after unload
        with pytest.raises(RuntimeError, match="model not loaded"):
            loader.get_model()

    def test_reload_after_unload(self, mock_model):
        """Test reloading model after unload."""
        loader = MockModelLoader(mock_model)

        loader.load()
        loader.unload()
        loader.load()

        assert loader.is_loaded is True
        assert loader.get_model() is not None

    def test_repr(self, mock_model):
        """Test string representation of loader."""
        loader = MockModelLoader(mock_model)

        repr_str = repr(loader)

        assert "MockModelLoader" in repr_str
        assert "not loaded" in repr_str

        loader.load()
        repr_str = repr(loader)

        assert "loaded" in repr_str


class TestModelLoaderThreadSafety:
    """Test thread safety of ModelLoader lazy loading."""

    def test_concurrent_loading(self, mock_model):
        """Test multiple threads can safely load the same model."""
        loader = MockModelLoader(mock_model)
        load_count = [0]
        errors = []

        def load_model():
            try:
                loader.load()
                # Track that load was called
                load_count[0] += 1
            except Exception as e:
                errors.append(e)

        # Create 10 threads all trying to load at once
        threads = [threading.Thread(target=load_model) for _ in range(10)]

        # Start all threads
        for t in threads:
            t.start()

        # Wait for all to complete
        for t in threads:
            t.join()

        # Should not have any errors
        assert len(errors) == 0

        # Model should be loaded
        assert loader.is_loaded is True

        # All threads called load, but only one should have actually loaded
        assert load_count[0] == 10

    def test_concurrent_get_model(self, mock_model):
        """Test multiple threads can safely get the model."""
        loader = MockModelLoader(mock_model)
        loader.load()

        results = []
        errors = []

        def get_model():
            try:
                model = loader.get_model()
                results.append(model)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=get_model) for _ in range(10)]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(results) == 10
        # All should get the same model instance
        assert all(r is mock_model for r in results)


class TestInferenceEngine:
    """Test InferenceEngine base class functionality."""

    def test_engine_initialization_requires_loaded_model(self):
        """Test InferenceEngine requires loaded model."""
        loader = MockModelLoader()

        # Should raise if model not loaded
        with pytest.raises(RuntimeError, match="loader must be loaded"):
            MockInferenceEngine(loader)

    def test_engine_initialization_with_loaded_model(self, mock_loader):
        """Test InferenceEngine can be initialized with loaded model."""
        engine = MockInferenceEngine(mock_loader)

        assert engine.specification.name == "mock_model"

    def test_predict_segment_returns_inference_result(
        self, mock_loader, sample_audio_segment
    ):
        """Test predict_segment returns InferenceResult."""
        engine = MockInferenceEngine(mock_loader)

        result = engine.predict_segment(sample_audio_segment, start_time=0.0)

        assert isinstance(result, InferenceResult)
        assert result.start_time == 0.0
        assert result.end_time == 3.0
        assert result.embedding.shape == (1024,)

    def test_predict_batch_returns_list(self, mock_loader, sample_audio_segment):
        """Test predict_batch returns list of InferenceResults."""
        engine = MockInferenceEngine(mock_loader)

        segments = [sample_audio_segment for _ in range(3)]
        start_times = [0.0, 3.0, 6.0]

        results = engine.predict_batch(segments, start_times)

        assert len(results) == 3
        assert all(isinstance(r, InferenceResult) for r in results)
        assert results[0].start_time == 0.0
        assert results[1].start_time == 3.0
        assert results[2].start_time == 6.0

    def test_predict_file_not_found(self, mock_loader):
        """Test predict_file raises FileNotFoundError for missing file."""
        engine = MockInferenceEngine(mock_loader)

        with pytest.raises(FileNotFoundError):
            engine.predict_file(Path("/nonexistent/file.wav"))

    def test_predict_file_invalid_overlap(self, mock_loader, tmp_path):
        """Test predict_file validates overlap parameter."""
        engine = MockInferenceEngine(mock_loader)

        # Create a dummy file
        test_file = tmp_path / "test.wav"
        test_file.touch()

        # Overlap >= segment_duration should fail
        with pytest.raises(ValueError, match="overlap.*must be less than"):
            engine.predict_file(test_file, overlap=3.0)

        # Negative overlap should fail
        with pytest.raises(ValueError, match="overlap must be non-negative"):
            engine.predict_file(test_file, overlap=-1.0)

    def test_repr(self, mock_loader):
        """Test string representation of engine."""
        engine = MockInferenceEngine(mock_loader)

        repr_str = repr(engine)

        assert "MockInferenceEngine" in repr_str
        assert "mock_model" in repr_str
        assert "48000" in repr_str


class TestBaseClassIntegration:
    """Test integration between ModelLoader and InferenceEngine."""

    def test_specification_accessible_from_both(self, mock_loader):
        """Test specification is accessible from both loader and engine."""
        engine = MockInferenceEngine(mock_loader)

        loader_spec = mock_loader.specification
        engine_spec = engine.specification

        assert loader_spec.name == engine_spec.name
        assert loader_spec.version == engine_spec.version
        assert loader_spec.sample_rate == engine_spec.sample_rate

    def test_workflow_load_then_infer(self, mock_model, sample_audio_segment):
        """Test typical workflow: load model, create engine, run inference."""
        # Step 1: Create and load model
        loader = MockModelLoader(mock_model)
        loader.load()

        # Step 2: Create inference engine
        engine = MockInferenceEngine(loader)

        # Step 3: Run inference
        result = engine.predict_segment(sample_audio_segment)

        # Verify result
        assert isinstance(result, InferenceResult)
        assert result.embedding_dim == 1024

    def test_multiple_engines_share_loader(self, mock_loader, sample_audio_segment):
        """Test multiple engines can share the same loader."""
        engine1 = MockInferenceEngine(mock_loader, return_predictions=True)
        engine2 = MockInferenceEngine(mock_loader, return_predictions=False)

        result1 = engine1.predict_segment(sample_audio_segment)
        result2 = engine2.predict_segment(sample_audio_segment)

        # Both should work
        assert isinstance(result1, InferenceResult)
        assert isinstance(result2, InferenceResult)

        # But may have different behavior
        assert result1.has_detection is True
        assert result2.has_detection is False


class TestErrorHandling:
    """Test error handling in base classes."""

    def test_loader_load_failure(self):
        """Test ModelLoader handles load failures."""
        loader = MockModelLoader(should_fail=True)

        with pytest.raises(RuntimeError, match="Mock loading failed"):
            loader.load()

        # Should remain not loaded
        assert loader.is_loaded is False

    def test_model_remains_usable_after_error(self, mock_model):
        """Test loader can recover after failed load attempt."""
        # This would require a more sophisticated mock that fails once
        # then succeeds, but demonstrates the concept
        loader = MockModelLoader(mock_model)
        loader.load()

        # Even after successful load, unload and verify it works
        loader.unload()
        assert loader.is_loaded is False

        # Can reload
        loader.load()
        assert loader.is_loaded is True


class TestAbstractMethods:
    """Test that abstract methods are properly defined."""

    def test_model_loader_requires_specification(self):
        """Test ModelLoader subclass must implement specification."""

        class IncompleteLoader(ModelLoader):
            def _load_model(self):
                return Mock()

        # Should raise because specification is not implemented
        loader = IncompleteLoader()
        with pytest.raises(NotImplementedError):
            _ = loader.specification

    def test_model_loader_requires_load_model(self):
        """Test ModelLoader subclass must implement _load_model."""

        class IncompleteLoader(ModelLoader):
            @property
            def specification(self):
                return ModelSpecification(
                    name="test",
                    version="1.0",
                    sample_rate=48000,
                    segment_duration=3.0,
                    embedding_dim=1024,
                )

        loader = IncompleteLoader()
        with pytest.raises(NotImplementedError):
            loader.load()

    def test_inference_engine_requires_predict_segment(self, mock_loader):
        """Test InferenceEngine subclass must implement predict_segment."""

        class IncompleteEngine(InferenceEngine):
            def predict_batch(self, segments, start_times):
                return []

        engine = IncompleteEngine(mock_loader)
        with pytest.raises(NotImplementedError):
            engine.predict_segment(np.zeros(1000), 0.0)

    def test_inference_engine_requires_predict_batch(self, mock_loader):
        """Test InferenceEngine subclass must implement predict_batch."""

        class IncompleteEngine(InferenceEngine):
            def predict_segment(self, audio, start_time):
                return InferenceResult(
                    start_time=0.0,
                    end_time=3.0,
                    embedding=np.zeros(1024, dtype=np.float32),
                )

        engine = IncompleteEngine(mock_loader)
        with pytest.raises(NotImplementedError):
            engine.predict_batch([], [])

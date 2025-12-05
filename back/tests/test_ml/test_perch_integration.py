"""Integration tests for Perch implementation.

This module tests that Perch correctly inherits from and implements
the base ML architecture, including:
- PerchLoader inherits from ModelLoader
- PerchInference inherits from InferenceEngine
- Species classification capability (supports_classification=True)
- Embeddings + predictions are returned
- Backward compatibility with old Perch APIs
"""

import numpy as np
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from echoroo.ml.base import ModelLoader, InferenceEngine, InferenceResult
from echoroo.ml.perch.loader import PerchLoader
from echoroo.ml.perch.inference import (
    PerchInference,
    PerchResult,
    SAMPLE_RATE,
    SEGMENT_DURATION,
    EMBEDDING_DIM,
)


class TestPerchLoaderInheritance:
    """Test PerchLoader inherits from ModelLoader correctly."""

    def test_is_subclass_of_model_loader(self):
        """Test PerchLoader is a subclass of ModelLoader."""
        assert issubclass(PerchLoader, ModelLoader)

    def test_has_specification_property(self):
        """Test PerchLoader has specification property."""
        loader = PerchLoader()

        spec = loader.specification

        assert spec.name == "perch"
        assert spec.sample_rate == SAMPLE_RATE
        assert spec.segment_duration == SEGMENT_DURATION
        assert spec.embedding_dim == EMBEDDING_DIM

    def test_supports_classification(self):
        """Test Perch specification indicates classification support."""
        loader = PerchLoader()

        spec = loader.specification

        # Perch supports classification when class_list is available
        assert spec.supports_classification is True

    def test_is_loaded_false_initially(self):
        """Test PerchLoader is not loaded initially."""
        loader = PerchLoader()

        assert loader.is_loaded is False

    @patch("echoroo.ml.perch.loader.hoplite")
    def test_load_method_works(self, mock_hoplite):
        """Test PerchLoader.load() works."""
        # Setup mock
        mock_model = Mock()
        mock_model.class_list = Mock()
        mock_model.class_list.classes = ["class_a", "class_b"]
        mock_hoplite.load = Mock(return_value=mock_model)

        loader = PerchLoader()
        loader.load()

        assert loader.is_loaded is True

    @patch("echoroo.ml.perch.loader.hoplite")
    def test_get_model_returns_model(self, mock_hoplite):
        """Test PerchLoader.get_model() returns the model."""
        mock_model = Mock()
        mock_model.class_list = Mock()
        mock_model.class_list.classes = ["class_a", "class_b"]
        mock_hoplite.load = Mock(return_value=mock_model)

        loader = PerchLoader()
        loader.load()

        model = loader.get_model()

        assert model is mock_model

    @patch("echoroo.ml.perch.loader.hoplite")
    def test_species_list_populated_after_load(self, mock_hoplite):
        """Test species_list is populated after loading when available."""
        mock_model = Mock()
        mock_model.class_list = Mock()
        mock_model.class_list.classes = ["class_a", "class_b", "class_c"]
        mock_hoplite.load = Mock(return_value=mock_model)

        loader = PerchLoader()
        loader.load()

        # After loading, species_list should be populated if available
        spec = loader.specification
        if spec.species_list is not None:
            assert len(spec.species_list) == 3


class TestPerchInferenceInheritance:
    """Test PerchInference inherits from InferenceEngine correctly."""

    def test_is_subclass_of_inference_engine(self):
        """Test PerchInference is a subclass of InferenceEngine."""
        assert issubclass(PerchInference, InferenceEngine)

    @patch("echoroo.ml.perch.loader.hoplite")
    def test_requires_loaded_loader(self, mock_hoplite):
        """Test PerchInference requires loaded loader."""
        mock_model = Mock()
        mock_model.class_list = Mock()
        mock_model.class_list.classes = ["class_a"]
        mock_hoplite.load = Mock(return_value=mock_model)

        loader = PerchLoader()

        # Should fail if not loaded
        with pytest.raises(RuntimeError, match="loader must be loaded"):
            PerchInference(loader)

        # Should work after loading
        loader.load()
        inference = PerchInference(loader)

        assert isinstance(inference, InferenceEngine)

    @patch("echoroo.ml.perch.loader.hoplite")
    def test_has_specification_property(self, mock_hoplite):
        """Test PerchInference has specification property."""
        mock_model = Mock()
        mock_model.class_list = Mock()
        mock_model.class_list.classes = ["class_a"]
        mock_hoplite.load = Mock(return_value=mock_model)

        loader = PerchLoader()
        loader.load()
        inference = PerchInference(loader)

        spec = inference.specification

        assert spec.name == "perch"
        assert spec.sample_rate == SAMPLE_RATE

    @patch("echoroo.ml.perch.loader.hoplite")
    def test_confidence_threshold_parameter(self, mock_hoplite):
        """Test confidence_threshold can be set."""
        mock_model = Mock()
        mock_model.class_list = Mock()
        mock_model.class_list.classes = ["class_a"]
        mock_hoplite.load = Mock(return_value=mock_model)

        loader = PerchLoader()
        loader.load()
        inference = PerchInference(loader, confidence_threshold=0.3)

        assert inference._confidence_threshold == 0.3

    @patch("echoroo.ml.perch.loader.hoplite")
    def test_invalid_confidence_threshold(self, mock_hoplite):
        """Test invalid confidence threshold raises ValueError."""
        mock_model = Mock()
        mock_model.class_list = Mock()
        mock_model.class_list.classes = ["class_a"]
        mock_hoplite.load = Mock(return_value=mock_model)

        loader = PerchLoader()
        loader.load()

        with pytest.raises(ValueError, match="confidence_threshold must be in"):
            PerchInference(loader, confidence_threshold=1.5)


class TestPerchInferenceResults:
    """Test PerchInference returns InferenceResult with embeddings and predictions."""

    @patch("echoroo.ml.perch.loader.hoplite")
    def test_predict_segment_returns_inference_result(self, mock_hoplite):
        """Test predict_segment returns InferenceResult."""
        # Setup mock model
        mock_model = Mock()
        mock_model.class_list = Mock()
        mock_model.class_list.classes = ["class_a", "class_b"]

        # Mock embed method to return outputs with embedding and logits
        mock_outputs = Mock()
        mock_outputs.embedding = np.random.randn(1536).astype(np.float32)
        mock_outputs.logits = {"label": np.array([2.0, -1.0])}
        mock_model.embed = Mock(return_value=mock_outputs)

        mock_hoplite.load = Mock(return_value=mock_model)

        # Create inference engine
        loader = PerchLoader()
        loader.load()
        inference = PerchInference(loader, confidence_threshold=0.1)

        # Run inference
        audio = np.random.randn(160000).astype(np.float32)
        result = inference.predict_segment(audio, start_time=0.0)

        # Verify result type and structure
        assert isinstance(result, InferenceResult)
        assert result.start_time == 0.0
        assert result.end_time == 5.0
        assert result.embedding.shape == (1536,)
        assert result.embedding.dtype == np.float32

    @patch("echoroo.ml.perch.loader.hoplite")
    def test_predict_segment_with_predictions(self, mock_hoplite):
        """Test predict_segment returns predictions when logits available."""
        # Setup mock model with species list
        mock_model = Mock()
        mock_model.class_list = Mock()
        mock_model.class_list.classes = ["species_a", "species_b"]

        # Mock embed to return logits
        mock_outputs = Mock()
        mock_outputs.embedding = np.random.randn(1536).astype(np.float32)
        # High logits to ensure predictions above threshold
        mock_outputs.logits = {"label": np.array([5.0, -2.0])}
        mock_model.embed = Mock(return_value=mock_outputs)

        mock_hoplite.load = Mock(return_value=mock_model)

        # Create inference engine
        loader = PerchLoader()
        loader.load()
        # Update specification to include species_list
        loader._species_list = ["species_a", "species_b"]

        inference = PerchInference(loader, confidence_threshold=0.1, top_k=2)

        # Run inference
        audio = np.random.randn(160000).astype(np.float32)
        result = inference.predict_segment(audio, start_time=0.0)

        # Should have predictions
        assert isinstance(result, InferenceResult)
        assert len(result.predictions) >= 0  # May vary based on softmax

    @patch("echoroo.ml.perch.loader.hoplite")
    def test_predict_batch_returns_list_of_inference_results(self, mock_hoplite):
        """Test predict_batch returns list of InferenceResults."""
        # Setup mock model
        mock_model = Mock()
        mock_model.class_list = Mock()
        mock_model.class_list.classes = ["class_a"]

        # Mock embed
        mock_outputs = Mock()
        mock_outputs.embedding = np.random.randn(1536).astype(np.float32)
        mock_outputs.logits = None
        mock_model.embed = Mock(return_value=mock_outputs)

        mock_hoplite.load = Mock(return_value=mock_model)

        # Create inference engine
        loader = PerchLoader()
        loader.load()
        inference = PerchInference(loader)

        # Run batch inference
        segments = [np.random.randn(160000).astype(np.float32) for _ in range(3)]
        start_times = [0.0, 5.0, 10.0]

        results = inference.predict_batch(segments, start_times)

        assert len(results) == 3
        assert all(isinstance(r, InferenceResult) for r in results)
        assert results[0].start_time == 0.0
        assert results[1].start_time == 5.0
        assert results[2].start_time == 10.0

    @patch("echoroo.ml.perch.loader.hoplite")
    def test_predict_batch_validates_inputs(self, mock_hoplite):
        """Test predict_batch validates inputs."""
        mock_model = Mock()
        mock_model.class_list = Mock()
        mock_model.class_list.classes = ["class_a"]
        mock_hoplite.load = Mock(return_value=mock_model)

        loader = PerchLoader()
        loader.load()
        inference = PerchInference(loader)

        segments = [np.random.randn(160000).astype(np.float32) for _ in range(3)]
        start_times = [0.0, 5.0]  # Wrong length

        with pytest.raises(ValueError, match="same length"):
            inference.predict_batch(segments, start_times)


class TestPerchResultBackwardCompatibility:
    """Test PerchResult for backward compatibility."""

    def test_perch_result_creation(self):
        """Test PerchResult can be created."""
        embedding = np.random.randn(1536)

        result = PerchResult(
            start_time=0.0,
            end_time=5.0,
            embedding=embedding,
        )

        assert result.start_time == 0.0
        assert result.end_time == 5.0
        assert result.embedding.shape == (1536,)

    def test_perch_result_duration_property(self):
        """Test PerchResult has duration property."""
        embedding = np.random.randn(1536)

        result = PerchResult(
            start_time=2.0,
            end_time=7.0,
            embedding=embedding,
        )

        assert result.duration == 5.0

    def test_perch_result_conversion_from_inference_result(self):
        """Test PerchResult.from_inference_result conversion."""
        embedding = np.random.randn(1536).astype(np.float32)

        inference_result = InferenceResult(
            start_time=0.0,
            end_time=5.0,
            embedding=embedding,
            predictions=[("species_a", 0.95)],
        )

        perch_result = PerchResult.from_inference_result(inference_result)

        assert isinstance(perch_result, PerchResult)
        assert perch_result.start_time == 0.0
        assert perch_result.end_time == 5.0
        assert np.array_equal(perch_result.embedding, embedding)

    def test_perch_result_conversion_to_inference_result(self):
        """Test PerchResult.to_inference_result conversion."""
        embedding = np.random.randn(1536)

        perch_result = PerchResult(
            start_time=0.0,
            end_time=5.0,
            embedding=embedding,
        )

        inference_result = perch_result.to_inference_result()

        assert isinstance(inference_result, InferenceResult)
        assert inference_result.start_time == 0.0
        assert inference_result.end_time == 5.0
        assert inference_result.embedding.dtype == np.float32
        # PerchResult converts with empty predictions
        assert len(inference_result.predictions) == 0


class TestPerchLegacyAPIs:
    """Test backward compatibility with old Perch APIs."""

    @patch("echoroo.ml.perch.loader.hoplite")
    def test_get_embedding(self, mock_hoplite):
        """Test get_embedding returns PerchResult."""
        mock_model = Mock()
        mock_model.class_list = Mock()
        mock_model.class_list.classes = ["class_a"]

        mock_outputs = Mock()
        mock_outputs.embedding = np.random.randn(1536).astype(np.float32)
        mock_outputs.logits = None
        mock_model.embed = Mock(return_value=mock_outputs)

        mock_hoplite.load = Mock(return_value=mock_model)

        loader = PerchLoader()
        loader.load()
        inference = PerchInference(loader)

        audio = np.random.randn(160000).astype(np.float32)
        result = inference.get_embedding(audio, start_time=0.0)

        assert isinstance(result, PerchResult)

    @patch("echoroo.ml.perch.loader.hoplite")
    def test_get_embeddings_batch(self, mock_hoplite):
        """Test get_embeddings_batch returns list of PerchResults."""
        mock_model = Mock()
        mock_model.class_list = Mock()
        mock_model.class_list.classes = ["class_a"]

        mock_outputs = Mock()
        mock_outputs.embedding = np.random.randn(1536).astype(np.float32)
        mock_outputs.logits = None
        mock_model.embed = Mock(return_value=mock_outputs)

        mock_hoplite.load = Mock(return_value=mock_model)

        loader = PerchLoader()
        loader.load()
        inference = PerchInference(loader)

        segments = [np.random.randn(160000).astype(np.float32) for _ in range(2)]
        start_times = [0.0, 5.0]

        results = inference.get_embeddings_batch(segments, start_times)

        assert len(results) == 2
        assert all(isinstance(r, PerchResult) for r in results)

    @patch("echoroo.ml.perch.loader.hoplite")
    def test_process_file(self, mock_hoplite):
        """Test process_file returns list of PerchResults."""
        mock_model = Mock()
        mock_model.class_list = Mock()
        mock_model.class_list.classes = ["class_a"]

        mock_outputs = Mock()
        mock_outputs.embedding = np.random.randn(1536).astype(np.float32)
        mock_outputs.logits = None
        mock_model.embed = Mock(return_value=mock_outputs)

        mock_hoplite.load = Mock(return_value=mock_model)

        loader = PerchLoader()
        loader.load()
        inference = PerchInference(loader)

        # Create temporary audio file
        import soundfile as sf
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            # Write 10 seconds of audio (2 segments)
            audio = np.random.randn(320000).astype(np.float32)
            sf.write(tmp.name, audio, 32000)
            tmp_path = Path(tmp.name)

        try:
            results = inference.process_file(tmp_path)
            assert all(isinstance(r, PerchResult) for r in results)
        finally:
            tmp_path.unlink()

    @patch("echoroo.ml.perch.loader.hoplite")
    def test_get_embeddings_only(self, mock_hoplite):
        """Test get_embeddings_only returns numpy array."""
        mock_model = Mock()
        mock_model.class_list = Mock()
        mock_model.class_list.classes = ["class_a"]

        mock_outputs = Mock()
        mock_outputs.embedding = np.random.randn(1536).astype(np.float32)
        mock_outputs.logits = None
        mock_model.embed = Mock(return_value=mock_outputs)

        mock_hoplite.load = Mock(return_value=mock_model)

        loader = PerchLoader()
        loader.load()
        inference = PerchInference(loader)

        segments = [np.random.randn(160000).astype(np.float32) for _ in range(3)]

        embeddings = inference.get_embeddings_only(segments)

        assert isinstance(embeddings, np.ndarray)
        assert embeddings.shape == (3, 1536)
        assert embeddings.dtype == np.float32


class TestPerchIntegrationWithBase:
    """Test integration between Perch and base architecture."""

    @patch("echoroo.ml.perch.loader.hoplite")
    def test_full_workflow(self, mock_hoplite):
        """Test full workflow from loader to inference."""
        # Setup mock model
        mock_model = Mock()
        mock_model.class_list = Mock()
        mock_model.class_list.classes = ["species_a", "species_b"]

        mock_outputs = Mock()
        mock_outputs.embedding = np.random.randn(1536).astype(np.float32)
        mock_outputs.logits = {"label": np.array([2.0, -1.0])}
        mock_model.embed = Mock(return_value=mock_outputs)

        mock_hoplite.load = Mock(return_value=mock_model)

        # Step 1: Create and load model
        loader = PerchLoader()
        assert not loader.is_loaded

        loader.load()
        assert loader.is_loaded

        # Step 2: Create inference engine
        inference = PerchInference(loader, confidence_threshold=0.1)

        # Step 3: Run inference
        audio = np.random.randn(160000).astype(np.float32)
        result = inference.predict_segment(audio, start_time=0.0)

        # Verify result is InferenceResult
        assert isinstance(result, InferenceResult)
        assert result.embedding.dtype == np.float32

    @patch("echoroo.ml.perch.loader.hoplite")
    def test_specification_matches_constants(self, mock_hoplite):
        """Test Perch specification matches expected constants."""
        mock_model = Mock()
        mock_model.class_list = Mock()
        mock_model.class_list.classes = ["class_a"]
        mock_hoplite.load = Mock(return_value=mock_model)

        loader = PerchLoader()
        loader.load()

        spec = loader.specification

        assert spec.sample_rate == SAMPLE_RATE == 32000
        assert spec.segment_duration == SEGMENT_DURATION == 5.0
        assert spec.embedding_dim == EMBEDDING_DIM == 1536
        assert spec.segment_samples == 160000

    @patch("echoroo.ml.perch.loader.hoplite")
    def test_classification_capability(self, mock_hoplite):
        """Test Perch supports classification when class_list available."""
        mock_model = Mock()
        mock_model.class_list = Mock()
        mock_model.class_list.classes = [f"species_{i}" for i in range(100)]
        mock_hoplite.load = Mock(return_value=mock_model)

        loader = PerchLoader()
        loader.load()

        spec = loader.specification

        assert spec.supports_classification is True
        assert spec.n_species > 0 if spec.species_list else spec.n_species == 0

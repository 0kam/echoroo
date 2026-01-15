"""Integration tests for BirdNET implementation.

This module tests that BirdNET correctly inherits from and implements
the base ML architecture, including:
- BirdNETLoader inherits from ModelLoader
- BirdNETInference inherits from InferenceEngine
- Backward compatibility with old BirdNETResult API
- Integration with the base architecture
"""

import numpy as np
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from echoroo.ml.base import ModelLoader, InferenceEngine, InferenceResult
from echoroo.ml.birdnet.loader import BirdNETLoader, BirdNETNotLoadedError
from echoroo.ml.birdnet.inference import (
    BirdNETInference,
    BirdNETResult,
    SAMPLE_RATE,
    SEGMENT_DURATION,
    EMBEDDING_DIM,
)


# Skip tests if birdnet package is not available
birdnet = pytest.importorskip("birdnet", reason="birdnet package not installed")


class TestBirdNETLoaderInheritance:
    """Test BirdNETLoader inherits from ModelLoader correctly."""

    def test_is_subclass_of_model_loader(self):
        """Test BirdNETLoader is a subclass of ModelLoader."""
        assert issubclass(BirdNETLoader, ModelLoader)

    def test_has_specification_property(self):
        """Test BirdNETLoader has specification property."""
        loader = BirdNETLoader()

        spec = loader.specification

        assert spec.name == "birdnet"
        assert spec.version == "2.4"
        assert spec.sample_rate == SAMPLE_RATE
        assert spec.segment_duration == SEGMENT_DURATION
        assert spec.embedding_dim == EMBEDDING_DIM
        assert spec.supports_classification is True

    def test_is_loaded_false_initially(self):
        """Test BirdNETLoader is not loaded initially."""
        loader = BirdNETLoader()

        assert loader.is_loaded is False

    @patch("birdnet.load")
    def test_load_method_works(self, mock_birdnet_load):
        """Test BirdNETLoader.load() works."""
        mock_model = Mock()
        mock_model.species_list = ["species_a", "species_b"]
        mock_model.get_sample_rate = Mock(return_value=48000)
        mock_model.get_embeddings_dim = Mock(return_value=1024)
        mock_model.n_species = 2
        mock_birdnet_load.return_value = mock_model

        loader = BirdNETLoader()
        loader.load()

        assert loader.is_loaded is True
        mock_birdnet_load.assert_called_once_with("acoustic", "2.4", "tf")

    @patch("birdnet.load")
    def test_get_model_returns_model(self, mock_birdnet_load):
        """Test BirdNETLoader.get_model() returns the model."""
        mock_model = Mock()
        mock_model.species_list = ["species_a", "species_b"]
        mock_model.get_sample_rate = Mock(return_value=48000)
        mock_model.get_embeddings_dim = Mock(return_value=1024)
        mock_model.n_species = 2
        mock_birdnet_load.return_value = mock_model

        loader = BirdNETLoader()
        loader.load()

        model = loader.get_model()

        assert model is mock_model

    def test_get_model_before_load_raises_legacy_error(self):
        """Test get_model raises BirdNETNotLoadedError for backward compatibility."""
        loader = BirdNETLoader()

        with pytest.raises(BirdNETNotLoadedError):
            loader.get_model()

    @patch("birdnet.load")
    def test_species_list_populated_after_load(self, mock_birdnet_load):
        """Test species_list is populated after loading."""
        mock_model = Mock()
        mock_model.species_list = ["species_a", "species_b", "species_c"]
        mock_model.get_sample_rate = Mock(return_value=48000)
        mock_model.get_embeddings_dim = Mock(return_value=1024)
        mock_model.n_species = 3
        mock_birdnet_load.return_value = mock_model

        loader = BirdNETLoader()

        # Before loading, species_list is None
        assert loader.specification.species_list is None

        loader.load()

        # After loading, species_list is populated
        assert loader.specification.species_list is not None
        assert len(loader.specification.species_list) == 3


class TestBirdNETInferenceInheritance:
    """Test BirdNETInference inherits from InferenceEngine correctly."""

    def test_is_subclass_of_inference_engine(self):
        """Test BirdNETInference is a subclass of InferenceEngine."""
        assert issubclass(BirdNETInference, InferenceEngine)

    @patch("birdnet.load")
    def test_requires_loaded_loader(self, mock_birdnet_load):
        """Test BirdNETInference requires loaded loader."""
        mock_model = Mock()
        mock_model.species_list = ["species_a"]
        mock_model.get_sample_rate = Mock(return_value=48000)
        mock_model.get_embeddings_dim = Mock(return_value=1024)
        mock_model.n_species = 1
        mock_birdnet_load.return_value = mock_model

        loader = BirdNETLoader()

        # Should fail if not loaded
        with pytest.raises(RuntimeError, match="loader must be loaded"):
            BirdNETInference(loader)

        # Should work after loading
        loader.load()
        inference = BirdNETInference(loader)

        assert isinstance(inference, InferenceEngine)

    @patch("birdnet.load")
    def test_has_specification_property(self, mock_birdnet_load):
        """Test BirdNETInference has specification property."""
        mock_model = Mock()
        mock_model.species_list = ["species_a"]
        mock_model.get_sample_rate = Mock(return_value=48000)
        mock_model.get_embeddings_dim = Mock(return_value=1024)
        mock_model.n_species = 1
        mock_birdnet_load.return_value = mock_model

        loader = BirdNETLoader()
        loader.load()
        inference = BirdNETInference(loader)

        spec = inference.specification

        assert spec.name == "birdnet"
        assert spec.sample_rate == SAMPLE_RATE

    @patch("birdnet.load")
    def test_confidence_threshold_property(self, mock_birdnet_load):
        """Test confidence_threshold can be get/set."""
        mock_model = Mock()
        mock_model.species_list = ["species_a"]
        mock_model.get_sample_rate = Mock(return_value=48000)
        mock_model.get_embeddings_dim = Mock(return_value=1024)
        mock_model.n_species = 1
        mock_birdnet_load.return_value = mock_model

        loader = BirdNETLoader()
        loader.load()
        inference = BirdNETInference(loader, confidence_threshold=0.5)

        assert inference.confidence_threshold == 0.5

        inference.confidence_threshold = 0.7
        assert inference.confidence_threshold == 0.7

    @patch("birdnet.load")
    def test_invalid_confidence_threshold(self, mock_birdnet_load):
        """Test invalid confidence threshold raises ValueError."""
        mock_model = Mock()
        mock_model.species_list = ["species_a"]
        mock_model.get_sample_rate = Mock(return_value=48000)
        mock_model.get_embeddings_dim = Mock(return_value=1024)
        mock_model.n_species = 1
        mock_birdnet_load.return_value = mock_model

        loader = BirdNETLoader()
        loader.load()
        inference = BirdNETInference(loader)

        with pytest.raises(ValueError, match="between 0.0 and 1.0"):
            inference.confidence_threshold = 1.5


class TestBirdNETInferenceResults:
    """Test BirdNETInference returns InferenceResult."""

    @patch("birdnet.load")
    def test_predict_segment_returns_inference_result(self, mock_birdnet_load):
        """Test predict_segment returns InferenceResult."""
        # Setup mock model
        mock_model = Mock()
        mock_model.species_list = ["species_a", "species_b"]
        mock_model.get_sample_rate = Mock(return_value=48000)
        mock_model.get_embeddings_dim = Mock(return_value=1024)
        mock_model.n_species = 2

        # Mock encode and predict methods
        mock_embeddings = MagicMock()
        mock_embeddings.embeddings = np.random.randn(1, 1, 1024)
        mock_model.encode = Mock(return_value=mock_embeddings)

        mock_predictions = MagicMock()
        mock_predictions.species_probs = np.array([[[0.9, 0.1]]])
        mock_model.predict = Mock(return_value=mock_predictions)

        mock_birdnet_load.return_value = mock_model

        # Create inference engine
        loader = BirdNETLoader()
        loader.load()
        inference = BirdNETInference(loader, confidence_threshold=0.5)

        # Run inference
        audio = np.random.randn(144000).astype(np.float32)
        result = inference.predict_segment(audio, start_time=0.0)

        # Verify result type
        assert isinstance(result, InferenceResult)
        assert result.start_time == 0.0
        assert result.end_time == 3.0
        assert result.embedding.shape == (1024,)
        assert result.embedding.dtype == np.float32

    @patch("birdnet.load")
    def test_predict_batch_returns_list_of_inference_results(self, mock_birdnet_load):
        """Test predict_batch returns list of InferenceResults."""
        # Setup mock model
        mock_model = Mock()
        mock_model.species_list = ["species_a"]
        mock_model.get_sample_rate = Mock(return_value=48000)
        mock_model.get_embeddings_dim = Mock(return_value=1024)
        mock_model.n_species = 1

        mock_embeddings = MagicMock()
        mock_embeddings.embeddings = np.random.randn(1, 1, 1024)
        mock_model.encode = Mock(return_value=mock_embeddings)

        mock_predictions = MagicMock()
        mock_predictions.species_probs = np.array([[[0.9]]])
        mock_model.predict = Mock(return_value=mock_predictions)

        mock_birdnet_load.return_value = mock_model

        # Create inference engine
        loader = BirdNETLoader()
        loader.load()
        inference = BirdNETInference(loader)

        # Run batch inference
        segments = [np.random.randn(144000).astype(np.float32) for _ in range(3)]
        start_times = [0.0, 3.0, 6.0]

        results = inference.predict_batch(segments, start_times)

        assert len(results) == 3
        assert all(isinstance(r, InferenceResult) for r in results)

    @patch("birdnet.load")
    def test_predict_batch_validates_inputs(self, mock_birdnet_load):
        """Test predict_batch validates inputs."""
        mock_model = Mock()
        mock_model.species_list = ["species_a"]
        mock_model.get_sample_rate = Mock(return_value=48000)
        mock_model.get_embeddings_dim = Mock(return_value=1024)
        mock_model.n_species = 1
        mock_birdnet_load.return_value = mock_model

        loader = BirdNETLoader()
        loader.load()
        inference = BirdNETInference(loader)

        segments = [np.random.randn(144000).astype(np.float32) for _ in range(3)]
        start_times = [0.0, 3.0]  # Wrong length

        with pytest.raises(ValueError, match="same length"):
            inference.predict_batch(segments, start_times)


class TestBirdNETResultBackwardCompatibility:
    """Test BirdNETResult for backward compatibility."""

    def test_birdnet_result_creation(self):
        """Test BirdNETResult can be created."""
        embedding = np.random.randn(1024)
        predictions = [("species_a", 0.95), ("species_b", 0.82)]

        result = BirdNETResult(
            start_time=0.0,
            end_time=3.0,
            embedding=embedding,
            predictions=predictions,
        )

        assert result.start_time == 0.0
        assert result.end_time == 3.0
        assert result.embedding.shape == (1024,)
        assert len(result.predictions) == 2

    def test_birdnet_result_properties(self):
        """Test BirdNETResult has expected properties."""
        embedding = np.random.randn(1024)
        predictions = [("species_a", 0.95)]

        result = BirdNETResult(
            start_time=0.0,
            end_time=3.0,
            embedding=embedding,
            predictions=predictions,
        )

        assert result.top_prediction == ("species_a", 0.95)
        assert result.has_detection is True

    def test_birdnet_result_conversion_from_inference_result(self):
        """Test BirdNETResult.from_inference_result conversion."""
        embedding = np.random.randn(1024).astype(np.float32)
        predictions = [("species_a", 0.95)]

        inference_result = InferenceResult(
            start_time=0.0,
            end_time=3.0,
            embedding=embedding,
            predictions=predictions,
        )

        birdnet_result = BirdNETResult.from_inference_result(inference_result)

        assert isinstance(birdnet_result, BirdNETResult)
        assert birdnet_result.start_time == 0.0
        assert birdnet_result.end_time == 3.0
        assert np.array_equal(birdnet_result.embedding, embedding)
        assert birdnet_result.predictions == predictions

    def test_birdnet_result_conversion_to_inference_result(self):
        """Test BirdNETResult.to_inference_result conversion."""
        embedding = np.random.randn(1024)
        predictions = [("species_a", 0.95)]

        birdnet_result = BirdNETResult(
            start_time=0.0,
            end_time=3.0,
            embedding=embedding,
            predictions=predictions,
        )

        inference_result = birdnet_result.to_inference_result()

        assert isinstance(inference_result, InferenceResult)
        assert inference_result.start_time == 0.0
        assert inference_result.end_time == 3.0
        assert inference_result.embedding.dtype == np.float32


class TestBirdNETLegacyAPIs:
    """Test backward compatibility with old BirdNET APIs."""

    @patch("birdnet.load")
    def test_predict_segment_legacy(self, mock_birdnet_load):
        """Test predict_segment_legacy returns BirdNETResult."""
        # Setup mock model
        mock_model = Mock()
        mock_model.species_list = ["species_a"]
        mock_model.get_sample_rate = Mock(return_value=48000)
        mock_model.get_embeddings_dim = Mock(return_value=1024)
        mock_model.n_species = 1

        mock_embeddings = MagicMock()
        mock_embeddings.embeddings = np.random.randn(1, 1, 1024)
        mock_model.encode = Mock(return_value=mock_embeddings)

        mock_predictions = MagicMock()
        mock_predictions.species_probs = np.array([[[0.9]]])
        mock_model.predict = Mock(return_value=mock_predictions)

        mock_birdnet_load.return_value = mock_model

        # Create inference engine
        loader = BirdNETLoader()
        loader.load()
        inference = BirdNETInference(loader)

        # Use legacy API
        audio = np.random.randn(144000).astype(np.float32)
        result = inference.predict_segment_legacy(audio, start_time=0.0)

        assert isinstance(result, BirdNETResult)

    @patch("birdnet.load")
    def test_predict_batch_legacy(self, mock_birdnet_load):
        """Test predict_batch_legacy returns list of BirdNETResults."""
        mock_model = Mock()
        mock_model.species_list = ["species_a"]
        mock_model.get_sample_rate = Mock(return_value=48000)
        mock_model.get_embeddings_dim = Mock(return_value=1024)
        mock_model.n_species = 1

        mock_embeddings = MagicMock()
        mock_embeddings.embeddings = np.random.randn(1, 1, 1024)
        mock_model.encode = Mock(return_value=mock_embeddings)

        mock_predictions = MagicMock()
        mock_predictions.species_probs = np.array([[[0.9]]])
        mock_model.predict = Mock(return_value=mock_predictions)

        mock_birdnet_load.return_value = mock_model

        loader = BirdNETLoader()
        loader.load()
        inference = BirdNETInference(loader)

        segments = [np.random.randn(144000).astype(np.float32) for _ in range(2)]
        start_times = [0.0, 3.0]

        results = inference.predict_batch_legacy(segments, start_times)

        assert len(results) == 2
        assert all(isinstance(r, BirdNETResult) for r in results)

    @patch("birdnet.load")
    def test_predict_file_legacy(self, mock_birdnet_load):
        """Test predict_file_legacy returns list of BirdNETResults."""
        mock_model = Mock()
        mock_model.species_list = ["species_a"]
        mock_model.get_sample_rate = Mock(return_value=48000)
        mock_model.get_embeddings_dim = Mock(return_value=1024)
        mock_model.n_species = 1

        # Mock encode to return embeddings for 2 segments
        mock_embeddings = MagicMock()
        mock_embeddings.embeddings = np.random.randn(1, 2, 1024)
        mock_model.encode = Mock(return_value=mock_embeddings)

        # Mock predict to return predictions for 2 segments
        mock_predictions = MagicMock()
        mock_predictions.species_probs = np.array([[[0.9], [0.8]]])
        mock_model.predict = Mock(return_value=mock_predictions)

        mock_birdnet_load.return_value = mock_model

        loader = BirdNETLoader()
        loader.load()
        inference = BirdNETInference(loader)

        # Create a temporary audio file
        import soundfile as sf
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            # Write 6 seconds of audio (2 segments)
            audio = np.random.randn(288000).astype(np.float32)
            sf.write(tmp.name, audio, 48000)
            tmp_path = Path(tmp.name)

        try:
            results = inference.predict_file_legacy(tmp_path)
            assert all(isinstance(r, BirdNETResult) for r in results)
        finally:
            tmp_path.unlink()


class TestBirdNETIntegrationWithBase:
    """Test integration between BirdNET and base architecture."""

    @patch("birdnet.load")
    def test_full_workflow(self, mock_birdnet_load):
        """Test full workflow from loader to inference."""
        # Setup mock model
        mock_model = Mock()
        mock_model.species_list = ["species_a", "species_b"]
        mock_model.get_sample_rate = Mock(return_value=48000)
        mock_model.get_embeddings_dim = Mock(return_value=1024)
        mock_model.n_species = 2

        mock_embeddings = MagicMock()
        mock_embeddings.embeddings = np.random.randn(1, 1, 1024)
        mock_model.encode = Mock(return_value=mock_embeddings)

        mock_predictions = MagicMock()
        mock_predictions.species_probs = np.array([[[0.9, 0.1]]])
        mock_model.predict = Mock(return_value=mock_predictions)

        mock_birdnet_load.return_value = mock_model

        # Step 1: Create and load model
        loader = BirdNETLoader()
        assert not loader.is_loaded

        loader.load()
        assert loader.is_loaded

        # Step 2: Create inference engine
        inference = BirdNETInference(loader, confidence_threshold=0.5)

        # Step 3: Run inference
        audio = np.random.randn(144000).astype(np.float32)
        result = inference.predict_segment(audio, start_time=0.0)

        # Verify result is InferenceResult
        assert isinstance(result, InferenceResult)
        assert result.embedding.dtype == np.float32

    @patch("birdnet.load")
    def test_specification_matches_constants(self, mock_birdnet_load):
        """Test BirdNET specification matches expected constants."""
        mock_model = Mock()
        mock_model.species_list = ["species_a"]
        mock_model.get_sample_rate = Mock(return_value=48000)
        mock_model.get_embeddings_dim = Mock(return_value=1024)
        mock_model.n_species = 1
        mock_birdnet_load.return_value = mock_model

        loader = BirdNETLoader()
        loader.load()

        spec = loader.specification

        assert spec.sample_rate == SAMPLE_RATE == 48000
        assert spec.segment_duration == SEGMENT_DURATION == 3.0
        assert spec.embedding_dim == EMBEDDING_DIM == 1024
        assert spec.segment_samples == 144000

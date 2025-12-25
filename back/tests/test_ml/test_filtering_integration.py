"""Integration tests for prediction filtering.

This module tests the filtering architecture including:
- FilterContext dataclass
- SpeciesFilter abstract base class
- PassThroughFilter (no-op implementation)
- BirdNETGeoFilter (using BirdNET geo model)
- filter_predictions helper method
"""

import pytest
from datetime import date
from unittest.mock import Mock, patch

from echoroo.ml.filters import (
    FilterContext,
    PassThroughFilter,
    SpeciesFilter,
    BirdNETGeoFilter,
)


class TestFilterContext:
    """Test FilterContext dataclass."""

    def test_create_full_context(self):
        """Test creating FilterContext with all fields."""
        ctx = FilterContext(
            latitude=35.6762,
            longitude=139.6503,
            week=19,
        )

        assert ctx.latitude == 35.6762
        assert ctx.longitude == 139.6503
        assert ctx.week == 19

    def test_create_minimal_context(self):
        """Test creating FilterContext with minimal fields."""
        ctx = FilterContext()

        assert ctx.latitude is None
        assert ctx.longitude is None
        assert ctx.week is None

    def test_is_valid_property(self):
        """Test is_valid property."""
        ctx_valid = FilterContext(latitude=35.6762, longitude=139.6503, week=19)
        ctx_no_week = FilterContext(latitude=35.6762, longitude=139.6503)
        ctx_no_lat = FilterContext(longitude=139.6503, week=19)
        ctx_empty = FilterContext()

        assert ctx_valid.is_valid is True
        assert ctx_no_week.is_valid is False
        assert ctx_no_lat.is_valid is False
        assert ctx_empty.is_valid is False

    def test_invalid_latitude(self):
        """Test validation of invalid latitude."""
        with pytest.raises(ValueError, match="latitude must be in"):
            FilterContext(latitude=91.0, longitude=0.0)

        with pytest.raises(ValueError, match="latitude must be in"):
            FilterContext(latitude=-91.0, longitude=0.0)

    def test_invalid_longitude(self):
        """Test validation of invalid longitude."""
        with pytest.raises(ValueError, match="longitude must be in"):
            FilterContext(latitude=0.0, longitude=181.0)

        with pytest.raises(ValueError, match="longitude must be in"):
            FilterContext(latitude=0.0, longitude=-181.0)

    def test_invalid_week(self):
        """Test validation of invalid week."""
        with pytest.raises(ValueError, match="week must be in"):
            FilterContext(week=0)

        with pytest.raises(ValueError, match="week must be in"):
            FilterContext(week=49)

    def test_valid_week_range(self):
        """Test valid week values (1-48)."""
        for week in [1, 24, 48]:
            ctx = FilterContext(week=week)
            assert ctx.week == week

    def test_from_recording_with_date(self):
        """Test creating FilterContext from recording metadata with date."""
        # May 15 is approximately week 19-20
        ctx = FilterContext.from_recording(
            latitude=35.6762,
            longitude=139.6503,
            recording_date=date(2024, 5, 15),
        )

        assert ctx.latitude == 35.6762
        assert ctx.longitude == 139.6503
        assert ctx.week is not None
        assert 1 <= ctx.week <= 48

    def test_from_recording_without_date(self):
        """Test creating FilterContext without date."""
        ctx = FilterContext.from_recording(
            latitude=35.6762,
            longitude=139.6503,
            recording_date=None,
        )

        assert ctx.latitude == 35.6762
        assert ctx.longitude == 139.6503
        assert ctx.week is None

    def test_from_recording_all_none(self):
        """Test creating FilterContext with all None values."""
        ctx = FilterContext.from_recording(
            latitude=None,
            longitude=None,
            recording_date=None,
        )

        assert ctx.latitude is None
        assert ctx.longitude is None
        assert ctx.week is None


class TestPassThroughFilter:
    """Test PassThroughFilter implementation."""

    def test_is_subclass_of_species_filter(self):
        """Test PassThroughFilter is a SpeciesFilter."""
        assert issubclass(PassThroughFilter, SpeciesFilter)

    def test_get_species_probabilities_returns_none(self):
        """Test get_species_probabilities returns None."""
        filter = PassThroughFilter()
        context = FilterContext(latitude=35.6762, longitude=139.6503, week=19)

        result = filter.get_species_probabilities(context)

        assert result is None

    def test_filter_predictions_returns_unchanged(self):
        """Test filter_predictions returns predictions unchanged when no probs."""
        filter = PassThroughFilter()
        context = FilterContext(latitude=35.6762, longitude=139.6503, week=19)
        predictions = [
            ("species_a", 0.95),
            ("species_b", 0.82),
            ("species_c", 0.65),
        ]

        result = filter.filter_predictions(predictions, context)

        assert result == predictions

    def test_repr(self):
        """Test string representation."""
        filter = PassThroughFilter()

        repr_str = repr(filter)

        assert "PassThroughFilter" in repr_str


class TestSpeciesFilterBase:
    """Test SpeciesFilter abstract base class."""

    def test_filter_predictions_with_occurrence_data(self):
        """Test filter_predictions filters based on occurrence probabilities."""

        class MockFilter(SpeciesFilter):
            def get_species_probabilities(self, context):
                return {
                    "species_a": 0.8,  # Above default threshold (0.03)
                    "species_b": 0.01,  # Below threshold
                    "species_c": 0.5,  # Above threshold
                }

        filter = MockFilter()
        context = FilterContext(latitude=35.0, longitude=139.0, week=19)
        predictions = [
            ("species_a", 0.95),
            ("species_b", 0.82),
            ("species_c", 0.65),
        ]

        result = filter.filter_predictions(predictions, context)

        # Should include species_a and species_c (above threshold)
        # Should exclude species_b (below threshold)
        assert len(result) == 2
        labels = [label for label, _ in result]
        assert "species_a" in labels
        assert "species_c" in labels
        assert "species_b" not in labels

    def test_filter_predictions_includes_unknown_species(self):
        """Test filter includes species not in occurrence data."""

        class MockFilter(SpeciesFilter):
            def get_species_probabilities(self, context):
                return {
                    "known_a": 0.8,
                    "known_b": 0.01,
                }

        filter = MockFilter()
        context = FilterContext(latitude=35.0, longitude=139.0, week=19)
        predictions = [
            ("known_a", 0.95),  # In data, above threshold
            ("known_b", 0.82),  # In data, below threshold
            ("unknown_c", 0.75),  # Not in data - should be included
        ]

        result = filter.filter_predictions(predictions, context)

        assert len(result) == 2
        labels = [label for label, _ in result]
        assert "known_a" in labels
        assert "unknown_c" in labels
        assert "known_b" not in labels

    def test_filter_predictions_custom_threshold(self):
        """Test filter_predictions with custom threshold."""

        class MockFilter(SpeciesFilter):
            def get_species_probabilities(self, context):
                return {
                    "species_a": 0.1,  # Above 0.05, below 0.15
                }

        filter = MockFilter()
        context = FilterContext(latitude=35.0, longitude=139.0, week=19)
        predictions = [("species_a", 0.95)]

        # With threshold 0.05, species_a should be included
        result = filter.filter_predictions(predictions, context, threshold=0.05)
        assert len(result) == 1

        # With threshold 0.15, species_a should be excluded
        result = filter.filter_predictions(predictions, context, threshold=0.15)
        assert len(result) == 0

    def test_filter_predictions_returns_unchanged_when_no_probs(self):
        """Test filter returns unchanged when get_species_probabilities returns None."""

        class NullFilter(SpeciesFilter):
            def get_species_probabilities(self, context):
                return None

        filter = NullFilter()
        context = FilterContext(latitude=35.0, longitude=139.0, week=19)
        predictions = [("species_a", 0.95), ("species_b", 0.82)]

        result = filter.filter_predictions(predictions, context)

        assert result == predictions


class TestBirdNETGeoFilter:
    """Test BirdNETGeoFilter implementation."""

    def test_is_subclass_of_species_filter(self):
        """Test BirdNETGeoFilter is a SpeciesFilter."""
        assert issubclass(BirdNETGeoFilter, SpeciesFilter)

    def test_initialization_default_values(self):
        """Test BirdNETGeoFilter initializes with default values."""
        filter = BirdNETGeoFilter()

        assert filter._version == "2.4"
        assert filter._backend == "tf"
        assert filter._model is None

    def test_initialization_custom_values(self):
        """Test BirdNETGeoFilter initializes with custom values."""
        filter = BirdNETGeoFilter(version="2.3", backend="np")

        assert filter._version == "2.3"
        assert filter._backend == "np"

    def test_is_loaded_initially_false(self):
        """Test is_loaded is False before model is loaded."""
        filter = BirdNETGeoFilter()

        assert filter.is_loaded is False

    def test_repr(self):
        """Test string representation."""
        filter = BirdNETGeoFilter()

        repr_str = repr(filter)

        assert "BirdNETGeoFilter" in repr_str
        assert "2.4" in repr_str
        assert "not loaded" in repr_str

    def test_get_species_probabilities_invalid_context(self):
        """Test get_species_probabilities returns None for invalid context."""
        filter = BirdNETGeoFilter()

        # Context without all required fields
        context = FilterContext(latitude=35.0)

        result = filter.get_species_probabilities(context)

        assert result is None

    @patch("echoroo.ml.filters.birdnet_geo.birdnet")
    def test_get_species_probabilities_with_mock(self, mock_birdnet):
        """Test get_species_probabilities with mocked birdnet."""
        # Setup mock
        mock_model = Mock()
        mock_result = [
            Mock(species_name="Parus minor_Japanese Tit", confidence=0.85),
            Mock(species_name="Corvus macrorhynchos_Large-billed Crow", confidence=0.3),
        ]
        mock_model.predict.return_value = mock_result
        mock_birdnet.load.return_value = mock_model

        filter = BirdNETGeoFilter()
        context = FilterContext(latitude=35.67, longitude=139.65, week=19)

        result = filter.get_species_probabilities(context)

        assert result is not None
        assert "Parus minor_Japanese Tit" in result
        assert result["Parus minor_Japanese Tit"] == 0.85
        assert result["Corvus macrorhynchos_Large-billed Crow"] == 0.3

        mock_birdnet.load.assert_called_once_with("geo", "2.4", "tf")
        mock_model.predict.assert_called_once_with(35.67, 139.65, week=19)

    @patch("echoroo.ml.filters.birdnet_geo.birdnet")
    def test_model_loads_once(self, mock_birdnet):
        """Test model is only loaded once (lazy loading with caching)."""
        mock_model = Mock()
        mock_model.predict.return_value = []
        mock_birdnet.load.return_value = mock_model

        filter = BirdNETGeoFilter()
        context = FilterContext(latitude=35.67, longitude=139.65, week=19)

        # Call multiple times
        filter.get_species_probabilities(context)
        filter.get_species_probabilities(context)
        filter.get_species_probabilities(context)

        # Model should only be loaded once
        mock_birdnet.load.assert_called_once()


class TestFilteringIntegration:
    """Test filtering works with different model predictions."""

    def test_filter_birdnet_predictions(self):
        """Test filtering BirdNET-style predictions."""
        filter = PassThroughFilter()
        context = FilterContext(latitude=35.6762, longitude=139.6503, week=19)

        # BirdNET format: (scientific_name_common_name, confidence)
        predictions = [
            ("Turdus merula_Common Blackbird", 0.95),
            ("Parus major_Great Tit", 0.82),
        ]

        result = filter.filter_predictions(predictions, context)

        assert len(result) == 2

    def test_filter_perch_predictions(self):
        """Test filtering Perch-style predictions."""
        filter = PassThroughFilter()
        context = FilterContext(latitude=35.6762, longitude=139.6503, week=19)

        # Perch format: (class_label, confidence)
        predictions = [
            ("class_12345", 0.88),
            ("class_67890", 0.76),
        ]

        result = filter.filter_predictions(predictions, context)

        assert len(result) == 2

    def test_empty_predictions(self):
        """Test filtering empty predictions list."""
        filter = PassThroughFilter()
        context = FilterContext(latitude=35.6762, longitude=139.6503, week=19)

        result = filter.filter_predictions([], context)

        assert result == []

    def test_graceful_degradation_no_context(self):
        """Test filter degrades gracefully with minimal context."""

        class StrictFilter(SpeciesFilter):
            def get_species_probabilities(self, context):
                if not context.is_valid:
                    return None
                raise RuntimeError("Should not be called for invalid context")

        filter = StrictFilter()
        context = FilterContext()  # No location
        predictions = [("species_a", 0.95)]

        # Should not raise, should return unchanged
        result = filter.filter_predictions(predictions, context)

        assert result == predictions


class TestFilteringWithModelIntegration:
    """Test filters can be used with model inference results."""

    def test_filter_inference_result_predictions(self):
        """Test filtering predictions from InferenceResult."""
        import numpy as np
        from echoroo.ml.base import InferenceResult

        # Create inference result with predictions
        embedding = np.random.randn(1024).astype(np.float32)
        predictions = [
            ("species_a", 0.95),
            ("species_b", 0.82),
            ("species_c", 0.65),
        ]

        result = InferenceResult(
            start_time=0.0,
            end_time=3.0,
            embedding=embedding,
            predictions=predictions,
        )

        # Filter the predictions
        filter = PassThroughFilter()
        context = FilterContext(latitude=35.6762, longitude=139.6503, week=19)

        filtered_predictions = filter.filter_predictions(
            result.predictions, context
        )

        # Create new InferenceResult with filtered predictions
        filtered_result = InferenceResult(
            start_time=result.start_time,
            end_time=result.end_time,
            embedding=result.embedding,
            predictions=filtered_predictions,
        )

        assert isinstance(filtered_result, InferenceResult)
        assert len(filtered_result.predictions) == 3

    def test_multiple_filters_can_be_applied(self):
        """Test multiple filters can be applied sequentially."""
        predictions = [
            ("species_a", 0.95),
            ("species_b", 0.82),
            ("species_c", 0.65),
        ]

        context = FilterContext(latitude=35.6762, longitude=139.6503, week=19)

        # Apply first filter
        filter1 = PassThroughFilter()
        result1 = filter1.filter_predictions(predictions, context)

        # Apply second filter
        filter2 = PassThroughFilter()
        result2 = filter2.filter_predictions(result1, context)

        assert result2 == predictions

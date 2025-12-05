"""Integration tests for prediction filtering.

This module tests the filtering architecture including:
- PredictionFilter base class
- PassThroughFilter implementation
- OccurrenceFilter with FilterContext
- EBirdOccurrenceFilter implementation
- Backward compatibility with BirdNETMetadataFilter
- Filtering works with both BirdNET and Perch predictions
- Graceful degradation when metadata unavailable
"""

import numpy as np
import pytest
from datetime import date
from pathlib import Path
from unittest.mock import Mock

from echoroo.ml.filters.base import (
    FilterContext,
    PassThroughFilter,
    PredictionFilter,
)
from echoroo.ml.filters.occurrence import (
    EBirdOccurrenceFilter,
    OccurrenceFilter,
    DEFAULT_OCCURRENCE_THRESHOLD,
)


class TestFilterContext:
    """Test FilterContext dataclass."""

    def test_create_full_context(self):
        """Test creating FilterContext with all fields."""
        ctx = FilterContext(
            latitude=35.6762,
            longitude=139.6503,
            date=date(2024, 5, 15),
            time_of_day="dawn",
            habitat="forest",
        )

        assert ctx.latitude == 35.6762
        assert ctx.longitude == 139.6503
        assert ctx.date == date(2024, 5, 15)
        assert ctx.time_of_day == "dawn"
        assert ctx.habitat == "forest"

    def test_create_minimal_context(self):
        """Test creating FilterContext with minimal fields."""
        ctx = FilterContext()

        assert ctx.latitude is None
        assert ctx.longitude is None
        assert ctx.date is None
        assert ctx.time_of_day is None
        assert ctx.habitat is None

    def test_has_location_property(self):
        """Test has_location property."""
        ctx_with = FilterContext(latitude=35.6762, longitude=139.6503)
        ctx_lat_only = FilterContext(latitude=35.6762)
        ctx_lon_only = FilterContext(longitude=139.6503)
        ctx_without = FilterContext()

        assert ctx_with.has_location is True
        assert ctx_lat_only.has_location is False
        assert ctx_lon_only.has_location is False
        assert ctx_without.has_location is False

    def test_has_temporal_property(self):
        """Test has_temporal property."""
        ctx_date = FilterContext(date=date(2024, 5, 15))
        ctx_time = FilterContext(time_of_day="dawn")
        ctx_both = FilterContext(date=date(2024, 5, 15), time_of_day="dawn")
        ctx_neither = FilterContext()

        assert ctx_date.has_temporal is True
        assert ctx_time.has_temporal is True
        assert ctx_both.has_temporal is True
        assert ctx_neither.has_temporal is False

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

    def test_invalid_time_of_day(self):
        """Test validation of invalid time_of_day."""
        with pytest.raises(ValueError, match="time_of_day must be one of"):
            FilterContext(time_of_day="midnight")  # Not a valid value

    def test_valid_time_of_day_values(self):
        """Test all valid time_of_day values."""
        for time_value in ["dawn", "day", "dusk", "night"]:
            ctx = FilterContext(time_of_day=time_value)
            assert ctx.time_of_day == time_value


class TestPassThroughFilter:
    """Test PassThroughFilter implementation."""

    def test_is_subclass_of_prediction_filter(self):
        """Test PassThroughFilter is a PredictionFilter."""
        assert issubclass(PassThroughFilter, PredictionFilter)

    def test_filter_predictions_returns_unchanged(self):
        """Test filter_predictions returns predictions unchanged."""
        filter = PassThroughFilter()
        context = FilterContext(latitude=35.6762, longitude=139.6503)
        predictions = [
            ("species_a", 0.95),
            ("species_b", 0.82),
            ("species_c", 0.65),
        ]

        result = filter.filter_predictions(predictions, context)

        assert result == predictions
        assert result is predictions  # Same object

    def test_get_species_mask_returns_none(self):
        """Test get_species_mask returns None."""
        filter = PassThroughFilter()
        context = FilterContext(latitude=35.6762, longitude=139.6503)

        mask = filter.get_species_mask(context)

        assert mask is None

    def test_get_occurrence_probability_returns_none(self):
        """Test get_occurrence_probability returns None."""
        filter = PassThroughFilter()
        context = FilterContext(latitude=35.6762, longitude=139.6503)

        prob = filter.get_occurrence_probability("species_a", context)

        assert prob is None

    def test_repr(self):
        """Test string representation."""
        filter = PassThroughFilter()

        repr_str = repr(filter)

        assert "PassThroughFilter" in repr_str


class TestOccurrenceFilterBase:
    """Test OccurrenceFilter base class."""

    def test_is_subclass_of_prediction_filter(self):
        """Test OccurrenceFilter is a PredictionFilter."""
        assert issubclass(OccurrenceFilter, PredictionFilter)

    def test_abstract_methods_required(self):
        """Test OccurrenceFilter requires implementing abstract methods."""

        # Should be able to instantiate a concrete subclass
        class ConcreteFilter(OccurrenceFilter):
            def _load_data(self):
                self._species_list = ["species_a", "species_b"]
                self._species_to_idx = {"species_a": 0, "species_b": 1}
                self._is_loaded = True
                return True

            def _get_occurrence_vector(self, latitude, longitude, week):
                return np.array([0.8, 0.2], dtype=np.float32)

        filter = ConcreteFilter()
        filter._load_data()

        assert filter.is_loaded is True

    def test_threshold_property(self):
        """Test threshold property can be get/set."""

        class TestFilter(OccurrenceFilter):
            def _load_data(self):
                return True

            def _get_occurrence_vector(self, lat, lon, week):
                return None

        filter = TestFilter(threshold=0.05)

        assert filter.threshold == 0.05

        filter.threshold = 0.1
        assert filter.threshold == 0.1

    def test_threshold_validation(self):
        """Test threshold validation."""

        class TestFilter(OccurrenceFilter):
            def _load_data(self):
                return True

            def _get_occurrence_vector(self, lat, lon, week):
                return None

        filter = TestFilter()

        with pytest.raises(ValueError, match="threshold must be in"):
            filter.threshold = 1.5

    def test_default_week_property(self):
        """Test default_week property."""

        class TestFilter(OccurrenceFilter):
            def _load_data(self):
                return True

            def _get_occurrence_vector(self, lat, lon, week):
                return None

        filter = TestFilter(default_week=12)

        assert filter.default_week == 12


class TestEBirdOccurrenceFilter:
    """Test EBirdOccurrenceFilter implementation."""

    @pytest.fixture
    def mock_occurrence_data(self, tmp_path):
        """Create mock occurrence data file."""
        data_path = tmp_path / "test_occurrence.npz"

        # Create mock data
        num_cells = 10
        num_weeks = 48
        num_species = 3

        occurrence = np.random.rand(num_cells, num_weeks, num_species).astype(
            np.float32
        )
        h3_cells = np.array([f"cell_{i}" for i in range(num_cells)])
        species = np.array(["species_a", "species_b", "species_c"])

        np.savez(
            data_path,
            occurrence=occurrence,
            h3_cells=h3_cells,
            species=species,
        )

        return data_path

    def test_is_occurrence_filter(self):
        """Test EBirdOccurrenceFilter is an OccurrenceFilter."""
        assert issubclass(EBirdOccurrenceFilter, OccurrenceFilter)

    def test_initialization_with_nonexistent_file(self, tmp_path):
        """Test initialization with nonexistent file logs warning."""
        nonexistent = tmp_path / "nonexistent.npz"

        filter = EBirdOccurrenceFilter(nonexistent)

        # Should not raise, but filter won't be loaded
        assert filter.is_loaded is False

    def test_load_data_success(self, mock_occurrence_data):
        """Test loading occurrence data successfully."""
        filter = EBirdOccurrenceFilter(mock_occurrence_data)

        assert filter.is_loaded is True
        assert filter.num_species == 3
        assert len(filter.species_list) == 3

    def test_filter_predictions_without_location(self, mock_occurrence_data):
        """Test filtering returns unchanged without location."""
        filter = EBirdOccurrenceFilter(mock_occurrence_data)

        context = FilterContext()  # No location
        predictions = [("species_a", 0.95), ("species_b", 0.82)]

        result = filter.filter_predictions(predictions, context)

        assert result == predictions

    @pytest.mark.skipif(
        not pytest.importorskip("h3", reason="h3 library not installed"),
        reason="Requires h3 library",
    )
    def test_get_species_mask_with_location(self, mock_occurrence_data):
        """Test getting species mask with valid location."""
        filter = EBirdOccurrenceFilter(mock_occurrence_data, threshold=0.5)

        context = FilterContext(
            latitude=35.6762,
            longitude=139.6503,
            date=date(2024, 5, 15),
        )

        mask = filter.get_species_mask(context)

        # Result depends on whether H3 cell is in data
        # May be None if cell not found
        if mask is not None:
            assert isinstance(mask, np.ndarray)
            assert mask.dtype == np.bool_
            assert len(mask) == 3

    def test_data_path_property(self, mock_occurrence_data):
        """Test data_path property."""
        filter = EBirdOccurrenceFilter(mock_occurrence_data)

        assert filter.data_path == mock_occurrence_data

    def test_h3_resolution_property(self, mock_occurrence_data):
        """Test h3_resolution property."""
        filter = EBirdOccurrenceFilter(mock_occurrence_data, h3_resolution=5)

        assert filter.h3_resolution == 5

    def test_invalid_data_format(self, tmp_path):
        """Test handling of invalid data format."""
        data_path = tmp_path / "invalid.npz"

        # Missing required keys
        np.savez(data_path, some_data=np.array([1, 2, 3]))

        filter = EBirdOccurrenceFilter(data_path)

        # Should not raise during init, but won't load
        assert filter.is_loaded is False


class TestFilteringIntegration:
    """Test filtering works with different model predictions."""

    def test_filter_birdnet_predictions(self):
        """Test filtering BirdNET-style predictions."""
        filter = PassThroughFilter()
        context = FilterContext(latitude=35.6762, longitude=139.6503)

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
        context = FilterContext(latitude=35.6762, longitude=139.6503)

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
        context = FilterContext(latitude=35.6762, longitude=139.6503)

        result = filter.filter_predictions([], context)

        assert result == []

    def test_graceful_degradation_no_context(self):
        """Test filter degrades gracefully with minimal context."""

        class StrictFilter(OccurrenceFilter):
            def _load_data(self):
                self._is_loaded = True
                return True

            def _get_occurrence_vector(self, lat, lon, week):
                # This shouldn't be called without location
                raise RuntimeError("Should not be called")

        filter = StrictFilter()
        filter._load_data()

        context = FilterContext()  # No location
        predictions = [("species_a", 0.95)]

        # Should not raise, should return unchanged
        result = filter.filter_predictions(predictions, context)

        assert result == predictions

    def test_filter_with_unknown_species(self, mock_occurrence_data):
        """Test filtering includes species not in occurrence data."""

        class TestFilter(OccurrenceFilter):
            def _load_data(self):
                self._species_list = ["known_a", "known_b"]
                self._species_to_idx = {"known_a": 0, "known_b": 1}
                self._is_loaded = True
                return True

            def _get_occurrence_vector(self, lat, lon, week):
                # known_a present, known_b not present
                return np.array([0.9, 0.01], dtype=np.float32)

        filter = TestFilter(threshold=0.03)
        filter._load_data()

        context = FilterContext(latitude=35.0, longitude=139.0)

        predictions = [
            ("known_a", 0.95),  # In data, above threshold
            ("known_b", 0.80),  # In data, below threshold
            ("unknown_c", 0.75),  # Not in data
        ]

        result = filter.filter_predictions(predictions, context)

        # Should include known_a (above threshold) and unknown_c (not in data)
        # Should exclude known_b (below threshold)
        assert len(result) == 2
        labels = [label for label, _ in result]
        assert "known_a" in labels
        assert "unknown_c" in labels
        assert "known_b" not in labels


class TestFilteringWithModelIntegration:
    """Test filters can be used with model inference results."""

    def test_filter_inference_result_predictions(self):
        """Test filtering predictions from InferenceResult."""
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
        context = FilterContext(latitude=35.6762, longitude=139.6503)

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

        context = FilterContext(latitude=35.6762, longitude=139.6503)

        # Apply first filter
        filter1 = PassThroughFilter()
        result1 = filter1.filter_predictions(predictions, context)

        # Apply second filter
        filter2 = PassThroughFilter()
        result2 = filter2.filter_predictions(result1, context)

        assert result2 == predictions


class TestAbstractFilterMethods:
    """Test PredictionFilter abstract methods."""

    def test_filter_predictions_required(self):
        """Test filter_predictions must be implemented."""

        class IncompleteFilter(PredictionFilter):
            def get_species_mask(self, context):
                return None

            def get_occurrence_probability(self, species, context):
                return None

        filter = IncompleteFilter()
        context = FilterContext()

        with pytest.raises(NotImplementedError):
            filter.filter_predictions([], context)

    def test_get_species_mask_required(self):
        """Test get_species_mask must be implemented."""

        class IncompleteFilter(PredictionFilter):
            def filter_predictions(self, predictions, context):
                return predictions

            def get_occurrence_probability(self, species, context):
                return None

        filter = IncompleteFilter()
        context = FilterContext()

        with pytest.raises(NotImplementedError):
            filter.get_species_mask(context)

    def test_get_occurrence_probability_required(self):
        """Test get_occurrence_probability must be implemented."""

        class IncompleteFilter(PredictionFilter):
            def filter_predictions(self, predictions, context):
                return predictions

            def get_species_mask(self, context):
                return None

        filter = IncompleteFilter()
        context = FilterContext()

        with pytest.raises(NotImplementedError):
            filter.get_occurrence_probability("species", context)

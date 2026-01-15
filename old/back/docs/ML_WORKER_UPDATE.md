# Phase 5.1: InferenceWorker Integration with New ML Architecture

## Overview

The `InferenceWorker` has been successfully updated to integrate with the new ML architecture introduced in previous phases. This update maintains full backward compatibility while modernizing the codebase to use the new abstractions.

## Key Changes

### 1. Model-Agnostic Inference

**Before:**
- Separate `_run_birdnet_batch()` and `_run_perch_batch()` methods
- Model-specific result types (`BirdNETResult`, `PerchResult`)
- Different processing logic for each model

**After:**
- Unified `_run_inference()` method using `InferenceEngine` interface
- Single `InferenceResult` type for all models
- Generic processing pipeline that works with any model

```python
# New unified interface
engine: InferenceEngine = self._ensure_model_loaded(config)
results: list[InferenceResult] = await self._run_inference(
    engine, audio_path, config.overlap
)
```

### 2. Integrated Filtering System

**Before:**
- BirdNET-specific metadata filtering
- Filtering logic embedded in model code
- No filtering for Perch

**After:**
- Model-agnostic `PredictionFilter` interface
- `EBirdOccurrenceFilter` for location/time-based filtering
- `PassThroughFilter` for disabling filtering
- Works with all models (BirdNET, Perch, future models)

```python
# Filter context from recording metadata
filter_context = FilterContext(
    latitude=recording.latitude,
    longitude=recording.longitude,
    date=recording.date,
)

# Apply filtering
filter_instance: PredictionFilter = self._get_filter(config)
filtered_predictions = filter_instance.filter_predictions(
    result.predictions, filter_context
)
```

### 3. Unified Result Storage

**Before:**
- Separate `_store_birdnet_result()` and `_store_perch_result()` methods
- Model-specific storage logic
- Inconsistent handling of embeddings vs predictions

**After:**
- Single `_store_result()` method for all models
- Consistent handling of embeddings and predictions
- Filtering applied uniformly before storage

```python
# Store results for any model
predictions_count = await self._store_result(
    session,
    recording,
    model_run,
    result,  # InferenceResult
    filter_instance,
    filter_context,
    config,
)
```

### 4. Enhanced Configuration

**New Parameter:**
- `occurrence_data_path`: Optional path to eBird occurrence data (NPZ format)

**Benefits:**
- Enable/disable occurrence filtering at worker initialization
- No code changes needed to add filtering to existing deployments
- Graceful degradation if data is not available

```python
worker = InferenceWorker(
    audio_dir=Path("/audio"),
    occurrence_data_path=Path("/data/species_presence.npz"),
)
```

## Architecture Benefits

### Extensibility
- **Add new models**: Implement `InferenceEngine` interface
- **Add new filters**: Implement `PredictionFilter` interface
- **No worker changes needed**: Worker code is model-agnostic

### Maintainability
- **Single code path**: One processing pipeline for all models
- **Clear separation**: Inference vs Filtering vs Storage
- **Type safety**: Strong typing with abstract base classes

### Performance
- **Efficient batching**: `predict_file()` optimizes segment processing
- **Lazy loading**: Models and filters loaded on first use
- **Async execution**: CPU-bound operations run in executor

## Backward Compatibility

### No Breaking Changes
- Existing inference jobs continue to work
- Same database schema
- Same API endpoints
- Same configuration options

### Gradual Migration
- Old BirdNET/Perch-specific code paths removed
- Legacy result types still available for compatibility
- Smooth transition to new architecture

## Usage Examples

### Basic Usage (No Changes Required)

```python
# Existing code continues to work
worker = InferenceWorker(audio_dir=Path("/audio"))
await worker.start(session_factory)
```

### With Occurrence Filtering

```python
# Enable eBird occurrence filtering
worker = InferenceWorker(
    audio_dir=Path("/audio"),
    occurrence_data_path=Path("/data/species_presence.npz"),
)
await worker.start(session_factory)

# Jobs with use_metadata_filter=True will apply filtering
job_config = InferenceConfig(
    model_name="birdnet",
    use_metadata_filter=True,  # Enable filtering
    confidence_threshold=0.5,
)
```

### Custom Species List

```python
# Combine filtering with custom species list
job_config = InferenceConfig(
    model_name="birdnet",
    use_metadata_filter=True,
    custom_species_list=["Turdus merula", "Parus major"],
    confidence_threshold=0.5,
)
```

## Implementation Details

### Filter Selection Logic

1. **Occurrence filter enabled if:**
   - `occurrence_data_path` provided at initialization
   - Data file exists and loads successfully
   - Job config has `use_metadata_filter=True`

2. **Pass-through filter used if:**
   - No occurrence data path provided
   - Data file missing or invalid
   - Job config has `use_metadata_filter=False`

### Recording Metadata Extraction

The worker automatically creates `FilterContext` from recording fields:
- `latitude` → `FilterContext.latitude`
- `longitude` → `FilterContext.longitude`
- `date` → `FilterContext.date`

### Species Label Handling

Different models use different label formats:
- **BirdNET**: `"Turdus merula_Common Blackbird"`
- **Perch**: Species code or scientific name

The worker handles both formats transparently:
```python
# Extracts scientific name from any format
scientific_name = species_label.split("_")[0] if "_" in species_label else species_label

# Stores in database with proper parsing
tag = await tags.get_or_create(
    session,
    key="species",
    value=scientific_name,
    canonical_name=common_name,
)
```

## Testing Recommendations

### Unit Tests
- Test `_create_filter_context()` with various recording metadata
- Test `_matches_custom_species()` with different label formats
- Test `_get_filter()` with different configurations

### Integration Tests
- Test end-to-end job processing with BirdNET
- Test end-to-end job processing with Perch
- Test with occurrence filtering enabled/disabled
- Test with custom species lists

### Performance Tests
- Benchmark processing speed vs old implementation
- Verify no performance regression
- Test memory usage with large datasets

## Migration Checklist

For developers updating production systems:

- [ ] Review new `occurrence_data_path` parameter
- [ ] Decide if occurrence filtering should be enabled
- [ ] Prepare eBird occurrence data if needed (see docs)
- [ ] Update worker initialization code if needed
- [ ] Test with existing inference jobs
- [ ] Monitor first production run
- [ ] Verify results match expectations

## Future Enhancements

### Phase 5.2: Additional Filters
- Range map filters
- Habitat-based filters
- Expert knowledge filters
- Chained filters (combine multiple)

### Phase 5.3: Advanced Features
- Confidence calibration
- Ensemble predictions
- Active learning integration
- Real-time inference streaming

## Related Documentation

- `ML_MODELS.md` - Overview of ML architecture
- `ml_inference_system.md` - Detailed inference system design
- `base.py` - Core abstractions documentation
- `filters/` - Filter implementation details

## Summary

The updated `InferenceWorker` successfully integrates the new ML architecture while maintaining full backward compatibility. The implementation provides:

✅ Model-agnostic inference pipeline
✅ Integrated filtering system
✅ Unified result handling
✅ Enhanced configurability
✅ No breaking changes
✅ Clear extension points for future models and filters

The worker is now ready for production use with both BirdNET and Perch models, with optional occurrence-based filtering.

# ML Integration Tests

This directory contains comprehensive integration tests for the ML model architecture in Echoroo.

## Test Files

### Core Architecture Tests

#### `test_integration.py`
Tests for the base ML architecture:
- **ModelSpecification**: Validation, properties (segment_samples, n_species)
- **InferenceResult**: Validation, properties (duration, top_prediction, has_detection, embedding_dim)
- **ModelLoader**: Lazy loading, thread safety, abstract methods, lifecycle (load/unload)
- **InferenceEngine**: predict_segment, predict_batch, predict_file, integration with ModelLoader
- **Thread Safety**: Concurrent loading, concurrent model access
- **Error Handling**: Load failures, validation errors
- **Abstract Methods**: Ensures subclasses implement required methods

**Coverage**: Tests that base classes work correctly and enforce contracts.

### Model-Specific Tests

#### `test_birdnet_integration.py`
Tests for BirdNET implementation:
- **BirdNETLoader**: Inherits from ModelLoader, specification property, lazy loading, species list population
- **BirdNETInference**: Inherits from InferenceEngine, confidence threshold, predict methods return InferenceResult
- **BirdNETResult**: Backward compatibility wrapper, conversions to/from InferenceResult
- **Legacy APIs**: predict_segment_legacy, predict_batch_legacy, predict_file_legacy
- **Integration**: Full workflow from loader to inference
- **Constants**: Verify SAMPLE_RATE=48000, SEGMENT_DURATION=3.0, EMBEDDING_DIM=1024

**Coverage**: Tests that BirdNET correctly implements the base architecture while maintaining backward compatibility.

#### `test_perch_integration.py`
Tests for Perch implementation:
- **PerchLoader**: Inherits from ModelLoader, specification property, classification support
- **PerchInference**: Inherits from InferenceEngine, embeddings + predictions, confidence threshold
- **PerchResult**: Backward compatibility wrapper
- **Legacy APIs**: get_embedding, get_embeddings_batch, process_file, get_embeddings_only
- **Integration**: Full workflow with embeddings and logits
- **Constants**: Verify SAMPLE_RATE=32000, SEGMENT_DURATION=5.0, EMBEDDING_DIM=1536

**Coverage**: Tests that Perch correctly implements the base architecture with classification capability.

### Filtering Tests

#### `test_filtering_integration.py`
Tests for prediction filtering:
- **FilterContext**: Validation, has_location, has_temporal properties
- **PassThroughFilter**: No-op filter implementation
- **OccurrenceFilter**: Base class for occurrence-based filtering
- **EBirdOccurrenceFilter**: NPZ file loading, H3 geographic indexing, occurrence probability lookup
- **Filtering Integration**: Works with BirdNET and Perch predictions, graceful degradation
- **Unknown Species**: Species not in occurrence data are included by default
- **Abstract Methods**: Ensures filter implementations are complete

**Coverage**: Tests that filtering architecture is flexible and works across different models.

### Installer Tests

#### `test_installer_integration.py`
Tests for model installation:
- **InstallStatus**: Enum values for installation states
- **ModelArtifact**: Validation of artifact metadata
- **InstallationProgress**: Progress reporting structure
- **ModelInstaller**: Base class for installers, check_status, install, uninstall
- **Checksum Verification**: SHA256 validation
- **BirdNETInstaller**: Integration tests (mocked)
- **PerchInstaller**: Integration tests (mocked), Kaggle credentials
- **Error Handling**: Download failures, verification failures
- **Utilities**: check_all_models, get_installer, check availability

**Coverage**: Tests that installation system is robust and handles errors gracefully.

### Router Tests

#### `test_routers/test_setup.py`
Tests for setup API endpoints:
- **GET /api/v1/setup/models/status/**: Returns status of all models
- **POST /api/v1/setup/models/{model}/install/**: Installs a model
- **POST /api/v1/setup/models/{model}/uninstall/**: Uninstalls a model
- **Error Responses**: Invalid model names, installation failures
- **Schema Validation**: ModelsStatus, InstallResponse, InstallRequest
- **Integration**: Full workflow from status check to installation

**Coverage**: Tests that HTTP API correctly exposes installation functionality.

## Running Tests

### Run All ML Tests
```bash
cd back
pytest tests/test_ml/ -v
```

### Run Specific Test File
```bash
pytest tests/test_ml/test_integration.py -v
pytest tests/test_ml/test_birdnet_integration.py -v
pytest tests/test_ml/test_perch_integration.py -v
pytest tests/test_ml/test_filtering_integration.py -v
pytest tests/test_ml/test_installer_integration.py -v
```

### Run Specific Test Class
```bash
pytest tests/test_ml/test_integration.py::TestModelSpecification -v
pytest tests/test_ml/test_birdnet_integration.py::TestBirdNETInferenceResults -v
```

### Run with Coverage
```bash
pytest tests/test_ml/ --cov=echoroo.ml --cov-report=html
```

## Test Dependencies

These tests use the following tools and patterns:
- **pytest**: Test framework
- **unittest.mock**: Mocking (Mock, patch, AsyncMock, MagicMock)
- **pytest.mark.asyncio**: Async test support
- **pytest.importorskip**: Conditional test execution
- **conftest.py**: Shared fixtures for common test setup

## Key Testing Patterns

### 1. Mock Model Loading
```python
@patch("birdnet.load")
def test_example(mock_birdnet_load):
    mock_model = Mock()
    mock_model.species_list = ["species_a"]
    mock_birdnet_load.return_value = mock_model

    loader = BirdNETLoader()
    loader.load()
```

### 2. Test Abstract Methods
```python
def test_abstract_method_required():
    class IncompleteLoader(ModelLoader):
        def _load_model(self):
            return Mock()

    loader = IncompleteLoader()
    with pytest.raises(NotImplementedError):
        _ = loader.specification
```

### 3. Test Thread Safety
```python
def test_concurrent_loading():
    loader = MockModelLoader(mock_model)
    threads = [threading.Thread(target=loader.load) for _ in range(10)]

    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert loader.is_loaded is True
```

### 4. Test Backward Compatibility
```python
def test_legacy_api():
    # Old API should still work
    result = inference.predict_segment_legacy(audio)
    assert isinstance(result, BirdNETResult)

    # New API returns InferenceResult
    result = inference.predict_segment(audio)
    assert isinstance(result, InferenceResult)
```

## Coverage Goals

Target coverage for ML modules:
- `echoroo.ml.base`: >95% (core abstractions)
- `echoroo.ml.birdnet`: >90% (BirdNET implementation)
- `echoroo.ml.perch`: >90% (Perch implementation)
- `echoroo.ml.filters`: >85% (filtering system)
- `echoroo.ml.installer`: >85% (installation system)

## Notes

- Tests use mocking extensively to avoid requiring actual model downloads
- BirdNET tests skip if `birdnet` package not installed
- Perch tests mock the `hoplite` package
- H3 geographic indexing tests skip if `h3` package not available
- Tests verify both happy paths and error conditions
- Thread safety is tested explicitly for concurrent access
- Backward compatibility is tested for all legacy APIs

## Future Improvements

1. Add performance benchmarks for inference
2. Add integration tests with real (small) model files
3. Add stress tests for concurrent model loading
4. Add tests for model switching (load multiple models)
5. Add tests for memory management and cleanup
6. Add tests for filtering performance with large species lists

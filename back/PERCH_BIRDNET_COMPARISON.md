# Perch vs BirdNET Implementation Comparison

## Overview
Both Perch and BirdNET now follow the same architectural pattern, inheriting from the base classes `ModelLoader` and `InferenceEngine`.

## Side-by-Side Comparison

### Model Specifications

| Aspect | BirdNET | Perch |
|--------|---------|-------|
| **Sample Rate** | 48,000 Hz | 32,000 Hz |
| **Segment Duration** | 3.0 seconds | 5.0 seconds |
| **Segment Samples** | 144,000 | 160,000 |
| **Embedding Dimension** | 1024 | 1536 |
| **Supports Classification** | True | False (Phase 1) |
| **Species List** | ~6,000 species | None (Phase 1) |
| **Backend** | birdnet package | perch-hoplite |

### Loader Implementation

#### BirdNETLoader
```python
class BirdNETLoader(ModelLoader):
    @property
    def specification(self) -> ModelSpecification:
        return ModelSpecification(
            name="birdnet",
            version="2.4",
            sample_rate=48000,
            segment_duration=3.0,
            embedding_dim=1024,
            supports_classification=True,
            species_list=self._species_list,
        )

    def _load_model(self) -> Any:
        import birdnet
        model = birdnet.load("acoustic", "2.4", "tf")
        self._species_list = list(model.species_list)
        return model
```

#### PerchLoader
```python
class PerchLoader(ModelLoader):
    @property
    def specification(self) -> ModelSpecification:
        return ModelSpecification(
            name="perch",
            version="2.0",
            sample_rate=32000,
            segment_duration=5.0,
            embedding_dim=1536,
            supports_classification=False,
            species_list=None,
        )

    def _load_model(self) -> Any:
        from perch_hoplite.zoo import model_configs
        model = model_configs.load_model_by_name(self._model_name)
        return model
```

**Similarity**: Both inherit from `ModelLoader`, implement `specification` property and `_load_model()` method.

### Inference Implementation

#### BirdNETInference
```python
class BirdNETInference(InferenceEngine):
    def __init__(self, loader, confidence_threshold=0.5, top_k=10):
        super().__init__(loader)
        self._confidence_threshold = confidence_threshold
        self._top_k = top_k

    def predict_segment(self, audio, start_time) -> InferenceResult:
        # Returns InferenceResult with embeddings AND predictions
        ...

    def predict_batch(self, segments, start_times) -> list[InferenceResult]:
        # Batch processing
        ...
```

#### PerchInference
```python
class PerchInference(InferenceEngine):
    def __init__(self, loader, batch_size=32):
        super().__init__(loader)
        self._batch_size = batch_size

    def predict_segment(self, audio, start_time) -> InferenceResult:
        # Returns InferenceResult with embeddings only (predictions=[])
        ...

    def predict_batch(self, segments, start_times) -> list[InferenceResult]:
        # Batch processing
        ...
```

**Similarity**: Both inherit from `InferenceEngine`, implement `predict_segment()` and `predict_batch()` methods returning `InferenceResult`.

## Method Signatures Comparison

### Common Methods (Inherited from Base Classes)

Both models support:

```python
# From ModelLoader
loader.load()                    # Load model into memory
loader.unload()                  # Free model from memory
loader.get_model()               # Get loaded model instance
loader.is_loaded                 # Check if loaded (property)
loader.specification             # Get model metadata (property)

# From InferenceEngine
engine.predict_segment(audio, start_time)          # Single segment
engine.predict_batch(segments, start_times)        # Batch of segments
engine.predict_file(path, overlap)                 # Entire audio file
engine.specification                               # Model metadata (property)
```

### Legacy Methods (Backward Compatibility)

#### BirdNET
```python
# Legacy methods return BirdNETResult
inference.predict_segment_legacy(audio, start_time) -> BirdNETResult
inference.predict_batch_legacy(segments, times) -> list[BirdNETResult]
inference.predict_file_legacy(path, overlap) -> list[BirdNETResult]

# Additional methods
inference.get_embeddings_only(segments) -> np.ndarray
inference.get_embeddings_from_file(path) -> np.ndarray
```

#### Perch
```python
# Legacy methods return PerchResult
inference.get_embedding(audio, start_time) -> PerchResult
inference.get_embeddings_batch(segments, times) -> list[PerchResult]
inference.process_file(path, overlap) -> list[PerchResult]

# Additional methods
inference.get_embeddings_only(segments) -> np.ndarray
```

## Result Objects Comparison

### BirdNETResult
```python
@dataclass
class BirdNETResult:
    start_time: float
    end_time: float
    embedding: np.ndarray  # (1024,)
    predictions: list[tuple[str, float]] = field(default_factory=list)

    # Conversion methods
    @classmethod
    def from_inference_result(cls, result: InferenceResult) -> BirdNETResult
    def to_inference_result(self) -> InferenceResult
```

### PerchResult
```python
@dataclass
class PerchResult:
    start_time: float
    end_time: float
    embedding: np.ndarray  # (1536,)

    # Conversion methods
    @classmethod
    def from_inference_result(cls, result: InferenceResult) -> PerchResult
    def to_inference_result(self) -> InferenceResult
```

**Difference**: Perch doesn't include `predictions` field (embedding-only model in Phase 1).

## Usage Examples

### Loading Models

Both models follow the same pattern:

```python
# BirdNET
from whombat.ml.birdnet import BirdNETLoader, BirdNETInference

birdnet_loader = BirdNETLoader()
birdnet_loader.load()
birdnet_inference = BirdNETInference(birdnet_loader)

# Perch
from whombat.ml.perch import PerchLoader, PerchInference

perch_loader = PerchLoader()
perch_loader.load()
perch_inference = PerchInference(perch_loader)
```

### Running Inference

Both models use identical API:

```python
# Process file with overlap
birdnet_results = birdnet_inference.predict_file(path, overlap=1.5)
perch_results = perch_inference.predict_file(path, overlap=2.0)

# All results are InferenceResult objects
for result in birdnet_results:
    print(f"{result.start_time}s: {result.embedding.shape}, {len(result.predictions)} predictions")

for result in perch_results:
    print(f"{result.start_time}s: {result.embedding.shape}, {len(result.predictions)} predictions")
```

### Getting Model Information

```python
# BirdNET
spec = birdnet_loader.specification
print(f"{spec.name} v{spec.version}")
print(f"Sample rate: {spec.sample_rate}Hz")
print(f"Embedding dim: {spec.embedding_dim}")
print(f"Supports classification: {spec.supports_classification}")
print(f"Number of species: {spec.n_species}")

# Perch
spec = perch_loader.specification
print(f"{spec.name} v{spec.version}")
print(f"Sample rate: {spec.sample_rate}Hz")
print(f"Embedding dim: {spec.embedding_dim}")
print(f"Supports classification: {spec.supports_classification}")
print(f"Number of species: {spec.n_species}")
```

## Key Differences

1. **Classification Support**:
   - BirdNET: Supports species classification out of the box
   - Perch: Embedding-only in Phase 1, classification planned for Phase 2

2. **Audio Specifications**:
   - BirdNET: 3-second segments at 48kHz
   - Perch: 5-second segments at 32kHz

3. **Embedding Dimensions**:
   - BirdNET: 1024-dimensional embeddings
   - Perch: 1536-dimensional embeddings

4. **Backend**:
   - BirdNET: Official `birdnet` Python package
   - Perch: `perch-hoplite` package (requires Kaggle credentials)

## Benefits of Unified Architecture

1. **Consistent API**: Both models can be used interchangeably
2. **Type Safety**: Same return types (`InferenceResult`) across models
3. **Easy Comparison**: Benchmark different models using same code
4. **Extensibility**: Easy to add new models following same pattern
5. **Maintainability**: Changes to base classes benefit all models
6. **Documentation**: Shared patterns make documentation clearer

## Next Steps

When adding classification to Perch (Phase 2):
1. Update `supports_classification=True` in specification
2. Load species list from perch-hoplite
3. Set `species_list` in specification
4. Populate `predictions` field in `predict_segment()`
5. Add `confidence_threshold` parameter like BirdNET

The architecture is already in place to support this with minimal changes!

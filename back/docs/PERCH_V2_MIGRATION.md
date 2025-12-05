# Perch V2 Migration Guide

## Overview

This guide explains the migration from `perch-hoplite` to `birdnet` library for Perch V2 model support.

## Background

### Problem with perch-hoplite

The original Perch loader used `perch-hoplite`, which has a critical dependency conflict:
- `perch-hoplite` requires **NumPy >= 2.0**
- `soundevent` (a core Whombat dependency) requires **NumPy < 2.0**

This made it impossible to install Perch support in the same environment as Whombat.

### Solution: birdnet Library

The `birdnet` library (v0.2.0+) provides an alternative approach:
- Uses ProtoBuf format models instead of TensorFlow SavedModel
- Compatible with NumPy < 2.0
- No dependency conflicts with soundevent
- Provides `load_perch_v2()` API (future/experimental)

## New Implementation

### Phase 6.1: New Loaders

Created two new modules:

1. **`loader_birdnet.py`** - Perch V2 loader using birdnet library
   - Class: `PerchLoaderBirdNet`
   - Device support: GPU or CPU
   - API: `birdnet.load_perch_v2(device)`
   - Species list: `model.species_list`

2. **`inference_birdnet.py`** - Inference engine for birdnet-based Perch
   - Class: `PerchInferenceBirdNet`
   - API: `model.encode()` for embeddings
   - API: `model.predict()` for classification
   - No logits conversion needed

### Key Differences from perch-hoplite

| Aspect | perch-hoplite | birdnet |
|--------|---------------|---------|
| Model format | TensorFlow SavedModel | ProtoBuf |
| NumPy version | >= 2.0 | < 2.0 (compatible) |
| Loading API | `model_configs.load_model_by_name()` | `load_perch_v2(device)` |
| Embedding API | `model.embed()` | `model.encode()` |
| Classification | Extract logits, apply softmax | `model.predict()` direct |
| Species list | `model.class_list["labels"].classes` | `model.species_list` |

## Usage

### Recommended: PerchLoaderBirdNet

```python
from whombat.ml.perch import PerchLoaderBirdNet, PerchInferenceBirdNet

# Load model
loader = PerchLoaderBirdNet(device="GPU")
loader.load()

# Create inference engine
inference = PerchInferenceBirdNet(
    loader,
    confidence_threshold=0.3,
    top_k=10,
)

# Run inference
results = inference.predict_file(Path("recording.wav"))

for result in results:
    print(f"{result.start_time}s:")
    print(f"  Embedding: {result.embedding.shape}")
    if result.has_detection:
        species, confidence = result.top_prediction
        print(f"  Top: {species} ({confidence:.2f})")
```

### Legacy: PerchLoader (Deprecated)

```python
from whombat.ml.perch import PerchLoader, PerchInference

# WARNING: This requires NumPy >= 2.0 (conflicts with soundevent)
loader = PerchLoader()  # Emits DeprecationWarning
loader.load()

inference = PerchInference(loader)
results = inference.predict_file(Path("recording.wav"))
```

## Model Registry

The model registry now includes both loaders:

- **`"perch"`** - Uses `PerchLoaderBirdNet` (recommended)
- **`"perch-hoplite"`** - Uses legacy `PerchLoader` (deprecated)

```python
from whombat.ml.registry import ModelRegistry

# Get recommended loader
perch_config = ModelRegistry.get("perch")
loader = perch_config.loader_class()
loader.load()
```

## Installation

### With birdnet (Recommended)

```bash
pip install "whombat[ml]"
```

This installs:
- `birdnet >= 0.2.0`
- All other ML dependencies (soundfile, etc.)

### With perch-hoplite (Deprecated)

```bash
# Requires separate environment due to NumPy conflict
pip install git+https://github.com/google-research/perch-hoplite.git
```

## Migration Checklist

If you're migrating from `PerchLoader` to `PerchLoaderBirdNet`:

- [ ] Update imports: `from whombat.ml.perch import PerchLoaderBirdNet, PerchInferenceBirdNet`
- [ ] Change loader instantiation: `PerchLoader()` → `PerchLoaderBirdNet()`
- [ ] Change inference engine: `PerchInference(loader)` → `PerchInferenceBirdNet(loader)`
- [ ] Verify device parameter: `device="GPU"` or `device="CPU"`
- [ ] Test inference results (embeddings and predictions)
- [ ] Remove perch-hoplite from dependencies

## API Compatibility

Both implementations provide the same `InferenceResult` format:

```python
@dataclass
class InferenceResult:
    start_time: float
    end_time: float
    embedding: NDArray[np.float32]  # Shape: (1536,)
    predictions: list[tuple[str, float]]  # [(species, confidence), ...]
    metadata: dict[str, Any]
```

This ensures seamless integration with existing Whombat code.

## Troubleshooting

### birdnet.load_perch_v2 not available

If you see this error:
```
AttributeError: birdnet.load_perch_v2() is not available in this version
```

This means your birdnet version doesn't support Perch V2 yet. Options:
1. Wait for birdnet to add Perch V2 support
2. Use legacy `PerchLoader` with perch-hoplite (requires separate environment)
3. Contact birdnet maintainers about Perch V2 support timeline

### NumPy version conflicts

If you need both soundevent and perch-hoplite:
1. Create separate virtual environments
2. Use `PerchLoaderBirdNet` instead (once available)
3. Use Docker containers for isolation

## Future Work

- Monitor birdnet releases for official Perch V2 support
- Add batch processing optimizations for birdnet API
- Implement caching for downloaded models
- Add GPU memory management for large batches

## References

- [birdnet library](https://github.com/kahst/BirdNET-Analyzer)
- [perch-hoplite](https://github.com/google-research/perch-hoplite)
- [Perch paper](https://arxiv.org/abs/2210.12852)
- [Whombat ML integration](../src/whombat/ml/README.md)

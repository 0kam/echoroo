# Perch to BirdNET Migration Guide

This guide explains the transition from perch-hoplite to BirdNET in Whombat v0.8.6+.

## Background

Starting with Whombat v0.8.6, support for the perch-hoplite package has been removed in favor of using BirdNET as the sole ML backend. This change simplifies the codebase, resolves dependency conflicts, and provides a unified API for audio analysis.

## Why the Change?

### Dependency Conflicts

The primary reason for removing perch-hoplite is a NumPy version conflict:
- **perch-hoplite** requires `numpy>=2.0`
- **soundevent** (core Whombat dependency) requires `numpy<2.0`

This incompatibility meant Perch users needed a separate virtual environment, adding complexity to the deployment and development process.

### Unified API

BirdNET provides both:
- **Embeddings**: 1024-dimensional audio feature vectors for similarity search
- **Classification**: 6,522 bird species identification

This dual functionality eliminates the need for multiple ML backends.

### GPU Support

Unlike perch-hoplite which had limited GPU support in the pip package, BirdNET offers:
- Native CUDA acceleration via `birdnet[and-cuda]`
- Optimized TensorFlow backend
- Efficient batch processing

### Simplified Maintenance

Maintaining a single ML model:
- Reduces testing complexity
- Simplifies dependency management
- Easier for contributors to understand
- Faster CI/CD pipelines

## Migration Steps

### 1. Update Dependencies

**Remove perch-hoplite** (if installed separately):
```bash
pip uninstall perch-hoplite
```

**Install BirdNET**:
```bash
pip install birdnet

# Or with GPU support
pip install birdnet[and-cuda]

# Or via Whombat extras
pip install whombat[ml]
```

### 2. Update Code

#### Loader Initialization

**Before (Perch)**:
```python
from whombat.ml.perch import PerchLoader

loader = PerchLoader()
loader.load()
model = loader.get_model()
```

**After (BirdNET)**:
```python
from whombat.ml.birdnet import BirdNETLoader

loader = BirdNETLoader()
loader.load()
model = loader.get_model()
```

#### Inference Engine

**Before (Perch)**:
```python
from whombat.ml.perch import PerchInference

inference = PerchInference(loader, confidence_threshold=0.5)
results = inference.predict_file("/path/to/audio.wav")
```

**After (BirdNET)**:
```python
from whombat.ml.birdnet import BirdNETInference

inference = BirdNETInference(loader, confidence_threshold=0.5, top_k=10)
results = inference.predict_file("/path/to/audio.wav")
```

#### Model Registry

**Before**:
```python
from whombat.ml.registry import ModelRegistry

# Both models registered
ModelRegistry.available_models()  # ['birdnet', 'perch']
```

**After**:
```python
from whombat.ml.registry import ModelRegistry

# Only BirdNET available
ModelRegistry.available_models()  # ['birdnet']
```

### 3. Update API Endpoints

If you're using the setup/installation API:

**Before**: Endpoints supported both `birdnet` and `perch`
```
POST /api/v1/setup/models/perch/install/
GET /api/v1/setup/models/status/
```

**After**: Only `birdnet` is supported
```
POST /api/v1/setup/models/birdnet/install/
GET /api/v1/setup/models/status/
```

The `/models/status/` endpoint now returns:
```json
{
  "birdnet": {
    "name": "birdnet",
    "status": "installed",
    "package_available": true,
    "requires_credentials": false
  },
  "perch": null,
  "created_at": "2025-12-05T10:30:00"
}
```

### 4. Regenerate Embeddings

**Important**: BirdNET and Perch embeddings are not compatible.

#### Embedding Dimensions
- **Perch**: 1536 dimensions
- **BirdNET**: 1024 dimensions

#### Database Migration

If you have existing embeddings in your database:

1. **Keep old embeddings** (optional, for archival):
   ```sql
   -- Rename existing embedding tables
   ALTER TABLE clip_embeddings RENAME TO clip_embeddings_perch_archive;
   ALTER TABLE sound_event_embeddings RENAME TO sound_event_embeddings_perch_archive;
   ```

2. **Regenerate with BirdNET**:
   ```python
   from whombat.ml.birdnet import BirdNETLoader, BirdNETInference
   from whombat.api.embeddings import regenerate_all_embeddings

   # Load BirdNET model
   loader = BirdNETLoader()
   loader.load()

   # Regenerate embeddings for all audio
   await regenerate_all_embeddings(session, loader)
   ```

3. **Update vector search indexes**:
   ```sql
   -- Drop old HNSW indexes
   DROP INDEX IF EXISTS idx_clip_embeddings_hnsw;
   DROP INDEX IF EXISTS idx_sound_event_embeddings_hnsw;

   -- Recreate for 1024 dimensions
   CREATE INDEX idx_clip_embeddings_hnsw
   ON clip_embeddings
   USING hnsw (embedding vector_cosine_ops)
   WITH (m = 16, ef_construction = 64);
   ```

### 5. Remove Kaggle Credentials

Perch required Kaggle API credentials for model downloads. BirdNET downloads models directly from its repository, so Kaggle credentials are no longer needed.

**Remove** (if set):
```bash
unset KAGGLE_USERNAME
unset KAGGLE_KEY
```

**Delete** (if exists):
```bash
rm ~/.kaggle/kaggle.json
```

## Feature Comparison

| Feature | Perch (perch-hoplite) | BirdNET |
|---------|----------------------|---------|
| Embedding Dimensions | 1536 | 1024 |
| Species Classification | ~15,000 (multi-taxa) | 6,522 (birds only) |
| NumPy Compatibility | >=2.0 (conflicts) | <2.0 (compatible) |
| GPU Support | Limited | Full CUDA support |
| Installation | Kaggle credentials | Direct download |
| Package Size | ~100MB | ~100MB |
| Audio Input | 5s @ 32kHz | 3s @ 48kHz |
| License | Apache 2.0 | CC BY-NC-SA 4.0 |

## Backward Compatibility

### Breaking Changes

1. **Removed modules**:
   - `whombat.ml.perch`
   - `whombat.ml.installer.perch`

2. **Removed functions**:
   - `whombat.ml.installer.check_perch_available()`
   - `whombat.ml.installer.check_kaggle_credentials()`

3. **API changes**:
   - Setup API no longer accepts `perch` as a model name
   - Model status endpoint returns `perch: null`

### Gradual Migration

For applications that need both embeddings temporarily:

1. **Export Perch embeddings** before upgrading:
   ```python
   import numpy as np
   from whombat.api.embeddings import export_embeddings

   # Export to file
   perch_embeddings = await export_embeddings(session, model="perch")
   np.save("perch_embeddings_backup.npy", perch_embeddings)
   ```

2. **Upgrade Whombat** and regenerate with BirdNET

3. **Compare** if needed for transition analysis

## Troubleshooting

### Import Errors

**Error**: `ModuleNotFoundError: No module named 'whombat.ml.perch'`

**Solution**: Update imports to use BirdNET:
```python
# Old
from whombat.ml.perch import PerchLoader

# New
from whombat.ml.birdnet import BirdNETLoader
```

### Embedding Dimension Mismatch

**Error**: `dimension mismatch: expected 1536, got 1024`

**Solution**: Regenerate embeddings with BirdNET (see Database Migration above)

### API 400 Error

**Error**: `Unknown model: perch. Available models: birdnet`

**Solution**: Update API calls to use `birdnet` instead of `perch`

## Benefits of BirdNET

### For Users

- **No credential setup**: No Kaggle account or API keys needed
- **Better GPU support**: Faster inference on CUDA devices
- **Unified workflow**: One model for embeddings and classification
- **Simpler installation**: Single `pip install birdnet` command

### For Developers

- **No NumPy conflicts**: Compatible with entire Whombat stack
- **Easier testing**: Single ML backend to test
- **Cleaner code**: Removed perch-hoplite adapter code
- **Faster CI/CD**: Fewer dependencies to install and test

## Timeline

- **v0.8.5 and earlier**: Both BirdNET and Perch supported
- **v0.8.6**: Perch removed, BirdNET only
- **v0.9.0+**: BirdNET as the stable ML backend

## Support

For issues or questions about migration:

1. Check the [BirdNET documentation](https://github.com/birdnet-team/birdnet/)
2. Review [ML_MODELS.md](./ML_MODELS.md) for setup details
3. Open an issue on [GitHub](https://github.com/okamoto-group/echoroo/issues)

## Appendix: Code Examples

### Complete Migration Example

```python
import asyncio
from whombat.ml.birdnet import BirdNETLoader, BirdNETInference
from whombat.system.database import get_session

async def migrate_to_birdnet():
    """Complete migration from Perch to BirdNET."""

    # 1. Initialize BirdNET
    print("Loading BirdNET model...")
    loader = BirdNETLoader()
    loader.load()
    print(f"Model loaded: {loader.specification}")

    # 2. Create inference engine
    inference = BirdNETInference(
        loader=loader,
        confidence_threshold=0.1,
        top_k=10
    )

    # 3. Process audio files
    audio_files = [
        "/path/to/audio1.wav",
        "/path/to/audio2.wav",
    ]

    for audio_file in audio_files:
        print(f"\nProcessing {audio_file}...")
        results = inference.predict_file(audio_file)

        for result in results:
            print(f"  {result.start_time:.1f}s - {result.end_time:.1f}s")
            print(f"  Embedding: {result.embedding.shape}")
            if result.has_detection:
                print(f"  Top species: {result.top_prediction}")

    # 4. Regenerate database embeddings (if needed)
    async with get_session() as session:
        from whombat.api.embeddings import regenerate_all_embeddings
        print("\nRegenerating embeddings...")
        await regenerate_all_embeddings(session, loader)
        await session.commit()

    print("\nMigration complete!")

# Run migration
asyncio.run(migrate_to_birdnet())
```

This guide should help you smoothly transition from Perch to BirdNET. The changes are primarily drop-in replacements with minimal code modifications required.

# ML Inference System Design Document

Echoroo ML Inference System - BirdNET / Perch 2.0 Integration

## 1. Background and Technical Research

### 1.1 Target Models

#### BirdNET V2.4
| Parameter | Value |
|-----------|-------|
| Segment Length | 3 seconds |
| Sample Rate | 48 kHz |
| Embedding Dimension | 1024 |
| Input Format | 2-channel mel spectrogram (96x511 pixels) |
| Species Coverage | 6,512 species |
| Framework | TensorFlow Lite |
| License | Model: CC BY-NC-SA 4.0, Code: MIT |

**Metadata Model Features:**
- Location-based species filtering (latitude/longitude)
- Seasonal filtering (week of year)
- Reduces false positives by limiting predictions to species likely present at the recording location/time

#### Google Perch 2.0
| Parameter | Value |
|-----------|-------|
| Segment Length | 5 seconds |
| Sample Rate | 32 kHz |
| Embedding Dimension | 1536 (Perch 2.0)|
| Input Format | 160,000 samples (5s x 32kHz) |
| Species Coverage | ~15,000 classes (~10,000 birds) |
| Framework | JAX -> TensorFlow/TFLite export |
| License | Apache 2.0 |

**Architecture:**
- EfficientNet-B3 backbone (~12M parameters)
- PCEN melspectrogram frontend
- 500 frames x 128 mel bands (20ms window, 10ms hop)
- Spatial embedding available: (5, 3, 1536)

### 1.2 Technology Stack

```
Current Stack:
- Database: SQLite (aiosqlite)
- ORM: SQLAlchemy 2.x (async)
- Migrations: Alembic
- Audio Processing: soundfile, torchaudio

Target Stack:
- Database: PostgreSQL + pgvector
- ML Runtime: TensorFlow/TFLite (BirdNET), JAX/TensorFlow (Perch)
- GPU: CUDA support via TensorFlow/PyTorch
- Vector Search: pgvector (HNSW/IVFFlat indexes)
```

### 1.3 pgvector Capabilities

| Feature | Description |
|---------|-------------|
| Max Dimensions | 16,000 (sufficient for both models) |
| Index Types | IVFFlat, HNSW |
| Distance Metrics | L2, Inner Product, Cosine |
| Performance | ~1ms for 1M vectors with HNSW |

---

## 2. Current System Analysis

### 2.1 Existing Data Models

```
Recording
    ├── Clip (recording_id, start_time, end_time)
    │   ├── ClipAnnotation (human annotations)
    │   │   └── SoundEventAnnotation[]
    │   │   └── ClipAnnotationTag[]
    │   └── ClipPrediction (ML predictions)
    │       └── SoundEventPrediction[]
    │       └── ClipPredictionTag[] (with score)
    │
    └── SoundEvent (geometry-based, directly linked to Recording)

ModelRun
    ├── name, version, description
    └── ModelRunPrediction[] -> ClipPrediction[]
```

**Key Observations:**
1. `Clip` already supports arbitrary time segments
2. `ClipPrediction` + `ClipPredictionTag` can store classification results with confidence scores
3. `ModelRun` tracks model metadata (name, version)
4. Missing: Embedding vector storage

### 2.2 Database Configuration

PostgreSQL support already exists in `back/src/whombat/system/database.py`:
- `postgresql+asyncpg` for async operations
- `postgresql+psycopg2` for sync operations
- Environment-based configuration via `WHOMBAT_DB_*` settings

### 2.3 Audio Processing

`back/src/whombat/api/audio.py` provides:
- `load_audio()`: Load audio with resampling, filtering
- Uses `torchaudio.functional.resample()` for sample rate conversion
- Returns `xarray.DataArray` with metadata

---

## 3. Proposed System Architecture

### 3.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Echoroo Frontend                        │
├─────────────────────────────────────────────────────────────────┤
│                         REST API Layer                          │
│  /api/v1/inference/   /api/v1/embeddings/   /api/v1/search/    │
├─────────────────────────────────────────────────────────────────┤
│                       Service Layer                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │ Inference   │  │ Embedding   │  │ Vector Search           │ │
│  │ Service     │  │ Service     │  │ Service                 │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
├─────────────────────────────────────────────────────────────────┤
│                       ML Runtime Layer                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │ BirdNET     │  │ Perch 2.0   │  │ Metadata Model          │ │
│  │ (TFLite)    │  │ (TF/JAX)    │  │ (Species Filter)        │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
├─────────────────────────────────────────────────────────────────┤
│                       Data Layer                                │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │              PostgreSQL + pgvector                          ││
│  │  ┌─────────┐  ┌─────────────┐  ┌─────────────────────────┐ ││
│  │  │ Clips   │  │ Predictions │  │ Embeddings (vector)     │ ││
│  │  └─────────┘  └─────────────┘  └─────────────────────────┘ ││
│  └─────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 Inference Pipeline Flow

```
Recording
    │
    ▼
┌─────────────────────────────────────────┐
│ 1. Segmentation                         │
│    - BirdNET: 3s segments, 48kHz        │
│    - Perch: 5s segments, 32kHz          │
│    - Overlap configurable (default: 0)  │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│ 2. Metadata Filtering (BirdNET only)    │
│    - Get site location (lat/lon)        │
│    - Calculate week of year             │
│    - Filter species list                │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│ 3. Batch Inference (GPU)                │
│    - Load model to GPU                  │
│    - Process segments in batches        │
│    - Extract embeddings + predictions   │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│ 4. Post-processing                      │
│    - Apply confidence threshold         │
│    - Deduplicate overlapping detections │
│    - Format results                     │
└─────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────┐
│ 5. Storage                              │
│    - Create/reuse Clip records          │
│    - Store ClipPrediction + Tags        │
│    - Store Embedding vectors            │
└─────────────────────────────────────────┘
```

---

## 4. Database Schema Design

### 4.1 New Tables

```sql
-- Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Embedding storage for clips
CREATE TABLE clip_embedding (
    id SERIAL PRIMARY KEY,
    clip_id INTEGER NOT NULL REFERENCES clip(id) ON DELETE CASCADE,
    model_run_id INTEGER NOT NULL REFERENCES model_run(id) ON DELETE CASCADE,
    embedding vector(1536),  -- Max dimension for Perch 2.0
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(clip_id, model_run_id)
);

-- Embedding storage for sound events
CREATE TABLE sound_event_embedding (
    id SERIAL PRIMARY KEY,
    sound_event_id INTEGER NOT NULL REFERENCES sound_event(id) ON DELETE CASCADE,
    model_run_id INTEGER NOT NULL REFERENCES model_run(id) ON DELETE CASCADE,
    embedding vector(1536),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(sound_event_id, model_run_id)
);

-- Vector similarity indexes
CREATE INDEX clip_embedding_hnsw_idx ON clip_embedding
    USING hnsw (embedding vector_cosine_ops);

CREATE INDEX sound_event_embedding_hnsw_idx ON sound_event_embedding
    USING hnsw (embedding vector_cosine_ops);

-- Inference job tracking
CREATE TABLE inference_job (
    id SERIAL PRIMARY KEY,
    uuid UUID NOT NULL UNIQUE DEFAULT gen_random_uuid(),
    model_run_id INTEGER REFERENCES model_run(id),
    dataset_id INTEGER REFERENCES dataset(id),
    recording_id INTEGER REFERENCES recording(id),
    status VARCHAR(20) NOT NULL DEFAULT 'pending',  -- pending, running, completed, failed
    progress FLOAT DEFAULT 0,
    total_clips INTEGER DEFAULT 0,
    processed_clips INTEGER DEFAULT 0,
    error_message TEXT,
    config JSONB,  -- Model-specific configuration
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    created_by_id INTEGER REFERENCES "user"(id)
);

-- Model configuration and metadata
ALTER TABLE model_run ADD COLUMN IF NOT EXISTS config JSONB;
ALTER TABLE model_run ADD COLUMN IF NOT EXISTS embedding_dimension INTEGER;
ALTER TABLE model_run ADD COLUMN IF NOT EXISTS segment_duration FLOAT;
ALTER TABLE model_run ADD COLUMN IF NOT EXISTS sample_rate INTEGER;
```

### 4.2 SQLAlchemy Models

```python
# back/src/whombat/models/embedding.py

from pgvector.sqlalchemy import Vector
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from whombat.models.base import Base

class ClipEmbedding(Base):
    """Embedding vector for a clip."""

    __tablename__ = "clip_embedding"
    __table_args__ = (
        UniqueConstraint("clip_id", "model_run_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    clip_id: Mapped[int] = mapped_column(ForeignKey("clip.id", ondelete="CASCADE"))
    model_run_id: Mapped[int] = mapped_column(ForeignKey("model_run.id", ondelete="CASCADE"))
    embedding: Mapped[list[float]] = mapped_column(Vector(1536))

    # Relationships
    clip: Mapped["Clip"] = relationship(init=False, repr=False)
    model_run: Mapped["ModelRun"] = relationship(init=False, repr=False)


class SoundEventEmbedding(Base):
    """Embedding vector for a sound event."""

    __tablename__ = "sound_event_embedding"
    __table_args__ = (
        UniqueConstraint("sound_event_id", "model_run_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, init=False)
    sound_event_id: Mapped[int] = mapped_column(ForeignKey("sound_event.id", ondelete="CASCADE"))
    model_run_id: Mapped[int] = mapped_column(ForeignKey("model_run.id", ondelete="CASCADE"))
    embedding: Mapped[list[float]] = mapped_column(Vector(1536))

    # Relationships
    sound_event: Mapped["SoundEvent"] = relationship(init=False, repr=False)
    model_run: Mapped["ModelRun"] = relationship(init=False, repr=False)
```

---

## 5. API Design

### 5.1 Inference Endpoints

```
POST /api/v1/inference/jobs/
    Create a new inference job for a dataset or recording

GET /api/v1/inference/jobs/
    List inference jobs with filtering

GET /api/v1/inference/jobs/{job_uuid}/
    Get job status and progress

DELETE /api/v1/inference/jobs/{job_uuid}/
    Cancel a running job

POST /api/v1/inference/jobs/{job_uuid}/start/
    Start a pending job (async)
```

### 5.2 Embedding Search Endpoints

```
POST /api/v1/embeddings/search/
    Find similar clips/sound events by embedding vector

GET /api/v1/embeddings/clips/{clip_uuid}/
    Get embedding for a specific clip

POST /api/v1/embeddings/clips/{clip_uuid}/similar/
    Find clips similar to a given clip
```

### 5.3 Request/Response Schemas

```python
# Inference Job Creation
class InferenceJobCreate(BaseModel):
    model_name: Literal["birdnet", "perch"]
    model_version: str = "latest"
    dataset_uuid: UUID | None = None
    recording_uuid: UUID | None = None
    config: InferenceConfig

class InferenceConfig(BaseModel):
    # Common
    confidence_threshold: float = 0.5
    overlap: float = 0.0  # Segment overlap ratio
    batch_size: int = 32
    use_gpu: bool = True

    # BirdNET specific
    use_metadata_filter: bool = True
    custom_species_list: list[str] | None = None

    # Output options
    store_embeddings: bool = True
    store_predictions: bool = True

# Embedding Search
class EmbeddingSearchRequest(BaseModel):
    embedding: list[float] | None = None
    clip_uuid: UUID | None = None
    model_name: str
    limit: int = 20
    min_similarity: float = 0.7

class EmbeddingSearchResult(BaseModel):
    clip: ClipSchema
    similarity: float
    model_run: ModelRunSchema
```

---

## 6. Implementation Roadmap

### Phase 1: PostgreSQL Migration (2-3 days)

**Objective:** Migrate from SQLite to PostgreSQL

**Tasks:**
1. Update docker-compose.yml with PostgreSQL service
2. Create migration scripts for existing data
3. Update settings to use PostgreSQL by default
4. Add pgvector extension installation
5. Test all existing functionality

**Files to modify:**
- `docker-compose.yml`
- `back/src/whombat/system/settings.py`
- `back/src/whombat/system/database.py`
- Add migration guide documentation

### Phase 2: Core Inference Infrastructure (3-4 days)

**Objective:** Build the inference job system

**Tasks:**
1. Create new models: `InferenceJob`, `ClipEmbedding`, `SoundEventEmbedding`
2. Create Alembic migrations
3. Implement inference job API (`back/src/whombat/api/inference.py`)
4. Implement inference routes (`back/src/whombat/routes/inference.py`)
5. Add background task processing (using asyncio or Celery)

**New files:**
- `back/src/whombat/models/embedding.py`
- `back/src/whombat/models/inference_job.py`
- `back/src/whombat/api/inference.py`
- `back/src/whombat/routes/inference.py`
- `back/src/whombat/schemas/inference.py`

### Phase 3: BirdNET Integration (4-5 days)

**Objective:** Implement BirdNET inference

**Tasks:**
1. Install birdnetlib or implement direct TFLite integration
2. Create BirdNET model wrapper
3. Implement audio preprocessing (48kHz, 3s segments)
4. Implement metadata model integration
   - Get site coordinates from Recording/Dataset
   - Calculate week of year from Recording.datetime
5. Implement batch inference with GPU support
6. Store predictions as ClipPrediction + ClipPredictionTag
7. Extract and store embeddings

**New files:**
- `back/src/whombat/ml/__init__.py`
- `back/src/whombat/ml/birdnet.py`
- `back/src/whombat/ml/base.py` (abstract model interface)

**Dependencies:**
```
birdnetlib>=0.15
tensorflow>=2.15
```

### Phase 4: Perch 2.0 Integration (3-4 days)

**Objective:** Implement Perch 2.0 inference

**Tasks:**
1. Download Perch model from Kaggle/TensorFlow Hub
2. Create Perch model wrapper
3. Implement audio preprocessing (32kHz, 5s segments)
4. Implement batch inference
5. Store predictions and embeddings

**New files:**
- `back/src/whombat/ml/perch.py`

**Dependencies:**
```
# Perch uses TensorFlow SavedModel format
tensorflow>=2.15
tensorflow-hub
```

### Phase 5: Vector Search (2-3 days)

**Objective:** Implement embedding-based similarity search

**Tasks:**
1. Create embedding search API
2. Implement pgvector queries with HNSW index
3. Add search endpoints to routes
4. Implement "find similar" functionality in frontend

**New files:**
- `back/src/whombat/api/embeddings.py`
- `back/src/whombat/routes/embeddings.py`

### Phase 6: Frontend Integration (3-4 days)

**Objective:** Build UI for inference and search

**Tasks:**
1. Inference job management UI
   - Start inference on dataset/recording
   - Monitor progress
   - View results
2. Embedding search UI
   - Search by clicking on a clip
   - Display similar clips
3. Integration with existing annotation workflow

---

## 7. Risk Assessment and Considerations

### 7.1 Technical Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| PostgreSQL migration breaks existing data | High | Thorough testing, backup strategy, rollback plan |
| GPU memory limitations | Medium | Implement batch size limits, memory monitoring |
| Model loading time | Medium | Keep models loaded in memory, lazy loading |
| Vector index performance at scale | Medium | Benchmark with realistic data volumes |

### 7.2 Operational Considerations

1. **Model Licensing:**
   - BirdNET model: CC BY-NC-SA 4.0 (non-commercial)
   - Perch: Apache 2.0 (commercial OK)
   - Document licensing requirements for users

2. **Resource Requirements:**
   - GPU: NVIDIA with CUDA support recommended
   - RAM: 8GB+ for model loading
   - Storage: Embeddings add ~6KB per clip (1536 dims x 4 bytes)

3. **Concurrency:**
   - Limit concurrent inference jobs per user
   - Implement job queue for large datasets

### 7.3 Data Considerations

1. **Embedding Versioning:**
   - Different model versions produce incompatible embeddings
   - Store model_run_id with each embedding
   - Consider re-computing embeddings when upgrading models

2. **Clip Deduplication:**
   - Same (recording, start_time, end_time) should share Clip record
   - Current UniqueConstraint handles this correctly

---

## 8. References

- [BirdNET-Analyzer GitHub](https://github.com/kahst/BirdNET-Analyzer)
- [BirdNET Models Documentation](https://birdnet-team.github.io/BirdNET-Analyzer/models.html)
- [Google Perch GitHub](https://github.com/google-research/perch)
- [Perch Kaggle Models](https://www.kaggle.com/models/google/bird-vocalization-classifier)
- [pgvector GitHub](https://github.com/pgvector/pgvector)
- [pgvector-python](https://github.com/pgvector/pgvector-python)
- [OpenSoundscape BirdNET/Perch Tutorial](https://opensoundscape.org/en/latest/tutorials/training_birdnet_and_perch.html)
- [BirdNET Embeddings Research](https://www.frontiersin.org/journals/ecology-and-evolution/articles/10.3389/fevo.2024.1409407/full)

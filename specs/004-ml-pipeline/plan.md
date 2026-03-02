# Implementation Plan: ML Pipeline

**Branch**: `004-ml-pipeline` | **Date**: 2026-03-02 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/004-ml-pipeline/spec.md`

## Summary

This plan covers the implementation of the ML pipeline for Echoroo v2. The pipeline automatically runs BirdNET species detection and Perch embedding generation when a dataset is imported, stores results as Annotation records and pgvector embeddings, and provides administrative tracking via DetectionRun. Similarity search (P2) enables users to find sounds similar to a reference using Perch embeddings. All ML processing runs asynchronously via Celery workers.

## Technical Context

**Language/Version**: Python 3.11 (Backend), TypeScript 5.x (Frontend)
**Primary Dependencies**: FastAPI, SQLAlchemy 2.0, Pydantic, Celery, Redis, BirdNET-Analyzer, TensorFlow/TFHub (Perch), pgvector, SvelteKit, Svelte 5, TanStack Query, Tailwind CSS
**Storage**: PostgreSQL 16+ with pgvector extension (HNSW index)
**Testing**: pytest (contract/integration/unit), vitest (frontend)
**Target Platform**: Linux server (Docker), modern web browsers
**Project Type**: Web application (frontend + backend + worker)
**Performance Goals**:
- BirdNET: 100 files (5 min each) in < 30 min
- Perch: 100 files (5 min each) in < 30 min
- Similarity search: 10,000 embeddings in < 3 sec
- UI responsiveness during ML processing < 1 sec
**Constraints**:
- ML models run on CPU (GPU optional for speed)
- Celery workers are separate processes
- All ML processing is non-blocking to the user
- VISION.md mandates clips are ephemeral (in-memory only)
**Scale/Scope**:
- Datasets with 1,000-10,000 recordings
- ~100 Annotations per recording (BirdNET)
- ~60 embeddings per 5-min recording (5-second windows)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### I. Clean Architecture ✅ PASS
- **API Layer**: FastAPI routers in `apps/api/echoroo/api/v1/` for detection-runs, similarity-search
- **Service Layer**: Business logic in `apps/api/echoroo/services/` (BirdNETService, PerchService, DetectionRunService, SimilaritySearchService)
- **Repository Layer**: Data access in `apps/api/echoroo/repositories/` (DetectionRunRepository, AnnotationRepository, EmbeddingRepository)
- **ML Layer**: Model wrappers in `apps/api/echoroo/ml/` (BirdNETWrapper, PerchWrapper)
- **Worker Layer**: Celery tasks in `apps/api/echoroo/workers/` (birdnet_task, perch_task)
- Dependency injection via FastAPI's `Depends()`

### II. Test-Driven Development ✅ WILL COMPLY
- Contract tests for all API endpoints (DetectionRun CRUD, similarity search)
- Integration tests for ML pipeline workflow (import → detect → embed)
- Unit tests for ML wrappers (mock model, verify processing logic)
- Unit tests for embedding vector operations

### III. Type Safety ✅ WILL COMPLY
- Pydantic schemas for all request/response validation
- SQLAlchemy 2.0 typed models for DetectionRun, Annotation, Embedding
- mypy strict mode validation
- pgvector column type as vector(1024)

### IV. ML Pipeline Architecture ✅ PASS (Core Feature)
- BirdNET inference via Celery background task
- Perch embedding generation via Celery background task
- DetectionRun tracking for all ML operations
- Chunked processing for large datasets
- Configurable confidence thresholds via SystemSetting

### V. API Versioning ✅ WILL COMPLY
- All endpoints under `/api/v1/`
- Admin endpoints under `/api/v1/admin/detection-runs`

### Security Requirements ✅ WILL COMPLY
- JWT token validation for all endpoints
- Admin-only access for DetectionRun management
- Rate limiting on similarity search endpoint

## Project Structure

### Documentation (this feature)

```text
specs/004-ml-pipeline/
├── spec.md              # Specification
├── plan.md              # This file
└── tasks.md             # Task breakdown
```

### Source Code (repository root)

```text
apps/api/
├── echoroo/
│   ├── api/v1/
│   │   ├── detection_runs.py       # Admin: DetectionRun CRUD (NEW)
│   │   └── similarity_search.py    # User: similarity search (NEW, P2)
│   ├── models/
│   │   ├── detection_run.py        # DetectionRun model (NEW)
│   │   ├── annotation_v2.py        # New Annotation model per VISION.md (NEW)
│   │   ├── embedding.py            # Embedding model with pgvector (NEW)
│   │   └── enums.py                # Add DetectionRunStatus, DetectionRunType, AnnotationSourceV2, AnnotationStatusV2 enums
│   ├── schemas/
│   │   ├── detection_run.py        # DetectionRun schemas (NEW)
│   │   ├── annotation_v2.py        # New Annotation schemas (NEW)
│   │   ├── embedding.py            # Embedding schemas (NEW)
│   │   └── similarity_search.py    # Similarity search schemas (NEW, P2)
│   ├── services/
│   │   ├── detection_run.py        # DetectionRun management (NEW)
│   │   ├── birdnet.py              # BirdNET inference wrapper (NEW)
│   │   ├── perch.py                # Perch embedding wrapper (NEW)
│   │   ├── similarity_search.py    # Vector search logic (NEW, P2)
│   │   └── ml_pipeline.py          # Orchestrator: trigger BirdNET+Perch after import (NEW)
│   ├── repositories/
│   │   ├── detection_run.py        # DetectionRun data access (NEW)
│   │   ├── annotation_v2.py        # New Annotation data access (NEW)
│   │   └── embedding.py            # Embedding data access with pgvector queries (NEW)
│   ├── ml/
│   │   ├── __init__.py             # ML module init (NEW)
│   │   ├── birdnet_wrapper.py      # BirdNET model loading & inference (NEW)
│   │   ├── perch_wrapper.py        # Perch model loading & inference (NEW)
│   │   ├── audio_processor.py      # Audio loading, resampling, chunking (NEW)
│   │   └── model_manager.py        # Model download & version management (NEW)
│   └── workers/
│       ├── celery_app.py           # Celery app configuration (NEW)
│       ├── birdnet_task.py         # BirdNET Celery task (NEW)
│       ├── perch_task.py           # Perch embedding Celery task (NEW)
│       └── pipeline_task.py        # Orchestrator task: triggers BirdNET + Perch (NEW)
├── alembic/
│   └── versions/                   # New migrations for DetectionRun, AnnotationV2, Embedding
└── tests/
    ├── contract/
    │   ├── test_detection_runs.py  # DetectionRun API tests (NEW)
    │   └── test_similarity_search.py # Similarity search tests (NEW, P2)
    ├── integration/
    │   └── test_ml_pipeline.py     # Full pipeline integration test (NEW)
    └── unit/
        ├── test_birdnet_wrapper.py # BirdNET wrapper tests (NEW)
        ├── test_perch_wrapper.py   # Perch wrapper tests (NEW)
        └── test_audio_processor.py # Audio processing tests (NEW)

apps/web/
├── src/
│   ├── lib/
│   │   ├── api/
│   │   │   ├── detection-runs.ts       # Admin: DetectionRun API client (NEW)
│   │   │   └── similarity-search.ts    # Similarity search API client (NEW, P2)
│   │   └── types/
│   │       └── ml.ts                   # ML-related TypeScript types (NEW)
│   └── routes/
│       └── (app)/
│           ├── admin/                  # Existing admin section
│           │   └── detection-runs/
│           │       └── +page.svelte    # DetectionRun management page (NEW)
│           └── projects/
│               └── [id]/
│                   └── search/
│                       └── +page.svelte  # Similarity search page (NEW, P2)
```

**Structure Decision**: New `ml/` module created under `apps/api/echoroo/` for ML-specific code (model wrappers, audio processing), keeping it separate from business logic in `services/`. The existing `workers/` directory is expanded with proper Celery app configuration. New data models follow VISION.md naming rather than Whombat-derived naming.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| New Annotation model alongside 003 models | VISION.md mandates new Annotation structure (time segments on recordings, not clips). Coexistence needed until 003 models are deprecated | Modifying 003 models would break existing annotation workflow that is in active use |
| TensorFlow + PyTorch in same project | BirdNET requires TensorFlow; Perch uses TFHub. Both are necessary per VISION.md | No single framework supports both models. Separate worker containers would add operational complexity for minimal benefit |

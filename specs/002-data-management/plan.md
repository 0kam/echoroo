# Implementation Plan: Data Management

**Branch**: `002-data-management` | **Date**: 2026-01-16 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/002-data-management/spec.md`

## Summary

This feature implements the core data management functionality for Echoroo v2, including Sites (geographic locations using Uber H3), Datasets (collections of audio recordings), Recordings (individual audio files with metadata), and Clips (time segments for analysis). The implementation follows Clean Architecture with API/Service/Repository layers and integrates with existing 001-administration entities (License, Recorder, Project).

## Technical Context

**Language/Version**: Python 3.11 (Backend), TypeScript 5.x (Frontend)
**Primary Dependencies**: FastAPI, SQLAlchemy 2.0, Pydantic, SvelteKit, Svelte 5, TanStack Query, Tailwind CSS, h3-py, soundfile, numpy
**Storage**: PostgreSQL 16+ with pgvector extension
**Testing**: pytest (contract/integration/unit), vitest (frontend)
**Target Platform**: Linux server (Docker), modern web browsers
**Project Type**: web (frontend + backend)
**Performance Goals**:
- 1000 recordings import < 10 minutes
- Recording list load < 2 seconds for 10,000 items
- Spectrogram generation < 3 seconds for 10-minute recordings
- Audio playback start < 500ms
- 50 concurrent users without performance degradation

**Constraints**:
- Audio files stored on server filesystem (not in database)
- Maximum supported recording duration: unlimited (stream processing)
- Supported formats: WAV, FLAC, MP3, OGG
- H3 resolution range: 5-15

**Scale/Scope**:
- Thousands of recordings per dataset
- Dozens of datasets per project
- Hundreds of clips per recording

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### I. Clean Architecture ✅ PASS
- **API Layer**: FastAPI endpoints in `apps/api/echoroo/api/v1/` for sites, datasets, recordings, clips
- **Service Layer**: Business logic in `apps/api/echoroo/services/` (SiteService, DatasetService, RecordingService, ClipService)
- **Repository Layer**: Data access in `apps/api/echoroo/repositories/` (SiteRepository, DatasetRepository, RecordingRepository, ClipRepository)
- **Domain Models**: Pure SQLAlchemy models in `apps/api/echoroo/models/`
- Dependencies injected via FastAPI Depends()

### II. Test-Driven Development ✅ WILL COMPLY
- Contract tests for all API endpoints (test_sites.py, test_datasets.py, test_recordings.py, test_clips.py)
- Integration tests for service layer workflows
- Unit tests for complex business logic (datetime pattern extraction, audio processing)

### III. Type Safety ✅ WILL COMPLY
- Pydantic schemas for all request/response validation
- SQLAlchemy 2.0 type hints for all models
- mypy strict mode validation
- TypeScript strict mode in frontend

### IV. ML Pipeline Architecture ✅ WILL COMPLY (Future)
- Audio import uses Celery for background processing
- Spectrogram generation cached (Redis/filesystem)
- Heavy operations (batch clip generation) via task queue

### V. API Versioning ✅ WILL COMPLY
- All endpoints under `/api/v1/`
- Breaking changes will increment version
- Backward compatible within v1

## Project Structure

### Documentation (this feature)

```text
specs/002-data-management/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── sites.yaml       # OpenAPI for sites
│   ├── datasets.yaml    # OpenAPI for datasets
│   ├── recordings.yaml  # OpenAPI for recordings
│   └── clips.yaml       # OpenAPI for clips
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
apps/api/
├── echoroo/
│   ├── api/v1/
│   │   ├── sites.py           # Site endpoints
│   │   ├── datasets.py        # Dataset endpoints
│   │   ├── recordings.py      # Recording endpoints
│   │   └── clips.py           # Clip endpoints
│   ├── services/
│   │   ├── site.py            # Site business logic
│   │   ├── dataset.py         # Dataset business logic
│   │   ├── recording.py       # Recording business logic
│   │   ├── clip.py            # Clip business logic
│   │   └── audio.py           # Audio processing utilities
│   ├── repositories/
│   │   ├── site.py            # Site data access
│   │   ├── dataset.py         # Dataset data access
│   │   ├── recording.py       # Recording data access
│   │   └── clip.py            # Clip data access
│   ├── models/
│   │   ├── site.py            # Site SQLAlchemy model
│   │   ├── dataset.py         # Dataset SQLAlchemy model
│   │   ├── recording.py       # Recording SQLAlchemy model (includes note field)
│   │   └── clip.py            # Clip SQLAlchemy model (includes note field)
│   ├── schemas/
│   │   ├── site.py            # Site Pydantic schemas
│   │   ├── dataset.py         # Dataset Pydantic schemas
│   │   ├── recording.py       # Recording Pydantic schemas
│   │   └── clip.py            # Clip Pydantic schemas
│   └── workers/
│       └── import_task.py     # Celery task for dataset import
├── alembic/
│   └── versions/              # Database migrations
└── tests/
    ├── contract/
    │   ├── test_sites.py
    │   ├── test_datasets.py
    │   ├── test_recordings.py
    │   └── test_clips.py
    └── integration/
        ├── test_dataset_import.py
        └── test_recording_workflow.py

apps/web/
├── src/
│   ├── lib/
│   │   ├── api/
│   │   │   ├── sites.ts       # Site API client
│   │   │   ├── datasets.ts    # Dataset API client
│   │   │   ├── recordings.ts  # Recording API client (update existing)
│   │   │   └── clips.ts       # Clip API client
│   │   ├── components/
│   │   │   ├── map/           # Map components (H3 hex selection)
│   │   │   ├── audio/         # Audio player, spectrogram
│   │   │   └── data/          # Data tables, lists
│   │   └── types/
│   │       └── data.ts        # TypeScript types for data entities
│   └── routes/
│       └── (app)/
│           └── projects/
│               └── [id]/
│                   ├── sites/         # Site management pages
│                   ├── datasets/      # Dataset management pages
│                   └── recordings/    # Recording browser pages
└── tests/
    └── *.test.ts
```

**Structure Decision**: Web application structure following existing patterns from 001-administration. Backend follows Clean Architecture with API/Service/Repository layers. Frontend uses SvelteKit route groups with shared components.

## Complexity Tracking

> No constitution violations requiring justification.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| N/A | N/A | N/A |
